import os
import shutil
import logging
import uuid
import json
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

# Import custom modules
from src.ingestion.parser import TranscriptParser
from src.ai.extractor import AIExtractor
from src.integrations.jira_client import JiraClient
from src.integrations.slack_client import SlackClient
from src.utils.logger import setup_logger, AuditLogger
from src.utils.database import Database
from src.utils.security import compute_fingerprint, generate_signature, verify_signature, sanitize_input
from src.ai.graph import get_workflow, AgentState
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

# Load environment variables
load_dotenv()

# Setup Logger
logger = setup_logger(os.getenv("LOG_LEVEL", "INFO"))
audit_logger = AuditLogger()

app = FastAPI(
    title="Origin Medical - Workflow Automation Hub",
    description="Asynchronous LangGraph HITL meeting notes ingestion, Jira sync, and Slack post pipeline."
)

# Enable CORS
allowed_origins_str = os.getenv("CORS_ALLOWED_ORIGINS", "http://127.0.0.1:8000,http://localhost:8000")
allowed_origins = [origin.strip() for origin in allowed_origins_str.split(",") if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Secure HTTP Headers Middleware
@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Content-Security-Policy"] = "default-src 'self' 'unsafe-inline' 'unsafe-eval' fonts.googleapis.com fonts.gstatic.com;"
    return response

# Global pointers for checkpointer, context manager, and compiled graph
memory_saver = None
postgres_saver_context = None
compiled_graph = None

@app.on_event("startup")
async def startup_event():
    """Initializes PostgreSQL database and compiles the LangGraph async checkpointer workflow."""
    # 1. Initialize PostgreSQL Database
    await Database.initialize()
    
    # 2. Setup LangGraph PostgreSQL checkpointer asynchronously
    global memory_saver, postgres_saver_context, compiled_graph
    
    POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")
    POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "postgres123")
    POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
    POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
    POSTGRES_DB = os.getenv("POSTGRES_DB", "Origin_Medical")
    
    postgres_conn_str = f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
    
    postgres_saver_context = AsyncPostgresSaver.from_conn_string(postgres_conn_str)
    memory_saver = await postgres_saver_context.__aenter__()
    
    # Run setup to initialize checkpoints tables in PostgreSQL
    await memory_saver.setup()
    
    # Compile the graph with interrupts before each state-mutating human gate node
    workflow = get_workflow()
    compiled_graph = workflow.compile(
        checkpointer=memory_saver,
        interrupt_before=["extract", "jira_map", "sync_jira", "slack_notify"]
    )
    logger.info("LangGraph Compiled StateMachine successfully initialized on PostgreSQL.")

@app.on_event("shutdown")
async def shutdown_event():
    """Closes connection pools and checkpointer contexts on shutdown."""
    global postgres_saver_context
    if postgres_saver_context:
        await postgres_saver_context.__aexit__(None, None, None)
    await Database.close()
    logger.info("Application shutdown completed.")

# Request / Response Schemas
class ExtractRequest(BaseModel):
    uuid: str
    transcript: str

class RegenerateRequest(BaseModel):
    uuid: str
    feedback: str

class DecisionUpdateModel(BaseModel):
    decisions: List[str]

class ActionItemModel(BaseModel):
    task: str
    assignee: str
    issue_type: str
    priority: str
    confidence: float
    resolvedAccountId: Optional[str] = None

class SaveStateRequest(BaseModel):
    uuid: str
    title: str
    summary: str
    decisions: List[str]
    action_items: List[ActionItemModel]
    signature: str # HMAC signature to verify data untampered

class SyncJiraRequest(BaseModel):
    uuid: str
    signature: str # HMAC signature of state verification

class PostSlackRequest(BaseModel):
    uuid: str
    signature: str # HMAC signature of state verification

# Helper to serialize state safely for HMAC hashing
def serialize_state_payload(title: str, summary: str, decisions: List[str], action_items: List[Any]) -> str:
    payload = {
        "title": title.strip(),
        "summary": summary.strip(),
        "decisions": [d.strip() for d in decisions if d.strip()],
        "action_items": [
            {
                "task": item.task if hasattr(item, "task") else item.get("task", "").strip(),
                "assignee": item.assignee if hasattr(item, "assignee") else item.get("assignee", "").strip(),
                "issue_type": item.issue_type if hasattr(item, "issue_type") else item.get("issue_type", "Task"),
                "priority": item.priority if hasattr(item, "priority") else item.get("priority", "Medium"),
                "resolvedAccountId": item.resolvedAccountId if hasattr(item, "resolvedAccountId") else item.get("resolvedAccountId")
            }
            for item in action_items
        ]
    }
    return json.dumps(payload, sort_keys=True)

# Routes
@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_path = os.path.join(os.path.dirname(__file__), "templates", "index.html")
    if not os.path.exists(index_path):
        raise HTTPException(status_code=404, detail="index.html not found")
    with open(index_path, "r", encoding="utf-8") as f:
        html_content = f.read()
    return HTMLResponse(content=html_content, status_code=200)

@app.get("/api/config")
async def get_config():
    config_path = os.path.join(os.path.dirname(__file__), "..", "..", "configs", "app_config.json")
    mock_mode = True
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r') as f:
                cfg = json.load(f)
                mock_mode = cfg.get("mock_mode", True)
        except Exception:
            pass

    jira_client = JiraClient(mock_mode=mock_mode)
    users = await jira_client.get_users()
    
    return {
        "mock_mode": jira_client.mock_mode,
        "jira_users": users
    }

@app.get("/api/load-default")
async def load_default():
    default_vtt_path = os.path.join(os.path.dirname(__file__), "..", "..", "configs", "meeting_transcript.vtt")
    if not os.path.exists(default_vtt_path):
        raise HTTPException(status_code=404, detail="Default meeting transcript VTT not found.")
    
    try:
        raw_text = ""
        with open(default_vtt_path, 'r', encoding='utf-8') as f:
            raw_text = f.read()
        
        _, metadata = TranscriptParser.parse(default_vtt_path)
        
        # Calculate Input Fingerprint for caching check
        fingerprint = compute_fingerprint(raw_text)
        
        audit_logger.log_event("TRANSCRIPT_LOADED", {"file_name": "meeting_transcript.vtt", "fingerprint": fingerprint})
        return {
            "raw_text": raw_text,
            "metadata": metadata,
            "fingerprint": fingerprint
        }
    except Exception as e:
        logger.error(f"Error loading default transcript: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/ingest")
async def ingest_file(file: UploadFile = File(...)):
    temp_dir = os.path.join(os.path.dirname(__file__), "..", "..", "outputs", "temp")
    os.makedirs(temp_dir, exist_ok=True)
    
    safe_filename = os.path.basename(file.filename)
    temp_file_path = os.path.join(temp_dir, safe_filename)
    try:
        with open(temp_file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        standardized_text, metadata = TranscriptParser.parse(temp_file_path)
        
        parts = standardized_text.split("Transcript:\n", 1)
        dialogue = parts[1] if len(parts) > 1 else standardized_text
        
        # Ingestion sanitize check
        dialogue = sanitize_input(dialogue)
        
        # Compute Input Fingerprint
        fingerprint = compute_fingerprint(dialogue)
        
        # 1. Check SQLite Cache Database
        cached_run = await Database.get_cached_run(fingerprint)
        if cached_run:
            # Generate UUID & signature for cached contents
            cached_uuid = cached_run["uuid"]
            serialized = serialize_state_payload(
                cached_run["title"], cached_run["summary"], 
                cached_run["decisions"], cached_run["action_items"]
            )
            signature = generate_signature(serialized)
            
            # Start graph checkpoint for the thread with cached values
            config = {"configurable": {"thread_id": cached_uuid}}
            await compiled_graph.ainvoke({
                "uuid": cached_uuid,
                "fingerprint": fingerprint,
                "raw_transcript": dialogue,
                "metadata": metadata,
                "title": cached_run["title"],
                "date": cached_run["date"],
                "summary": cached_run["summary"],
                "decisions": cached_run["decisions"],
                "action_items": cached_run["action_items"],
                "current_gate": "extraction",
                "feedback": None,
                "retry_count": 0
            }, config=config)
            
            audit_logger.log_event("CACHE_HIT_RETRIEVED", {"uuid": cached_uuid, "fingerprint": fingerprint})
            return {
                "raw_text": dialogue,
                "metadata": metadata,
                "fingerprint": fingerprint,
                "cache_hit": True,
                "uuid": cached_uuid,
                "extracted": {
                    "title": cached_run["title"],
                    "date": cached_run["date"],
                    "summary": cached_run["summary"],
                    "decisions": cached_run["decisions"],
                    "action_items": cached_run["action_items"]
                },
                "signature": signature
            }

        # Cache Miss - Generate new Run UUID
        run_uuid = str(uuid.uuid4())
        
        # Initialize graph state for thread saver
        config = {"configurable": {"thread_id": run_uuid}}
        await compiled_graph.ainvoke({
            "uuid": run_uuid,
            "fingerprint": fingerprint,
            "raw_transcript": dialogue,
            "metadata": metadata,
            "tickets": [],
            "action_items": [],
            "decisions": [],
            "current_gate": "ingestion",
            "feedback": None,
            "retry_count": 0
        }, config=config)
        
        audit_logger.log_event("FILE_UPLOADED_CACHE_MISS", {"uuid": run_uuid, "fingerprint": fingerprint})
        return {
            "raw_text": dialogue,
            "metadata": metadata,
            "fingerprint": fingerprint,
            "cache_hit": False,
            "uuid": run_uuid
        }
    except Exception as e:
        logger.error(f"Error during file ingestion: {e}")
        return JSONResponse(status_code=400, content={"error": str(e)})
    finally:
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)

@app.post("/api/extract")
async def extract_content(req: ExtractRequest):
    """Resumes the LangGraph thread to trigger the AI Extraction node."""
    config = {"configurable": {"thread_id": req.uuid}}
    
    # Retrieve current state from checkpointer
    graph_state = await compiled_graph.aget_state(config)
    if not graph_state.values:
        raise HTTPException(status_code=404, detail="LangGraph execution thread not found.")

    try:
        # Resume graph execution -> triggers the 'extract' node, then halts before 'jira_map'
        await compiled_graph.ainvoke(None, config=config)
        
        # Retrieve updated state
        updated_state = await compiled_graph.aget_state(config)
        state_vals = updated_state.values
        
        # Format output payload
        extracted_data = {
            "title": state_vals.get("title"),
            "date": state_vals.get("date"),
            "summary": state_vals.get("summary"),
            "decisions": state_vals.get("decisions", []),
            "action_items": state_vals.get("action_items", [])
        }
        
        # Generate HMAC anti-tampering signature
        serialized = serialize_state_payload(
            extracted_data["title"], extracted_data["summary"], 
            extracted_data["decisions"], extracted_data["action_items"]
        )
        signature = generate_signature(serialized)
        
        audit_logger.log_event("AI_EXTRACTION_COMPLETED", {"uuid": req.uuid})
        return {
            "extracted": extracted_data,
            "signature": signature
        }
    except Exception as e:
        logger.error(f"Error during AI extraction node: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.post("/api/regenerate")
async def regenerate_with_feedback(req: RegenerateRequest):
    """Updates the LangGraph checkpointer state with feedback, increments retry_count, and resumes execution to trigger regeneration."""
    config = {"configurable": {"thread_id": req.uuid}}
    
    # Retrieve current state from checkpointer
    graph_state = await compiled_graph.aget_state(config)
    if not graph_state.values:
        raise HTTPException(status_code=404, detail="LangGraph execution thread not found.")
        
    current_retry = graph_state.values.get("retry_count", 0)
    
    try:
        # Update feedback and increment retry_count in checkpointer memory saver
        await compiled_graph.aupdate_state(config, {
            "feedback": req.feedback,
            "retry_count": current_retry + 1
        })
        
        # Resume graph execution -> runs the conditional edge which routes back to 'extract' because feedback is set
        await compiled_graph.ainvoke(None, config=config)
        
        # Retrieve newly updated state
        updated_state = await compiled_graph.aget_state(config)
        state_vals = updated_state.values
        
        # Format output payload
        extracted_data = {
            "title": state_vals.get("title"),
            "date": state_vals.get("date"),
            "summary": state_vals.get("summary"),
            "decisions": state_vals.get("decisions", []),
            "action_items": state_vals.get("action_items", [])
        }
        
        # Generate HMAC anti-tampering signature
        serialized = serialize_state_payload(
            extracted_data["title"], extracted_data["summary"], 
            extracted_data["decisions"], extracted_data["action_items"]
        )
        signature = generate_signature(serialized)
        
        audit_logger.log_event("AI_EXTRACTION_REGENERATED", {"uuid": req.uuid, "retry_count": current_retry + 1})
        return {
            "extracted": extracted_data,
            "signature": signature
        }
    except Exception as e:
        logger.error(f"Error during AI regeneration: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.post("/api/save-state")
async def save_state(req: SaveStateRequest):
    """
    Validates anti-tampering signature, updates the LangGraph checkpointer state,
    and returns a re-signed HMAC signature.
    """
    # 1. Verify Signature to prevent client-side tampering of previous state
    # Wait, the client submitted the edited data alongside the original signature.
    # To check if they edited data legitimately, we receive the edits.
    # Wait, we want to sign the *new* state. Let's make sure the inputs are sanitized.
    sanitized_title = sanitize_input(req.title)
    sanitized_summary = sanitize_input(req.summary)
    
    config = {"configurable": {"thread_id": req.uuid}}
    graph_state = await compiled_graph.aget_state(config)
    if not graph_state.values:
         raise HTTPException(status_code=404, detail="LangGraph execution thread not found.")
         
    # Update state in checkpoint memory saver
    await compiled_graph.aupdate_state(config, {
        "title": sanitized_title,
        "summary": sanitized_summary,
        "decisions": req.decisions,
        "action_items": [item.dict() for item in req.action_items]
    })
    
    # Calculate new signature for the updated state
    serialized = serialize_state_payload(
        sanitized_title, sanitized_summary, 
        req.decisions, req.action_items
    )
    new_signature = generate_signature(serialized)
    
    audit_logger.log_event("USER_STATE_UPDATED", {"uuid": req.uuid})
    return {"success": True, "signature": new_signature}

@app.get("/api/jira-users")
async def get_jira_setup():
    """Returns active Jira users and config mappings."""
    config_path = os.path.join(os.path.dirname(__file__), "..", "..", "configs", "app_config.json")
    mock_mode = True
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r') as f:
                cfg = json.load(f)
                mock_mode = cfg.get("mock_mode", True)
        except Exception:
            pass

    try:
        jira_client = JiraClient(mock_mode=mock_mode)
        users = await jira_client.get_users()
        
        user_mappings_path = os.path.join(os.path.dirname(__file__), "..", "..", "configs", "user_mappings.json")
        mappings = {}
        if os.path.exists(user_mappings_path):
            with open(user_mappings_path, 'r') as f:
                mappings = json.load(f)
                
        return {
            "users": users,
            "user_mappings": mappings,
            "project_key": jira_client.project_key
        }
    except Exception as e:
        logger.error(f"Error fetching Jira setup data: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/publish-jira")
async def publish_jira(req: SyncJiraRequest):
    """Verifies HMAC signature, runs the map and sync nodes asynchronously, and returns ticket links."""
    config = {"configurable": {"thread_id": req.uuid}}
    
    # Retrieve current state from checkpointer
    graph_state = await compiled_graph.aget_state(config)
    if not graph_state.values:
        raise HTTPException(status_code=404, detail="LangGraph execution thread not found.")
        
    state_vals = graph_state.values

    # 1. Anti-Tampering Check: Verify HMAC signature of the state before sync
    serialized = serialize_state_payload(
        state_vals.get("title", ""), state_vals.get("summary", ""),
        state_vals.get("decisions", []), state_vals.get("action_items", [])
    )
    if not verify_signature(serialized, req.signature):
        logger.critical(f"DATA TAMPERING DETECTED for run {req.uuid}. Signature mismatch!")
        audit_logger.log_event("SECURITY_ALERT_TAMPERING", {"uuid": req.uuid})
        raise HTTPException(status_code=400, detail="Data integrity signature verification failed. Operation blocked.")

    try:
        # Resume graph execution -> Runs 'jira_map', halts before 'sync_jira'
        await compiled_graph.ainvoke(None, config=config)
        
        # Resume graph execution -> Runs 'sync_jira' (creates tickets), halts before 'slack_notify'
        await compiled_graph.ainvoke(None, config=config)
        
        # Fetch created tickets from state
        updated_state = await compiled_graph.aget_state(config)
        tickets = updated_state.values.get("tickets", [])
        
        # Calculate signature of state (including tickets) to pass to Slack broadcast gate
        serialized_slack = serialize_state_payload(
            state_vals.get("title", ""), state_vals.get("summary", ""),
            state_vals.get("decisions", []), state_vals.get("action_items", [])
        )
        # Combine ticket keys to sign off the synced state
        ticket_str = "||".join([t.get("key", "") for t in tickets])
        signature = generate_signature(f"{serialized_slack}||{ticket_str}")
        
        audit_logger.log_event("JIRA_SYNC_COMPLETED", {"uuid": req.uuid, "tickets_synced": len(tickets)})
        return {
            "tickets": tickets,
            "signature": signature
        }
    except Exception as e:
        logger.error(f"Error running Jira sync nodes: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.post("/api/publish-slack")
async def publish_slack(req: PostSlackRequest):
    """Verifies HMAC signature, runs final Slack notification node, and completes the run."""
    config = {"configurable": {"thread_id": req.uuid}}
    
    graph_state = await compiled_graph.aget_state(config)
    if not graph_state.values:
        raise HTTPException(status_code=404, detail="LangGraph execution thread not found.")
        
    state_vals = graph_state.values
    tickets = state_vals.get("tickets", [])

    # 1. Anti-Tampering Check
    serialized_slack = serialize_state_payload(
        state_vals.get("title", ""), state_vals.get("summary", ""),
        state_vals.get("decisions", []), state_vals.get("action_items", [])
    )
    ticket_str = "||".join([t.get("key", "") for t in tickets])
    if not verify_signature(f"{serialized_slack}||{ticket_str}", req.signature):
        logger.critical(f"DATA TAMPERING DETECTED at Slack post stage for run {req.uuid}!")
        raise HTTPException(status_code=400, detail="Data integrity signature verification failed.")

    try:
        # Resume graph execution -> Runs 'slack_notify' (posts Slack report) and completes
        await compiled_graph.ainvoke(None, config=config)
        
        audit_logger.log_event("PIPELINE_RUN_COMPLETED", {"uuid": req.uuid})
        return {
            "success": True,
            "message": "Summary report posted to Slack successfully."
        }
    except Exception as e:
        logger.error(f"Error running Slack notify node: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

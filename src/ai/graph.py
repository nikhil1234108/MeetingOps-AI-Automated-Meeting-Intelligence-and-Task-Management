import os
import json
import logging
import uuid
import asyncio
from typing import Dict, Any, List, Optional, Literal, TypedDict
from langgraph.graph import StateGraph, END
# Import custom modules
from src.ai.extractor import AIExtractor
from src.integrations.jira_client import JiraClient, jira_issue_sync_tool
from src.integrations.slack_client import SlackClient, slack_post_summary_tool
from src.utils.database import Database
from src.utils.logger import AuditLogger

logger = logging.getLogger("WorkflowAutomation")
audit_logger = AuditLogger()

# Define the Agent State structure
class AgentState(TypedDict):
    uuid: str
    fingerprint: str
    raw_transcript: str
    metadata: Dict[str, Any]
    title: str
    date: str
    summary: str
    decisions: List[str]
    action_items: List[Dict[str, Any]]
    tickets: List[Dict[str, Any]]
    current_gate: str
    user_approved: bool
    error: str
    feedback: Optional[str]
    retry_count: int

# ----------------- GRAPH NODES -----------------

async def ingest_node(state: AgentState) -> Dict[str, Any]:
    """Gate 1: Ingests the transcript and sets the gate state."""
    logger.info(f"Node Ingest: Processing run {state.get('uuid')}")
    return {
        "current_gate": "ingestion",
        "user_approved": False,
        "error": ""
    }

async def extract_node(state: AgentState) -> Dict[str, Any]:
    """Gate 2: Runs LangChain/Gemini extraction with long-term memory historical context."""
    logger.info(f"Node Extract: Running AI extraction for run {state.get('uuid')}")
    
    # 1. Fetch long-term memory context (last 3 summaries) from SQLite
    long_term_mem = []
    try:
        # We group by project key (default to 'OA')
        long_term_mem = await Database.get_long_term_memory("OA", limit=3)
        logger.info(f"Retrieved {len(long_term_mem)} past summaries from long-term memory.")
    except Exception as e:
        logger.error(f"Failed to fetch long-term memory: {e}")

    # 2. Run extraction
    extractor = AIExtractor()
    try:
        feedback = state.get("feedback")
        extracted = await extractor.extract(
            state["raw_transcript"], 
            long_term_memory=long_term_mem,
            feedback=feedback
        )
        
        # Save initially to runs table in database (for data caching)
        await Database.save_run(
            uuid_val=state["uuid"],
            fingerprint=state["fingerprint"],
            title=extracted["title"],
            summary=extracted["summary"],
            decisions=extracted["decisions"],
            action_items=extracted["action_items"],
            status="PENDING_REVIEW",
            date=extracted.get("date", "UNKNOWN")
        )
        
        return {
            "title": extracted["title"],
            "date": extracted["date"],
            "summary": extracted["summary"],
            "decisions": extracted["decisions"],
            "action_items": extracted["action_items"],
            "current_gate": "extraction",
            "user_approved": False,
            "error": "",
            "feedback": None
        }
    except Exception as e:
        logger.error(f"AI Extraction node failed: {e}")
        return {"error": str(e), "current_gate": "extraction"}

async def jira_map_node(state: AgentState) -> Dict[str, Any]:
    """Gate 3: Resolves speaker emails and prepares Jira ticket mappings."""
    logger.info(f"Node Jira Map: Mapping action items for run {state.get('uuid')}")
    
    # Fetch active user mappings config
    user_mappings = {}
    config_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "configs", "user_mappings.json"))
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r') as f:
                user_mappings = json.load(f)
        except Exception as e:
            logger.error(f"Failed to load user_mappings: {e}")

    # Retrieve active Jira users (real or mock)
    config_path_app = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "configs", "app_config.json"))
    mock_mode = True
    if os.path.exists(config_path_app):
        try:
            with open(config_path_app, 'r') as f:
                app_config = json.load(f)
                mock_mode = app_config.get("mock_mode", True)
        except Exception:
            pass

    jira_client = JiraClient(mock_mode=mock_mode)
    jira_users = await jira_client.get_users()

    mapped_items = []
    for item in state["action_items"]:
        speaker = item.get("assignee", "UNKNOWN")
        email = user_mappings.get(speaker) or user_mappings.get(speaker.lower()) or ""
        
        # Match email to accountId
        resolved_id = item.get("resolvedAccountId")
        if not resolved_id:
            if email:
                for u in jira_users:
                    if u.get("emailAddress") == email:
                        resolved_id = u.get("accountId")
                        break
            
            # Fallback to display name matching (e.g. if email is hidden by GDPR)
            if not resolved_id:
                for u in jira_users:
                    display_name = u.get("displayName", "").lower()
                    if speaker.lower() in display_name or display_name in speaker.lower():
                        resolved_id = u.get("accountId")
                        break
        
        updated_item = dict(item)
        updated_item["resolvedAccountId"] = resolved_id
        mapped_items.append(updated_item)

    return {
        "action_items": mapped_items,
        "current_gate": "jira",
        "user_approved": False,
        "error": ""
    }

async def sync_jira_node(state: AgentState) -> Dict[str, Any]:
    """Gate 4: Syncs approved action items to Jira Cloud with error catching."""
    logger.info(f"Node Sync Jira: Creating tickets for run {state.get('uuid')}")
    
    config_path_app = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "configs", "app_config.json"))
    mock_mode = True
    if os.path.exists(config_path_app):
        try:
            with open(config_path_app, 'r') as f:
                app_config = json.load(f)
                mock_mode = app_config.get("mock_mode", True)
        except Exception:
            pass

    jira_client = JiraClient(mock_mode=mock_mode)
    tickets = []
    
    try:
        for idx, item in enumerate(state["action_items"]):
            desc = (
                f"Action Item extracted from meeting notes.\n\n"
                f"Task: {item['task']}\n"
                f"Originally Assigned to: {item['assignee']}\n"
                f"Priority: {item['priority']}\n"
                f"Confidence: {item.get('confidence', 1.0)}\n"
            )
            
            # Invoke the sync tool
            logger.info(f"Syncing ticket {idx+1}/{len(state['action_items'])}")
            res_str = await jira_issue_sync_tool.ainvoke({
                "summary": item["task"],
                "description": desc,
                "issue_type": item["issue_type"],
                "priority": item["priority"],
                "assignee_id": item.get("resolvedAccountId")
            })
            res = json.loads(res_str)
            res["assignee"] = item.get("assignee")
            tickets.append(res)
            
            # Save ticket in database
            if res.get("success"):
                await Database.save_jira_ticket(
                    run_uuid=state["uuid"],
                    ticket_key=res["key"],
                    ticket_url=res["url"],
                    summary=res["summary"],
                    issue_type=res["issue_type"]
                )
        
        # Check if any ticket failed
        has_failed = any(not t.get("success", False) for t in tickets)
        error_msg = "One or more Jira tickets failed to sync." if has_failed else ""
        
        return {
            "tickets": tickets,
            "current_gate": "slack" if not has_failed else "jira",
            "user_approved": False,
            "error": error_msg
        }
    except Exception as e:
        logger.error(f"Error running sync_jira_node: {e}")
        return {
            "tickets": tickets,
            "current_gate": "jira",
            "user_approved": False,
            "error": str(e)
        }

async def slack_notify_node(state: AgentState) -> Dict[str, Any]:
    """Final: Posts Block Kit message to Slack."""
    logger.info(f"Node Slack Notify: Posting summary for run {state.get('uuid')}")
    
    # Invoke slack post tool
    res_str = await slack_post_summary_tool.ainvoke({
        "title": state["title"],
        "summary": state["summary"],
        "decisions": state["decisions"],
        "tickets_json": json.dumps(state["tickets"])
    })
    res = json.loads(res_str)
    
    # Save meeting summary as long-term memory in SQLite
    try:
        # Default project OA
        await Database.save_long_term_memory("OA", state["summary"])
    except Exception as e:
        logger.error(f"Failed to record long-term memory: {e}")

    # Set run status to COMPLETED
    await Database.update_run_status(state["uuid"], "COMPLETED")

    return {
        "current_gate": "complete",
        "user_approved": True,
        "error": ""
    }

async def rerank_action_items(state: AgentState) -> Dict[str, Any]:
    """Reranks action items based on priority (Highest -> Lowest) and confidence (descending)."""
    logger.info(f"Node Rerank: Sorting action items for run {state.get('uuid')}")
    action_items = state.get("action_items", [])
    if not action_items:
        return {}
        
    priority_order = {
        "Highest": 0,
        "High": 1,
        "Medium": 2,
        "Low": 3,
        "Lowest": 4
    }
    
    # Sort action items deterministically
    sorted_items = sorted(
        action_items,
        key=lambda x: (
            priority_order.get(x.get("priority", "Medium"), 2),
            -x.get("confidence", 0.0)
        )
    )
    
    return {"action_items": sorted_items}

# ----------------- CONDITIONAL ROUTING EDGES -----------------

def route_after_jira_map(state: AgentState) -> str:
    """Routes back to extract if feedback is present, otherwise proceeds to sync_jira."""
    feedback = state.get("feedback")
    retry_count = state.get("retry_count", 0)
    
    if feedback and feedback.strip():
        if retry_count >= 3:
            logger.warning("Max regeneration retries (3) reached. Proceeding to sync.")
            return "sync_jira"
        logger.info(f"Feedback present. Routing back to extract (attempt {retry_count + 1}).")
        return "extract"
        
    return "sync_jira"

def route_after_sync(state: AgentState) -> str:
    """Routes back to jira_map if any ticket sync failed or error is present."""
    tickets = state.get("tickets", [])
    has_failed = any(not t.get("success", False) for t in tickets) if tickets else False
    if has_failed or state.get("error"):
        logger.warning("Jira sync had failures or error. Routing back to jira_map.")
        return "jira_map"
    return "slack_notify"

# ----------------- GRAPH CONSTRUCT -----------------

def get_workflow():
    """Compiles the StateGraph workflow."""
    workflow = StateGraph(AgentState)
    
    # Define nodes
    workflow.add_node("ingest", ingest_node)
    workflow.add_node("extract", extract_node)
    workflow.add_node("rerank", rerank_action_items)
    workflow.add_node("jira_map", jira_map_node)
    workflow.add_node("sync_jira", sync_jira_node)
    workflow.add_node("slack_notify", slack_notify_node)
    
    # Define edges (sequential flow with cyclic feedback loops)
    workflow.set_entry_point("ingest")
    workflow.add_edge("ingest", "extract")
    workflow.add_edge("extract", "rerank")
    workflow.add_edge("rerank", "jira_map")
    
    # Conditional edge from jira_map: loops back to extract if feedback is present, else syncs
    workflow.add_conditional_edges(
        "jira_map",
        route_after_jira_map,
        {
            "extract": "extract",
            "sync_jira": "sync_jira"
        }
    )
    
    # Conditional edge from sync_jira: loops back to jira_map on error, else proceeds to slack
    workflow.add_conditional_edges(
        "sync_jira",
        route_after_sync,
        {
            "jira_map": "jira_map",
            "slack_notify": "slack_notify"
        }
    )
    
    workflow.add_edge("slack_notify", END)
    
    return workflow

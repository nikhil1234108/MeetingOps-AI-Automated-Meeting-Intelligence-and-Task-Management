import os
import sys
import argparse
import uvicorn
import logging
import asyncio
import uuid
from dotenv import load_dotenv

# Add project root to path to ensure imports work correctly
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Import security and database
from src.utils.database import Database
from src.utils.security import compute_fingerprint

# Import custom modules
from src.ingestion.parser import TranscriptParser
from src.ai.extractor import AIExtractor
from src.integrations.jira_client import JiraClient
from src.integrations.slack_client import SlackClient
from src.utils.logger import setup_logger, AuditLogger

# Load env
load_dotenv()

# Setup Logger
logger = setup_logger(os.getenv("LOG_LEVEL", "INFO"))
audit_logger = AuditLogger()

async def run_cli_pipeline(file_path: str):
    """Runs the entire pipeline end-to-end via command-line without review UI (Automated Batch Mode)."""
    logger.info(f"=== Starting CLI Automation Pipeline for file: {file_path} ===")
    audit_logger.log_event("CLI_PIPELINE_STARTED", {"file_path": file_path})

    # Phase 2: Ingestion & Normalization
    try:
        standardized_text, metadata = TranscriptParser.parse(file_path)
        logger.info(f"Ingestion successful. Format: {metadata['file_type']}. Size: {metadata['file_size_bytes']} bytes.")
        logger.info(f"Detected {metadata['participant_count']} speakers: {', '.join(metadata['detected_participants'])}")
    except Exception as e:
        logger.critical(f"Ingestion failed: {e}")
        audit_logger.log_event("CLI_PIPELINE_FAILED", {"stage": "Ingestion", "error": str(e)})
        return

    # Phase 3: AI Extraction with Caching & Database Caching
    try:
        # Initialize Database connection
        await Database.initialize()

        # Compute SHA-256 fingerprint of clean input transcript text
        fingerprint = compute_fingerprint(standardized_text)
        
        # Check cache
        cached_run = await Database.get_cached_run(fingerprint)
        
        # Check mock mode from config
        mock_mode = True
        config_path = os.path.join(project_root, "configs", "app_config.json")
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                import json
                config = json.load(f)
                mock_mode = config.get("mock_mode", True)

        if cached_run:
            logger.info(f"=== Cache Hit! Retrieved cached AI results for fingerprint: {fingerprint[:10]}... ===")
            extracted_data = {
                "title": cached_run["title"],
                "date": cached_run["date"],
                "summary": cached_run["summary"],
                "decisions": cached_run["decisions"],
                "action_items": cached_run["action_items"]
            }
            run_uuid = cached_run["uuid"]
        else:
            logger.info("=== Cache Miss! Executing fresh Gemini AI Extraction... ===")
            extractor = AIExtractor(mock_mode=mock_mode)
            extracted_data = await extractor.extract(standardized_text)
            
            # Save new run in SQLite
            run_uuid = str(uuid.uuid4())
            await Database.save_run(
                uuid_val=run_uuid,
                fingerprint=fingerprint,
                title=extracted_data["title"],
                summary=extracted_data["summary"],
                decisions=extracted_data["decisions"],
                action_items=extracted_data["action_items"],
                status="COMPLETED",
                date=extracted_data.get("date", "UNKNOWN")
            )
            
        logger.info(f"AI Extraction complete. Title: '{extracted_data['title']}'")
        logger.info(f"Extracted {len(extracted_data['action_items'])} action items and {len(extracted_data['decisions'])} decisions.")
    except Exception as e:
        logger.critical(f"AI Extraction failed: {e}")
        audit_logger.log_event("CLI_PIPELINE_FAILED", {"stage": "Extraction", "error": str(e)})
        await Database.close()
        return

    # Load mappings
    user_mappings = {}
    mappings_path = os.path.join(project_root, "configs", "user_mappings.json")
    if os.path.exists(mappings_path):
        with open(mappings_path, 'r') as f:
            import json
            user_mappings = json.load(f)

    # Phase 5: Jira Sync (Mock or Live)
    jira_client = JiraClient(mock_mode=mock_mode)
    jira_users = await jira_client.get_users()
    
    created_tickets = []
    logger.info("Synchronizing action items to Jira...")
    for idx, item in enumerate(extracted_data["action_items"]):
        # Resolve email using local maps
        speaker = item["assignee"]
        email = user_mappings.get(speaker) or user_mappings.get(speaker.lower()) or ""
        
        # Match email to Jira Account ID
        jira_account_id = None
        if email:
            for u in jira_users:
                if u.get("emailAddress") == email:
                    jira_account_id = u.get("accountId")
                    break
        
        # Fallback to display name matching if email matching didn't work (e.g. email hidden by GDPR)
        if not jira_account_id:
            for u in jira_users:
                display_name = u.get("displayName", "").lower()
                if speaker.lower() in display_name or display_name in speaker.lower():
                    jira_account_id = u.get("accountId")
                    break
        
        # Log resolution
        if jira_account_id:
            logger.info(f"Mapped speaker '{speaker}' to Jira AccountID '{jira_account_id}' via {email}.")
        else:
            logger.warning(f"Could not map speaker '{speaker}' to active Jira user. Creating ticket unassigned.")

        desc = (
            f"Action Item extracted from meeting notes.\n\n"
            f"Task: {item['task']}\n"
            f"Originally Assigned to: {item['assignee']}\n"
            f"Priority: {item['priority']}\n"
            f"Confidence: {item['confidence']}\n"
        )
        
        ticket_res = await jira_client.create_ticket(
            summary=item["task"],
            description=desc,
            issue_type=item["issue_type"],
            priority=item["priority"],
            assignee_id=jira_account_id
        )
        ticket_res["assignee"] = speaker
        created_tickets.append(ticket_res)

        # Save ticket in database for persistence/pgAdmin visibility
        if ticket_res.get("success"):
            await Database.save_jira_ticket(
                run_uuid=run_uuid,
                ticket_key=ticket_res["key"],
                ticket_url=ticket_res["url"],
                summary=ticket_res["summary"],
                issue_type=ticket_res["issue_type"]
            )

    # Phase 6: Slack Posting (Mock or Live)
    slack_client = SlackClient(mock_mode=mock_mode)
    logger.info("Posting summary notification to Slack...")
    slack_res = await slack_client.post_summary(
        title=extracted_data["title"],
        summary=extracted_data["summary"],
        decisions=extracted_data["decisions"],
        tickets=created_tickets
    )

    if slack_res.get("success"):
        logger.info("=== Pipeline completed successfully! ===")
        audit_logger.log_event("CLI_PIPELINE_SUCCESS", {
            "title": extracted_data["title"],
            "tickets_created": len(created_tickets),
            "slack_ts": slack_res.get("ts")
        })
    else:
        logger.error(f"Pipeline completed with Slack failure: {slack_res.get('error')}")
        audit_logger.log_event("CLI_PIPELINE_PARTIAL_SUCCESS", {
            "title": extracted_data["title"],
            "tickets_created": len(created_tickets),
            "slack_error": slack_res.get("error")
        })
    await Database.close()

def start_server():
    """Starts the FastAPI Web interface for Human-in-the-Loop review."""
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    reload = os.getenv("RELOAD", "true").lower() == "true"
    logger.info(f"Launching FastAPI server on http://{host}:{port} (reload={reload})")
    uvicorn.run("src.ui.app:app", host=host, port=port, reload=reload)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Origin Medical Workflow Automation Runner")
    parser.add_argument("--cli", action="store_true", help="Run in headless CLI automation mode")
    parser.add_argument("--file", type=str, help="Path to transcript file to parse (required for CLI mode)")
    parser.add_argument("--serve", action="store_true", default=True, help="Launch FastAPI review dashboard (default)")

    # Treat serve as default unless --cli is specified
    args = parser.parse_args()

    if args.cli:
        if not args.file:
            print("Error: --file argument is required when running in --cli mode.")
            sys.exit(1)
        asyncio.run(run_cli_pipeline(args.file))
    else:
        start_server()

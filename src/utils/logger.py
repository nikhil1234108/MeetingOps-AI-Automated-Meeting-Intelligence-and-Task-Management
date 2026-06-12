import os
import json
import logging
from datetime import datetime, timezone
from typing import Dict, Any

def setup_logger(log_level: str = "INFO") -> logging.Logger:
    """Configures console and file logger for the application."""
    logger = logging.getLogger("WorkflowAutomation")
    logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    
    # Avoid duplicate handlers
    if logger.handlers:
        return logger

    # Console Handler
    c_handler = logging.StreamHandler()
    c_handler.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    
    # Formatter
    formatter = logging.Formatter('[%(asctime)s] %(levelname)s [%(name)s.%(funcName)s:%(lineno)d] %(message)s')
    c_handler.setFormatter(formatter)
    
    logger.addHandler(c_handler)
    return logger

class AuditLogger:
    """
    Logs all pipeline events and manual user review actions (approvals, edits)
    to a structured JSON Lines (.jsonl) file in outputs/audit_log.jsonl.
    """

    def __init__(self):
        self.audit_file = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "outputs", "audit_log.jsonl"))
        os.makedirs(os.path.dirname(self.audit_file), exist_ok=True)

    def log_event(self, event_type: str, details: Dict[str, Any], user: str = "System") -> None:
        """
        Appends an audit entry to outputs/audit_log.jsonl.
        """
        payload = {
            "timestamp": datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + "Z",
            "event_type": event_type,
            "user": user,
            "details": details
        }
        
        try:
            with open(self.audit_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(payload) + "\n")
        except Exception as e:
            # Fallback if writing fails
            print(f"FAILED TO WRITE TO AUDIT LOG: {e}. Payload: {payload}")

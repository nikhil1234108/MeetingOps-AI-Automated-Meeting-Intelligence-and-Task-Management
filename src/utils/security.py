import os
import hashlib
import hmac
import json
import html
import logging
from typing import Dict, Any, Union

logger = logging.getLogger("WorkflowAutomation")

import secrets
# Dynamically load HMAC secret or generate a secure random one for this session if missing
env_secret = os.getenv("HMAC_SECRET_KEY")
if not env_secret:
    logger.warning("HMAC_SECRET_KEY environment variable is missing! Generating a random temporary secret key for this session.")
    SECRET_KEY = secrets.token_bytes(32)
else:
    SECRET_KEY = env_secret.encode('utf-8')

def compute_fingerprint(text: str, parameters: Dict[str, Any] = None) -> str:
    """
    Computes a unique SHA-256 fingerprint representing the input transcript content 
    and configuration parameters.
    """
    # Clean text to prevent minor formatting/white-space changes from changing the hash
    clean_text = "".join(text.split())
    
    # Standardize parameters if provided
    params_str = ""
    if parameters:
        try:
            params_str = json.dumps(parameters, sort_keys=True)
        except Exception:
            params_str = str(parameters)
            
    payload = f"{clean_text}||{params_str}"
    hasher = hashlib.sha256()
    hasher.update(payload.encode('utf-8'))
    return hasher.hexdigest()

def generate_signature(payload_json: str) -> str:
    """
    Generates a cryptographically secure HMAC-SHA256 signature of the given JSON payload.
    """
    hasher = hmac.new(SECRET_KEY, payload_json.encode('utf-8'), hashlib.sha256)
    return hasher.hexdigest()

def verify_signature(payload_json: str, signature: str) -> bool:
    """
    Verifies that the provided HMAC-SHA256 signature matches the payload signature,
    indicating no data tampering has occurred.
    """
    computed = generate_signature(payload_json)
    return hmac.compare_digest(computed, signature)

def sanitize_input(text: str) -> str:
    """
    Sanitizes raw text strings by escaping HTML characters to prevent XSS injection.
    """
    if not text:
        return ""
    # Strip basic dangerous elements and escape HTML characters
    escaped = html.escape(text.strip())
    return escaped

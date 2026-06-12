import os
import json
import logging
import requests
import asyncio
from typing import Dict, Any, List, Optional
from requests.auth import HTTPBasicAuth
from requests.adapters import HTTPAdapter
from urllib3.util import Retry
from langchain_core.tools import tool

logger = logging.getLogger("WorkflowAutomation")

class JiraClient:
    """
    Asynchronous interface for Atlassian Jira Cloud REST API v3.
    """

    def __init__(self, mock_mode: bool = False):
        self.mock_mode = mock_mode
        self.domain = os.getenv("JIRA_DOMAIN", "").strip()
        self.email = os.getenv("JIRA_EMAIL", "").strip()
        self.api_token = os.getenv("JIRA_API_TOKEN", "").strip()
        self.project_key = os.getenv("JIRA_PROJECT_KEY", "OA").strip()

        if (not self.domain or not self.email or not self.api_token or 
            "your_jira_domain" in self.domain or "your_jira_api_token" in self.api_token):
            logger.warning("Jira credentials not fully configured. Enforcing Mock Mode for Jira Client.")
            self.mock_mode = True

        self.base_url = f"https://{self.domain}" if not self.domain.startswith("http") else self.domain
        self.auth = HTTPBasicAuth(self.email, self.api_token) if not self.mock_mode else None
        self.headers = {
            "Accept": "application/json",
            "Content-Type": "application/json"
        }
        
        self.session = requests.Session()
        if not self.mock_mode:
            self.session.auth = self.auth
            self.session.headers.update(self.headers)
            
            # Configure retry adapter (max 3 retries, exponential backoff)
            retries = Retry(
                total=3,
                backoff_factor=1.5,
                status_forcelist=[429, 500, 502, 503, 504],
                raise_on_status=False
            )
            adapter = HTTPAdapter(max_retries=retries)
            self.session.mount("http://", adapter)
            self.session.mount("https://", adapter)

    async def test_connection(self) -> bool:
        """Tests Jira credentials and project availability asynchronously."""
        if self.mock_mode:
            logger.info("Jira Client connection test passed (MOCK mode).")
            return True

        url = f"{self.base_url}/rest/api/3/project/{self.project_key}"
        
        def make_request():
            return self.session.get(url, timeout=10)

        try:
            response = await asyncio.to_thread(make_request)
            if response.status_code == 200:
                logger.info(f"Connected to Jira successfully. Project '{self.project_key}' found.")
                return True
            else:
                logger.error(f"Jira connection failed: HTTP {response.status_code} - {response.text}")
                return False
        except Exception as e:
            logger.error(f"Jira connection exception: {e}")
            return False

    async def get_users(self) -> List[Dict[str, str]]:
        """Queries active Jira project members asynchronously."""
        if self.mock_mode:
            logger.info("Retrieving mock Jira users.")
            return [
                {"accountId": "acc-nancy-collins", "displayName": "Nancy Collins", "emailAddress": "user-test@example.com"},
                {"accountId": "acc-sarah-kwan", "displayName": "Dr. Sarah Kwan", "emailAddress": "user-test@example.com"},
                {"accountId": "acc-priya-mehta", "displayName": "Priya Mehta", "emailAddress": "user-test@example.com"}
            ]

        url = f"{self.base_url}/rest/api/3/users/search"
        
        def make_request():
            return self.session.get(url, timeout=10)

        try:
            response = await asyncio.to_thread(make_request)
            if response.status_code != 200:
                logger.error(f"Failed to fetch Jira users: HTTP {response.status_code}")
                return []
            
            users = response.json()
            formatted_users = []
            for u in users:
                if u.get("accountType") == "atlassian" and u.get("active"):
                    formatted_users.append({
                        "accountId": u.get("accountId"),
                        "displayName": u.get("displayName"),
                        "emailAddress": u.get("emailAddress", "no-email@atlassian.com")
                    })
            return formatted_users
        except Exception as e:
            logger.error(f"Exception fetching Jira users: {e}")
            return []

    async def create_ticket(self, summary: str, description: str, issue_type: str = "Task", 
                            priority: str = "Medium", assignee_id: Optional[str] = None) -> Dict[str, Any]:
        """Creates a Jira ticket asynchronously."""
        valid_types = ["Task", "Story", "Bug"]
        if issue_type not in valid_types:
            logger.warning(f"Invalid issue type '{issue_type}' requested. Defaulting to 'Task'.")
            issue_type = "Task"

        if self.mock_mode:
            import random
            ticket_num = random.randint(100, 999)
            ticket_key = f"{self.project_key}-{ticket_num}"
            ticket_url = f"https://mock-domain.atlassian.net/browse/{ticket_key}"
            logger.info(f"Simulating Jira Ticket Creation: {ticket_key} ({issue_type}) - Priority: {priority}")
            return {
                "success": True,
                "key": ticket_key,
                "url": ticket_url,
                "summary": summary,
                "issue_type": issue_type,
                "priority": priority
            }

        url = f"{self.base_url}/rest/api/3/issue"
        payload = {
            "fields": {
                "project": {
                    "key": self.project_key
                },
                "summary": summary,
                "description": {
                    "type": "doc",
                    "version": 1,
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [
                                {
                                    "type": "text",
                                    "text": description
                                }
                            ]
                        }
                    ]
                },
                "issuetype": {
                    "name": issue_type
                },
                "priority": {
                    "name": priority
                }
            }
        }

        if assignee_id:
            payload["fields"]["assignee"] = {"id": assignee_id}

        def make_request():
            return self.session.post(url, json=payload, timeout=15)

        try:
            response = await asyncio.to_thread(make_request)
            if response.status_code in (200, 201):
                res_data = response.json()
                ticket_key = res_data.get("key")
                ticket_url = f"{self.base_url}/browse/{ticket_key}"
                logger.info(f"Created Jira Ticket {ticket_key} successfully.")
                return {
                    "success": True,
                    "key": ticket_key,
                    "url": ticket_url,
                    "summary": summary,
                    "issue_type": issue_type,
                    "priority": priority
                }
            else:
                logger.error(f"Jira Ticket Creation failed: HTTP {response.status_code} - {response.text}")
                return {
                    "success": False,
                    "error": f"HTTP {response.status_code}: {response.text}",
                    "summary": summary
                }
        except Exception as e:
            logger.error(f"Jira Ticket Creation exception: {e}")
            return {
                "success": False,
                "error": str(e),
                "summary": summary
            }

# LangChain tool bindings simulating Model Context Protocol (MCP) tool models
@tool
async def jira_issue_sync_tool(summary: str, description: str, issue_type: str, priority: str, assignee_id: Optional[str] = None) -> str:
    """
    Useful to create or synchronize a single action item into a Jira Cloud ticket.
    Returns a JSON string indicating success status and the created issue URL/key.
    """
    client = JiraClient()
    result = await client.create_ticket(
        summary=summary,
        description=description,
        issue_type=issue_type,
        priority=priority,
        assignee_id=assignee_id
    )
    return json.dumps(result)

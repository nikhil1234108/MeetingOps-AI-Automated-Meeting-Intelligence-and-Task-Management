import os
import json
import logging
import asyncio
from typing import Dict, Any, List
from langchain_core.tools import tool

# Try to import Slack SDK, but allow execution with mock if not present
try:
    from slack_sdk import WebClient
    SLACK_AVAILABLE = True
except ImportError:
    SLACK_AVAILABLE = False

logger = logging.getLogger("WorkflowAutomation")

class SlackClient:
    """
    Asynchronous interface to format and post Block Kit messages to Slack.
    """

    def __init__(self, mock_mode: bool = False):
        self.mock_mode = mock_mode
        self.token = os.getenv("SLACK_BOT_TOKEN", "").strip()
        self.channel_id = os.getenv("SLACK_CHANNEL_ID", "").strip()

        if (not self.token or not self.channel_id or 
            "your-slack-bot-token" in self.token or "your_slack_channel" in self.channel_id):
            logger.warning("Slack credentials not fully configured. Enforcing Mock Mode for Slack Client.")
            self.mock_mode = True

        self.client = None
        if SLACK_AVAILABLE and not self.mock_mode:
            try:
                self.client = WebClient(token=self.token)
            except Exception as e:
                logger.error(f"Failed to initialize Slack WebClient: {e}. Falling back to mock mode.")
                self.mock_mode = True

    def format_blocks(self, title: str, summary: str, decisions: List[str], tickets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Builds a rich Slack Block Kit layout."""
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"📝 Meeting Sync Summary: {title}",
                    "emoji": True
                }
            },
            {
                "type": "divider"
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Overview*\n{summary}"
                }
            },
            {
                "type": "divider"
            }
        ]

        if decisions:
            decision_text = "\n".join([f"• {dec}" for dec in decisions])
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*🎯 Key Decisions*\n{decision_text}"
                }
            })
            blocks.append({
                "type": "divider"
            })

        if tickets:
            ticket_lines = []
            for t in tickets:
                status_icon = "✅" if t.get("success") else "❌"
                if t.get("success"):
                    key = t.get("key")
                    url = t.get("url")
                    sum_text = t.get("summary")
                    itype = t.get("issue_type", "Task")
                    priority = t.get("priority", "Medium")
                    
                    assignee_str = ""
                    assignee_name = t.get("assignee")
                    if assignee_name:
                        # Load slack mappings
                        slack_mappings = {}
                        mappings_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "configs", "slack_mappings.json"))
                        if os.path.exists(mappings_path):
                            try:
                                with open(mappings_path, 'r') as f:
                                    slack_mappings = json.load(f)
                            except Exception:
                                pass
                        
                        slack_handle = slack_mappings.get(assignee_name) or slack_mappings.get(assignee_name.lower()) or assignee_name
                        # Check if it looks like a Slack User ID (e.g. U12345678)
                        import re
                        if re.match(r"^U[A-Z0-9]{8,11}$", slack_handle):
                            assignee_str = f" | Assignee: <@{slack_handle}>"
                        else:
                            assignee_str = f" | Assignee: @{slack_handle}"
                    
                    ticket_lines.append(
                        f"{status_icon} *<{url}|[{key}]>* {sum_text}\n"
                        f"    _Type: {itype} | Priority: {priority}{assignee_str}_"
                    )
                else:
                    sum_text = t.get("summary")
                    err = t.get("error", "API Error")
                    # Truncate error to avoid Slack's 3000-char block limit
                    if len(err) > 100:
                        err = err[:97] + "..."
                    ticket_lines.append(f"❌ *Failed to Create:* {sum_text} (Error: {err})")
            
            action_text = "\n\n".join(ticket_lines)
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*📋 Jira Action Items Created*\n{action_text}"
                }
            })
        else:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*📋 Jira Action Items*\n_No action items identified for Jira creation._"
                }
            })

        blocks.append({
            "type": "divider"
        })
        blocks.append({
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "⚡ *Origin Medical Workflow Automation Engine* • Human-approved"
                }
            ]
        })

        return blocks

    async def post_summary(self, title: str, summary: str, decisions: List[str], tickets: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Posts the summary and ticket hyperlinks to Slack asynchronously."""
        blocks = self.format_blocks(title, summary, decisions, tickets)

        if self.mock_mode or not self.client:
            if not self.client and not self.mock_mode:
                logger.warning("Slack WebClient is not initialized. Falling back to simulation mode.")
            logger.info("Simulating Slack post. Outputting Block Kit JSON:")
            logger.info(json.dumps(blocks, indent=2))
            
            preview_file = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "outputs", "slack_preview.json"))
            os.makedirs(os.path.dirname(preview_file), exist_ok=True)
            
            def save_to_file():
                with open(preview_file, 'w') as f:
                    json.dump(blocks, f, indent=2)

            await asyncio.to_thread(save_to_file)
            
            return {
                "success": True,
                "channel": self.channel_id,
                "ts": "mock_timestamp_12345.67890",
                "message": "Slack message simulated successfully. Payload logged to outputs/slack_preview.json"
            }

        def post():
            return self.client.chat_postMessage(
                channel=self.channel_id,
                text=f"Meeting Sync Summary: {title}",
                blocks=blocks
            )

        try:
            response = await asyncio.to_thread(post)
            logger.info(f"Posted meeting summary to Slack channel '{self.channel_id}' successfully.")
            return {
                "success": True,
                "channel": response.get("channel"),
                "ts": response.get("ts"),
                "message": "Slack message posted successfully."
            }
        except Exception as e:
            logger.error(f"Failed to post message to Slack: {e}")
            return {
                "success": False,
                "error": str(e)
            }

@tool
async def slack_post_summary_tool(title: str, summary: str, decisions: List[str], tickets_json: str) -> str:
    """
    Useful to post the final meeting summary, decisions log, and active Jira ticket links
    as a formatted Block Kit message to the team Slack channel.
    tickets_json must be a JSON string listing created tickets.
    """
    client = SlackClient()
    tickets = json.loads(tickets_json)
    result = await client.post_summary(
        title=title,
        summary=summary,
        decisions=decisions,
        tickets=tickets
    )
    return json.dumps(result)

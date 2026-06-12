import os
import sys
import unittest
import json
import asyncio
import shutil
from dotenv import load_dotenv
load_dotenv()

# Add project root to path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Import components
from src.ingestion.parser import TranscriptParser
from src.ai.extractor import AIExtractor, MeetingAnalysisSchema, ActionItemSchema
from src.integrations.jira_client import JiraClient
from src.integrations.slack_client import SlackClient
from src.utils.security import compute_fingerprint, generate_signature, verify_signature
from src.utils.database import Database

class TestWorkflowAutomation(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.vtt_file = os.path.join(project_root, "configs", "meeting_transcript.vtt")
        # Ensure database is initialized for tests
        await Database.initialize()

    async def asyncTearDown(self):
        # Gracefully close connection pool after each test
        await Database.close()

    async def test_vtt_parser(self):
        """Validates that the parser successfully ingests WebVTT files, cleans text, and estimates duration."""
        self.assertTrue(os.path.exists(self.vtt_file), "Default VTT transcript does not exist!")
        
        standardized_text, metadata = TranscriptParser.parse(self.vtt_file)
        
        self.assertEqual(metadata["file_type"], "VTT")
        self.assertTrue(metadata["file_size_bytes"] > 0)
        self.assertIn("Nancy Collins", metadata["detected_participants"])
        self.assertIn("Priya Mehta", metadata["detected_participants"])
        self.assertIn("Dr. Sarah Kwan", metadata["detected_participants"])
        
        self.assertIn("Transcript:", standardized_text)
        self.assertIn("[00:00:08] Nancy Collins:", standardized_text)
        
        # Test clean text utility
        dirty = "Hello \t \n\n\n World  "
        self.assertEqual(TranscriptParser.clean_text(dirty), "Hello\nWorld")

    async def test_security_fingerprint_and_signatures(self):
        """Verifies SHA-256 fingerprint generation and HMAC-SHA256 signature verification."""
        text = "Meeting dialogue transcript text."
        fingerprint1 = compute_fingerprint(text, {"param1": "val1"})
        fingerprint2 = compute_fingerprint(text, {"param1": "val1"})
        
        # Same text and parameters must result in identical fingerprints (determinism)
        self.assertEqual(fingerprint1, fingerprint2)
        
        # Different params must result in different fingerprints
        fingerprint3 = compute_fingerprint(text, {"param1": "val2"})
        self.assertNotEqual(fingerprint1, fingerprint3)
        
        # Test HMAC signature verification
        payload = '{"title": "Sync Meeting", "summary": "Text summary"}'
        signature = generate_signature(payload)
        
        # Verify matching payload
        self.assertTrue(verify_signature(payload, signature))
        
        # Verify modified/tampered payload fails validation
        tampered_payload = '{"title": "Sync Meeting", "summary": "Text summary tampered"}'
        self.assertFalse(verify_signature(tampered_payload, signature))

    async def test_ai_extractor_mock(self):
        """Verifies the AI extractor schema parsing, structures, and mock mode outputs."""
        extractor = AIExtractor(mock_mode=True)
        extracted = await extractor.extract("Mock transcript line")
        
        self.assertEqual(extracted["title"], "Patient Skin Cancer Education Brochure Alignment Meeting")
        self.assertTrue(len(extracted["decisions"]) > 0)
        self.assertTrue(len(extracted["action_items"]) > 0)
        
        # Validate Pydantic Schema compatibility
        validated = MeetingAnalysisSchema(**extracted)
        self.assertEqual(validated.title, extracted["title"])
        self.assertEqual(validated.action_items[0].assignee, "Priya")
        self.assertIn(validated.action_items[0].issue_type, ["Task", "Story", "Bug"])

    async def test_action_item_reranking(self):
        """Verifies deterministic action item sorting by priority and confidence descending."""
        from src.ai.graph import rerank_action_items
        
        test_state = {
            "uuid": "test-uuid",
            "action_items": [
                {"task": "Low Priority Item", "assignee": "Priya", "issue_type": "Story", "priority": "Low", "confidence": 0.95},
                {"task": "Highest Priority Item 1", "assignee": "Sarah", "issue_type": "Task", "priority": "Highest", "confidence": 0.80},
                {"task": "Highest Priority Item 2", "assignee": "Nancy", "issue_type": "Bug", "priority": "Highest", "confidence": 0.95},
                {"task": "Medium Priority Item", "assignee": "Priya", "issue_type": "Story", "priority": "Medium", "confidence": 0.90}
            ]
        }
        
        result = await rerank_action_items(test_state)
        sorted_items = result["action_items"]
        
        # Check sort order: Highest (0) to Lowest (4), and then confidence desc (0.95 before 0.80)
        self.assertEqual(sorted_items[0]["task"], "Highest Priority Item 2")
        self.assertEqual(sorted_items[1]["task"], "Highest Priority Item 1")
        self.assertEqual(sorted_items[2]["task"], "Medium Priority Item")
        self.assertEqual(sorted_items[3]["task"], "Low Priority Item")

    async def test_cyclic_graph_routing(self):
        """Verifies state graph routing decisions for feedback and sync errors."""
        from src.ai.graph import route_after_jira_map, route_after_sync
        
        # Scenario 1: Feedback present, retry count under limit
        state_feedback = {"feedback": "Fix assignees", "retry_count": 0}
        self.assertEqual(route_after_jira_map(state_feedback), "extract")
        
        # Scenario 2: Feedback present, retry count hits limit
        state_max_retry = {"feedback": "Fix assignees", "retry_count": 3}
        self.assertEqual(route_after_jira_map(state_max_retry), "sync_jira")
        
        # Scenario 3: Feedback empty/None
        state_no_feedback = {"feedback": None, "retry_count": 0}
        self.assertEqual(route_after_jira_map(state_no_feedback), "sync_jira")
        
        # Scenario 4: Sync successful
        state_sync_success = {"tickets": [{"success": True, "key": "OA-1"}], "error": ""}
        self.assertEqual(route_after_sync(state_sync_success), "slack_notify")
        
        # Scenario 5: Sync failure
        state_sync_fail = {"tickets": [{"success": False, "error": "Failed"}], "error": ""}
        self.assertEqual(route_after_sync(state_sync_fail), "jira_map")
        
        # Scenario 6: Sync exception/error in state
        state_sync_error = {"tickets": [], "error": "Fatal Error"}
        self.assertEqual(route_after_sync(state_sync_error), "jira_map")

    async def test_ai_extractor_feedback_mock(self):
        """Verifies AIExtractor processes feedback correctly in mock mode."""
        extractor = AIExtractor(mock_mode=True)
        
        # Test assign Nancy instruction
        extracted = await extractor.extract("Mock transcript", feedback="Please assign all tasks to Nancy")
        self.assertIn("Refined based on feedback", extracted["summary"])
        for item in extracted["action_items"]:
            self.assertEqual(item["assignee"], "Nancy")

    async def test_jira_client_mock(self):
        """Verifies that the Jira Client correctly simulates connection checks, user lookups, and ticket generation."""
        client = JiraClient(mock_mode=True)
        self.assertTrue(await client.test_connection())
        
        users = await client.get_users()
        self.assertEqual(len(users), 3)
        self.assertEqual(users[0]["displayName"], "Nancy Collins")
        
        # Create issue check
        res = await client.create_ticket(
            summary="Review draft",
            description="Testing Jira client",
            issue_type="Task",
            priority="Medium",
            assignee_id="acc-nancy-collins"
        )
        self.assertTrue(res["success"])
        self.assertTrue(res["key"].startswith(client.project_key + "-"))
        self.assertIn("browse", res["url"])

    async def test_slack_client_mock(self):
        """Verifies the Slack Web Client formats Block Kit messages and simulates posts."""
        client = SlackClient(mock_mode=True)
        tickets = [
            {"success": True, "key": "OA-123", "url": "https://jira.com/browse/OA-123", "summary": "Task 1", "issue_type": "Story", "priority": "High"},
            {"success": False, "summary": "Task 2", "error": "HTTP 401 Unauthorized"}
        ]
        
        res = await client.post_summary(
            title="Alignment Sync",
            summary="This is a summary of our discussion.",
            decisions=["Decision A", "Decision B"],
            tickets=tickets
        )
        
        self.assertTrue(res["success"])
        
        # Verify preview file was created
        preview_file = os.path.join(project_root, "outputs", "slack_preview.json")
        self.assertTrue(os.path.exists(preview_file))
        
        with open(preview_file, 'r') as f:
            blocks = json.load(f)
            self.assertEqual(blocks[0]["type"], "header")
            self.assertIn("Alignment Sync", blocks[0]["text"]["text"])

    async def test_postgres_db_cache(self):
        """Verifies database insertion, UUID associations, and cached fingerprint checks."""
        fingerprint = "test_fp_12345"
        run_uuid = "test-uuid-999"
        
        # Save a run state to the database
        await Database.save_run(
            uuid_val=run_uuid,
            fingerprint=fingerprint,
            title="Database Test Meeting",
            summary="This is a DB test run.",
            decisions=["Decision 1"],
            action_items=[{"task": "Task A", "assignee": "Priya", "issue_type": "Story", "priority": "Medium", "confidence": 1.0}],
            status="PENDING_REVIEW",
            date="2026-06-12"
        )
        
        # Query cached run using fingerprint
        cached = await Database.get_cached_run(fingerprint)
        self.assertIsNotNone(cached)
        self.assertEqual(cached["uuid"], run_uuid)
        self.assertEqual(cached["title"], "Database Test Meeting")
        self.assertEqual(cached["date"], "2026-06-12")
        self.assertEqual(cached["decisions"][0], "Decision 1")

        # Test long-term memory save & fetch
        await Database.save_long_term_memory("OA", "Past summary 1")
        await Database.save_long_term_memory("OA", "Past summary 2")
        
        past_mem = await Database.get_long_term_memory("OA", limit=2)
        self.assertEqual(len(past_mem), 2)
        self.assertEqual(past_mem[0], "Past summary 1")
        self.assertEqual(past_mem[1], "Past summary 2")

if __name__ == "__main__":
    unittest.main()

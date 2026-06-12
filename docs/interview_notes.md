# Origin Medical Internship Challenge - Technical Walkthrough & Interview Guide

This guide is prepared to help you defend every design decision, explain your architecture, discuss failure handling, and outline how you would extend or scale this automation in your follow-up interview call.

---

## 1. Architectural Decisions & Tradeoffs

### Why custom FastAPI + Vanilla Web UI over Zapier/Make?
- **Tradeoff**: No-code platforms (Make/Zapier) are quick to set up but introduce vendor lock-in, recurring license costs, and lack clean version control.
- **Defence**: A custom Python application using FastAPI represents engineering rigour. It is fully unit-testable, allows custom git-based CI/CD, doesn't require third-party licensing fees, and can be easily containerized using Docker to run on any cloud platform.

### Why separate Ingestion, AI Extraction, and Integrations?
- **Tradeoff**: Putting all logic in a single script is simpler but violates the **Single Responsibility Principle (SRP)**.
- **Defence**: We separate:
  1. `parser.py` (Ingestion & Normalization)
  2. `extractor.py` (AI Core)
  3. `jira_client.py` & `slack_client.py` (API clients)
  4. `app.py` (Presentation & Review)
  This modular structure ensures that changes to the Jira REST API layout do not affect the WebVTT parser logic, and changing the AI model from Gemini to another LLM only requires modifying a single client class.

---

## 2. Ingestion Pipeline & Normalization Rules

### How do we handle diverse inputs?
- For subtitle files (**WebVTT / SRT**): We strip subtitle index headers and style blocks, parse timestamps into standard formats (`[HH:MM:SS]`), and group lines under speaker identifiers.
- For **PDFs / Word docs**: We parse text page-by-page or cell-by-cell, merging duplicate line breaks.
- **Standardized representation**: All parsed files are normalized into:
  ```text
  Meeting Information
  File Name: ...
  Detected Participants: ...
  Estimated Duration: ...

  Transcript:
  [Timestamp] Speaker: Statement
  ```
  This is the *only* text format passed to Gemini. By keeping the input format identical regardless of source, we increase extraction quality and reduce model hallucination.

---

## 3. Human-in-the-Loop (HITL) Design

### Why are there 4 distinct gates?
1. **Gate 1 (Ingestion Parser)**: Catch character encoding glitches, corrupted PDF layouts, or OCR typos *before* spending token budgets on the LLM.
2. **Gate 2 (AI summary & items)**: AI is non-deterministic and can miss items or hallucinate tasks. This gate allows the coordinator to refine task descriptions, remove irrelevant items, or change priorities.
3. **Gate 3 (Jira Mappings)**: Ensures ticket assignments are accurate. In transcripts, speakers might go by first names (e.g. "Priya"), which must be mapped to valid Jira account IDs. If an assignee is unknown, the dashboard blocks submission until selected from a dropdown of active Jira users.
4. **Gate 4 (Slack Broadcast)**: Previews the final Slack Block Kit layout to ensure formatting looks clean and links are active.

---

## 4. Failure Scenarios & Edge Case Mitigation

### Q: What happens if the Jira API goes down midway through creating 10 tickets?
- **Answer**: The Jira creation loop uses a transactional tracking pattern. It logs the status of each ticket creation. If ticket #5 fails, the system logs the error but does not roll back successfully created tickets. The dashboard displays the failure and offers a "Retry Failed Tickets" button. This prevents duplicate ticket creation for tasks #1 through #4.

### Q: How do you handle Safety Filters on the Gemini API?
- **Answer**: Clinical syncs discussing skin cancer, lesions, or medical treatments can occasionally trip safety filters (classified as "medical advice" or "harmful content"). The extractor handles API exceptions by catching safety filter blocks, and the dashboard falls back to warning the coordinator or loading a pre-analyzed layout, allowing manual entry instead of crashing the pipeline.

### Q: What if multiple meeting participants map to the same person?
- **Answer**: We handle this using alias arrays in `configs/user_mappings.json`. Multiple keys (e.g., `"Sarah"`, `"Dr. Sarah Kwan"`, `"Kwan"`) can point to the same email. This also allows mapping all participants to a single email address for debugging.

---

## 5. Scaling and Production Enhancements

If given more time or budget, we would implement the following production upgrades:
1. **Asynchronous Task Queue (Celery/Redis)**: Instead of running extraction and API calls synchronously on FastAPI, run them as background tasks.
2. **User Directory Synchronization**: Automatically poll the Jira directory every 24 hours to sync the local `user_mappings.json` automatically, keeping list mapping up-to-date.
3. **Semantic Duplicate Detection**: Use vector embeddings (e.g. cosine similarity) to check if an extracted action item already exists on the Jira board, preventing duplicate tickets across subsequent sprint planning syncs.
4. **Multi-Tenant OAuth**: Replace Basic Authentication with OAuth 2.0, allowing multiple teams to connect their individual Jira and Slack workspaces securely.

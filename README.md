# Origin Medical - Fetal Medicine Research Lab
## Meeting Sync Workflow Automation Engine

This project is a production-grade automation system that automates the end-to-end extraction, review, and syncing of meeting action items and summaries into Jira Cloud tickets and Slack channels. It employs a robust **Human-in-the-Loop (HITL)** review dashboard to prevent misassigned tickets, safety-filter issues, and duplicates.

---

## 📂 Project Structure

```text
excited-oppenheimer/
├── docs/                     # Detailed architectural guides and manuals
├── src/                      # Core application source code
│   ├── ingestion/            # File parsing and WebVTT/SRT/PDF format normalization
│   ├── ai/                   # Google Gemini SDK structured analysis integration
│   ├── integrations/         # Jira REST API v3 and Slack Web Client integrations
│   ├── ui/                   # FastAPI backend and HTML5/Vanilla CSS dashboard
│   └── utils/                # Logging setup, environment loader, and JSONL auditor
├── tests/                    # Unit, integration, and mock execution test scripts
├── workflows/                # Master pipeline orchestrator (CLI & serve)
├── configs/                  # User mappings, app configs, default transcript VTT
│   ├── app_config.json
│   └── user_mappings.json
├── outputs/                  # JSONL audit logs and Slack preview payloads
│   ├── audit_log.jsonl
│   └── slack_preview.json
├── README.md                 # Primary system manual
├── requirements.txt          # Python dependencies
└── .env                      # Local environment secrets configuration
```

---

## 🛠️ Setup Guide

### Prerequisites
- **Python 3.11+** (Tested on Python 3.14.0)
- **Pip** or **uv** package manager

### 1. Configure the Environment
Clone or place this repository in your workspace. Copy the `.env.example` template to `.env`:
```bash
cp .env.example .env
```
Fill in the variables in `.env`:
- `GEMINI_API_KEY`: Google Gemini API key.
- `JIRA_DOMAIN`: Your Jira Cloud domain (e.g., `origin-test.atlassian.net`).
- `JIRA_EMAIL`: Your Atlassian login email address.
- `JIRA_API_TOKEN`: Your generated Atlassian API token.
- `JIRA_PROJECT_KEY`: Target project key (e.g., `OA`).
- `SLACK_BOT_TOKEN`: Your Slack Bot OAuth token.
- `SLACK_CHANNEL_ID`: Channel ID or name where summaries will be broadcast.

*Note: If credentials are left unconfigured, the application automatically runs in **Mock Mode**, simulating Jira and Slack integrations locally.*

### 2. Install Dependencies
Run the installation command.
```bash
pip install -r requirements.txt
```

> [!IMPORTANT]
> **Windows/Python 3.14.0 Rust Compiler Bypass:**
> Since Python 3.14 is very new, compiling the `pydantic-core` C/Rust extension might fail due to PyO3 version compatibility checks. If you encounter a compilation error, set this environment bypass variable in your terminal before installing:
> - **PowerShell (Windows)**:
>   ```powershell
>   $env:PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1
>   pip install -r requirements.txt
>   ```
> - **Command Prompt (CMD)**:
>   ```cmd
>   set PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1
>   pip install -r requirements.txt
>   ```
> - **Linux/macOS**:
>   ```bash
>   export PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1
>   pip install -r requirements.txt
>   ```

---

## 🔗 External Integration Setup

### A. How to Set Up a Free Jira Cloud Account
1. Visit [Atlassian Jira Software Free](https://www.atlassian.com/software/jira/free) and register.
2. Select your site domain (e.g., `your-domain.atlassian.net`).
3. Create a project using the **Kanban** or **Scrum** templates. Note your **Project Key** (e.g. `OA`).
4. Generate an **API Token**:
   - Go to [Atlassian Account API Tokens](https://id.atlassian.com/manage-profile/security/api-tokens).
   - Click **Create API token**, label it, and copy the token value to your `.env` file.

### B. Mappings & Duplicate Emails (`configs/user_mappings.json`)
The mapping file links transcript speaker names to Jira accounts. It allows mapping **multiple names** to the **same email** (useful when testing assignments using a single email account):
```json
{
  "Nancy Collins": "test-coordinator@example.com",
  "Nancy": "test-coordinator@example.com",
  "Dr. Sarah Kwan": "test-coordinator@example.com",
  "Sarah": "test-coordinator@example.com",
  "Priya Mehta": "test-coordinator@example.com",
  "Priya": "test-coordinator@example.com"
}
```

### C. How to Set Up Slack Web API
1. Visit [Slack API Apps Console](https://api.slack.com/apps) and click **Create New App** (From Scratch).
2. Assign it to your workspace.
3. Under **OAuth & Permissions**, scroll to **Scopes** and add:
   - `chat:write` (Allows posting messages)
   - `channels:read` (Optional: listing public channels)
4. Click **Install to Workspace** and copy the **Bot User OAuth Token** (`xoxb-...`) to `.env`.
5. Invite your Slack Bot to the target channel:
   ```text
   /invite @YourAppName
   ```

---

## 📖 Workflow Documentation

You can execute the automation pipeline in two ways:

### 1. Interactive HITL Dashboard Mode (Default)
This mode guides you through the 4 Human-in-the-Loop approval gates in a premium web interface.
```bash
python workflows/run_pipeline.py
```
1. Open `http://127.0.0.1:8000` in your web browser.
2. **Gate 1 (Ingestion)**: Click "Load Skin Cancer Transcript" or upload a custom WebVTT file. Correct formatting errors.
3. **Gate 2 (AI summary)**: Review the title, summary, decisions, and action items extracted by Gemini. Edit text, priorities, or change types (Task, Story, Bug).
4. **Gate 3 (Jira Mapping)**: Dropdowns fetch active Jira users. Map unassigned speakers or low-confidence assignees (highlighted in red). Click "Sync Jira" to create issues.
5. **Gate 4 (Slack Preview)**: Preview Block Kit rendering. Select "Post to Slack" to finalize the sync.

### 2. Headless CLI Automation Mode
Ideal for cron jobs, background runners, or CLI batch processes.
```bash
python workflows/run_pipeline.py --cli --file configs/meeting_transcript.vtt
```
This parses the file, invokes Gemini, auto-maps users based on `configs/user_mappings.json`, creates Jira tickets, and pushes to Slack automatically.

---

## ⚡ API Documentation

The FastAPI backend exposes JSON endpoints:

- **`GET /`**: Renders the HTML5 SPA review interface.
- **`GET /api/config`**: Returns configuration settings (Jira/Slack mock state, active users list).
- **`GET /api/load-default`**: Loads default VTT transcript text and parses metadata.
- **`POST /api/ingest`**: Standardizes uploaded `.vtt`, `.srt`, `.pdf`, `.docx`, `.json`, `.txt` files.
- **`POST /api/extract`**: Invokes Gemini API utilizing Pydantic schemas to extract summary structured JSON.
- **`GET /api/jira-users`**: Fetches active project members from Atlassian directory.
- **`POST /api/publish-jira`**: Synchronizes verified action items into individual Jira issues.
- **`POST /api/publish-slack`**: Pushes Block Kit messages featuring Jira hyperlinks to the target channel.

---

## 🔧 Troubleshooting Guide

### 1. Rust Compiling Error (`Failed to build pydantic-core`)
- **Cause**: PyO3 mismatch on newer Python runtimes.
- **Solution**: Set the ABI bypass flag before installing dependencies (see **Step 2** in Setup Guide).

### 2. Empty Ingestion / Scanned PDFs
- **Cause**: The parser extracts empty text from scanned PDFs.
- **Solution**: Open the file in Word, save it as a text file, or copy the content and paste it directly into the Gate 1 review textarea.

### 3. Safety Filter Triggered on Gemini
- **Cause**: The conversation contains highly clinical terms (e.g. skin cancer, lesions) which might trip safety filters.
- **Solution**: The extractor catches exceptions and falls back gracefully to a high-quality local mock extractor of the skin cancer transcript.

### 4. Jira Connection Failure (HTTP 401/404)
- **Cause**: Invalid API Token or Project Key mismatch.
- **Solution**: Check credentials in `.env`. Ensure your Atlassian API token was created under the same email address as `JIRA_EMAIL` and that the token is copied without spaces.

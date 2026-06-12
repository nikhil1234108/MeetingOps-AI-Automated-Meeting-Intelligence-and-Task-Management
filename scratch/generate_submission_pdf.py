import os
from fpdf import FPDF

class SubmissionPDF(FPDF):
    def header(self):
        if self.page_no() > 1:
            self.set_font("helvetica", "B", 9)
            self.set_text_color(0, 51, 102) # Dark blue
            self.cell(0, 10, "MeetingOps - AI-Automated Meeting Intelligence & Task Management", border=0, align="L")
            self.set_draw_color(0, 51, 102)
            self.line(10, 18, 200, 18)
            self.ln(12)

    def footer(self):
        self.set_y(-15)
        self.set_font("helvetica", "I", 8)
        self.set_text_color(128)
        self.cell(0, 10, f"Page {self.page_no()}/{{nb}} | Candidate: Nikhil Sai Vempati", 0, 0, "C")

def generate_pdf():
    pdf = SubmissionPDF()
    pdf.alias_nb_pages()
    pdf.add_page()
    
    # ------------------ TITLE PAGE ------------------
    pdf.set_font("helvetica", "B", 22)
    pdf.set_text_color(0, 51, 102) # Dark blue
    pdf.cell(0, 25, "Role Challenge Submission Report", ln=True, align="C")
    
    pdf.set_font("helvetica", "B", 13)
    pdf.set_text_color(51, 51, 51)
    pdf.cell(0, 10, "MeetingOps: AI-Automated Meeting Intelligence & Task Management", ln=True, align="C")
    pdf.ln(10)
    
    # Horizontal rule
    pdf.set_draw_color(0, 51, 102)
    pdf.set_line_width(0.8)
    pdf.line(40, 55, 170, 55)
    pdf.ln(15)
    
    # Candidate Info Table-style
    pdf.set_font("helvetica", "B", 11)
    pdf.set_text_color(0, 51, 102)
    pdf.cell(45, 8, "Candidate Name:", ln=False)
    pdf.set_font("helvetica", "", 11)
    pdf.set_text_color(51, 51, 51)
    pdf.cell(0, 8, "Nikhil Sai Vempati", ln=True)
    
    pdf.set_font("helvetica", "B", 11)
    pdf.set_text_color(0, 51, 102)
    pdf.cell(45, 8, "Submission Date:", ln=False)
    pdf.set_font("helvetica", "", 11)
    pdf.set_text_color(51, 51, 51)
    pdf.cell(0, 8, "June 12, 2026", ln=True)
    
    pdf.set_font("helvetica", "B", 11)
    pdf.set_text_color(0, 51, 102)
    pdf.cell(45, 8, "Primary Repository:", ln=False)
    pdf.set_font("helvetica", "", 11)
    pdf.set_text_color(0, 0, 255) # Blue for link
    repo_url = "https://github.com/nikhil1234108/MeetingOps-AI-Automated-Meeting-Intelligence-and-Task-Management"
    pdf.cell(0, 8, "GitHub Repository Link", link=repo_url, ln=True)
    
    pdf.ln(15)
    
    # ------------------ SECTION 1: HYPERLINKS ------------------
    pdf.set_font("helvetica", "B", 14)
    pdf.set_text_color(0, 51, 102)
    pdf.cell(0, 10, "1. Project Submission Hyperlinks", ln=True)
    
    pdf.set_font("helvetica", "", 10.5)
    pdf.set_text_color(51, 51, 51)
    pdf.write(5, "This role challenge is structured with all source code, workflows, configurations, and outputs pushed to a public GitHub repository. Below are active hyperlinks pointing directly to the components of the solution:\n\n")
    
    def add_link_item(label, text, url_suffix):
        full_url = repo_url + url_suffix if url_suffix.startswith("/") else url_suffix
        pdf.set_font("helvetica", "B", 11)
        pdf.set_text_color(0, 51, 102)
        pdf.write(6, f"  * {label}: ")
        pdf.set_font("helvetica", "", 11)
        pdf.set_text_color(0, 0, 255)
        pdf.write(6, text, link=full_url)
        pdf.set_text_color(51, 51, 51)
        pdf.ln()

    add_link_item("GitHub Project Repository", "nikhil1234108/MeetingOps-AI-Automated-Meeting-Intelligence", "")
    add_link_item("Meeting Transcript (WebVTT File)", "configs/meeting_transcript.vtt", "/blob/master/configs/meeting_transcript.vtt")
    add_link_item("Automation Source Directory", "src/ Core Codebase", "/tree/master/src")
    add_link_item("Jira & Slack Pipeline Runner", "workflows/run_pipeline.py", "/blob/master/workflows/run_pipeline.py")
    add_link_item("Created Jira Tickets (Jira Outputs Folder)", "jira_outputs Folder", "/tree/master/jira_outputs")
    add_link_item("Slack Summary Broadcasts (Slack Outputs Folder)", "Slack_Outpu_Screenshorts Folder", "/tree/master/Slack_Outpu_Screenshorts")
    
    pdf.ln(10)
    
    # ------------------ SECTION 2: ARCHITECTURE ------------------
    pdf.set_font("helvetica", "B", 14)
    pdf.set_text_color(0, 51, 102)
    pdf.cell(0, 10, "2. System Architecture & Approach", ln=True)
    
    pdf.set_font("helvetica", "", 10.5)
    pdf.set_text_color(51, 51, 51)
    
    pdf.set_font("helvetica", "B", 11)
    pdf.write(6, "  A. Multi-Format Ingestion & Sanitization:\n")
    pdf.set_font("helvetica", "", 10.5)
    pdf.write(5, "     The ingestion engine supports transcripts in WebVTT, SRT, PDF, DOCX, JSON, and TXT formats. Files are sanitized using HTML escaping to protect the downstream UI and LLM integrations from XSS or code injection payloads. The VTT parser handles block timings, speaker identifiers, and dialog normalization.\n\n")
    
    pdf.set_font("helvetica", "B", 11)
    pdf.write(6, "  B. Structured AI Extraction (Google Gemini API):\n")
    pdf.set_font("helvetica", "", 10.5)
    pdf.write(5, "     Uses the Google Gemini API bound to Pydantic structured schemas (`MeetingAnalysisSchema`) to guarantee structured JSON output (title, date, summary, decisions list, action items). LLM errors are propagated as critical failures instead of silently falling back to mock data.\n\n")
    
    pdf.add_page() # Move to page 2 for rest of write-up
    
    pdf.set_font("helvetica", "B", 11)
    pdf.write(6, "  C. Human-in-the-Loop (HITL) Web Interface:\n")
    pdf.set_font("helvetica", "", 10.5)
    pdf.write(5, "     FastAPI serves a premium dashboard built using clean HTML5 and Vanilla CSS. The UI features four sequential approval gates: Ingestion Review, AI Extraction Verification, Jira Speaker-to-User Mapping, and Slack Block Kit Broadcast Preview. Users can edit extracted titles, summaries, decisions, assignee mappings, and ticket metadata (e.g., priorities or ticket types) prior to external synchronizations.\n\n")
    
    pdf.set_font("helvetica", "B", 11)
    pdf.write(6, "  D. State Persistence & Safety Signatures:\n")
    pdf.set_font("helvetica", "", 10.5)
    pdf.write(5, "     Migrated the checkpointer context manager from SQLite to PostgreSQL (`AsyncPostgresSaver`) to support enterprise-grade concurrency and thread safety. Transcripts and state checkpointer tables are tracked using SHA-256 fingerprint caching. To ensure data integrity, state payloads are signed and verified using an HMAC-SHA256 signature to block client-side tampering of approved details.\n\n")

    pdf.set_font("helvetica", "B", 11)
    pdf.write(6, "  E. Robust Integration Adapters:\n")
    pdf.set_font("helvetica", "", 10.5)
    pdf.write(5, "     - Jira Adapter: Leverages a `requests.Session` mounted with urllib3 retry adapters to automatically recover from rate limits (HTTP 429) and transient 5xx server issues using exponential backoff.\n"
                 "     - Slack Adapter: Broadcasts rich Block Kit layouts containing clickable ticket links. Resolves speakers to their Slack handles using a local `slack_mappings.json` file to safely mention assignees without requiring broad directory-read scopes.\n\n")

    pdf.set_font("helvetica", "B", 11)
    pdf.write(6, "  F. Cyclic Feedback Loops & Action Item Reranking:\n")
    pdf.set_font("helvetica", "", 10.5)
    pdf.write(5, "     Implemented a fully cyclic LangGraph workflow. If the user provides corrections/feedback, the state machine loops back to the AI extraction node for regeneration (enforcing a 3-attempt safety limit). Sync failures also loop back to the mapping step. Action items are automatically and deterministically reranked by priority and confidence score descending.\n\n")

    pdf.add_page() # Move to page 3 for Section 3 & 4
    
    # ------------------ SECTION 3: ASSUMPTIONS ------------------
    pdf.set_font("helvetica", "B", 14)
    pdf.set_text_color(0, 51, 102)
    pdf.cell(0, 10, "3. Design Assumptions & Edge Cases Handled", ln=True)
    
    pdf.set_font("helvetica", "", 10.5)
    pdf.set_text_color(51, 51, 51)
    
    pdf.write(5, "  * GDPR Directory Email Hiding: Atlassian Jira Cloud V3 hides user emails by default (`no-email@atlassian.com`). To circumvent this, the engine performs case-insensitive display name matching (e.g. mapping transcript 'Priya' to displayName 'Priya') to identify account IDs.\n"
                 "  * Slack Block Limits: Slack Block Kit text fields crash if a block exceeds 3000 characters. To prevent crashes from long error details, error descriptions are safely truncated to 100 characters.\n"
                 "  * Environment Fallback: If `HMAC_SECRET_KEY` is omitted from `.env` in production, the engine dynamically generates a cryptographically secure `secrets.token_bytes(32)` sequence for the active session, resolving security audit concerns of hardcoded default secrets.\n\n")

    pdf.ln(5)

    # ------------------ SECTION 4: FUTURE IMPROVEMENTS ------------------
    pdf.set_font("helvetica", "B", 14)
    pdf.set_text_color(0, 51, 102)
    pdf.cell(0, 10, "4. Future Enhancements Given More Time", ln=True)
    
    pdf.set_font("helvetica", "", 10.5)
    pdf.set_text_color(51, 51, 51)
    
    pdf.write(5, "  1. Dynamic Jira Directory Synchronization: Implement a background worker to periodically poll the Jira Users API and sync display names/emails into local configs.\n"
                 "  2. OAuth 2.0 Integration: Replace basic authorization tokens with proper user-authorized OAuth flows for Slack and Atlassian, securing tenant access.\n"
                 "  3. Native Voice Transcription: Add direct support for MP3/WAV/MP4 file uploads in the ingestion gate, using Gemini's native multimodal audio capabilities to transcribe and summarize in one step.\n\n")
    
    pdf.ln(10)
    
    # Signature
    pdf.set_font("helvetica", "I", 11)
    pdf.set_text_color(0, 51, 102)
    pdf.cell(0, 10, "Submitted by Nikhil Sai Vempati - Lead Software Engineer", ln=True, align="R")

    # Output file
    output_pdf_path = r"C:\Users\Dell\Documents\antigravity\excited-oppenheimer\MeetingOps_Submission_v2.pdf"
    pdf.output(output_pdf_path)
    print("PDF successfully generated at:", output_pdf_path)
    
    # Also copy to outputs/ and jira_outputs/
    import shutil
    shutil.copy(output_pdf_path, r"C:\Users\Dell\Documents\antigravity\excited-oppenheimer\jira_outputs\MeetingOps_Submission_v2.pdf")
    print("PDF copied to jira_outputs/MeetingOps_Submission_v2.pdf")

if __name__ == "__main__":
    generate_pdf()

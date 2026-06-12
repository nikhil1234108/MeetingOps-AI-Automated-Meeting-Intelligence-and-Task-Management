import os
import json
import logging
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
from typing import Literal

# Try importing LangChain Google GenAI bindings, allow fallback if missing
try:
    from langchain_google_genai import ChatGoogleGenerativeAI
    from langchain_core.prompts import ChatPromptTemplate
    LANGCHAIN_AVAILABLE = True
except ImportError:
    LANGCHAIN_AVAILABLE = False

logger = logging.getLogger("WorkflowAutomation")

class ActionItemSchema(BaseModel):
    task: str = Field(description="Clear and concise description of the task.")
    assignee: str = Field(description="The name of the participant assigned to the task (e.g., 'Priya' or 'Nancy'), or 'UNKNOWN' if not mentioned.")
    issue_type: Literal["Task", "Story", "Bug"] = Field(description="Dynamic Jira issue classification: 'Bug' for fixes/errors/creams/aftercare issues; 'Story' for feature sections, major writing parts, research spikes; 'Task' for operational, scheduling, note-compiling, or general items.")
    priority: Literal["Highest", "High", "Medium", "Low", "Lowest"] = Field(default="Medium", description="The priority level of the task based on its urgency/impact in the conversation.")
    confidence: float = Field(description="Confidence score between 0.0 and 1.0 of the extraction and assignee mapping.")

class MeetingAnalysisSchema(BaseModel):
    title: str = Field(description="Descriptive title of the meeting.")
    date: str = Field(description="Date of the meeting in YYYY-MM-DD format if mentioned, else 'UNKNOWN'.")
    summary: str = Field(description="A concise summary of the meeting context and outcomes (3-5 sentences).")
    decisions: List[str] = Field(description="List of key decisions made during the meeting.")
    action_items: List[ActionItemSchema] = Field(description="List of extracted action items.")


class AIExtractor:
    """
    Interfaces with Gemini using LangChain to extract structured summaries,
    decisions, and action items, incorporating long-term memory context.
    """

    def __init__(self, mock_mode: bool = False):
        self.mock_mode = mock_mode
        self.api_key = os.getenv("GEMINI_API_KEY")

        if not self.api_key or self.api_key == "your_gemini_api_key_here":
            logger.warning("Gemini API Key not configured. Forcing Mock Mode in LangChain Extractor.")
            self.mock_mode = True

        self.model = None
        if LANGCHAIN_AVAILABLE and not self.mock_mode:
            try:
                # Initialize ChatGoogleGenerativeAI (LangChain binding)
                self.model = ChatGoogleGenerativeAI(
                    model="gemini-2.5-flash", # LangChain Gemini 2.5 stable flash
                    google_api_key=self.api_key,
                    temperature=0.1
                )
            except Exception as e:
                logger.error(f"Failed to initialize LangChain Gemini: {e}. Falling back to mock mode.")
                self.mock_mode = True

    async def extract(self, standardized_transcript: str, long_term_memory: List[str] = None, feedback: str = None) -> Dict[str, Any]:
        """
        Sends transcript and historical memory to Gemini using LangChain structured tool calling.
        """
        if self.mock_mode:
            logger.info("AIExtractor running in MOCK mode. Returning simulated extraction.")
            return self._get_mock_extraction(feedback=feedback)

        # Format long-term memory context
        memory_context = ""
        if long_term_memory:
            memory_context = "\n=== LONG-TERM HISTORICAL CONTEXT (Past Meeting Summaries) ===\n"
            for i, past_sum in enumerate(long_term_memory):
                memory_context += f"Previous Sync {i+1}: {past_sum}\n"
            memory_context += "============================================================\n"

        system_instruction = (
            "You are a professional assistant specialized in medical/clinical product sync parsing.\n"
            "Analyze the transcript and extract structural information matching the schema."
        )

        feedback_instruction = ""
        if feedback:
            feedback_instruction = f"""
=== IMPORTANT: HUMAN FEEDBACK / CORRECTION ON PREVIOUS EXTRACTION ===
The human operator provided the following corrections/feedback on the previous extraction:
"{feedback}"
Please adapt your extraction (summary, decisions, and action items) to incorporate this feedback completely.
====================================================================
"""

        user_prompt = f"""
        {memory_context}
        {feedback_instruction}
        
        Analyze this meeting transcript and extract structured details:
        
        Transcript Content:
        {standardized_transcript}
        """

        try:
            # Bind the structured schema as a tool-calling format
            structured_llm = self.model.with_structured_output(MeetingAnalysisSchema)
            
            # Run the invocation
            res = await structured_llm.ainvoke(user_prompt)
            
            # Convert schema back to JSON dict
            data = res.model_dump()
            logger.info("Successfully completed async AI extraction via LangChain Gemini API.")
            return data
        except Exception as e:
            logger.critical(f"Error during LangChain Gemini invocation: {e}.")
            raise e

    def _get_mock_extraction(self, feedback: str = None) -> Dict[str, Any]:
        """Provides high-quality mock data matching the patient brochure transcript."""
        data = {
            "title": "Patient Skin Cancer Education Brochure Alignment Meeting",
            "date": "2026-06-12",
            "summary": "The clinical and product teams aligned on the structure and core content for the upcoming patient skin cancer brochure. Dr. Kwan explained the medical distinctions between UVA and UVB rays, basal cell carcinoma, squamous cell carcinoma, actinic keratoses, and melanoma. The team agreed on standardizing patient descriptions, highlighting warning signs of treatment reactions, and specifying broad-spectrum mineral sunscreen recommendations.",
            "decisions": [
                "Structure the brochure starting with the basics of UV radiation followed by descriptions of specific skin lesions.",
                "Incorporate the real-world 'truck driver scenario' to illustrate window glass UVA exposure.",
                "Create a dedicated FAQ section to address patient misconceptions (e.g. whether squamous cell can turn into melanoma).",
                "Explain the practical geometry of surgical excision to manage post-op expectations around scar lengths.",
                "Ensure warnings for topical reactions (crusting/redness) and PDT aftercare (strict sun avoidance for 48 hours) are prominent.",
                "Recommend broad-spectrum mineral sunscreens containing zinc oxide (e.g., Sheer Zinc SPF 50, EltaMD, COTZ) over chemical sunscreens."
            ],
            "action_items": [
                {
                    "task": "Draft the brochure section describing the truck driver scenario to explain UVA exposure through window glass.",
                    "assignee": "Priya",
                    "issue_type": "Story",
                    "priority": "High",
                    "confidence": 0.95
                },
                {
                    "task": "Create the FAQ section, specifically addressing 'Can one type of skin cancer turn into another?'.",
                    "assignee": "Priya",
                    "issue_type": "Story",
                    "priority": "Medium",
                    "confidence": 0.95
                },
                {
                    "task": "Write an explanation of the surgical geometry of excision (why scars are three times the lesion size) to prevent post-op confusion.",
                    "assignee": "Priya",
                    "issue_type": "Story",
                    "priority": "Medium",
                    "confidence": 0.90
                },
                {
                    "task": "Add a prominent warning in the brochure explaining that topical creams (imiquimod/5-FU) cause red, crusting reactions which show the treatment is working.",
                    "assignee": "Priya",
                    "issue_type": "Bug",
                    "priority": "High",
                    "confidence": 0.92
                },
                {
                    "task": "Add a strict warning in the aftercare section requiring 48 hours of complete sun avoidance post-PDT treatment.",
                    "assignee": "Priya",
                    "issue_type": "Bug",
                    "priority": "High",
                    "confidence": 0.95
                },
                {
                    "task": "Incorporate specific drugstore mineral sunscreen product recommendations (Neutrogena Sheer Zinc, EltaMD, COTZ) into the prevention section.",
                    "assignee": "Priya",
                    "issue_type": "Story",
                    "priority": "Medium",
                    "confidence": 0.88
                },
                {
                    "task": "Schedule the next follow-up sync meeting for two weeks from now once the draft is ready for review.",
                    "assignee": "Nancy",
                    "issue_type": "Task",
                    "priority": "Medium",
                    "confidence": 0.95
                },
                {
                    "task": "Review the finalized brochure draft once Priya submits it next Friday.",
                    "assignee": "Sarah",
                    "issue_type": "Task",
                    "priority": "High",
                    "confidence": 0.90
                }
            ]
        }
        
        if feedback:
            feedback_clean = feedback.strip()
            data["summary"] += f" (Refined based on feedback: {feedback_clean})"
            data["decisions"].append(f"Refinement Decision: Addressed human feedback: '{feedback_clean}'")
            
            # Check for assign to Nancy instruction
            if "assign" in feedback_clean.lower() and "nancy" in feedback_clean.lower():
                for item in data["action_items"]:
                    item["assignee"] = "Nancy"
            elif "assign" in feedback_clean.lower() and "sarah" in feedback_clean.lower():
                for item in data["action_items"]:
                    item["assignee"] = "Sarah"
            elif "assign" in feedback_clean.lower() and "priya" in feedback_clean.lower():
                for item in data["action_items"]:
                    item["assignee"] = "Priya"
                    
        return data

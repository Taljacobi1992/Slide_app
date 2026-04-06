import re
import json
import os
from huggingface_hub import InferenceClient
from dotenv import load_dotenv
from revision_manager import RevisionManager
from config import MODEL_NAME

load_dotenv()


# ──────────────────────────────────────────────
#  Global State
# ──────────────────────────────────────────────

deck_state = {
    "skeleton": None,
    "agent": None,
    "revision_manager": RevisionManager(),
    "pending_outline": None,
    "user_prompt": "",
    "document_text": "",
}


#  Slide Helpers

def get_slide_choices():
    if deck_state["skeleton"] is None:
        return []
    choices = []
    for slide in deck_state["skeleton"].get("slides", []):
        num = slide.get("slide_num", "?")
        desc = slide.get("slide_description", "ללא תיאור")
        choices.append(f"[שקף {num}] {desc}")
    return choices


def parse_slide_num_from_selection(selection: str) -> str | None:
    match = re.match(r"\[שקף (.+?)\]", selection)
    return match.group(1) if match else None


def get_slide_by_num(slide_num: str) -> dict | None:
    if deck_state["skeleton"] is None:
        return None
    for slide in deck_state["skeleton"]["slides"]:
        if str(slide.get("slide_num", "")) == slide_num:
            return slide
    return None


def detect_slide_count(user_prompt: str) -> int | None:
    patterns = [
        r'(\d+)\s*שקפים',
        r'(\d+)\s*שקף',
        r'(\d+)\s*slides?',
        r'מצגת\s*(?:של|בת|עם)\s*(\d+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, user_prompt)
        if match:
            return int(match.group(1))
    return None


#  LLM Helpers

def call_edit_llm(prompt: str) -> str:
    agent = deck_state["agent"]
    response = InferenceClient(
        provider="groq",
        api_key=os.getenv("HF_TOKEN")
    ).chat.completions.create(
        model=agent.model_name,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        max_tokens=1000
    )
    return response.choices[0].message.content


def call_llm_raw(prompt: str, model_name: str = MODEL_NAME) -> str:
    response = InferenceClient(
        provider="groq",
        api_key=os.getenv("HF_TOKEN")
    ).chat.completions.create(
        model=model_name,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=2000
    )
    return response.choices[0].message.content


def parse_llm_json(raw_response: str) -> dict:
    cleaned = raw_response.strip()
    if cleaned.startswith("```"):
        cleaned = "\n".join(cleaned.split("\n")[1:])
    if cleaned.endswith("```"):
        cleaned = "\n".join(cleaned.split("\n")[:-1])
    return json.loads(cleaned)
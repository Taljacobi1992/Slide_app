import re
from typing import Optional
from utils.revision_manager import RevisionManager


#  Global app state

deck_state: dict = {
    "skeleton": None,
    "agent": None,
    "revision_manager": RevisionManager(),
    "pending_outline": None,
    "user_prompt": "",
    "document_text": "",
}


#  Slide selection helpers

def get_slide_choices() -> list[str]:
    """Return a list of slide label strings for the Gradio dropdown."""
    if deck_state["skeleton"] is None:
        return []
    choices: list[str] = []
    for slide in deck_state["skeleton"].get("slides", []):
        num = slide.get("slide_num", "?")
        desc: str = slide.get("slide_description", "ללא תיאור")
        choices.append(f"[שקף {num}] {desc}")
    return choices


def parse_slide_num_from_selection(selection: str) -> Optional[str]:
    """Extract the slide number string from a '[שקף X] ...' dropdown value."""
    match: Optional[re.Match] = re.match(r"\[שקף (.+?)\]", selection)
    return match.group(1) if match else None


def get_slide_by_num(slide_num: Optional[str]) -> Optional[dict]:
    """Look up a slide dict in the current skeleton by its slide_num."""
    if deck_state["skeleton"] is None or slide_num is None:
        return None
    for slide in deck_state["skeleton"]["slides"]:
        if str(slide.get("slide_num", "")) == slide_num:
            return slide
    return None


def detect_slide_count(user_prompt: str) -> Optional[int]:
    """Try to detect a requested slide count from the user prompt text."""
    patterns: list[str] = [
        r'(\d+)\s*שקפים',
        r'(\d+)\s*שקף',
        r'(\d+)\s*עמוד',
        r'(\d+)\s*עמודים',
        r'(\d+)\s*slides?',
        r'מצגת\s*(?:של|בת|עם)\s*(\d+)',
    ]
    for pattern in patterns:
        match: Optional[re.Match] = re.search(pattern, user_prompt)
        if match:
            return int(match.group(1))
    return None

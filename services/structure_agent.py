import json
from typing import Optional
from utils.state import deck_state
from utils.llm import call_llm_raw, parse_llm_json
from utils.slide_builder import build_base_slide_entry, build_content_objects_for_layout
from ui.renderers import render_outline_html
from prompts import build_structure_prompt, build_outline_edit_prompt
from schemas.layouts import AVAILABLE_LAYOUTS


#  Outline Generation

def _build_count_instructions(slide_count: Optional[int]) -> tuple[str, str]:
    """Build count instruction and rule strings based on requested slide count."""
    if slide_count:
        count_instruction = f"מספר שקפים מבוקש: {slide_count}"
        count_rule = (
            f"5. עדיף להציע פחות שקפים עם נושאים אמיתיים מאשר {slide_count} שקפים עם נושאים בדויים.\n"
            f"6. אם המידע מספיק רק ל-3 שקפים למרות שנדרשו {slide_count} — הצע 3 בלבד וציין זאת."
        )
    else:
        count_instruction = "מספר שקפים: לא צוין — הצע מספר שקפים מתאים על בסיס כמות המידע הזמין."
        count_rule = "5. התאם את מספר השקפים לכמות המידע הזמין. אל תציע שקפים שאין להם מספיק מידע."
    return count_instruction, count_rule


def generate_outline(user_prompt: str, document_text: str, slide_count: Optional[int]) -> dict:
    """Generate a proposed presentation outline from prompt and document text."""
    count_instruction, count_rule = _build_count_instructions(slide_count)
    prompt: str = build_structure_prompt(user_prompt, document_text, count_instruction, count_rule)
    raw_response: str = call_llm_raw(prompt)
    return parse_llm_json(raw_response)


#  Outline Editing

def edit_outline(edit_instruction: str) -> tuple[str, str]:
    """Edit the pending outline based on a user instruction."""
    outline: Optional[dict] = deck_state.get("pending_outline")
    if outline is None:
        return "❌ אין מבנה מוצע לעריכה", ""

    outline_json: str = json.dumps(outline, indent=2, ensure_ascii=False)
    prompt: str = build_outline_edit_prompt(outline_json, edit_instruction)

    try:
        raw_response: str = call_llm_raw(prompt)
        updated_outline: dict = parse_llm_json(raw_response)
        deck_state["pending_outline"] = updated_outline

        outline_html: str = render_outline_html(updated_outline)
        return f"✅ המבנה עודכן — {len(updated_outline.get('slides', []))} שקפים", outline_html
    except Exception as e:
        return f"❌ שגיאה בעדכון מבנה: {str(e)}", render_outline_html(outline)



#  Outline → Skeleton Conversion


def outline_to_skeleton(outline: dict) -> dict:
    """Convert an approved outline into a full skeleton JSON for SlideAgent."""
    skeleton: dict = {
        "preset_name": outline.get("preset_name", "מבנה מותאם"),
        "slides": [],
    }

    for slide in outline.get("slides", []):
        slide_num: int = slide.get("slide_num", 1)
        title: str = slide.get("title", "")
        layout: str = slide.get("layout", "title_bullets")
        topics = slide.get("topics", [])
        has_content: bool = slide.get("has_content", True)

        entry: dict = _build_base_slide_entry(slide_num, title, layout)
        content_objects: list[dict] = _build_content_objects_for_layout(
            layout, slide_num, title, topics, has_content
        )
        entry["slide_objects"].extend(content_objects)
        skeleton["slides"].append(entry)

    return skeleton

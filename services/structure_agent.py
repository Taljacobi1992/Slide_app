import json
from typing import Optional
from utils.state import deck_state
from utils.llm import call_llm_raw, parse_llm_json
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

def _build_title_object(title: str) -> dict:
    """Create the standard title slide-object dict."""
    return {
        "object_id": "Title 1",
        "object_name": f"כותרת {title}",
        "object_type": "text",
        "object_description": f'כותרת בשם "{title}"',
    }


def _build_base_slide_entry(slide_num: int, title: str, layout: str) -> dict:
    """Create a skeleton slide entry with just the title object."""
    return {
        "slide_num": slide_num,
        "slide_description": title,
        "slide_layout": layout,
        "slide_objects": [_build_title_object(title)],
    }


def _build_bullets_objects(slide_num: int, title: str, topics: list, has_content: bool) -> list[dict]:
    """Build content objects for a title_bullets layout."""
    if not (isinstance(topics, list) and topics):
        return []
    topics_str: str = ", ".join(topics)
    return [{
        "object_id": "Content 1",
        "object_name": f"תוכן שקף {slide_num}",
        "object_type": "text",
        "object_description": (
            f"שדה תוכן בבולטים — הנושא: {title}. "
            f"תחומים לכיסוי: {topics_str}. "
            f"יש לחלץ את התוכן מהנחיית המשתמש והמסמך בלבד — אין להמציא פרטים."
        ),
        "has_source_content": has_content,
    }]


def _build_text_objects(slide_num: int, title: str, topics: list, has_content: bool) -> list[dict]:
    """Build content objects for a title_text layout."""
    if not (isinstance(topics, list) and topics):
        return []
    topics_str: str = ", ".join(topics)
    return [{
        "object_id": "Content 1",
        "object_name": f"תוכן שקף {slide_num}",
        "object_type": "text",
        "object_description": (
            f"שדה תוכן בפסקה רציפה — הנושא: {title}. "
            f"תחומים לכיסוי: {topics_str}. "
            f"כתוב כפסקה אחת רצופה, לא בבולטים. "
            f"יש לחלץ את התוכן מהנחיית המשתמש והמסמך בלבד."
        ),
        "has_source_content": has_content,
    }]


def _build_two_columns_objects(title: str, topics: dict, has_content: bool) -> list[dict]:
    objects: list[dict] = []
    if not isinstance(topics, dict):
        return objects

    right_data = topics.get("right", {})
    left_data = topics.get("left", {})
    right_label: str = right_data.get("label", "ימין")
    left_label: str = left_data.get("label", "שמאל")
    right_topics_str: str = ", ".join(right_data.get("topics", []))
    left_topics_str: str = ", ".join(left_data.get("topics", []))

    for side, obj_id, side_label, this_label, this_topics, other_label, other_topics in [
        ("right", "Content Right", "ימנית", right_label, right_topics_str, left_label, left_topics_str),
        ("left",  "Content Left",  "שמאלית", left_label, left_topics_str, right_label, right_topics_str),
    ]:
        objects.append({
            "object_id": obj_id,
            "object_name": f"תוכן עמודה {side_label} — {title}",
            "object_type": "text",
            "object_description": (
                f"שדה תוכן בבולטים עבור עמודה {side_label} בלבד — '{this_label}'. "
                f"כתוב אך ורק על: {this_topics}. "
                f"העמודה השנייה ('{other_label}') מכסה את: {other_topics} — אל תחזור על נושאים אלו. "
                f"התוכן של שתי העמודות חייב להיות שונה ומשלים זה את זה. "
                f"יש לחלץ מהמקורות בלבד."
            ),
            "has_source_content": has_content,
        })
    return objects


def _build_key_statement_objects(title: str, topics: list, has_content: bool) -> list[dict]:
    """Build content objects for a title_key_statement layout."""
    topic_hint: str = topics[0] if isinstance(topics, list) and topics else title
    return [{
        "object_id": "Key Statement",
        "object_name": f"משפט מפתח — {title}",
        "object_type": "text",
        "object_description": (
            f"משפט מפתח אחד בלבד — קצר, חזק ומשמעותי. "
            f"הנושא: {topic_hint}. "
            f"כתוב משפט אחד בלבד (לא בולטים, לא פסקה). "
            f"יש לחלץ מהמקורות בלבד."
        ),
        "has_source_content": has_content,
    }]


def _build_content_objects_for_layout(
    layout: str, slide_num: int, title: str, topics, has_content: bool
) -> list[dict]:
    """Route to the correct content-object builder based on layout type."""
    if layout in ("title_only", "section_header"):
        return []
    if layout == "title_bullets":
        return _build_bullets_objects(slide_num, title, topics, has_content)
    if layout == "title_text":
        return _build_text_objects(slide_num, title, topics, has_content)
    if layout == "title_two_columns":
        return _build_two_columns_objects(title, topics, has_content)
    if layout == "title_key_statement":
        return _build_key_statement_objects(title, topics, has_content)
    # Fallback — treat unknown layouts like bullets
    if isinstance(topics, list) and topics:
        return _build_bullets_objects(slide_num, title, topics, has_content)
    return []


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

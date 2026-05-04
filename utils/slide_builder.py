"""Slide builder utilities — shared helpers for constructing slide and object dicts."""

from schemas.layouts import AVAILABLE_LAYOUTS


# ── Title Object ──

def build_title_object(title: str) -> dict:
    """Create the standard title slide-object dict."""
    return {
        "object_id": "Title 1",
        "object_name": f"כותרת {title}",
        "object_type": "text",
        "object_description": f'כותרת בשם "{title}"',
    }


# ── Base Slide Entry ──

def build_base_slide_entry(slide_num: int, title: str, layout: str) -> dict:
    """Create a skeleton slide entry with just the title object."""
    return {
        "slide_num": slide_num,
        "slide_description": title,
        "slide_layout": layout,
        "slide_objects": [build_title_object(title)],
    }


# ── Layout-Specific Object Builders ──

def build_bullets_objects(slide_num: int, title: str, topics: list, has_content: bool) -> list[dict]:
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


def build_text_objects(slide_num: int, title: str, topics: list, has_content: bool) -> list[dict]:
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


def build_two_columns_objects(title: str, topics: dict, has_content: bool) -> list[dict]:
    """Build content objects for a title_two_columns layout."""
    objects: list[dict] = []
    if not isinstance(topics, dict):
        return objects

    right_data = topics.get("right", {})
    left_data = topics.get("left", {})
    right_label: str = right_data.get("label", "ימין")
    left_label: str = left_data.get("label", "שמאל")
    right_topics_str: str = ", ".join(right_data.get("topics", []))
    left_topics_str: str = ", ".join(left_data.get("topics", []))

    for obj_id, side_label, this_label, this_topics, other_label, other_topics in [
        ("Content Right", "ימנית", right_label, right_topics_str, left_label, left_topics_str),
        ("Content Left",  "שמאלית", left_label, left_topics_str, right_label, right_topics_str),
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


def build_key_statement_objects(title: str, topics: list, has_content: bool) -> list[dict]:
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


# ── Router ──

def build_content_objects_for_layout(
    layout: str, slide_num: int, title: str, topics, has_content: bool
) -> list[dict]:
    """Route to the correct content-object builder based on layout type."""
    if layout in ("title_only", "section_header"):
        return []
    if layout == "title_bullets":
        return build_bullets_objects(slide_num, title, topics, has_content)
    if layout == "title_text":
        return build_text_objects(slide_num, title, topics, has_content)
    if layout == "title_two_columns":
        return build_two_columns_objects(title, topics, has_content)
    if layout == "title_key_statement":
        return build_key_statement_objects(title, topics, has_content)
    # Fallback
    if isinstance(topics, list) and topics:
        return build_bullets_objects(slide_num, title, topics, has_content)
    return []

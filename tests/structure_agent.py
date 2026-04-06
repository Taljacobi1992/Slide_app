import json
from state import deck_state, call_llm_raw, parse_llm_json
from renderers import render_outline_html
from prompts import build_structure_prompt, build_outline_edit_prompt
from config import AVAILABLE_LAYOUTS


def generate_outline(user_prompt: str, document_text: str, slide_count: int | None) -> dict:
    """Generate a proposed presentation structure from prompt + document."""

    if slide_count:
        count_instruction = f"מספר שקפים מבוקש: {slide_count}"
        count_rule = (
            f"5. עדיף להציע פחות שקפים עם נושאים אמיתיים מאשר {slide_count} שקפים עם נושאים בדויים.\n"
            f"6. אם המידע מספיק רק ל-3 שקפים למרות שנדרשו {slide_count} — הצע 3 בלבד וציין זאת."
        )
    else:
        count_instruction = "מספר שקפים: לא צוין — הצע מספר שקפים מתאים על בסיס כמות המידע הזמין."
        count_rule = "5. התאם את מספר השקפים לכמות המידע הזמין. אל תציע שקפים שאין להם מספיק מידע."

    prompt = build_structure_prompt(user_prompt, document_text, count_instruction, count_rule)
    raw_response = call_llm_raw(prompt)
    return parse_llm_json(raw_response)


def edit_outline(edit_instruction):
    """Edit the proposed outline based on user instruction before approval."""
    outline = deck_state.get("pending_outline")
    if outline is None:
        return "❌ אין מבנה מוצע לעריכה", ""

    outline_json = json.dumps(outline, indent=2, ensure_ascii=False)
    prompt = build_outline_edit_prompt(outline_json, edit_instruction)

    try:
        raw_response = call_llm_raw(prompt)
        updated_outline = parse_llm_json(raw_response)
        deck_state["pending_outline"] = updated_outline

        outline_html = render_outline_html(updated_outline)
        return f"✅ המבנה עודכן — {len(updated_outline.get('slides', []))} שקפים", outline_html
    except Exception as e:
        return f"❌ שגיאה בעדכון מבנה: {str(e)}", render_outline_html(outline)


def outline_to_skeleton(outline: dict) -> dict:
    """Convert an approved outline into a full skeleton JSON compatible with SlideAgent."""
    skeleton = {
        "preset_name": outline.get("preset_name", "מבנה מותאם"),
        "slides": []
    }

    for slide in outline.get("slides", []):
        slide_num = slide.get("slide_num", 1)
        title = slide.get("title", "")
        layout = slide.get("layout", "title_bullets")
        topics = slide.get("topics", [])
        has_content = slide.get("has_content", True)

        slide_entry = {
            "slide_num": slide_num,
            "slide_description": title,
            "slide_layout": layout,
            "slide_objects": [
                {
                    "object_id": "Title 1",
                    "object_name": f"כותרת {title}",
                    "object_type": "text",
                    "object_description": f'כותרת בשם "{title}"',
                }
            ]
        }


        if layout in ("title_only", "section_header"):
            pass

        elif layout == "title_bullets":
            if isinstance(topics, list) and topics:
                topics_str = ", ".join(topics)
                slide_entry["slide_objects"].append({
                    "object_id": "Content 1",
                    "object_name": f"תוכן שקף {slide_num}",
                    "object_type": "text",
                    "object_description": (
                        f"שדה תוכן בבולטים — הנושא: {title}. "
                        f"תחומים לכיסוי: {topics_str}. "
                        f"יש לחלץ את התוכן מהנחיית המשתמש והמסמך בלבד — אין להמציא פרטים."
                    ),
                    "has_source_content": has_content
                })

        elif layout == "title_text":
            if isinstance(topics, list) and topics:
                topics_str = ", ".join(topics)
                slide_entry["slide_objects"].append({
                    "object_id": "Content 1",
                    "object_name": f"תוכן שקף {slide_num}",
                    "object_type": "text",
                    "object_description": (
                        f"שדה תוכן בפסקה רציפה — הנושא: {title}. "
                        f"תחומים לכיסוי: {topics_str}. "
                        f"כתוב כפסקה אחת רצופה, לא בבולטים. "
                        f"יש לחלץ את התוכן מהנחיית המשתמש והמסמך בלבד."
                    ),
                    "has_source_content": has_content
                })

        elif layout == "title_two_columns":
            if isinstance(topics, dict):
                right = topics.get("right", {})
                left = topics.get("left", {})
                right_label = right.get("label", "ימין")
                right_topics = right.get("topics", [])
                left_label = left.get("label", "שמאל")
                left_topics = left.get("topics", [])

                if right_topics:
                    slide_entry["slide_objects"].append({
                        "object_id": "Content Right",
                        "object_name": f"עמודה ימנית — {right_label}",
                        "object_type": "text",
                        "object_description": (
                            f"שדה תוכן בבולטים — עמודה ימנית: {right_label}. "
                            f"תחומים לכיסוי: {', '.join(right_topics)}. "
                            f"יש לחלץ את התוכן מהמקורות בלבד."
                        ),
                        "has_source_content": has_content
                    })
                if left_topics:
                    slide_entry["slide_objects"].append({
                        "object_id": "Content Left",
                        "object_name": f"עמודה שמאלית — {left_label}",
                        "object_type": "text",
                        "object_description": (
                            f"שדה תוכן בבולטים — עמודה שמאלית: {left_label}. "
                            f"תחומים לכיסוי: {', '.join(left_topics)}. "
                            f"יש לחלץ את התוכן מהמקורות בלבד."
                        ),
                        "has_source_content": has_content
                    })
            else:
                if isinstance(topics, list) and topics:
                    topics_str = ", ".join(topics)
                    slide_entry["slide_objects"].append({
                        "object_id": "Content 1",
                        "object_name": f"תוכן שקף {slide_num}",
                        "object_type": "text",
                        "object_description": f"שדה תוכן בבולטים — הנושא: {title}. תחומים: {topics_str}.",
                        "has_source_content": has_content
                    })

        elif layout == "title_key_statement":
            topic_hint = topics[0] if isinstance(topics, list) and topics else title
            slide_entry["slide_objects"].append({
                "object_id": "Key Statement",
                "object_name": f"משפט מפתח — {title}",
                "object_type": "text",
                "object_description": (
                    f"משפט מפתח אחד בלבד — קצר, חזק ומשמעותי. "
                    f"הנושא: {topic_hint}. "
                    f"כתוב משפט אחד בלבד (לא בולטים, לא פסקה). "
                    f"יש לחלץ מהמקורות בלבד."
                ),
                "has_source_content": has_content
            })

        else:
            if isinstance(topics, list) and topics:
                topics_str = ", ".join(topics)
                slide_entry["slide_objects"].append({
                    "object_id": "Content 1",
                    "object_name": f"תוכן שקף {slide_num}",
                    "object_type": "text",
                    "object_description": f"שדה תוכן בבולטים — הנושא: {title}. תחומים: {topics_str}.",
                    "has_source_content": has_content
                })

        skeleton["slides"].append(slide_entry)

    return skeleton
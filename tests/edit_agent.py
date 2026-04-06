import json
import re
import gradio as gr

from state import deck_state, call_edit_llm, parse_llm_json, parse_slide_num_from_selection, get_slide_by_num
from renderers import render_deck_preview, format_slide_preview
from prompts import build_deck_edit_prompt, build_slide_edit_prompt
from config import LAYOUT_OBJECT_TEMPLATES


# ──────────────────────────────────────────────
#  Layout Change
# ──────────────────────────────────────────────

def apply_layout_change(slide: dict, new_layout: str) -> bool:
    """Change a slide's layout, replacing content objects while keeping the title."""
    if new_layout not in LAYOUT_OBJECT_TEMPLATES:
        return False

    title = slide.get("slide_description", "")

    title_objects = [o for o in slide.get("slide_objects", []) if "כותרת" in o.get("object_name", "").lower()]
    if not title_objects:
        title_objects = [{
            "object_id": "Title 1",
            "object_name": f"כותרת {title}",
            "object_type": "text",
            "object_description": f'כותרת בשם "{title}"',
            "generated_content": title,
            "validation_status": "skipped"
        }]

    new_objects = list(title_objects)
    for tmpl in LAYOUT_OBJECT_TEMPLATES[new_layout]:
        obj_name_suffix = (tmpl["object_id"]
                           .replace("Content ", "תוכן ")
                           .replace("Key Statement", "משפט מפתח")
                           .replace("Right", "ימין")
                           .replace("Left", "שמאל"))
        new_objects.append({
            "object_id": tmpl["object_id"],
            "object_name": f"{obj_name_suffix} — {title}",
            "object_type": tmpl["object_type"],
            "object_description": tmpl["desc_template"].format(title=title),
            "generated_content": "",
            "validation_status": "pending_regeneration"
        })

    slide["slide_objects"] = new_objects
    slide["slide_layout"] = new_layout
    return True


# ──────────────────────────────────────────────
#  Apply Edits to Skeleton
# ──────────────────────────────────────────────

def apply_edits_to_skeleton(edit_data: dict, scope_slide_num: str = None) -> int:
    skeleton = deck_state["skeleton"]
    applied_count = 0

    # Handle layout changes first
    for layout_change in edit_data.get("layout_changes", []):
        target_slide_num = str(layout_change.get("slide_num", ""))
        new_layout = layout_change.get("new_layout", "")
        if scope_slide_num:
            target_slide_num = scope_slide_num
        for slide in skeleton["slides"]:
            if str(slide.get("slide_num", "")) == target_slide_num:
                if apply_layout_change(slide, new_layout):
                    applied_count += 1
                break

    # Handle content edits
    for edit in edit_data.get("edits", []):
        edit_slide_num = str(edit.get("slide_num", ""))
        edit_object_id = edit.get("object_id", "")
        edit_object_name = edit.get("object_name", "")
        new_content = edit.get("new_content", "")
        matched = False
        if scope_slide_num:
            edit_slide_num = scope_slide_num
        for slide in skeleton["slides"]:
            if str(slide.get("slide_num", "")) == edit_slide_num:
                for obj in slide.get("slide_objects", []):
                    obj_id = obj.get("object_id", "")
                    obj_name = obj.get("object_name", "")
                    if (edit_object_id and obj_id == edit_object_id) or \
                       (edit_object_name and obj_name == edit_object_name):
                        obj["generated_content"] = new_content
                        obj["validation_status"] = "edited_by_agent"
                        applied_count += 1
                        matched = True
                        break
                if matched:
                    break
        if not matched and edit_object_name:
            for slide in skeleton["slides"]:
                for obj in slide.get("slide_objects", []):
                    if obj.get("object_name", "") == edit_object_name:
                        obj["generated_content"] = new_content
                        obj["validation_status"] = "edited_by_agent"
                        applied_count += 1
                        matched = True
                        break
                if matched:
                    break
    return applied_count


# ──────────────────────────────────────────────
#  Deck-Level Chat Edit
# ──────────────────────────────────────────────

def deck_chat_edit(user_message, chat_history):
    if deck_state["skeleton"] is None:
        chat_history = chat_history or []
        chat_history.append({"role": "user", "content": user_message})
        chat_history.append({"role": "assistant", "content": "❌ יש ליצור מצגת קודם בלשונית 'יצירת מצגת'."})
        return (chat_history,
                '<div class="preview-empty">התצוגה תתעדכן לאחר עריכה</div>',
                json.dumps({}, indent=2, ensure_ascii=False),
                gr.update(choices=[]))

    skeleton = deck_state["skeleton"]
    rev_manager = deck_state["revision_manager"]

    chat_history = chat_history or []
    chat_history.append({"role": "user", "content": user_message})

    deck_json = json.dumps(skeleton, indent=2, ensure_ascii=False)
    edit_prompt = build_deck_edit_prompt(
        deck_json, deck_state.get("user_prompt", ""),
        deck_state.get("document_text", "לא סופק"), user_message
    )

    try:
        raw_response = call_edit_llm(edit_prompt)
        edit_data = parse_llm_json(raw_response)
        applied_count = apply_edits_to_skeleton(edit_data)

        summary = edit_data.get("summary", "")
        if applied_count > 0:
            rev_manager.save_revision(skeleton=skeleton, action="עריכה", description=summary)
            rev_id = rev_manager.get_latest_id()
            assistant_msg = f"✅ {summary} ({applied_count} אובייקטים עודכנו) — גרסה {rev_id}"
        else:
            raw_edits = json.dumps(edit_data.get("edits", []), ensure_ascii=False, indent=2)
            existing_ids = []
            for s in skeleton["slides"]:
                for o in s.get("slide_objects", []):
                    existing_ids.append(f"slide_num {s.get('slide_num')}: {o.get('object_id')} ({o.get('object_name')})")
            assistant_msg = (
                f"⚠️ {summary}\n\n"
                f"הסוכן החזיר:\n{raw_edits}\n\n"
                f"אובייקטים קיימים במצגת:\n" + "\n".join(existing_ids)
            )

    except (json.JSONDecodeError, KeyError) as e:
        assistant_msg = f"⚠️ לא הצלחתי לעבד את התשובה. נסה לנסח מחדש את הבקשה.\n\nשגיאה: {str(e)}"

    chat_history.append({"role": "assistant", "content": assistant_msg})
    full_json = json.dumps(skeleton, indent=2, ensure_ascii=False)
    preview_html = render_deck_preview(skeleton)
    revision_choices = rev_manager.get_revision_choices()

    return chat_history, preview_html, full_json, gr.update(choices=revision_choices)


# ──────────────────────────────────────────────
#  Slide-Level Chat Edit
# ──────────────────────────────────────────────

def on_slide_selected(slide_selection):
    if not slide_selection or deck_state["skeleton"] is None:
        return "בחר שקף כדי לראות את התוכן שלו"
    slide_num = parse_slide_num_from_selection(slide_selection)
    slide = get_slide_by_num(slide_num)
    if slide is None:
        return "❌ שקף לא נמצא"
    return format_slide_preview(slide)


def slide_chat_edit(user_message, slide_selection, chat_history):
    if deck_state["skeleton"] is None:
        chat_history = chat_history or []
        chat_history.append({"role": "user", "content": user_message})
        chat_history.append({"role": "assistant", "content": "❌ יש ליצור מצגת קודם בלשונית 'יצירת מצגת'."})
        return chat_history, "בחר שקף כדי לראות את התוכן שלו", gr.update(choices=[])

    if not slide_selection:
        chat_history = chat_history or []
        chat_history.append({"role": "user", "content": user_message})
        chat_history.append({"role": "assistant", "content": "❌ יש לבחור שקף קודם."})
        return chat_history, "", gr.update(choices=[])

    slide_num = parse_slide_num_from_selection(slide_selection)
    slide = get_slide_by_num(slide_num)

    if slide is None:
        chat_history = chat_history or []
        chat_history.append({"role": "user", "content": user_message})
        chat_history.append({"role": "assistant", "content": "❌ שקף לא נמצא."})
        return chat_history, "", gr.update(choices=[])

    skeleton = deck_state["skeleton"]
    rev_manager = deck_state["revision_manager"]

    chat_history = chat_history or []
    chat_history.append({"role": "user", "content": user_message})

    slide_json = json.dumps(slide, indent=2, ensure_ascii=False)
    obj_list_str = ', '.join(
        o.get('object_id', '') + ' (' + o.get('object_name', '') + ')'
        for o in slide.get('slide_objects', [])
    )

    edit_prompt = build_slide_edit_prompt(
        slide_json, slide_num, slide.get("slide_layout", "לא מוגדר"),
        deck_state.get("user_prompt", ""),
        deck_state.get("document_text", "לא סופק"),
        user_message, obj_list_str
    )

    try:
        raw_response = call_edit_llm(edit_prompt)
        edit_data = parse_llm_json(raw_response)
        applied_count = apply_edits_to_skeleton(edit_data, scope_slide_num=slide_num)

        summary = edit_data.get("summary", "")
        if applied_count > 0:
            rev_manager.save_revision(
                skeleton=skeleton,
                action=f"עריכת שקף {slide_num}",
                description=summary
            )
            rev_id = rev_manager.get_latest_id()
            assistant_msg = f"✅ {summary} ({applied_count} אובייקטים עודכנו) — גרסה {rev_id}"
        else:
            obj_list = [f"{o.get('object_id')} ({o.get('object_name')})" for o in slide.get("slide_objects", [])]
            assistant_msg = (
                f"⚠️ {summary}\n\n"
                f"אובייקטים בשקף {slide_num}:\n" + "\n".join(obj_list)
            )

    except (json.JSONDecodeError, KeyError) as e:
        assistant_msg = f"⚠️ לא הצלחתי לעבד את התשובה. נסה לנסח מחדש את הבקשה.\n\nשגיאה: {str(e)}"

    chat_history.append({"role": "assistant", "content": assistant_msg})

    updated_slide = get_slide_by_num(slide_num)
    preview = format_slide_preview(updated_slide) if updated_slide else ""
    revision_choices = rev_manager.get_revision_choices()

    return chat_history, preview, gr.update(choices=revision_choices)


# ──────────────────────────────────────────────
#  Revision Management
# ──────────────────────────────────────────────

def restore_revision(revision_selection):
    if not revision_selection or deck_state["skeleton"] is None:
        return "❌ יש לבחור גרסה", json.dumps(deck_state.get("skeleton", {}), indent=2, ensure_ascii=False)
    rev_manager = deck_state["revision_manager"]
    match = re.match(r"\[גרסה (\d+)\]", revision_selection)
    if not match:
        return "❌ לא ניתן לזהות מספר גרסה", json.dumps(deck_state["skeleton"], indent=2, ensure_ascii=False)
    revision_id = int(match.group(1))
    restored = rev_manager.restore_revision(revision_id)
    if restored is None:
        return "❌ גרסה לא נמצאה", json.dumps(deck_state["skeleton"], indent=2, ensure_ascii=False)
    deck_state["skeleton"] = restored
    full_json = json.dumps(restored, indent=2, ensure_ascii=False)
    return f"✅ שוחזר לגרסה {revision_id} — העריכה הבאה תיצור גרסה חדשה", full_json


def export_json():
    if deck_state["skeleton"] is None:
        return None
    output_path = "presentation_output.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(deck_state["skeleton"], f, indent=2, ensure_ascii=False)
    return output_path
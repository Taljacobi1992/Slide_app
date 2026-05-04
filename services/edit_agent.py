"""Edit agent — handles deck-level and slide-level chat edits."""

import json
import re
from typing import Optional

import gradio as gr

from utils.state import deck_state, parse_slide_num_from_selection, get_slide_by_num, get_slide_choices
from utils.llm import call_llm, parse_llm_json
from utils.slide_builder import build_base_slide_entry, build_content_objects_for_layout
from ui.renderers import render_deck_preview, format_slide_preview
from prompts import build_deck_edit_prompt, build_slide_edit_prompt
from schemas.layouts import LAYOUT_OBJECT_TEMPLATES





#  Layout Change

def _find_title_objects(slide: dict) -> list[dict]:
    """Extract existing title objects from a slide, or create a default one."""
    title: str = slide.get("slide_description", "")
    title_objects: list[dict] = [
        o for o in slide.get("slide_objects", [])
        if "כותרת" in o.get("object_name", "").lower()
    ]
    if not title_objects:
        title_objects = [{
            "object_id": "Title 1",
            "object_name": f"כותרת {title}",
            "object_type": "text",
            "object_description": f'כותרת בשם "{title}"',
            "generated_content": title,
            "validation_status": "skipped",
        }]
    return title_objects


def _build_new_layout_objects(title: str, new_layout: str) -> list[dict]:
    """Build content objects for a new layout from templates."""
    objects: list[dict] = []
    for tmpl in LAYOUT_OBJECT_TEMPLATES[new_layout]:
        obj_name_suffix: str = (
            tmpl["object_id"]
            .replace("Content ", "תוכן ")
            .replace("Key Statement", "משפט מפתח")
            .replace("Right", "ימין")
            .replace("Left", "שמאל")
        )
        objects.append({
            "object_id": tmpl["object_id"],
            "object_name": f"{obj_name_suffix} — {title}",
            "object_type": tmpl["object_type"],
            "object_description": tmpl["desc_template"].format(title=title),
            "generated_content": "",
            "validation_status": "pending_regeneration",
        })
    return objects


def apply_layout_change(slide: dict, new_layout: str) -> bool:
    """Change a slide's layout, replacing content objects while keeping the title."""
    if new_layout not in LAYOUT_OBJECT_TEMPLATES:
        return False

    title: str = slide.get("slide_description", "")
    title_objects: list[dict] = _find_title_objects(slide)
    new_objects: list[dict] = list(title_objects) + _build_new_layout_objects(title, new_layout)

    slide["slide_objects"] = new_objects
    slide["slide_layout"] = new_layout
    return True


#  Apply Edits to Skeleton

def _apply_layout_changes(edit_data: dict, skeleton: dict, scope_slide_num: Optional[str]) -> int:
    """Apply layout changes from edit_data to skeleton slides."""
    count: int = 0
    for layout_change in edit_data.get("layout_changes", []):
        target_num: str = scope_slide_num or str(layout_change.get("slide_num", ""))
        new_layout: str = layout_change.get("new_layout", "")
        for slide in skeleton["slides"]:
            if str(slide.get("slide_num", "")) == target_num:
                if apply_layout_change(slide, new_layout):
                    count += 1
                break
    return count


def _find_object_in_slide(slide: dict, object_id: str, object_name: str) -> Optional[dict]:
    """Find a matching object in a slide by id or name."""
    for obj in slide.get("slide_objects", []):
        obj_id: str = obj.get("object_id", "")
        obj_name: str = obj.get("object_name", "")
        if (object_id and obj_id == object_id) or (object_name and obj_name == object_name):
            return obj
    return None


def _apply_single_edit(edit: dict, skeleton: dict, scope_slide_num: Optional[str]) -> bool:
    """Apply a single content edit to the skeleton, return True if matched."""
    edit_slide_num: str = scope_slide_num or str(edit.get("slide_num", ""))
    edit_object_id: str = edit.get("object_id", "")
    edit_object_name: str = edit.get("object_name", "")
    new_content: str = edit.get("new_content", "")

    # Try exact slide match first
    for slide in skeleton["slides"]:
        if str(slide.get("slide_num", "")) == edit_slide_num:
            obj: Optional[dict] = _find_object_in_slide(slide, edit_object_id, edit_object_name)
            if obj is not None:
                obj["generated_content"] = new_content
                obj["validation_status"] = "edited_by_agent"
                return True

    # Fallback — search all slides by name
    if edit_object_name:
        for slide in skeleton["slides"]:
            for obj in slide.get("slide_objects", []):
                if obj.get("object_name", "") == edit_object_name:
                    obj["generated_content"] = new_content
                    obj["validation_status"] = "edited_by_agent"
                    return True
    return False


def apply_edits_to_skeleton(edit_data: dict, scope_slide_num: Optional[str] = None) -> int:
    """Apply all edits (layout changes + content) from LLM response to the skeleton."""
    skeleton: dict = deck_state["skeleton"]
    applied: int = _apply_layout_changes(edit_data, skeleton, scope_slide_num)

    for edit in edit_data.get("edits", []):
        if _apply_single_edit(edit, skeleton, scope_slide_num):
            applied += 1

    return applied


#  Chat Helpers

def _no_deck_response(user_message: str, chat_history: list[dict]) -> list[dict]:
    """Append an error reply when no deck exists."""
    chat_history = chat_history or []
    chat_history.append({"role": "user", "content": user_message})
    chat_history.append({"role": "assistant", "content": "❌ יש ליצור מצגת קודם בלשונית 'יצירת מצגת'."})
    return chat_history


def _build_success_message(summary: str, applied_count: int, rev_id: int) -> str:
    """Build assistant message for a successful edit."""
    return f"✅ {summary} ({applied_count} אובייקטים עודכנו) — גרסה {rev_id}"


def _build_no_changes_deck_message(summary: str, edit_data: dict, skeleton: dict) -> str:
    """Build assistant message when no edits were applied (deck scope)."""
    raw_edits: str = json.dumps(edit_data.get("edits", []), ensure_ascii=False, indent=2)
    existing_ids: list[str] = []
    for s in skeleton["slides"]:
        for o in s.get("slide_objects", []):
            existing_ids.append(
                f"slide_num {s.get('slide_num')}: {o.get('object_id')} ({o.get('object_name')})"
            )
    return (
        f"⚠️ {summary}\n\nהסוכן החזיר:\n{raw_edits}\n\n"
        f"אובייקטים קיימים במצגת:\n" + "\n".join(existing_ids)
    )


def _build_no_changes_slide_message(summary: str, slide: dict, slide_num: str) -> str:
    """Build assistant message when no edits were applied (slide scope)."""
    obj_list: list[str] = [
        f"{o.get('object_id')} ({o.get('object_name')})"
        for o in slide.get("slide_objects", [])
    ]
    return f"⚠️ {summary}\n\nאובייקטים בשקף {slide_num}:\n" + "\n".join(obj_list)


def _regenerate_pending_objects(skeleton: dict) -> None:
    """Scan skeleton for pending_regeneration objects and regenerate them."""
    agent = deck_state.get("agent")
    if agent is None:
        return
    user_prompt = deck_state.get("user_prompt", "")
    document_text = deck_state.get("document_text", "")
    for slide in skeleton.get("slides", []):
        has_pending = any(
            obj.get("validation_status") == "pending_regeneration"
            for obj in slide.get("slide_objects", [])
        )
        if has_pending:
            agent.regenerate_pending_objects(slide, user_prompt, document_text)



#  Deck-Level Chat Edit

def _execute_deck_edit(user_message: str, skeleton: dict) -> tuple[str, int, dict]:
    """Call LLM to edit the deck and apply changes. Returns (message, applied_count, edit_data)."""
    deck_json: str = json.dumps(skeleton, indent=2, ensure_ascii=False)
    edit_prompt: str = build_deck_edit_prompt(
        deck_json, deck_state.get("user_prompt", ""),
        deck_state.get("document_text", "לא סופק"), user_message,
    )
    raw_response: str = call_llm(edit_prompt, role="edit")
    edit_data: dict = parse_llm_json(raw_response)
    applied_count: int = apply_edits_to_skeleton(edit_data)
    _regenerate_pending_objects(skeleton)
    return edit_data.get("summary", ""), applied_count, edit_data


def deck_chat_edit(user_message: str, chat_history: list[dict]) -> tuple:
    """Process a deck-level natural-language edit request via chat."""
    if deck_state["skeleton"] is None:
        history = _no_deck_response(user_message, chat_history)
        return (
            history,
            '<div class="preview-empty">התצוגה תתעדכן לאחר עריכה</div>',
            json.dumps({}, indent=2, ensure_ascii=False),
            gr.update(choices=[]),
        )

    skeleton: dict = deck_state["skeleton"]
    rev_manager = deck_state["revision_manager"]
    chat_history = chat_history or []
    chat_history.append({"role": "user", "content": user_message})

    try:
        summary, applied_count, edit_data = _execute_deck_edit(user_message, skeleton)
        if applied_count > 0:
            rev_manager.save_revision(skeleton=skeleton, action="עריכה", description=summary)
            assistant_msg = _build_success_message(summary, applied_count, rev_manager.get_latest_id())
        else:
            assistant_msg = _build_no_changes_deck_message(summary, edit_data, skeleton)
    except (json.JSONDecodeError, KeyError) as e:
        assistant_msg = f"⚠️ לא הצלחתי לעבד את התשובה. נסה לנסח מחדש את הבקשה.\n\nשגיאה: {str(e)}"

    chat_history.append({"role": "assistant", "content": assistant_msg})
    full_json: str = json.dumps(skeleton, indent=2, ensure_ascii=False)
    preview_html: str = render_deck_preview(skeleton)
    return chat_history, preview_html, full_json, gr.update(choices=rev_manager.get_revision_choices())


#  Slide-Level Chat Edit

def on_slide_selected(slide_selection: str) -> str:
    """Return a formatted preview when the user selects a slide."""
    if not slide_selection or deck_state["skeleton"] is None:
        return "בחר שקף כדי לראות את התוכן שלו"
    slide_num: Optional[str] = parse_slide_num_from_selection(slide_selection)
    slide: Optional[dict] = get_slide_by_num(slide_num)
    if slide is None:
        return "❌ שקף לא נמצא"
    return format_slide_preview(slide)


def _validate_slide_selection(
    user_message: str, slide_selection: str, chat_history: list[dict]
) -> tuple[Optional[str], Optional[dict], list[dict]]:
    """Validate inputs for slide edit. Returns (slide_num, slide, chat_history) or appends error."""
    chat_history = chat_history or []

    if not slide_selection:
        chat_history.append({"role": "user", "content": user_message})
        chat_history.append({"role": "assistant", "content": "❌ יש לבחור שקף קודם."})
        return None, None, chat_history

    slide_num: Optional[str] = parse_slide_num_from_selection(slide_selection)
    slide: Optional[dict] = get_slide_by_num(slide_num)

    if slide is None:
        chat_history.append({"role": "user", "content": user_message})
        chat_history.append({"role": "assistant", "content": "❌ שקף לא נמצא."})
        return None, None, chat_history

    return slide_num, slide, chat_history


def _execute_slide_edit(
    user_message: str, slide: dict, slide_num: str
) -> tuple[str, int, dict]:
    """Call LLM to edit a single slide and apply changes."""
    slide_json: str = json.dumps(slide, indent=2, ensure_ascii=False)
    obj_list_str: str = ", ".join(
        o.get("object_id", "") + " (" + o.get("object_name", "") + ")"
        for o in slide.get("slide_objects", [])
    )
    edit_prompt: str = build_slide_edit_prompt(
        slide_json, slide_num, slide.get("slide_layout", "לא מוגדר"),
        deck_state.get("user_prompt", ""),
        deck_state.get("document_text", "לא סופק"),
        user_message, obj_list_str,
    )
    raw_response: str = call_llm(edit_prompt, role="edit")
    edit_data: dict = parse_llm_json(raw_response)
    applied_count: int = apply_edits_to_skeleton(edit_data, scope_slide_num=slide_num)
    _regenerate_pending_objects(deck_state["skeleton"])
    return edit_data.get("summary", ""), applied_count, edit_data


def slide_chat_edit(
    user_message: str, slide_selection: str, chat_history: list[dict]
) -> tuple:
    """Process a slide-level natural-language edit request via chat."""
    if deck_state["skeleton"] is None:
        history = _no_deck_response(user_message, chat_history)
        return history, "בחר שקף כדי לראות את התוכן שלו", gr.update(choices=[])

    slide_num, slide, chat_history = _validate_slide_selection(
        user_message, slide_selection, chat_history
    )
    if slide is None:
        return chat_history, "", gr.update(choices=[])

    skeleton: dict = deck_state["skeleton"]
    rev_manager = deck_state["revision_manager"]
    chat_history.append({"role": "user", "content": user_message})

    try:
        summary, applied_count, edit_data = _execute_slide_edit(user_message, slide, slide_num)
        if applied_count > 0:
            rev_manager.save_revision(
                skeleton=skeleton, action=f"עריכת שקף {slide_num}", description=summary,
            )
            assistant_msg = _build_success_message(summary, applied_count, rev_manager.get_latest_id())
        else:
            assistant_msg = _build_no_changes_slide_message(summary, slide, slide_num)
    except (json.JSONDecodeError, KeyError) as e:
        assistant_msg = f"⚠️ לא הצלחתי לעבד את התשובה. נסה לנסח מחדש את הבקשה.\n\nשגיאה: {str(e)}"

    chat_history.append({"role": "assistant", "content": assistant_msg})
    updated_slide: Optional[dict] = get_slide_by_num(slide_num)
    preview: str = format_slide_preview(updated_slide) if updated_slide else ""
    return chat_history, preview, gr.update(choices=rev_manager.get_revision_choices())


#  Revision Management

def restore_revision(revision_selection: str) -> tuple[str, str]:
    """Restore the deck to a previously saved revision."""
    if not revision_selection or deck_state["skeleton"] is None:
        return "❌ יש לבחור גרסה", json.dumps(deck_state.get("skeleton", {}), indent=2, ensure_ascii=False)

    rev_manager = deck_state["revision_manager"]
    match: Optional[re.Match] = re.match(r"\[גרסה (\d+)\]", revision_selection)
    if not match:
        return "❌ לא ניתן לזהות מספר גרסה", json.dumps(deck_state["skeleton"], indent=2, ensure_ascii=False)

    revision_id: int = int(match.group(1))
    restored: Optional[dict] = rev_manager.restore_revision(revision_id)
    if restored is None:
        return "❌ גרסה לא נמצאה", json.dumps(deck_state["skeleton"], indent=2, ensure_ascii=False)

    deck_state["skeleton"] = restored
    full_json: str = json.dumps(restored, indent=2, ensure_ascii=False)
    return f"✅ שוחזר לגרסה {revision_id} — העריכה הבאה תיצור גרסה חדשה", full_json


def export_json() -> Optional[str]:
    """Export the current deck skeleton to a JSON file and return its path."""
    if deck_state["skeleton"] is None:
        return None
    output_path: str = "presentation_output.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(deck_state["skeleton"], f, indent=2, ensure_ascii=False)
    return output_path




# ── New Slide Addition ──

def _renumber_slides(skeleton: dict) -> None:
    """Renumber all slides sequentially after an insertion."""
    for i, slide in enumerate(skeleton["slides"], start=1):
        slide["slide_num"] = i
        for obj in slide.get("slide_objects", []):
            pass  # object_ids are layout-based, not position-based — no change needed


def _get_adjacent_slides_json(skeleton: dict, insert_index: int) -> str:
    """Return JSON of the slides immediately before and after the insertion point."""
    slides = skeleton["slides"]
    adjacent = []
    if insert_index > 0:
        adjacent.append(slides[insert_index - 1])
    if insert_index < len(slides):
        adjacent.append(slides[insert_index])
    return json.dumps(adjacent, indent=2, ensure_ascii=False)


def add_slide(
    instruction: str,
    position_selection: str,
    before_or_after: str,
    layout_choice: str,
) -> tuple:
    """Add a new slide to the deck based on natural language instruction."""
    if deck_state["skeleton"] is None:
        return ("❌ יש ליצור מצגת קודם", 
                '<div class="preview-empty">אין מצגת</div>',
                "{}", gr.update(choices=[]))

    if not instruction or not instruction.strip():
        return ("❌ יש להזין תיאור לשקף החדש",
                render_deck_preview(),
                json.dumps(deck_state["skeleton"], indent=2, ensure_ascii=False),
                gr.update(choices=[]))

    skeleton = deck_state["skeleton"]
    rev_manager = deck_state["revision_manager"]

    # Determine insertion index
    slide_num = parse_slide_num_from_selection(position_selection) if position_selection else None
    if slide_num is None:
        insert_index = len(skeleton["slides"])  # append at end
    else:
        base_index = next(
            (i for i, s in enumerate(skeleton["slides"])
             if str(s.get("slide_num", "")) == slide_num), 
            len(skeleton["slides"]) - 1
        )
        insert_index = base_index if before_or_after == "לפני" else base_index + 1

    # Build context for LLM
    adjacent_json = _get_adjacent_slides_json(skeleton, insert_index)
    forced_layout = layout_choice if layout_choice and layout_choice != "אוטומטי" else None

    try:
        # Ask LLM to plan the new slide
        from prompts import build_new_slide_prompt

        prompt = build_new_slide_prompt(
            user_instruction=instruction,
            user_prompt=deck_state.get("user_prompt", ""),
            document_text=deck_state.get("document_text", ""),
            adjacent_slides_json=adjacent_json,
            forced_layout=forced_layout,
        )
        raw_response = call_llm(prompt, role="structure")
        slide_plan = parse_llm_json(raw_response)

        # Build the new slide dict (reuse structure_agent helpers)
        title = slide_plan.get("title", "שקף חדש")
        layout = slide_plan.get("layout", "title_bullets")
        topics = slide_plan.get("topics", [])
        has_content = slide_plan.get("has_content", True)

        new_slide = build_base_slide_entry(
            slide_num=insert_index + 1,
            title=title,
            layout=layout,
        )
        content_objects = build_content_objects_for_layout(
            layout, insert_index + 1, title, topics, has_content
        )
        new_slide["slide_objects"].extend(content_objects)

        # Insert and renumber
        skeleton["slides"].insert(insert_index, new_slide)
        _renumber_slides(skeleton)

        # Generate content via slide agent
        agent = deck_state.get("agent")
        if agent:
            agent.generate_slide(
                slide=new_slide,
                user_prompt=deck_state.get("user_prompt", ""),
                document_text=deck_state.get("document_text", ""),
            )

        rev_manager.save_revision(
            skeleton=skeleton,
            action="הוספת שקף",
            description=f"שקף חדש: {title}",
        )

        return (
            f"✅ שקף '{title}' נוסף בהצלחה — גרסה {rev_manager.get_latest_id()}",
            render_deck_preview(skeleton),
            json.dumps(skeleton, indent=2, ensure_ascii=False),
            gr.update(choices=get_slide_choices()),
        )

    except (json.JSONDecodeError, KeyError) as e:
        return (f"❌ שגיאה ביצירת שקף: {str(e)}",
                render_deck_preview(skeleton),
                json.dumps(skeleton, indent=2, ensure_ascii=False),
                gr.update(choices=[]))

"""
FastAPI REST layer for the Presentation Generator.

Exposes the same core logic that Gradio uses, as clean REST endpoints.
Swagger UI is auto-generated at /docs, ReDoc at /redoc.

Two flows:
  1) Template-free:  POST /outline/generate → PUT /outline/edit → POST /outline/approve → PUT /deck/edit | /slide/{n}/edit
  2) Template-based: POST /deck/generate   →                                              PUT /deck/edit | /slide/{n}/edit
"""

import json
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from api_models import (
    GenerateOutlineRequest, EditOutlineRequest, GenerateFromTemplateRequest,
    DeckEditRequest, SlideEditRequest,
    OutlineResponse, DeckResponse, EditResultResponse,
    RevisionsListResponse, RevisionInfo, RestoreResponse, ErrorResponse,
)
from state import deck_state, detect_slide_count, call_edit_llm, parse_llm_json, get_slide_by_num
from structure_agent import generate_outline, edit_outline as _edit_outline_core, outline_to_skeleton
from slide_agent import SlideAgent
from revision_manager import RevisionManager
from edit_agent import apply_edits_to_skeleton
from renderers import render_deck_preview
from prompts import build_deck_edit_prompt, build_slide_edit_prompt



#  App Setup


app = FastAPI(
    title="Presentation Generator API",
    description=(
        "REST API for generating and editing slides.\n\n"
        "**Template-free flow:** generate-outline → edit-outline → approve → edit\n\n"
        "**Template-based flow:** generate-from-template → edit"
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _ensure_deck_exists():
    if deck_state["skeleton"] is None:
        raise HTTPException(status_code=409, detail="אין מצגת פעילה. יש ליצור מצגת קודם.")


def _ensure_outline_exists():
    if deck_state.get("pending_outline") is None:
        raise HTTPException(status_code=409, detail="אין מבנה מוצע. יש ליצור מבנה קודם דרך /outline/generate.")


#  Flow 1 — Template-Free

@app.post(
    "/api/outline/generate",
    response_model=OutlineResponse,
    summary="שלב 1 (ללא תבנית): יצירת מבנה מוצע",
    tags=["Template-Free Flow"],
)
def api_generate_outline(req: GenerateOutlineRequest):
    """
    Generate a proposed presentation outline from a user prompt and optional document.
    Returns an outline for review — call `/outline/approve` to generate the actual content.
    """
    # Detect slide count from prompt text if not explicitly given
    slide_count = req.slide_count or detect_slide_count(req.user_prompt)

    # Store context for later steps
    deck_state["user_prompt"] = req.user_prompt
    deck_state["document_text"] = req.document_text or ""

    # Content warning
    total_words = len(req.user_prompt.split()) + len((req.document_text or "").split())
    content_warning = None
    if total_words < 20:
        content_warning = f"כמות המידע מצומצמת ({total_words} מילים). מומלץ להוסיף מסמך מקור."

    try:
        outline = generate_outline(req.user_prompt, req.document_text, slide_count)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"שגיאה ביצירת מבנה: {str(e)}")

    deck_state["pending_outline"] = outline

    return OutlineResponse(
        status="outline_ready",
        slide_count=len(outline.get("slides", [])),
        outline=outline,
        content_warning=content_warning,
    )


@app.put(
    "/api/outline/edit",
    response_model=OutlineResponse,
    summary="שלב 2 (אופציונלי): עריכת המבנה המוצע",
    tags=["Template-Free Flow"],
)
def api_edit_outline(req: EditOutlineRequest):
    """
    Edit the proposed outline before approving it.
    For example: "הוסף שקף על לוחות זמנים" or "הסר את שקף 3".
    """
    _ensure_outline_exists()

    outline = deck_state["pending_outline"]
    outline_json = json.dumps(outline, indent=2, ensure_ascii=False)

    from prompts import build_outline_edit_prompt
    from state import call_llm_raw

    prompt = build_outline_edit_prompt(outline_json, req.edit_instruction)

    try:
        raw_response = call_llm_raw(prompt)
        updated_outline = parse_llm_json(raw_response)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"שגיאה בעדכון מבנה: {str(e)}")

    deck_state["pending_outline"] = updated_outline

    return OutlineResponse(
        status="outline_updated",
        slide_count=len(updated_outline.get("slides", [])),
        outline=updated_outline,
    )


@app.post(
    "/api/outline/approve",
    response_model=DeckResponse,
    summary="שלב 3: אישור מבנה ויצירת תוכן",
    tags=["Template-Free Flow"],
)
def api_approve_outline():
    """
    Approve the current outline and generate full slide content.
    Converts the outline to a skeleton and runs SlideAgent on every slide.
    """
    _ensure_outline_exists()

    outline = deck_state["pending_outline"]
    skeleton = outline_to_skeleton(outline)

    agent = SlideAgent(language="hebrew")
    rev_manager = RevisionManager()

    deck_state["skeleton"] = skeleton
    deck_state["agent"] = agent
    deck_state["revision_manager"] = rev_manager
    deck_state["pending_outline"] = None

    user_prompt = deck_state.get("user_prompt", "")
    document_text = deck_state.get("document_text", "")

    for slide in skeleton["slides"]:
        agent.generate_slide(slide=slide, user_prompt=user_prompt, document_text=document_text)

    rev_manager.save_revision(skeleton=skeleton, action="יצירה", description="יצירת מצגת ממבנה מותאם")

    return DeckResponse(
        status="deck_created",
        slide_count=len(skeleton.get("slides", [])),
        revision_id=rev_manager.get_latest_id(),
        deck=skeleton,
    )



#  Flow 2 — Template-Based


@app.post(
    "/api/deck/generate",
    response_model=DeckResponse,
    summary="יצירת מצגת מתבנית",
    tags=["Template-Based Flow"],
)
def api_generate_from_template(req: GenerateFromTemplateRequest):
    """
    Generate slide content from a pre-built skeleton template (JSON).
    Skips the outline step entirely — goes straight to content generation.
    """
    skeleton = req.template

    if "slides" not in skeleton or not skeleton["slides"]:
        raise HTTPException(status_code=422, detail="התבנית חייבת לכלול מערך 'slides' עם שקף אחד לפחות.")

    agent = SlideAgent(language="hebrew")
    rev_manager = RevisionManager()

    deck_state["skeleton"] = skeleton
    deck_state["agent"] = agent
    deck_state["user_prompt"] = req.user_prompt or ""
    deck_state["document_text"] = req.document_text or ""
    deck_state["revision_manager"] = rev_manager
    deck_state["pending_outline"] = None

    for slide in skeleton["slides"]:
        agent.generate_slide(slide=slide, user_prompt=req.user_prompt or "", document_text=req.document_text or "")

    rev_manager.save_revision(skeleton=skeleton, action="יצירה", description="יצירת מצגת ראשונית עם תבנית")

    return DeckResponse(
        status="deck_created",
        slide_count=len(skeleton.get("slides", [])),
        revision_id=rev_manager.get_latest_id(),
        deck=skeleton,
    )



#  Shared — Deck & Slide Editing


@app.put(
    "/api/deck/edit",
    response_model=EditResultResponse,
    summary="עריכת מצגת שלמה",
    tags=["Editing"],
)
def api_edit_deck(req: DeckEditRequest):
    """
    Apply a natural-language edit across the entire deck.
    For example: "הפוך את כל המצגת לפורמלית יותר" or "קצר את כל השקפים".
    """
    _ensure_deck_exists()

    skeleton = deck_state["skeleton"]
    rev_manager = deck_state["revision_manager"]

    deck_json = json.dumps(skeleton, indent=2, ensure_ascii=False)
    edit_prompt = build_deck_edit_prompt(
        deck_json,
        deck_state.get("user_prompt", ""),
        deck_state.get("document_text", "לא סופק"),
        req.user_message,
    )

    try:
        raw_response = call_edit_llm(edit_prompt)
        edit_data = parse_llm_json(raw_response)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"שגיאה בעיבוד תשובת LLM: {str(e)}")

    applied_count = apply_edits_to_skeleton(edit_data)
    summary = edit_data.get("summary", "")

    revision_id = 0
    if applied_count > 0:
        rev_manager.save_revision(skeleton=skeleton, action="עריכה", description=summary)
        revision_id = rev_manager.get_latest_id()

    return EditResultResponse(
        status="edited" if applied_count > 0 else "no_changes",
        applied_count=applied_count,
        summary=summary,
        revision_id=revision_id,
        deck=skeleton,
    )


@app.put(
    "/api/slide/{slide_num}/edit",
    response_model=EditResultResponse,
    summary="עריכת שקף בודד",
    tags=["Editing"],
)
def api_edit_slide(slide_num: int, req: SlideEditRequest):
    """
    Apply a natural-language edit to a specific slide.
    For example: "עדכן את Content 1 עם תאריך האירוע" or "שנה layout לשתי עמודות".
    """
    _ensure_deck_exists()

    slide = get_slide_by_num(str(slide_num))
    if slide is None:
        raise HTTPException(status_code=404, detail=f"שקף {slide_num} לא נמצא.")

    skeleton = deck_state["skeleton"]
    rev_manager = deck_state["revision_manager"]

    slide_json = json.dumps(slide, indent=2, ensure_ascii=False)
    obj_list_str = ", ".join(
        f"{o.get('object_id', '')} ({o.get('object_name', '')})"
        for o in slide.get("slide_objects", [])
    )

    edit_prompt = build_slide_edit_prompt(
        slide_json, str(slide_num), slide.get("slide_layout", "לא מוגדר"),
        deck_state.get("user_prompt", ""),
        deck_state.get("document_text", "לא סופק"),
        req.user_message, obj_list_str,
    )

    try:
        raw_response = call_edit_llm(edit_prompt)
        edit_data = parse_llm_json(raw_response)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"שגיאה בעיבוד תשובת LLM: {str(e)}")

    applied_count = apply_edits_to_skeleton(edit_data, scope_slide_num=str(slide_num))
    summary = edit_data.get("summary", "")

    revision_id = 0
    if applied_count > 0:
        rev_manager.save_revision(skeleton=skeleton, action=f"עריכת שקף {slide_num}", description=summary)
        revision_id = rev_manager.get_latest_id()

    return EditResultResponse(
        status="edited" if applied_count > 0 else "no_changes",
        applied_count=applied_count,
        summary=summary,
        revision_id=revision_id,
        deck=skeleton,
    )



#  Utility — Export & Revisions


@app.get(
    "/api/deck/export",
    response_model=DeckResponse,
    summary="ייצוא המצגת הנוכחית",
    tags=["Utility"],
)
def api_export_deck():
    """Return the current deck JSON."""
    _ensure_deck_exists()
    skeleton = deck_state["skeleton"]
    rev_manager = deck_state["revision_manager"]
    return DeckResponse(
        status="ok",
        slide_count=len(skeleton.get("slides", [])),
        revision_id=rev_manager.get_latest_id(),
        deck=skeleton,
    )


@app.get(
    "/api/revisions",
    response_model=RevisionsListResponse,
    summary="רשימת גרסאות",
    tags=["Utility"],
)
def api_list_revisions():
    """List all saved revisions for the current session."""
    _ensure_deck_exists()
    rev_manager = deck_state["revision_manager"]
    items = []
    for rev in reversed(rev_manager.revisions):
        items.append(RevisionInfo(
            revision_id=rev["revision_id"],
            timestamp=rev["timestamp"],
            action=rev["action"],
            description=rev["description"],
        ))
    return RevisionsListResponse(revisions=items)


@app.put(
    "/api/revisions/{revision_id}/restore",
    response_model=RestoreResponse,
    summary="שחזור גרסה",
    tags=["Utility"],
)
def api_restore_revision(revision_id: int):
    """Restore the deck to a previous revision."""
    _ensure_deck_exists()
    rev_manager = deck_state["revision_manager"]
    restored = rev_manager.restore_revision(revision_id)
    if restored is None:
        raise HTTPException(status_code=404, detail=f"גרסה {revision_id} לא נמצאה.")
    deck_state["skeleton"] = restored
    return RestoreResponse(
        status="restored",
        revision_id=revision_id,
        deck=restored,
    )

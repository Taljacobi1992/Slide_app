"""FastAPI API routes for the slide generation tool."""

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from services.slide_agent import SlideAgent
from services.structure_agent import generate_outline, edit_outline, outline_to_skeleton
from services.edit_agent import deck_chat_edit, slide_chat_edit, add_slide
from utils.state import deck_state, detect_slide_count
from utils.revision_manager import RevisionManager


# ══════════════════════════════════════════════
#  Request Models
# ══════════════════════════════════════════════


class GenerateRequest(BaseModel):
    """Request body for generating a presentation."""
    user_prompt: str = ""
    document_text: str = ""
    slide_count: Optional[int] = Field(default=None, ge=1, le=30)
    template_json: Optional[dict] = None


class OutlineEditRequest(BaseModel):
    """Request body for editing a pending outline."""
    edit_instruction: str


class DeckEditRequest(BaseModel):
    """Request body for deck-level chat edit."""
    user_message: str
    chat_history: list[dict] = Field(default_factory=list)


class SlideEditRequest(BaseModel):
    """Request body for slide-level chat edit."""
    user_message: str
    slide_num: str
    chat_history: list[dict] = Field(default_factory=list)


class AddSlideRequest(BaseModel):
    """Request body for adding a new slide."""
    instruction: str
    position_slide_num: Optional[str] = None
    before_or_after: str = "אחרי"
    layout: str = "אוטומטי"



# ══════════════════════════════════════════════
#  Router
# ══════════════════════════════════════════════

router = APIRouter(prefix="/api")


# ── Health ──

@router.get("/health")
async def health_check() -> dict:
    """Health check endpoint."""
    return {"status": "ok"}


# ── Generation ──

@router.post("/generate")
async def api_generate(req: GenerateRequest) -> dict:
    """Generate a presentation from user prompt and optional template."""
    has_template: bool = req.template_json is not None
    has_prompt: bool = bool(req.user_prompt and req.user_prompt.strip())

    if not has_template and not has_prompt:
        raise HTTPException(status_code=400, detail="יש להזין הנחיית משתמש או לספק תבנית")

    if has_template:
        skeleton: dict = req.template_json
        agent: SlideAgent = SlideAgent(language="hebrew")
        rev_manager: RevisionManager = RevisionManager()

        deck_state["skeleton"] = skeleton
        deck_state["agent"] = agent
        deck_state["user_prompt"] = req.user_prompt
        deck_state["document_text"] = req.document_text
        deck_state["revision_manager"] = rev_manager
        deck_state["pending_outline"] = None

        agent.generate_all_slides(
            slides=skeleton["slides"],
            user_prompt=req.user_prompt,
            document_text=req.document_text,
        )

        rev_manager.save_revision(
            skeleton=skeleton, action="יצירה",
            description="יצירת מצגת ראשונית עם תבנית",
        )
        return {"status": "success", "message": "המצגת נוצרה בהצלחה", "skeleton": skeleton}

    slide_count: Optional[int] = detect_slide_count(req.user_prompt) or req.slide_count

    deck_state["user_prompt"] = req.user_prompt
    deck_state["document_text"] = req.document_text

    try:
        outline: dict = generate_outline(req.user_prompt, req.document_text, slide_count)
        deck_state["pending_outline"] = outline
        return {
            "status": "pending_approval",
            "message": f"מבנה מוצע עם {len(outline.get('slides', []))} שקפים",
            "outline": outline,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"שגיאה ביצירת מבנה: {str(e)}")


@router.post("/outline/approve")
async def api_approve_outline() -> dict:
    """Approve the pending outline and generate the full presentation."""
    outline: Optional[dict] = deck_state.get("pending_outline")
    if outline is None:
        raise HTTPException(status_code=400, detail="אין מבנה מוצע לאישור")

    skeleton: dict = outline_to_skeleton(outline)
    agent: SlideAgent = SlideAgent(language="hebrew")
    rev_manager: RevisionManager = RevisionManager()

    deck_state["skeleton"] = skeleton
    deck_state["agent"] = agent
    deck_state["revision_manager"] = rev_manager
    deck_state["pending_outline"] = None

    agent.generate_all_slides(
        slides=skeleton["slides"],
        user_prompt=deck_state.get("user_prompt", ""),
        document_text=deck_state.get("document_text", ""),
    )

    rev_manager.save_revision(
        skeleton=skeleton, action="יצירה",
        description="יצירת מצגת ממבנה מותאם",
    )
    return {"status": "success", "message": "המצגת נוצרה בהצלחה", "skeleton": skeleton}


@router.post("/outline/edit")
async def api_edit_outline(req: OutlineEditRequest) -> dict:
    """Edit the pending outline before approval."""
    message, _ = edit_outline(req.edit_instruction)
    outline: Optional[dict] = deck_state.get("pending_outline")
    return {"status": "success", "message": message, "outline": outline}


# ── Editing ──

@router.post("/edit/deck")
async def api_deck_edit(req: DeckEditRequest) -> dict:
    """Apply a deck-level natural language edit."""
    if deck_state["skeleton"] is None:
        raise HTTPException(status_code=400, detail="אין מצגת לעריכה")

    chat_history, preview_html, full_json, _ = deck_chat_edit(
        req.user_message, req.chat_history,
    )
    return {
        "status": "success",
        "chat_history": chat_history,
        "skeleton": deck_state["skeleton"],
    }


@router.post("/edit/slide")
async def api_slide_edit(req: SlideEditRequest) -> dict:
    """Apply a slide-level natural language edit."""
    if deck_state["skeleton"] is None:
        raise HTTPException(status_code=400, detail="אין מצגת לעריכה")

    slide_selection: str = f"[שקף {req.slide_num}] "
    chat_history, preview, _ = slide_chat_edit(
        req.user_message, slide_selection, req.chat_history,
    )
    return {
        "status": "success",
        "chat_history": chat_history,
        "skeleton": deck_state["skeleton"],
    }


@router.post("/slide/add")
async def api_add_slide(req: AddSlideRequest) -> dict:
    """Add a new slide to the deck."""
    if deck_state["skeleton"] is None:
        raise HTTPException(status_code=400, detail="אין מצגת")

    position_selection: str = (
        f"[שקף {req.position_slide_num}] " if req.position_slide_num else ""
    )

    status_msg, _, full_json, _ = add_slide(
        req.instruction, position_selection,
        req.before_or_after, req.layout,
    )
    return {
        "status": "success",
        "message": status_msg,
        "skeleton": deck_state["skeleton"],
    }
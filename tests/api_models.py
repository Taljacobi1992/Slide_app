"""
Pydantic models for the Presentation API.
These define the request/response schemas that appear in the Swagger docs.
"""

from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Optional


#  Request Models

class GenerateOutlineRequest(BaseModel):
    """Template-free flow — step 1: generate a proposed outline."""
    user_prompt: str = Field(..., description="הנחיית המשתמש (נדרש)")
    document_text: Optional[str] = Field("", description="טקסט מסמך מקור (אופציונלי)")
    slide_count: Optional[int] = Field(None, ge=1, le=30, description="מספר שקפים מבוקש (None = אוטומטי)")

    model_config = {"json_schema_extra": {"examples": [
        {"user_prompt": "מצגת על חקירת אירוע טיסת חירום", "document_text": "...", "slide_count": 5}
    ]}}


class EditOutlineRequest(BaseModel):
    """Template-free flow — step 2 (optional): edit the proposed outline before approval."""
    edit_instruction: str = Field(..., description='בקשת שינוי, לדוגמה: "הוסף שקף על לוחות זמנים"')


class GenerateFromTemplateRequest(BaseModel):
    """Template-based flow — step 1: upload a skeleton template and generate content."""
    template: dict = Field(..., description="JSON skeleton של התבנית (כולל slides)")
    user_prompt: Optional[str] = Field("", description="הנחיית משתמש (אופציונלי)")
    document_text: Optional[str] = Field("", description="טקסט מסמך מקור (אופציונלי)")



class generateFromTemplateRequest(BaseModel):
    """Tempalte-based flow - step 2 (optional): edit generated content."""



class DeckEditRequest(BaseModel):
    """Edit the entire deck via a natural-language instruction."""
    user_message: str = Field(..., description='הנחיית עריכה, לדוגמה: "הפוך את כל המצגת לפורמלית יותר"')


class SlideEditRequest(BaseModel):
    """Edit a single slide via a natural-language instruction."""
    user_message: str = Field(..., description='הנחיית עריכה, לדוגמה: "עדכן את Content 1 עם תאריך האירוע"')


#  Response Models

class OutlineResponse(BaseModel):
    """Returned after generating or editing an outline."""
    status: str
    slide_count: int
    outline: dict
    content_warning: Optional[str] = None


class DeckResponse(BaseModel):
    """Returned after generating, approving, or editing a full deck."""
    status: str
    slide_count: int
    revision_id: int
    deck: dict


class EditResultResponse(BaseModel):
    """Returned after a deck-level or slide-level edit."""
    status: str
    applied_count: int
    summary: str
    revision_id: int
    deck: dict


class RevisionInfo(BaseModel):
    revision_id: int
    timestamp: str
    action: str
    description: str


class RevisionsListResponse(BaseModel):
    revisions: list[RevisionInfo]


class RestoreResponse(BaseModel):
    status: str
    revision_id: int
    deck: dict


class ErrorResponse(BaseModel):
    status: str = "error"
    detail: str

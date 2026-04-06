from services.slide_agent import SlideAgent, ValidatorAgent
from services.structure_agent import generate_outline, edit_outline, outline_to_skeleton
from services.edit_agent import (
    deck_chat_edit, slide_chat_edit, on_slide_selected,
    apply_edits_to_skeleton, restore_revision, export_json
)
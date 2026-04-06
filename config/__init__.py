import os
from config.config import settings

from schemas.layouts import (
    AVAILABLE_LAYOUTS,
    LAYOUT_ICONS,
    STATUS_ICONS,
    LAYOUT_OBJECT_TEMPLATES,
)

# Environment variables
API_KEY: str = os.getenv(settings.model.api_key_env, "")
os.environ["OPENAI_API_KEY"] = API_KEY
os.environ["OPENAI_API_BASE"] = settings.model.url

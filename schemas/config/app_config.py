from pydantic import BaseModel, Field


class AppSettings(BaseModel):
    """General application settings."""
    max_revisions: int = Field(gt=0)
    max_validation_retries: int = Field(ge=0)
    language: str
    no_info_message: str



"""
class AppConfig(BaseModel):
    host: str
    port: str
"""
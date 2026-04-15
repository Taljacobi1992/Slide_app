import os
from pathlib import Path
from pydantic_settings import BaseSettings
from schemas.config.app_config import AppSettings
from schemas.config.llm_api_config import ModelConfig, AgentsConfig


ROOT_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model: ModelConfig
    agents: AgentsConfig
    settings: AppSettings


with open(os.path.join(ROOT_DIR, "config/config.json"), encoding="utf-8") as f:
    settings = Settings.model_validate_json(f.read())
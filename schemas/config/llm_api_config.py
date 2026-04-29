from pydantic import BaseModel, Field


class ModelConfig(BaseModel):
    """LLM provider connection settings."""
    name: str
    url: str
    api_key_env: str
    api_endpoint: str


class AgentParams(BaseModel):
    """Temperature, top_p, and token limit for a single agent role."""
    temperature: float = Field(ge=0.0, le=2.0)
    top_p: float = Field(ge=0.0, le=1.0)
    max_tokens: int = Field(gt=0)


class AgentsConfig(BaseModel):
    """LLM parameters for each agent role."""
    generation: AgentParams
    validation: AgentParams
    edit: AgentParams
    structure: AgentParams


"""
class LLMApiConfig(BaseModel):
    api_url: str
    api_endpoint: str
    model_name: str
    model_api_key: str
    model_temperature: float = 0.1
"""

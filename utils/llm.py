"""LLM utilities — model instances and call helpers for each agent role."""

import os
import re
import json
import httpx
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage

from config import settings

load_dotenv()

#  Lazy Model Cache (created on first use, not at import time)

_models: dict[str, ChatOpenAI] = {}


def _get_model(role: str) -> ChatOpenAI:
    """Return a cached ChatOpenAI instance for the given role, creating it on first use."""
    if role in _models:
        return _models[role]

    api_key: str = os.getenv(settings.model.api_key_env, "")
    base_url: str = f"{settings.model.url}/{settings.model.api_endpoint.split('/', 1)[0]}"
    http_client = httpx.Client(verify=False)
    http_async_client = httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(verify=False))

    agent_configs: dict = {
        "generation": settings.agents.generation,
        "validation": settings.agents.validation,
        "edit": settings.agents.edit,
        "structure": settings.agents.structure,
    }
    agent_cfg = agent_configs.get(role, settings.agents.generation)

    _models[role] = ChatOpenAI(
        model_name=settings.model.name,
        api_key=api_key,
        base_url=base_url,
        http_client=http_client,
        http_async_client=http_async_client,
        temperature=agent_cfg.temperature,
        top_p=agent_cfg.top_p,
        max_tokens=agent_cfg.max_tokens,
    )
    return _models[role]


#  Call Helpers

def call_llm(prompt: str, role: str = "generation") -> str:
    """Send a prompt to the LLM using the model configured for the given role."""
    model: ChatOpenAI = _get_model(role)

    try:
        response = model.invoke([HumanMessage(content=prompt)])
        return response.content or ""
    except Exception as e:
        print(f"[LLM] Error ({role}): {e}")
        return ""


def call_llm_raw(prompt: str) -> str:
    """Call LLM with the structure role (used for outline generation)."""
    return call_llm(prompt, role="structure")


def parse_llm_json(raw_response: str) -> dict:
    """Parse a JSON object from an LLM response, handling common LLM quirks."""
    cleaned: str = raw_response.strip()

    # Strip markdown fences
    if cleaned.startswith("```"):
        cleaned = "\n".join(cleaned.split("\n")[1:])
    if cleaned.endswith("```"):
        cleaned = "\n".join(cleaned.split("\n")[:-1])
    cleaned = cleaned.strip()

    # Extract just the JSON object — ignore any text before/after
    first_brace: int = cleaned.find("{")
    last_brace: int = cleaned.rfind("}")
    if first_brace != -1 and last_brace != -1:
        cleaned = cleaned[first_brace:last_brace + 1]

    # Remove trailing commas before } or ]
    cleaned = re.sub(r",\s*([}\]])", r"\1", cleaned)

    # Remove single-line comments
    cleaned = re.sub(r"//.*?\n", "\n", cleaned)

    # Remove newlines inside JSON string values
    fixed_chars: list[str] = []
    in_string: bool = False
    prev_char: str = ""
    for char in cleaned:
        if char == '"' and prev_char != "\\":
            in_string = not in_string
        if char == "\n" and in_string:
            fixed_chars.append(" ")
        else:
            fixed_chars.append(char)
        prev_char = char
    cleaned = "".join(fixed_chars)

    return json.loads(cleaned)
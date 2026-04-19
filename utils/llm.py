"""LLM utilities — model instances and call helpers for each agent role."""

import os
import json
import httpx
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage

from config import settings

load_dotenv()

#  Credentials

API_KEY: str = os.getenv(settings.model.api_key_env, "")
BASE_URL: str = f"{settings.model.url}/{settings.model.api_endpoint.split('/', 1)[0]}"
HTTP_CLIENT = httpx.Client(verify=False)
HTTP_ASYNC_CLIENT = httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(verify=False))


#  Model Instances

generation_model: ChatOpenAI = ChatOpenAI(
    model_name=settings.model.name,
    api_key=API_KEY,
    base_url=BASE_URL,
    http_client=HTTP_CLIENT,
    http_async_client=HTTP_ASYNC_CLIENT,
    temperature=settings.agents.generation.temperature,
    top_p=settings.agents.generation.top_p,
    max_tokens=settings.agents.generation.max_tokens,
)

validation_model: ChatOpenAI = ChatOpenAI(
    model_name=settings.model.name,
    api_key=API_KEY,
    base_url=BASE_URL,
    http_client=HTTP_CLIENT,
    http_async_client=HTTP_ASYNC_CLIENT,
    temperature=settings.agents.validation.temperature,
    top_p=settings.agents.validation.top_p,
    max_tokens=settings.agents.validation.max_tokens,
)

edit_model: ChatOpenAI = ChatOpenAI(
    model_name=settings.model.name,
    api_key=API_KEY,
    base_url=BASE_URL,
    http_client=HTTP_CLIENT,
    http_async_client=HTTP_ASYNC_CLIENT,
    temperature=settings.agents.edit.temperature,
    top_p=settings.agents.edit.top_p,
    max_tokens=settings.agents.edit.max_tokens,
)

structure_model: ChatOpenAI = ChatOpenAI(
    model_name=settings.model.name,
    api_key=API_KEY,
    base_url=BASE_URL,
    http_client=HTTP_CLIENT,
    http_async_client=HTTP_ASYNC_CLIENT,
    temperature=settings.agents.structure.temperature,
    top_p=settings.agents.structure.top_p,
    max_tokens=settings.agents.structure.max_tokens,
)


#  Call Helpers

def call_llm(prompt: str, role: str = "generation") -> str:
    """Send a prompt to the LLM using the model configured for the given role."""
    models: dict[str, ChatOpenAI] = {
        "generation": generation_model,
        "validation": validation_model,
        "edit": edit_model,
        "structure": structure_model,
    }
    model: ChatOpenAI = models.get(role, generation_model)

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
    """Parse a JSON object from an LLM response, stripping markdown fences."""
    cleaned: str = raw_response.strip()
    if cleaned.startswith("```"):
        cleaned = "\n".join(cleaned.split("\n")[1:])
    if cleaned.endswith("```"):
        cleaned = "\n".join(cleaned.split("\n")[:-1])
    return json.loads(cleaned)

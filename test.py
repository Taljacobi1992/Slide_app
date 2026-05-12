from enum import verify
from mimetypes import MimeTypes
import os
from fastapi import FastAPI
import requests
import json

from urllib3 import request

bearer_token = "AI_SERVICES_TOKEN"

model_url = "https://ai-services.ai.idt.cts"
endpoint = "v1/chat/completions"

headers = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Authorization": f"Bearer {bearer_token}"
}

body = {
    "logprobs": False,
    "max_tokens": 1000,
    "messages": [
        {
            "role": "user",
            "content": "What is LLM?"
        }
    ],
    "model": "openai/gpt-oss-120b",
    "temperature": 1,
    "top_p": 0.95
}

res = requests.post(f"{model_url}/{endpoint}", json=body, headers=headers)
print(json.dumps(res.json(), input=2))
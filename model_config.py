import os
from dotenv import load_dotenv
import requests
import json

load_dotenv()
bearer_token = os.getenv("AI_SERVICES_TOKEN")

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
            "content": "Tell me a bit about LLMs"
        }
    ],
    "model": "openai/gpt-oss-120b",
    "temperature": 1,
    "top_p": 0.95
}

res = requests.post(f"{model_url}/{endpoint}", json=body, headers=headers)
print(json.dumps(res.json(), input=2))
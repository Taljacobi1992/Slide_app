import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()
model_url = "https://ai-services.ai.idt.cts"

os.environ["OPEMAI_API_KEY"] = os.getenv("AI_SERVICES_TOKEN")
os.environ["OPEMAI_API_BASE"] = model_url

model = ChatOpenAI(model_name="openai/gpt-oss-120b", temperature=0.3, top_p=0.9)

res = model.invoke("Hello, how are you?")
print(res)
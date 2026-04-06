"""
Main entry point — runs FastAPI + Gradio on a single server.

- Swagger UI:  http://localhost:8000/docs
- ReDoc:       http://localhost:8000/redoc
- Gradio UI:   http://localhost:8000/ui
- API base:    http://localhost:8000/api/...
"""

import uvicorn
from dotenv import load_dotenv

load_dotenv()

from api import app as fastapi_app    # FastAPI REST endpoints

# ── Import and mount Gradio ──
# We import the Gradio app builder from the existing notebook logic.
# Gradio mounts as a sub-application at /ui.

from app_gradio import build_app as build_gradio_app
import gradio as gr

gradio_app = build_gradio_app()
fastapi_app = gr.mount_gradio_app(fastapi_app, gradio_app, path="/ui")


if __name__ == "__main__":
    print("=" * 60)
    print("  Presentation Generator")
    print("  Swagger:  http://localhost:8000/docs")
    print("  Gradio:   http://localhost:8000/ui")
    print("=" * 60)
    uvicorn.run(fastapi_app, host="0.0.0.0", port=8000)

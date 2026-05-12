FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY pyproject.toml .
RUN pip install --no-cache-dir \
    fastapi \
    uvicorn \
    gradio \
    langchain-core \
    langchain-openai \
    pydantic \
    pydantic-settings \
    python-dotenv

# Copy project files
COPY config/ config/
COPY schemas/ schemas/
COPY utils/ utils/
COPY services/ services/
COPY prompts/ prompts/
COPY ui/ ui/
COPY api.py .
COPY main.py .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

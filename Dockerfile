# syntax=docker/dockerfile:1
# Fly.io image for the FastAPI dashboard. The database is external Supabase.
# Match the daily workflow: do not install the embeddings extra in the web image.
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

ARG UV_SYNC_FLAGS=""

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NATIVE_TLS=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# 1) Install dependencies first for Docker layer caching.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync ${UV_SYNC_FLAGS} --frozen --no-install-project --no-dev

# 2) Copy app source and install the project.
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync ${UV_SYNC_FLAGS} --frozen --no-dev

EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]

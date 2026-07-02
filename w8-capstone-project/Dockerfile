# syntax=docker/dockerfile:1
# Multi-stage build: resolve dependencies with uv, then run on a slim image.

# --- Builder: install locked dependencies into /app/.venv --------------------
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder

# chroma-hnswlib may need to compile from source if no wheel matches.
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0 \
    UV_HTTP_TIMEOUT=300

WORKDIR /app

# Dependencies first so this layer caches across source-only changes.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# --- Runtime -----------------------------------------------------------------
FROM python:3.13-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY . .

EXPOSE 8007

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8007/api/health', timeout=4)"

# main.py binds 127.0.0.1 with --reload for local dev; inside the container we
# bind 0.0.0.0 without reload.
CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8007"]

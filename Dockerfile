# syntax=docker/dockerfile:1
#
# FinAlly: single-container build (PLAN §11, TEAM_CONTRACT §5/§6).
#
# Container layout:
#   /app/backend   FastAPI app (uv project; venv at /app/backend/.venv)
#   /app/static    Next.js static export (frontend/out), served by FastAPI
#   /app/db        SQLite dir, mount the named volume here: -v finally-data:/app/db
#
# .env is NOT baked in; pass it at runtime with --env-file .env.

# ---------- Stage 1: build the frontend static export ----------
FROM node:20-slim AS frontend
WORKDIR /build/frontend
ENV NEXT_TELEMETRY_DISABLED=1

# Install deps first for layer caching.
COPY frontend/package.json frontend/package-lock.json* ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi

COPY frontend/ ./
RUN npm run build && test -f out/index.html

# ---------- Stage 2: Python runtime ----------
FROM python:3.12-slim AS runtime

COPY --from=ghcr.io/astral-sh/uv:0.9.26 /uv /uvx /usr/local/bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app/backend

# Dependencies only (cached unless pyproject/lock change).
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Application code, then a final sync (no-op for a non-packaged project).
COPY backend/ ./
RUN uv sync --frozen --no-dev

# Frontend build output.
COPY --from=frontend /build/frontend/out /app/static

RUN mkdir -p /app/db

ENV PATH="/app/backend/.venv/bin:${PATH}" \
    FINALLY_STATIC_DIR=/app/static \
    FINALLY_DB_PATH=/app/db/finally.db \
    LITELLM_LOCAL_MODEL_COST_MAP=True

VOLUME ["/app/db"]
EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=5 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]

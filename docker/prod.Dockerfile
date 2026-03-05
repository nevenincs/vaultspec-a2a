# Production multi-stage build (ADR-019: service separation).
# Stage 1: Build React frontend to static HTML/JS/CSS.
# Stage 2a: Python base -- shared deps layer.
# Stage 2b: API (control surface) with embedded frontend assets.
# Stage 2c: Worker (agent executor) -- no frontend assets.

# ── Stage 1: Frontend build ──────────────────────────────────────────────────
FROM node:22-alpine AS frontend-build

WORKDIR /app/src/ui
COPY src/ui/package*.json ./
RUN npm ci
COPY src/ui/ .
RUN npm run build

# ── Stage 2a: Python base (shared by api + worker) ──────────────────────────
FROM python:3.13-slim-bookworm AS python-base
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

# Two-phase uv sync: deps first (cached), then app
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-install-project --no-dev --locked

COPY lib/ ./lib/

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev --frozen --no-editable

# Non-root user
RUN groupadd -g 1001 app && useradd -u 1001 -g app -m appuser
USER appuser

# ── Stage 2b: API (control surface) ─────────────────────────────────────────
FROM python-base AS api

COPY --from=frontend-build /app/src/ui/build ./lib/api/static/

# Control surface: auto_spawn_worker=False (worker is a separate container)
ENV VAULTSPEC_AUTO_SPAWN_WORKER=false \
    VAULTSPEC_WORKER_URL=http://worker:8001

EXPOSE 8000
CMD ["uv", "run", "uvicorn", "lib.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]

# ── Stage 2c: Worker (agent executor) ───────────────────────────────────────
FROM python-base AS worker

# Worker does not serve frontend assets -- no COPY from frontend-build
ENV VAULTSPEC_API_BASE_URL=http://api:8000

EXPOSE 8001
CMD ["uv", "run", "uvicorn", "lib.worker.app:create_worker_app", "--factory", "--host", "0.0.0.0", "--port", "8001"]

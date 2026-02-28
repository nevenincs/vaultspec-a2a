# Production multi-stage build.
# Stage 1: Build SvelteKit frontend to static HTML/JS/CSS.
# Stage 2: Python runtime with embedded frontend assets.

# ── Stage 1: Frontend build ──────────────────────────────────────────────────
FROM node:22-alpine AS frontend-build

WORKDIR /app/src/ui
COPY src/ui/package*.json ./
RUN npm ci
COPY src/ui/ .
RUN npm run build

# ── Stage 2: Python runtime ──────────────────────────────────────────────────
FROM python:3.13-slim-bookworm AS runtime
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
COPY --from=frontend-build /app/src/ui/build ./lib/api/static/

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev --frozen --no-editable

# Non-root user
RUN groupadd -g 1001 app && useradd -u 1001 -g app -m appuser
USER appuser

EXPOSE 8000
CMD ["uv", "run", "uvicorn", "lib.api.app:app", "--host", "0.0.0.0", "--port", "8000"]

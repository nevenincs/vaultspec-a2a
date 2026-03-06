# Lightweight dev images for the docker compose dev workflow.
# Two independent targets: python-base (backend dev) and node-base (vite dev).

# ── Python base: backend dev with hot-reload ─────────────────────────────────
FROM python:3.13-slim-bookworm AS python-base
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

# Two-phase sync: deps first (cached layer), then app code
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-install-project --locked

COPY src/vaultspec_a2a/ ./src/vaultspec_a2a/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-editable

EXPOSE 8000

# ── Node base: vite dev server with HMR ──────────────────────────────────────
FROM node:22-alpine AS node-base

WORKDIR /app/src/ui
COPY src/ui/package*.json ./
RUN npm ci

EXPOSE 5173

# ── Mock Seeder base: continuous DB population daemon ──────────────────────────
FROM python-base AS mock-seeder

# This container's sole purpose is to loop through mock team presets
# and stream trace data directly using the local AsyncSqliteSaver.

CMD ["uv", "run", "python", "docker/run.py"]

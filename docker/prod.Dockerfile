# Production multi-stage build (ADR-019: service separation).
# Stage 1: Build React frontend to static HTML/JS/CSS.
#          Also installs root node_modules (ACP runtime deps — pure JS).
# Stage 2a: Python base -- shared deps layer.
# Stage 2b: Gateway (control surface) with embedded frontend assets.
# Stage 2c: Worker (agent executor) with ACP Node.js runtime.

# ── Stage 1: Frontend build + ACP runtime deps ───────────────────────────────
FROM node:22-alpine AS frontend-build

WORKDIR /app/src/ui
COPY src/ui/package*.json ./
RUN npm ci
COPY src/ui/ .
RUN npm run build

# Install root node_modules (contains @zed-industries/claude-agent-acp).
# node_modules are pure JavaScript — portable from Alpine to any OS.
WORKDIR /app
COPY package*.json ./
RUN npm ci --omit=dev

# ── Stage 2a: Python base (shared by gateway + worker) ──────────────────────
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

COPY src/vaultspec_a2a/ ./src/vaultspec_a2a/

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev --frozen --no-editable

# Non-root user
RUN groupadd -g 1001 app && useradd -u 1001 -g app -m appuser
USER appuser

# ── Stage 2b: Gateway (control surface) ─────────────────────────────────────
FROM python-base AS gateway

# Copy SPA assets to a path independent of the Python package layout.
# APP-N04: __file__ traversal resolves into site-packages in non-editable
# installs; VAULTSPEC_UI_BUILD_DIR overrides the computed path in app.py.
COPY --from=frontend-build /app/src/ui/dist ./src/ui/dist/

# Worker runs as a separate container — never auto-spawn inside Docker.
ENV VAULTSPEC_WORKER_URL=http://worker:8001 \
    VAULTSPEC_UI_BUILD_DIR=/app/src/ui/dist \
    VAULTSPEC_AUTO_SPAWN_WORKER=false

EXPOSE 8000
CMD ["uv", "run", "uvicorn", "vaultspec_a2a.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]

# ── Stage 2c: Worker (agent executor) ───────────────────────────────────────
FROM python-base AS worker

# PROV-O01: ACP runtime — Claude/Gemini providers spawn claude-agent-acp as a
# Node.js subprocess.  The worker needs a glibc-compatible node binary.
# node:22-slim is Debian/bookworm-based, compatible with python:3.13-slim-bookworm.
# node_modules are pure JavaScript from the Alpine frontend-build stage — portable.
COPY --from=node:22-slim /usr/local/bin/node /usr/local/bin/node
COPY --from=frontend-build /app/node_modules ./node_modules/

# PROV-O02: VAULTSPEC_PROJECT_ROOT prevents path traversal resolving into
# site-packages in non-editable installs (factory.py _PROJECT_ROOT).
ENV VAULTSPEC_MCP_API_BASE_URL=http://gateway:8000 \
    VAULTSPEC_PROJECT_ROOT=/app

EXPOSE 8001
CMD ["uv", "run", "uvicorn", "vaultspec_a2a.worker.app:create_worker_app", "--factory", "--host", "0.0.0.0", "--port", "8001"]

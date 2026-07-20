# Production multi-stage build (ADR-019: service separation).
# A2A is headless — there is no frontend to build (dashboard ADR D7).
# Stage 1: Install root node_modules (ACP runtime deps — glibc native binaries).
# Stage 2a: Python base -- shared deps layer.
# Stage 2b: Gateway (control surface).
# Stage 2c: Worker (agent executor) with ACP Node.js runtime.

# ── Stage 1: ACP runtime node deps (glibc, worker-libc-matched) ─────────────
# MUST match the worker's libc: @agentclientprotocol/claude-agent-acp bundles
# @anthropic-ai/claude-agent-sdk, whose 0.3.x line ships libc-SPECIFIC native
# binaries as optionalDependencies (…-linux-x64 for glibc, …-linux-x64-musl for
# musl). npm installs only the variant matching the build host's libc, so this
# stage MUST be glibc (Debian) to produce a binary the glibc worker can load —
# building on Alpine (musl) yields a musl binary that will not load in the
# bookworm worker. node:22-slim is Debian/bookworm-based, matching the worker.
FROM node:22-slim AS node-deps

# Install root node_modules (contains @agentclientprotocol/claude-agent-acp).
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
COPY alembic.ini ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-install-project --no-dev --locked

COPY src/vaultspec_a2a/ ./src/vaultspec_a2a/
# The wheel force-includes the desktop component-manifest schema from the
# repository root, so the build context must carry it or the project build fails.
COPY schemas/ ./schemas/

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev --frozen --no-editable

# Non-root user
RUN groupadd -g 1001 app && useradd -u 1001 -g app -m appuser
# The SQLite database and checkpoint files live under /app/data, which Compose
# backs with a named volume. Create the directory owned by the non-root user
# while still root: Docker seeds a fresh named volume from the image mountpoint,
# so this ownership carries into the volume and lets the runtime open the
# database (SQLite reports "unable to open database file" against a root-owned
# mount otherwise).
RUN mkdir -p /app/data && chown appuser:app /app/data
USER appuser

# ── Stage 2b: Gateway (control surface) ─────────────────────────────────────
FROM python-base AS gateway

# Worker runs as a separate container — never auto-spawn inside Docker.
ENV VAULTSPEC_WORKER_URL=http://worker:18001 \
    VAULTSPEC_PROJECT_ROOT=/app \
    VAULTSPEC_AUTO_SPAWN_WORKER=false

EXPOSE 18000
CMD ["/app/.venv/bin/python", "-m", "uvicorn", "vaultspec_a2a.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "18000"]

# ── Stage 2c: Worker (agent executor) ───────────────────────────────────────
FROM node:22-slim AS gemini-cli
ARG GEMINI_CLI_NPM_SPEC=@google/gemini-cli@0.3.3
RUN npm install -g ${GEMINI_CLI_NPM_SPEC}

# ── Stage 2d: Worker (agent executor) ───────────────────────────────────────
FROM python-base AS worker

# PROV-O01: ACP runtime — Claude/Gemini providers spawn claude-agent-acp as a
# Node.js subprocess.  The worker needs a glibc-compatible node binary.
# node:22-slim is Debian/bookworm-based, compatible with python:3.13-slim-bookworm.
# node_modules carry the claude-agent-sdk glibc native binary, built in the
# glibc node-deps stage above so it loads under this glibc node (the adapter
# falls back to the vendored SDK when no system claude is present, so the native
# binary IS on the Docker Claude path).
COPY --from=node:22-slim /usr/local/bin/node /usr/local/bin/node
COPY --from=node-deps /app/node_modules ./node_modules/
# PROV-DOCKER-01: Gemini CLI is the official ACP entry point for Gemini. Install
# it in a dedicated Node stage and copy the package runtime into the worker so
# Docker support does not depend on a host-level gemini binary.
COPY --from=gemini-cli /usr/local/lib/node_modules/@google /usr/local/lib/node_modules/@google

# PROV-O02: VAULTSPEC_PROJECT_ROOT prevents path traversal resolving into
# site-packages in non-editable installs (factory.py _PROJECT_ROOT).
ENV VAULTSPEC_GATEWAY_URL=http://gateway:18000 \
    VAULTSPEC_PROJECT_ROOT=/app

EXPOSE 18001
CMD ["/app/.venv/bin/python", "-m", "uvicorn", "vaultspec_a2a.worker.app:create_worker_app", "--factory", "--host", "0.0.0.0", "--port", "18001"]

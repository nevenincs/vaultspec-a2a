# Lightweight dev image for the docker compose dev workflow.
# Single target: python-base (backend dev with hot-reload).

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

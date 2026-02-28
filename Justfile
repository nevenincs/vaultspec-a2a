set windows-shell := ["powershell.exe", "-c"]
set dotenv-load := true

# Bootstrap: install all dependencies
setup: _check-uv _check-node
    uv sync --all-groups
    cd src/ui && npm install
    @echo "Setup complete. Run 'just dev' to start."

# Development: fixture server + vite frontend (local, no Docker)
dev:
    just _dev-fixture &
    cd src/ui && npm run dev

# Development with real backend (requires .env with API keys)
dev-real:
    uv run uvicorn lib.api.app:app --reload --port 8000 &
    cd src/ui && npm run dev

# Docker: start dev environment (fixture server + vite + Jaeger)
up:
    docker compose up --build

# Docker: stop dev environment
down:
    docker compose down

# Run test suite
test *ARGS:
    uv run pytest {{ARGS}}

# Lint check
lint:
    uv run ruff check .
    uv run ruff format --check .

# Auto-fix lint + format
format:
    uv run ruff check --fix .
    uv run ruff format .

# Type check
typecheck:
    uv run ty check

# Frontend type check
check-ui:
    cd src/ui && npm run check

# Build production Docker image
docker-build:
    docker build -t vaultspec-a2a .

# ── Internal recipes ─────────────────────────────────────────────────────────

_dev-fixture:
    cd src/ui/dev && uv run python fixture_server.py

_check-uv:
    @uv --version || (echo "Install uv: https://docs.astral.sh/uv/" && exit 1)

_check-node:
    @node --version || (echo "Install Node 22: https://nodejs.org/" && exit 1)

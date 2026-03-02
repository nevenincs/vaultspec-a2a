set windows-shell := ["powershell.exe", "-c"]
set dotenv-load := true

# Bootstrap: install all dependencies
setup: _check-uv _check-node
    uv sync --all-groups
    npm install
    cd src/ui && npm install
    @echo "Setup complete. Run 'just dev' to start."

# Development: fixture server + vite frontend (local, no Docker)
dev:
    just _dev-fixture &
    cd src/ui && npm run dev

# Development with real backend (API + worker + frontend, requires .env)
dev-real:
    just _dev-worker &
    uv run uvicorn lib.api.app:create_app --factory --reload --port 8000 &
    cd src/ui && npm run dev

# Start just the worker process (for split-terminal development)
worker:
    uv run uvicorn lib.worker.app:create_worker_app --factory --reload --host 127.0.0.1 --port 8001

# Docker: start dev environment (fixture server + vite + Jaeger)
up:
    docker compose up --build

# Docker: start production environment (API + worker + Jaeger)
up-prod:
    docker compose -f docker-compose.prod.yml up --build

# Docker: stop dev environment
down:
    docker compose down

# Docker: stop production environment
down-prod:
    docker compose -f docker-compose.prod.yml down

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

# Build production Docker images
docker-build:
    docker build -t vaultspec-a2a-api --target api .
    docker build -t vaultspec-a2a-worker --target worker .

# ── Internal recipes ─────────────────────────────────────────────────────────

_dev-fixture:
    cd src/ui/dev && uv run python fixture_server.py

_dev-worker:
    uv run uvicorn lib.worker.app:create_worker_app --factory --reload --host 127.0.0.1 --port 8001

_check-uv:
    @uv --version || (echo "Install uv: https://docs.astral.sh/uv/" && exit 1)

_check-node:
    @node --version || (echo "Install Node 22: https://nodejs.org/" && exit 1)

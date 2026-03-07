set windows-shell := ["powershell.exe", "-c"]
set dotenv-load := true

# Bootstrap: install all dependencies
setup: _check-uv _check-node
    uv sync --all-groups
    npm install
    cd src/ui && npm install
    @echo "Setup complete. Run 'just dev' to start."

# Development: API + worker + vite frontend (local, no Docker)
# NOTE: Uses & for backgrounding — requires bash, not PowerShell.
dev:
    just _dev-worker &
    uv run uvicorn vaultspec_a2a.api.app:create_app --factory --reload --port 8000 &
    cd src/ui && npm run dev

# Start just the worker process (for split-terminal development)
worker:
    uv run vaultspec service start worker

# Docker: start dev environment (vite + mocks + Jaeger)
up:
    docker compose -f docker-compose.dev.yml up --build

# Docker: start production environment (API + worker + Jaeger)
up-prod:
    docker compose -f docker-compose.prod.yml up --build

# Docker: stop dev environment
down:
    docker compose -f docker-compose.dev.yml down

# Docker: stop production environment
down-prod:
    docker compose -f docker-compose.prod.yml down

# Run test suite
test *ARGS:
    uv run pytest {{ARGS}}

# Run unit tests only (excludes live tests, same as CI)
test-unit *ARGS:
    uv run pytest -m "not live" {{ARGS}}

# Run live tests only (requires live ACP backend)
test-live *ARGS:
    uv run pytest -m live {{ARGS}}

# Run tests with coverage report
test-cov *ARGS:
    uv run pytest --cov=src/vaultspec_a2a --cov-report=term-missing {{ARGS}}

# Quick pre-push check: lint + typecheck
check:
    just lint
    just typecheck

# Full CI pipeline: lint + typecheck + unit tests
ci:
    just lint
    just typecheck
    just test-unit

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

# Dependency audit
audit:
    uv run deptry src/

# Build distribution package
build:
    uv build

# Remove build artifacts and caches
clean:
    Remove-Item -Recurse -Force dist/, *.egg-info -ErrorAction SilentlyContinue
    fd -t d __pycache__ --exclude .venv -x Remove-Item -Recurse -Force

# Build production Docker images
docker-build:
    docker build -t vaultspec-a2a-api -f docker/prod.Dockerfile --target api .
    docker build -t vaultspec-a2a-worker -f docker/prod.Dockerfile --target worker .

# Run a preps scenario (solo_coder | pipeline_team | plan_approval | autonomous)
preps SCENARIO:
    uv run vaultspec run mock {{SCENARIO}}

# List available preps scenarios
preps-list:
    uv run vaultspec run mock

# Run smoke evaluation suite (routing + gate compliance)
eval-smoke:
    uv run vaultspec test benchmark smoke

# Run nightly evaluation suite (all 6 dimensions, requires LANGSMITH_API_KEY)
eval-nightly:
    uv run vaultspec test benchmark nightly

# Run a provider connectivity probe (claude | gemini | openai | zhipu)
probe PROVIDER:
    uv run vaultspec run probe {{PROVIDER}}

# List teams (optional status filter)
teams *STATUS:
    uv run vaultspec team list {{STATUS}}

# Check service health
service-status:
    uv run vaultspec service status

# Stop running services
service-stop:
    uv run vaultspec service stop

# Start standalone MCP server (stdio by default, use TRANSPORT=streamable-http for HTTP)
mcp TRANSPORT="stdio" *ARGS:
    uv run vaultspec-mcp --transport {{TRANSPORT}} {{ARGS}}

# ── Internal recipes ─────────────────────────────────────────────────────────

_dev-worker:
    uv run uvicorn vaultspec_a2a.worker.app:create_worker_app --factory --reload --host 127.0.0.1 --port 8001

_check-uv:
    @uv --version || (echo "Install uv: https://docs.astral.sh/uv/" && exit 1)

_check-node:
    @node --version || (echo "Install Node 22: https://nodejs.org/" && exit 1)

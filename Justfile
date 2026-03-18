set windows-shell := ["powershell.exe", "-c"]
set dotenv-load := true

# Bootstrap: install all dependencies
setup: _check-uv _check-node
    uv sync --all-groups
    npm install
    cd src/ui && npm install
    @echo "Setup complete. Run 'just dev' for the recommended frontend workflow."

# Frontend-ready local development guide (split terminals, no Docker)
dev:
    @echo "Frontend-ready local workflow:"
    @echo "  Terminal 1: just dev-gateway"
    @echo "  Terminal 2: just dev-worker"
    @echo "  Terminal 3: just dev-ui"
    @echo ""
    @echo "Starting the Vite UI in this terminal now..."
    cd src/ui && npm run dev

# Frontend-ready local gateway process (foreground)
dev-gateway:
    uv run uvicorn vaultspec_a2a.api.app:create_app --factory --reload --host 127.0.0.1 --port 8000

# Frontend-ready local worker process (foreground)
dev-worker:
    uv run uvicorn vaultspec_a2a.worker.app:create_worker_app --factory --reload --host 127.0.0.1 --port 8001

# Frontend-ready local UI process (foreground)
dev-ui:
    cd src/ui && npm run dev

# Frontend-ready Docker stack (gateway + worker + Vite)
up:
    docker compose -f docker-compose.dev.yml up --build

# Alias for the frontend-ready Docker stack
dev-stack:
    docker compose -f docker-compose.dev.yml up --build

# Full integration Docker stack (frontend + mocks + tracing)
up-integration:
    docker compose -f docker-compose.dev.yml -f docker-compose.integration.yml up --build

# Alias for the full integration stack
dev-integration:
    docker compose -f docker-compose.dev.yml -f docker-compose.integration.yml up --build

# Production-like Docker stack (gateway + worker + Jaeger)
up-prod:
    docker compose -f docker-compose.prod.yml up --build

# Production-like Postgres Docker stack
up-prod-postgres:
    docker compose -f docker-compose.prod.yml -f docker-compose.prod.postgres.yml up --build

# Stop the frontend-ready Docker stack
down:
    docker compose -f docker-compose.dev.yml down

# Stop the full integration Docker stack
down-integration:
    docker compose -f docker-compose.dev.yml -f docker-compose.integration.yml down

# Stop the production-like Docker stack
down-prod:
    docker compose -f docker-compose.prod.yml down

# Stop the production-like Postgres Docker stack
down-prod-postgres:
    docker compose -f docker-compose.prod.yml -f docker-compose.prod.postgres.yml down -v

# Run test suite
test *ARGS:
    uv run pytest {{ARGS}}

# Run unit tests only (excludes live tests, same as CI)
test-unit *ARGS:
    uv run pytest -m "not live" {{ARGS}}

# Run live tests only (requires live ACP backend)
test-live *ARGS:
    uv run pytest -m live {{ARGS}}

# Run requires_jaeger tests against the persistent local Jaeger instance
# (OTLP gRPC on localhost:4317, UI/query on localhost:16686, health on
# http://localhost:13133/status). Start it with `just jaeger-up`.
test-tracing *ARGS:
    uv run pytest -m requires_jaeger {{ARGS}}

# Start the persistent local Jaeger container used for reviewable tracing tests
# and local trace inspection.
jaeger-up:
    docker run -d --name jaeger-local -p 4317:4317 -p 4318:4318 -p 16686:16686 -p 13133:13133 -e COLLECTOR_OTLP_ENABLED=true cr.jaegertracing.io/jaegertracing/jaeger:2.16.0; Write-Host "Jaeger UI: http://localhost:16686  Health: http://localhost:13133/status"

# Stop and remove the local Jaeger container
jaeger-down:
    -docker stop jaeger-local
    -docker rm jaeger-local

# Check persistent local Jaeger health (OpenTelemetry health extension:
# http://localhost:13133/status must return 200)
jaeger-health:
    $code = (Invoke-WebRequest -Uri "http://localhost:13133/status" -UseBasicParsing -ErrorAction SilentlyContinue).StatusCode; if ($code -eq 200) { Write-Host "Jaeger healthy (200)" } else { Write-Host "Jaeger not ready (got: $code)"; exit 1 }

# Run requires_vidaimock tests against a live local VidaiMock instance (start with just vidaimock-up)
test-mock *ARGS:
    uv run pytest -m requires_vidaimock {{ARGS}}

# Start VidaiMock via integration compose (serves tapes at http://localhost:8100)
vidaimock-up:
    docker compose -f docker-compose.integration.yml up -d --build vidaimock; Write-Host "VidaiMock running at http://localhost:8100/v1/models"

# Stop and remove the local VidaiMock container
vidaimock-down:
    docker compose -f docker-compose.integration.yml stop vidaimock
    docker compose -f docker-compose.integration.yml rm -f vidaimock

# Check VidaiMock health (/v1/models must return 200)
vidaimock-health:
    $code = (Invoke-WebRequest -Uri "http://localhost:8100/v1/models" -UseBasicParsing -ErrorAction SilentlyContinue).StatusCode; if ($code -eq 200) { Write-Host "VidaiMock healthy (200)" } else { Write-Host "VidaiMock not ready (got: $code)"; exit 1 }

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
    docker build -t vaultspec-a2a-gateway -f docker/prod.Dockerfile --target gateway .
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

# Hard-fail provider readiness check for certifying live suites
verify-live-provider PROVIDER:
    just probe {{PROVIDER}}

# Hard-fail selection of the first healthy real provider for certifying live suites
verify-live-provider-certifying:
    uv run python -m vaultspec_a2a.providers.probes.certifying

# Phase 2 live Postgres recovery verification
verify-live-recovery-postgres:
    $provider = uv run python -m vaultspec_a2a.providers.probes.certifying; if (-not $provider) { exit 1 }; $env:VAULTSPEC_LIVE_TEST_PROVIDER = ($provider | Select-Object -Last 1).Trim(); uv run pytest src/vaultspec_a2a/tests/test_crash_recovery.py src/vaultspec_a2a/tests/test_permission_durability_live.py -m live -q

# Live orchestration verification on the certifying Postgres backend
verify-live-orchestration:
    $provider = uv run python -m vaultspec_a2a.providers.probes.certifying; if (-not $provider) { exit 1 }; $env:VAULTSPEC_LIVE_TEST_PROVIDER = ($provider | Select-Object -Last 1).Trim(); uv run pytest src/vaultspec_a2a/tests/test_ipc_heartbeat_live.py src/vaultspec_a2a/tests/test_mcp_e2e_live.py -m live -q

# Prod-like Docker/Postgres verification using the production compose stack
verify-prodlike-docker:
    uv run vaultspec test prodlike-docker

# Provider-specific prod-like Docker verification for Claude
verify-claude-docker:
    uv run vaultspec test claude-docker

# Provider-specific prod-like Docker verification for Gemini
verify-gemini-docker:
    uv run vaultspec test gemini-docker

# Provider-specific prod-like Docker verification (claude | gemini)
verify-prodlike-docker-provider PROVIDER:
    uv run vaultspec test prodlike-provider {{PROVIDER}}

# List teams (optional status filter)
teams *STATUS:
    uv run vaultspec team list {{STATUS}}

# Check tracked local service health
service-status:
    uv run vaultspec service status

# Stop tracked local services
service-stop:
    uv run vaultspec service stop

# Start standalone MCP server (stdio by default, use TRANSPORT=streamable-http for HTTP)
mcp TRANSPORT="stdio" *ARGS:
    uv run vaultspec-mcp --transport {{TRANSPORT}} {{ARGS}}

# Frontend-critical backend verification (repo-local temp/cache dirs)
verify-frontend-backend:
    $pytestRoot=Join-Path (Join-Path $HOME ".codex\memories") "vaultspec-pytest"; $tmpDir=Join-Path $pytestRoot "tmp"; $cacheDir=Join-Path $pytestRoot "cache"; New-Item -ItemType Directory -Force $tmpDir, $cacheDir | Out-Null; $env:TMP=$tmpDir; $env:TEMP=$tmpDir; $env:TMPDIR=$tmpDir; $env:PYTEST_DEBUG_TEMPROOT=$tmpDir; $env:LANGSMITH_TRACING="false"; $env:OTEL_SDK_DISABLED="true"; if (Test-Path .\.venv\Scripts\python.exe) { .\.venv\Scripts\python.exe -m pytest src\vaultspec_a2a\api\tests\test_endpoints.py src\vaultspec_a2a\api\tests\test_internal.py src\vaultspec_a2a\api\schemas\tests\test_schemas.py src\vaultspec_a2a\worker\tests\test_executor.py --capture=sys -o cache_dir=$cacheDir --basetemp=$tmpDir } else { uv run python -m pytest src\vaultspec_a2a\api\tests\test_endpoints.py src\vaultspec_a2a\api\tests\test_internal.py src\vaultspec_a2a\api\schemas\tests\test_schemas.py src\vaultspec_a2a\worker\tests\test_executor.py --capture=sys -o cache_dir=$cacheDir --basetemp=$tmpDir }

# Core routing/gating verification (repo-local temp/cache dirs)
verify-core:
    $pytestRoot=Join-Path (Join-Path $HOME ".codex\memories") "vaultspec-pytest"; $tmpDir=Join-Path $pytestRoot "tmp"; $cacheDir=Join-Path $pytestRoot "cache"; New-Item -ItemType Directory -Force $tmpDir, $cacheDir | Out-Null; $env:TMP=$tmpDir; $env:TEMP=$tmpDir; $env:TMPDIR=$tmpDir; $env:PYTEST_DEBUG_TEMPROOT=$tmpDir; $env:LANGSMITH_TRACING="false"; $env:OTEL_SDK_DISABLED="true"; if (Test-Path .\.venv\Scripts\python.exe) { .\.venv\Scripts\python.exe -m pytest src\vaultspec_a2a\core\tests\test_graph.py src\vaultspec_a2a\core\tests\test_supervisor.py src\vaultspec_a2a\core\tests\test_worker.py src\vaultspec_a2a\core\nodes\tests\test_supervisor.py src\vaultspec_a2a\core\nodes\tests\test_worker.py --capture=sys -o cache_dir=$cacheDir --basetemp=$tmpDir } else { uv run python -m pytest src\vaultspec_a2a\core\tests\test_graph.py src\vaultspec_a2a\core\tests\test_supervisor.py src\vaultspec_a2a\core\tests\test_worker.py src\vaultspec_a2a\core\nodes\tests\test_supervisor.py src\vaultspec_a2a\core\nodes\tests\test_worker.py --capture=sys -o cache_dir=$cacheDir --basetemp=$tmpDir }

# Live backend smoke checks against the local gateway + worker stack
smoke-backend:
    $pytestRoot=Join-Path (Join-Path $HOME ".codex\memories") "vaultspec-pytest"; $tmpDir=Join-Path $pytestRoot "tmp"; $cacheDir=Join-Path $pytestRoot "cache"; New-Item -ItemType Directory -Force $tmpDir, $cacheDir | Out-Null; $env:TMP=$tmpDir; $env:TEMP=$tmpDir; $env:TMPDIR=$tmpDir; $env:PYTEST_DEBUG_TEMPROOT=$tmpDir; $env:LANGSMITH_TRACING="false"; $env:OTEL_SDK_DISABLED="true"; if (Test-Path .\.venv\Scripts\python.exe) { .\.venv\Scripts\python.exe -m pytest src\vaultspec_a2a\tests\test_smoke.py -m live --capture=sys -o cache_dir=$cacheDir --basetemp=$tmpDir } else { uv run python -m pytest src\vaultspec_a2a\tests\test_smoke.py -m live --capture=sys -o cache_dir=$cacheDir --basetemp=$tmpDir }

# Check checked-in compose/env files for obvious secret material
check-secrets:
    $pytestRoot=Join-Path (Join-Path $HOME ".codex\memories") "vaultspec-pytest"; $tmpDir=Join-Path $pytestRoot "tmp"; $cacheDir=Join-Path $pytestRoot "cache"; New-Item -ItemType Directory -Force $tmpDir, $cacheDir | Out-Null; $env:TMP=$tmpDir; $env:TEMP=$tmpDir; $env:TMPDIR=$tmpDir; $env:PYTEST_DEBUG_TEMPROOT=$tmpDir; $env:LANGSMITH_TRACING="false"; $env:OTEL_SDK_DISABLED="true"; if (Test-Path .\.venv\Scripts\python.exe) { .\.venv\Scripts\python.exe -m pytest src\vaultspec_a2a\tests\test_repo_hygiene.py --capture=sys -o cache_dir=$cacheDir --basetemp=$tmpDir } else { uv run python -m pytest src\vaultspec_a2a\tests\test_repo_hygiene.py --capture=sys -o cache_dir=$cacheDir --basetemp=$tmpDir }

_check-uv:
    @uv --version || (echo "Install uv: https://docs.astral.sh/uv/" && exit 1)

_check-node:
    @node --version || (echo "Install Node 22: https://nodejs.org/" && exit 1)

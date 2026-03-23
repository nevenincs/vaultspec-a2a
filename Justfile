set windows-shell := ["powershell.exe", "-c"]
set shell := ["bash", "-cu"]
set dotenv-load := true

# ---------------------------------------------------------------------------
# Default: list all available recipes
# ---------------------------------------------------------------------------

# Show all available recipes
default:
    @just --list

# ---------------------------------------------------------------------------
# Top-level dispatchers
# ---------------------------------------------------------------------------

# Development toolchain — dispatch to dev-<subcommand>
dev *ARGS:
    just dev-{{ARGS}}

# Production CLI passthrough — dispatch to prod-<subcommand>
prod *ARGS:
    just prod-{{ARGS}}

# Full CI pipeline: lint + typecheck + unit tests
ci:
    just dev code check all
    just dev test unit

# ===========================================================================
# dev hooks — Commit pipeline
# ===========================================================================

# Dispatch: just dev hooks <action> [*args]
dev-hooks ACTION *ARGS:
    just _dev-hooks-{{ACTION}} {{ARGS}}

# Bootstrap the local virtualenv used by the repo hook pipeline.
_dev-hooks-bootstrap:
    uv venv .venv --allow-existing
    uv sync --locked --group dev

# Install the repo-managed, path-agnostic prek hook shim.
_dev-hooks-install:
    just _dev-hooks-bootstrap
    uv run --group dev python -m vaultspec_a2a.control.hooks install

# Remove the repo-managed hook shim.
_dev-hooks-remove:
    uv run --group dev python -m vaultspec_a2a.control.hooks remove

# Run the read-only prek pipeline outside a commit attempt.
_dev-hooks-run *ARGS:
    uv run --group dev --no-sync --frozen prek run {{ARGS}}

# Apply autofixes outside the Git stash/restore cycle, then rerun hooks.
_dev-hooks-fix *ARGS:
    just _dev-code-fix-all
    just _dev-hooks-run {{ARGS}}

# ===========================================================================
# dev service — Service lifecycle management
# ===========================================================================

# Dispatch: just dev service <action> [targets...]
dev-service *ARGS:
    just _dev-service-dispatch {{ARGS}}

# Internal dispatcher for service actions
_dev-service-dispatch ACTION *TARGETS:
    #!/usr/bin/env pwsh
    $action = "{{ACTION}}"
    $targets = "{{TARGETS}}"

    # Handle "db" subgroup
    if ($action -eq "db") {
        just _dev-service-db $targets
        exit $LASTEXITCODE
    }

    # Default target is "all"
    if ([string]::IsNullOrWhiteSpace($targets)) {
        $targets = "all"
    }

    # Expand group targets
    $prodTargets = @("gateway", "worker", "ui", "postgres")
    $devTargets = @("jaeger", "vidaimock")
    $allTargets = $prodTargets + $devTargets

    $resolvedTargets = @()
    foreach ($t in ($targets -split '\s+')) {
        switch ($t) {
            "all"  { $resolvedTargets += $allTargets }
            "prod" { $resolvedTargets += $prodTargets }
            "dev"  { $resolvedTargets += $devTargets }
            default { $resolvedTargets += $t }
        }
    }

    foreach ($target in $resolvedTargets) {
        $recipe = "_dev-service-${action}-${target}"
        just $recipe
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }

# --- start recipes ---

# Start the gateway API server (foreground, hot-reload)
_dev-service-start-gateway:
    #!/usr/bin/env pwsh
    $port = if ($env:VAULTSPEC_PORT) { $env:VAULTSPEC_PORT } else { "8000" }
    uv run uvicorn vaultspec_a2a.api.app:create_app --factory --reload --host 127.0.0.1 --port $port

# Start the worker executor (foreground, hot-reload)
_dev-service-start-worker:
    #!/usr/bin/env pwsh
    $port = if ($env:VAULTSPEC_WORKER_PORT) { $env:VAULTSPEC_WORKER_PORT } else { "8001" }
    uv run uvicorn vaultspec_a2a.worker.app:create_worker_app --factory --reload --host 127.0.0.1 --port $port

# Start the Vite frontend dev server (foreground)
_dev-service-start-ui:
    cd src/ui && npm run dev

# Start PostgreSQL via docker compose
_dev-service-start-postgres:
    docker compose -f docker-compose.prod.postgres.yml up -d postgres

# Start Jaeger tracing collector (OTLP gRPC :4317, UI :16686, health :13133)
_dev-service-start-jaeger:
    docker run -d --name jaeger-local -p 4317:4317 -p 4318:4318 -p 16686:16686 -p 13133:13133 -e COLLECTOR_OTLP_ENABLED=true cr.jaegertracing.io/jaegertracing/jaeger:2.16.0; echo "Jaeger UI: http://localhost:16686  Health: http://localhost:13133/status"

# Start VidaiMock LLM provider via integration compose
_dev-service-start-vidaimock:
    docker compose -f docker-compose.integration.yml up -d --build vidaimock; echo "VidaiMock running at http://localhost:8100/v1/models"

# --- stop recipes (graceful) ---

# Stop the gateway gracefully
_dev-service-stop-gateway:
    #!/usr/bin/env pwsh
    $port = if ($env:VAULTSPEC_PORT) { $env:VAULTSPEC_PORT } else { "8000" }
    $procs = Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -match "python|uvicorn" -and $_.CommandLine -match $port }
    if ($procs) { $procs | Stop-Process -Force; Write-Host "Gateway stopped." } else { Write-Host "Gateway not running." }

# Stop the worker gracefully
_dev-service-stop-worker:
    #!/usr/bin/env pwsh
    $port = if ($env:VAULTSPEC_WORKER_PORT) { $env:VAULTSPEC_WORKER_PORT } else { "8001" }
    $procs = Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -match "python|uvicorn" -and $_.CommandLine -match $port }
    if ($procs) { $procs | Stop-Process -Force; Write-Host "Worker stopped." } else { Write-Host "Worker not running." }

# Stop the UI dev server
_dev-service-stop-ui:
    #!/usr/bin/env pwsh
    $procs = Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -eq "node" -and $_.CommandLine -match "vite" }
    if ($procs) { $procs | Stop-Process -Force; Write-Host "UI stopped." } else { Write-Host "UI not running." }

# Stop PostgreSQL container
_dev-service-stop-postgres:
    -docker compose -f docker-compose.prod.postgres.yml stop postgres

# Stop Jaeger container
_dev-service-stop-jaeger:
    -docker stop jaeger-local

# Stop VidaiMock container
_dev-service-stop-vidaimock:
    docker compose -f docker-compose.integration.yml stop vidaimock

# --- kill recipes (force) ---

# Force-kill the gateway process
_dev-service-kill-gateway:
    #!/usr/bin/env pwsh
    $port = if ($env:VAULTSPEC_PORT) { $env:VAULTSPEC_PORT } else { "8000" }
    $procs = Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -match "python|uvicorn" -and $_.CommandLine -match $port }
    if ($procs) { $procs | Stop-Process -Force; Write-Host "Gateway killed." } else { Write-Host "Gateway not running." }

# Force-kill the worker process
_dev-service-kill-worker:
    #!/usr/bin/env pwsh
    $port = if ($env:VAULTSPEC_WORKER_PORT) { $env:VAULTSPEC_WORKER_PORT } else { "8001" }
    $procs = Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -match "python|uvicorn" -and $_.CommandLine -match $port }
    if ($procs) { $procs | Stop-Process -Force; Write-Host "Worker killed." } else { Write-Host "Worker not running." }

# Force-kill the UI dev server
_dev-service-kill-ui:
    #!/usr/bin/env pwsh
    $procs = Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -eq "node" -and $_.CommandLine -match "vite" }
    if ($procs) { $procs | Stop-Process -Force; Write-Host "UI killed." } else { Write-Host "UI not running." }

# Force-kill PostgreSQL container
_dev-service-kill-postgres:
    -docker compose -f docker-compose.prod.postgres.yml kill postgres

# Force-kill Jaeger container
_dev-service-kill-jaeger:
    -docker kill jaeger-local

# Force-kill VidaiMock container
_dev-service-kill-vidaimock:
    docker compose -f docker-compose.integration.yml kill vidaimock

# --- restart recipes ---

# Restart the gateway (stop then start)
_dev-service-restart-gateway:
    just _dev-service-stop-gateway
    just _dev-service-start-gateway

# Restart the worker (stop then start)
_dev-service-restart-worker:
    just _dev-service-stop-worker
    just _dev-service-start-worker

# Restart the UI dev server (stop then start)
_dev-service-restart-ui:
    just _dev-service-stop-ui
    just _dev-service-start-ui

# Restart PostgreSQL (stop then start)
_dev-service-restart-postgres:
    just _dev-service-stop-postgres
    just _dev-service-start-postgres

# Restart Jaeger (remove old container then start)
_dev-service-restart-jaeger:
    just _dev-service-stop-jaeger
    -docker rm jaeger-local
    just _dev-service-start-jaeger

# Restart VidaiMock (stop then start)
_dev-service-restart-vidaimock:
    just _dev-service-stop-vidaimock
    just _dev-service-start-vidaimock

# --- rebuild recipes ---

# Rebuild gateway: re-sync deps then restart
_dev-service-rebuild-gateway:
    uv sync --all-groups
    just _dev-service-restart-gateway

# Rebuild worker: re-sync deps then restart
_dev-service-rebuild-worker:
    uv sync --all-groups
    just _dev-service-restart-worker

# Rebuild UI: reinstall npm deps then restart
_dev-service-rebuild-ui:
    cd src/ui && npm install
    just _dev-service-restart-ui

# Rebuild PostgreSQL: destroy volume and recreate
_dev-service-rebuild-postgres:
    docker compose -f docker-compose.prod.postgres.yml down -v
    just _dev-service-start-postgres

# Rebuild Jaeger: remove container and restart
_dev-service-rebuild-jaeger:
    just _dev-service-stop-jaeger
    -docker rm jaeger-local
    just _dev-service-start-jaeger

# Rebuild VidaiMock: rebuild docker image and restart
_dev-service-rebuild-vidaimock:
    docker compose -f docker-compose.integration.yml up -d --build --force-recreate vidaimock

# --- health recipes ---

# Check gateway health via doctor.py
_dev-service-health-gateway:
    uv run python -m vaultspec_a2a.control.doctor services gateway

# Check worker health via doctor.py
_dev-service-health-worker:
    uv run python -m vaultspec_a2a.control.doctor services worker

# Check UI dev server health via doctor.py
_dev-service-health-ui:
    uv run python -m vaultspec_a2a.control.doctor services ui

# Check PostgreSQL health via doctor.py
_dev-service-health-postgres:
    uv run python -m vaultspec_a2a.control.doctor services postgres

# Check Jaeger health via doctor.py
_dev-service-health-jaeger:
    uv run python -m vaultspec_a2a.control.doctor services jaeger

# Check VidaiMock health via doctor.py
_dev-service-health-vidaimock:
    uv run python -m vaultspec_a2a.control.doctor services vidaimock

# --- logs recipes ---

# Tail gateway logs (foreground services print to terminal — this is a no-op hint)
_dev-service-logs-gateway:
    @echo "Gateway runs in foreground. Start it with: just dev service start gateway"

# Tail worker logs (foreground services print to terminal — this is a no-op hint)
_dev-service-logs-worker:
    @echo "Worker runs in foreground. Start it with: just dev service start worker"

# Tail UI logs (foreground services print to terminal — this is a no-op hint)
_dev-service-logs-ui:
    @echo "UI runs in foreground. Start it with: just dev service start ui"

# Tail PostgreSQL container logs
_dev-service-logs-postgres:
    docker compose -f docker-compose.prod.postgres.yml logs -f postgres

# Tail Jaeger container logs
_dev-service-logs-jaeger:
    docker logs -f jaeger-local

# Tail VidaiMock container logs
_dev-service-logs-vidaimock:
    docker compose -f docker-compose.integration.yml logs -f vidaimock

# --- probe recipe ---

# Run a provider connectivity probe (claude | gemini | openai | zhipu | --list)
dev-service-probe PROVIDER:
    uv run python -m vaultspec_a2a.providers.probes.{{PROVIDER}}

# --- db subgroup ---

# Dispatch database operations: migrate, snapshot, restore, clear
_dev-service-db *ARGS:
    uv run python -m vaultspec_a2a.control.db {{ARGS}}

# ===========================================================================
# dev code — Code quality
# ===========================================================================

# Dispatch: just dev code <action> [target]
dev-code ACTION TARGET="all":
    just _dev-code-{{ACTION}}-{{TARGET}}

# --- check recipes (read-only) ---

# Run ruff linter (check only)
_dev-code-check-lint:
    uv run ruff check .

# Run ty type checker
_dev-code-check-type:
    uv run ty check

# Run frontend type/lint checks
_dev-code-check-ui:
    cd src/ui && npm run check

# Run all code quality checks: lint + type + ui
_dev-code-check-all:
    just _dev-code-check-lint
    just _dev-code-check-type
    just _dev-code-check-ui

# --- fix recipes (auto-repair) ---

# Auto-fix lint errors and format code
_dev-code-fix-lint:
    uv run ruff check --fix .
    uv run ruff format .

# Auto-fix frontend lint/format issues
_dev-code-fix-ui:
    cd src/ui && npm run fix

# Auto-fix all: lint + ui
_dev-code-fix-all:
    just _dev-code-fix-lint
    just _dev-code-fix-ui

# ===========================================================================
# dev test — Testing
# ===========================================================================

# Dispatch: just dev test <target> [*args]
dev-test TARGET *ARGS:
    just _dev-test-{{TARGET}} {{ARGS}}

# Run unit tests (excludes live, requires_jaeger, requires_vidaimock)
_dev-test-unit *ARGS:
    uv run pytest -m "not live and not requires_jaeger and not requires_vidaimock" {{ARGS}}

# Run live tests (requires running backend + live ACP provider)
_dev-test-live *ARGS:
    uv run pytest -m live {{ARGS}}

# Run smoke tests against local gateway + worker stack
_dev-test-smoke *ARGS:
    uv run pytest src/vaultspec_a2a/tests/test_smoke.py -m live {{ARGS}}

# Run tracing tests (requires local Jaeger: just dev service start jaeger)
_dev-test-tracing *ARGS:
    uv run pytest -m requires_jaeger {{ARGS}}

# Run mock tests (requires VidaiMock: just dev service start vidaimock)
_dev-test-mock *ARGS:
    uv run pytest -m requires_vidaimock {{ARGS}}

# Run verification suites: docker, provider, endpoints, core
_dev-test-verify *ARGS:
    uv run python -m vaultspec_a2a.control.verify {{ARGS}}

# CI gate: unit tests + tracing (matches CI pipeline)
_dev-test-ci *ARGS:
    just _dev-test-unit {{ARGS}}
    just _dev-test-tracing {{ARGS}}

# Run the complete test suite
_dev-test-all *ARGS:
    uv run pytest {{ARGS}}

# Run tests with coverage report
_dev-test-cov *ARGS:
    uv run pytest --cov=src/vaultspec_a2a --cov-report=term-missing {{ARGS}}

# ===========================================================================
# dev build — Build artifacts
# ===========================================================================

# Dispatch: just dev build <target>
dev-build TARGET:
    just _dev-build-{{TARGET}}

# Build Python sdist + wheel
_dev-build-package:
    uv build

# Build local dev Docker images (gateway + worker)
_dev-build-docker:
    docker compose -f docker-compose.dev.yml build

# Build production multi-stage Docker images
_dev-build-docker-prod:
    docker build -t vaultspec-a2a-gateway -f docker/prod.Dockerfile --target gateway .
    docker build -t vaultspec-a2a-worker -f docker/prod.Dockerfile --target worker .

# Remove dist/, egg-info, and __pycache__ directories
_dev-build-clean:
    #!/usr/bin/env pwsh
    Remove-Item -Recurse -Force dist/, *.egg-info -ErrorAction SilentlyContinue
    Get-ChildItem -Path . -Directory -Recurse -Filter __pycache__ | Where-Object { $_.FullName -notmatch '\.venv' } | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

# ===========================================================================
# dev deps — Dependency management
# ===========================================================================

# Dispatch: just dev deps <action>
dev-deps ACTION:
    just _dev-deps-{{ACTION}}

# Full bootstrap: install all Python and Node dependencies
_dev-deps-install: _check-uv _check-node
    uv sync --all-groups
    npm install
    cd src/ui && npm install
    @echo "Dependencies installed. Run 'just dev service start gateway' to begin."

# Sync to lockfile (dev group only)
_dev-deps-sync:
    uv sync --locked --group dev

# Upgrade all dependencies
_dev-deps-upgrade:
    uv sync --upgrade --all-groups

# Regenerate the lockfile
_dev-deps-lock:
    uv lock

# ===========================================================================
# prod — Production CLI passthrough
# ===========================================================================

# Passthrough to Python CLI: vaultspec team <args>
prod-team *ARGS:
    uv run vaultspec team {{ARGS}}

# Passthrough to Python CLI: vaultspec agent <args>
prod-agent *ARGS:
    uv run vaultspec agent {{ARGS}}

# ===========================================================================
# Convenience aliases (backward compat during transition)
# ===========================================================================

# Run a preps scenario (backward compat — use: just dev test mock <scenario>)
preps SCENARIO:
    uv run python -m vaultspec_a2a.tests.preps.{{SCENARIO}}

# List available preps scenarios (backward compat — use: just dev test mock --list)
preps-list:
    uv run python -m vaultspec_a2a.tests.preps

# Start standalone MCP server (stdio by default, use TRANSPORT=streamable-http for HTTP)
mcp TRANSPORT="stdio" *ARGS:
    uv run vaultspec-mcp --transport {{TRANSPORT}} {{ARGS}}

# ===========================================================================
# Internal helpers
# ===========================================================================

# Verify uv is installed
_check-uv:
    @uv --version || (echo "Install uv: https://docs.astral.sh/uv/" && exit 1)

# Verify Node.js is installed
_check-node:
    @node --version || (echo "Install Node 22: https://nodejs.org/" && exit 1)

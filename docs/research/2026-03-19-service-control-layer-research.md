# Service Control Layer — Research & Gap Analysis

**Date**: 2026-03-19
**Status**: FINAL — Revision 3 (blind review applied, CLI shapes finalized)
**Triggered by**: CLI usability audit (2026-03-19), operator honest assessment, permission pipeline live audit
**Prior art**: `2026-03-08-process-supervision-models.md`, `2026-03-08-industry-service-stack-ux-patterns.md`, `2026-03-19-langgraph-control-plane-layer-mapping.md`
**ADR**: `docs/adrs/038-control-layer-cli-justfile-separation.md`
**Plan**: `docs/plans/2026-03-19-control-layer-execution-plan.md`
**Reference implementation**: `Y:/code/vaultspec-core-worktrees/main/` — Justfile + CLI separation pattern

---

## 1. Problem Statement

The VaultSpec A2A system has a **production-quality execution plane** — LangGraph
compiles graphs, ACP spawns Claude, tool calls execute, files appear on disk,
Jaeger captures 260-span traces. But the **control plane** — the layer that
starts services, validates preconditions, surfaces status, and enables operator
interaction — is non-functional as a coherent unit.

From the live operator assessment (2026-03-19):

> 11 of the 18 minutes were spent fighting service startup — not the system
> itself, but the operational scaffolding around it.

The operator had to:

1. Kill zombie processes from prior sessions (PID 84828 using 7GB RAM)
2. Discover port 8000 is held by a Windows system service — no detection
3. Set 7 environment variables manually
4. Start gateway via raw uvicorn because `service start` doesn't work
5. Restart everything twice to align config

**Expected time from first command to working system**: <30 seconds.
**Actual time**: 18 minutes.

---

## 2. Architectural Decision: CLI/Justfile Separation

### 2.1 The vaultspec-core Pattern

The vaultspec-core repository established a clean separation that has been
validated in production:

**Python CLI (`vaultspec-core`)** — Production, user-facing commands only:

- Operates against a workspace that is already set up
- Manages domain resources (vault, rules, skills, agents, config, system, hooks)
- Has `doctor` and `readiness` because they validate the **workspace** (the
  thing the CLI operates on), not dev infrastructure
- Standardized root options: `--target`, `--verbose`, `--debug`, `--version`
- MCP server (`vaultspec-mcp`) is a **separate executable**, not a subcommand

**Justfile** — Development toolchain:

- `just sync`, `just check`, `just test`, `just build`, `just publish`
- Target-based dispatch: `just check lint`, `just test python`, `just build docker`
- All service lifecycle, Docker orchestration, CI pipeline concerns live here
- Case/esac validation for targets, clear error on unknown target

### 2.2 Applying This to vaultspec-a2a

The current vaultspec-a2a CLI mixes production commands with dev tooling:

| Current CLI Group | Classification | Disposition |
|-------------------|---------------|-------------|
| `team` | **PRODUCTION** | Keep — this IS the product |
| `agent` | **PRODUCTION** | Keep — single-agent operations |
| `service` | **DEV TOOLING** | Remove from CLI → Justfile `dev` recipes |
| `test` | **DEV TOOLING** | Remove from CLI → Justfile `test` recipes |
| `run` (mock, probe) | **DEV TOOLING** | Remove from CLI → Justfile `run` recipes |
| `database` | **DEV TOOLING** | Remove from CLI → Justfile `db` recipes |
| `mcp` | **OUT OF SCOPE** | Remove from CLI — MCP is a separate executable already |

**The Python CLI's job is to operate teams. The Justfile's job is to operate
the development environment.** Every Python CLI command assumes the backend
(gateway + worker) is already running and fail-fast checks if it isn't.

### 2.3 MCP Server — Completely Out of Scope

The MCP server is a separate process (`vaultspec-mcp`) with its own transport
and lifecycle. It does not need CLI management, Justfile recipes, or any
integration with the service control layer. It connects to the gateway over
HTTP like any other client. No changes needed.

---

## 3. What Must Change

### 3.1 Commands to REMOVE from Python CLI

These files and their registrations in `cli/__init__.py` must be deleted:

| File | Command | Reason |
|------|---------|--------|
| `cli/_service.py` | `service start/stop/kill/status` | Dev tooling — moves to Justfile |
| `cli/_test.py` | `test unit/smoke/benchmark/prodlike-*` | Dev tooling — moves to Justfile |
| `cli/_verify.py` | (imported by _test.py) | Dev tooling — moves to Justfile |
| `cli/_run.py` | `run mock/probe` | Dev tooling — moves to Justfile |
| `cli/_database.py` | `database update/clear/snapshot/restore` | Dev tooling — moves to Justfile |
| `cli/_mcp.py` | `mcp status/tools/discovery` | Out of scope — MCP is separate |

### 3.2 Commands to KEEP in Python CLI

| File | Command | Why |
|------|---------|-----|
| `cli/_team.py` | `team start/status/resume/stop/delete/archive/list/presets/respond/overview` | Core product — team operations |
| `cli/_agent.py` | `agent list/ask` | Core product — single-agent operations |

### 3.3 Commands to ADD to Python CLI

| Command | Purpose |
|---------|---------|
| `team watch` | Live event streaming with inline permission approval (P2) |

### 3.4 What the Stripped CLI Looks Like

```text
vaultspec [--verbose] [--debug] [--version] [--show-config] <command> ...

  team
    start       Start a new team from a preset
    status      Get team status for a thread
    watch       Stream live events for a thread (P2)
    resume      Send a message into a thread
    stop        Cancel a running team
    delete      Delete a thread
    archive     Archive a completed thread
    list        List teams (optional status filter)
    presets     List available team presets
    respond     Respond to a pending permission request
    overview    Show team-wide status

  agent
    list        List available agent presets
    ask         Send a question to an agent preset
```

Root options (following vaultspec-core pattern):

| Option | Short | Meaning |
|--------|-------|---------|
| `--verbose` | `-v` | Enable INFO logging |
| `--debug` | `-d` | Enable DEBUG logging |
| `--version` | `-V` | Print version and exit |
| `--show-config` | | Print resolved settings and exit |

### 3.5 Fail-Fast Backend Check

Every production CLI command must fail fast if the backend is not running.
The current `_api_client()` in `_util.py` already catches `ConnectError` and
prints a clean message. This must be hardened:

```python
@contextmanager
def _api_client() -> Generator[httpx.Client]:
    """Yield a sync httpx client pointed at the gateway API.

    Fail-fast: if gateway is unreachable, print an actionable error
    directing the user to `just dev-gateway` or `just up`.
    """
    from ..core.config import settings
    base_url = f"http://127.0.0.1:{settings.port}/api"
    try:
        with httpx.Client(base_url=base_url, timeout=30.0) as client:
            _preflight_check(client)
            yield client
    except (httpx.ConnectError, httpx.ConnectTimeout):
        click.echo(
            f"Error: Gateway not running at http://127.0.0.1:{settings.port}\n"
            f"\n"
            f"Start the backend first:\n"
            f"  just dev-gateway    (terminal 1)\n"
            f"  just dev-worker     (terminal 2)\n"
            f"\n"
            f"Or use Docker:\n"
            f"  just up",
            err=True,
        )
        raise SystemExit(1) from None
```

---

## 4. Justfile Redesign

### 4.1 Structure: Mirroring vaultspec-core

The Justfile adopts the vaultspec-core pattern: **recipe + target** dispatch
using `case/esac`, with clear `dev` and `prod` namespaces.

### 4.2 Proposed Justfile

```justfile
set positional-arguments := false
set dotenv-load := true

local_image := "vaultspec-a2a:local"

default:
  @just --list

# --- dev namespace: service lifecycle, doctoring, health ---

# Start a dev service (foreground)
dev target='all':
  case "{{target}}" in \
    gateway) \
      uv run uvicorn vaultspec_a2a.api.app:create_app \
        --factory --reload --host 127.0.0.1 --port 8000 ;; \
    worker) \
      uv run uvicorn vaultspec_a2a.worker.app:create_worker_app \
        --factory --reload --host 127.0.0.1 --port 8001 ;; \
    ui) \
      cd src/ui && npm run dev ;; \
    all) \
      echo "Split-terminal workflow:" && \
      echo "  Terminal 1: just dev gateway" && \
      echo "  Terminal 2: just dev worker" && \
      echo "  Terminal 3: just dev ui" ;; \
    *) \
      echo "unknown dev target: {{target}}" >&2; \
      exit 1 ;; \
  esac

# Run system health checks (doctor)
doctor target='all':
  case "{{target}}" in \
    ports) \
      uv run python -m vaultspec_a2a.control.doctor ports ;; \
    config) \
      uv run python -m vaultspec_a2a.control.doctor config ;; \
    services) \
      uv run python -m vaultspec_a2a.control.doctor services ;; \
    all) \
      uv run python -m vaultspec_a2a.control.doctor ;; \
    *) \
      echo "unknown doctor target: {{target}}" >&2; \
      exit 1 ;; \
  esac

# Docker dev stack
up target='dev':
  case "{{target}}" in \
    dev) \
      docker compose -f docker-compose.dev.yml up --build ;; \
    integration) \
      docker compose -f docker-compose.dev.yml \
        -f docker-compose.integration.yml up --build ;; \
    prod) \
      docker compose -f docker-compose.prod.yml up --build ;; \
    prod-postgres) \
      docker compose -f docker-compose.prod.yml \
        -f docker-compose.prod.postgres.yml up --build ;; \
    *) \
      echo "unknown up target: {{target}}" >&2; \
      exit 1 ;; \
  esac

# Stop Docker stack
down target='dev':
  case "{{target}}" in \
    dev) \
      docker compose -f docker-compose.dev.yml down ;; \
    integration) \
      docker compose -f docker-compose.dev.yml \
        -f docker-compose.integration.yml down ;; \
    prod) \
      docker compose -f docker-compose.prod.yml down ;; \
    prod-postgres) \
      docker compose -f docker-compose.prod.yml \
        -f docker-compose.prod.postgres.yml down -v ;; \
    *) \
      echo "unknown down target: {{target}}" >&2; \
      exit 1 ;; \
  esac

# --- test namespace ---

test target='unit' *ARGS:
  case "{{target}}" in \
    unit) \
      uv run pytest -m "not live" {{ARGS}} ;; \
    live) \
      uv run pytest -m live {{ARGS}} ;; \
    tracing) \
      uv run pytest -m requires_jaeger {{ARGS}} ;; \
    mock) \
      uv run pytest -m requires_vidaimock {{ARGS}} ;; \
    smoke) \
      uv run pytest -m smoke {{ARGS}} ;; \
    all) \
      just test unit {{ARGS}} && \
      just test tracing {{ARGS}} ;; \
    *) \
      echo "unknown test target: {{target}}" >&2; \
      exit 1 ;; \
  esac

# --- check namespace: lint, type, audit ---

check target='all':
  case "{{target}}" in \
    lint) \
      uv run ruff check . ;; \
    format) \
      uv run ruff format --check . ;; \
    type) \
      uv run ty check ;; \
    ui) \
      cd src/ui && npm run check ;; \
    all) \
      just check lint && \
      just check format && \
      just check type ;; \
    *) \
      echo "unknown check target: {{target}}" >&2; \
      exit 1 ;; \
  esac

# --- fix namespace ---

fix target='lint':
  case "{{target}}" in \
    lint) \
      uv run ruff check --fix . && \
      uv run ruff format . ;; \
    *) \
      echo "unknown fix target: {{target}}" >&2; \
      exit 1 ;; \
  esac

# --- build namespace ---

build target='python':
  case "{{target}}" in \
    python) \
      uv build ;; \
    docker) \
      docker buildx build --load -t {{ local_image }} . ;; \
    all) \
      just build python && \
      just build docker ;; \
    *) \
      echo "unknown build target: {{target}}" >&2; \
      exit 1 ;; \
  esac

# --- run namespace: mock scenarios, probes ---

run target *ARGS:
  case "{{target}}" in \
    mock) \
      uv run python -m vaultspec_a2a.tests.preps {{ARGS}} ;; \
    probe) \
      uv run python -m vaultspec_a2a.providers.probes {{ARGS}} ;; \
    *) \
      echo "unknown run target: {{target}}" >&2; \
      exit 1 ;; \
  esac

# --- db namespace: migrations, snapshots ---

db target *ARGS:
  case "{{target}}" in \
    migrate) \
      uv run python -m alembic upgrade head ;; \
    clear) \
      echo "Destructive: pass --yes" && \
      uv run python -m vaultspec_a2a.control.db clear {{ARGS}} ;; \
    snapshot) \
      uv run python -m vaultspec_a2a.control.db snapshot {{ARGS}} ;; \
    restore) \
      uv run python -m vaultspec_a2a.control.db restore {{ARGS}} ;; \
    *) \
      echo "unknown db target: {{target}}" >&2; \
      exit 1 ;; \
  esac

# --- infra namespace: jaeger, vidaimock ---

infra target action='up':
  case "{{target}}-{{action}}" in \
    jaeger-up) \
      docker run -d --name jaeger-local \
        -p 4317:4317 -p 4318:4318 -p 16686:16686 -p 13133:13133 \
        -e COLLECTOR_OTLP_ENABLED=true \
        cr.jaegertracing.io/jaegertracing/jaeger:2.16.0 ;; \
    jaeger-down) \
      docker stop jaeger-local; docker rm jaeger-local ;; \
    jaeger-health) \
      curl -sf http://localhost:13133/status && echo "healthy" || echo "not ready" ;; \
    vidaimock-up) \
      docker compose -f docker-compose.integration.yml up -d --build vidaimock ;; \
    vidaimock-down) \
      docker compose -f docker-compose.integration.yml stop vidaimock && \
      docker compose -f docker-compose.integration.yml rm -f vidaimock ;; \
    vidaimock-health) \
      curl -sf http://localhost:8100/v1/models && echo "healthy" || echo "not ready" ;; \
    *) \
      echo "unknown infra target: {{target}} {{action}}" >&2; \
      exit 1 ;; \
  esac

# --- verify namespace: prod-like validations ---

verify target *ARGS:
  case "{{target}}" in \
    prodlike-docker) \
      uv run python -m vaultspec_a2a.control.verify prodlike_docker ;; \
    provider) \
      uv run python -m vaultspec_a2a.control.verify provider {{ARGS}} ;; \
    frontend-backend) \
      uv run pytest src/vaultspec_a2a/api/tests/ \
        src/vaultspec_a2a/worker/tests/test_executor.py -q ;; \
    core) \
      uv run pytest src/vaultspec_a2a/core/tests/ -q ;; \
    *) \
      echo "unknown verify target: {{target}}" >&2; \
      exit 1 ;; \
  esac

# --- prod namespace: maps to production Python CLI ---

team *ARGS:
  uv run vaultspec team {{ARGS}}

agent *ARGS:
  uv run vaultspec agent {{ARGS}}

# --- setup ---

setup:
  uv sync --all-groups && \
  npm install && \
  cd src/ui && npm install && \
  echo "Setup complete. Run 'just dev gateway' to start."
```

### 4.3 Key Design Decisions

1. **`just dev gateway`** replaces `vaultspec service start gateway` — foreground,
   with reload, visible output, Ctrl+C to stop. No background process management.

2. **`just doctor`** replaces the proposed `vaultspec doctor` CLI command — doctor
   validates the dev environment (ports, services, config), which is a dev concern.

3. **`just up`** replaces `vaultspec up` — Docker compose lifecycle is dev tooling.

4. **`just test`** replaces `vaultspec test` — test execution is never production.

5. **`just db`** replaces `vaultspec database` — migration/snapshot is dev tooling.

6. **`just team` / `just agent`** are thin passthroughs to the production CLI —
   the Justfile provides a uniform `just <verb>` surface for everything.

---

## 5. The `control` Module

Commands that move out of the CLI still need Python implementations. These
move to a new `src/vaultspec_a2a/control/` module that is invoked by the
Justfile via `python -m` but is NOT registered as a CLI command group.

```text
src/vaultspec_a2a/control/
├── __init__.py
├── doctor.py      # Port scanning, config validation, service health
├── db.py          # Database clear, snapshot, restore (from _database.py)
└── verify.py      # Prod-like Docker verification (from _verify.py)
```

The `_service.py` functions (spawn, stop, kill, PID tracking) are deleted
entirely. The Justfile uses foreground `uvicorn` processes — no background
process management, no PID registry, no zombie problem.

---

## 6. Audit Findings Inventory

### 6.1 From CLI Usability Audit (2026-03-19)

Organized by the control layer gap they expose. **Disposition** now reflects
the CLI/Justfile separation.

#### Gap A: Service Lifecycle Management

| Finding | Severity | Status | Disposition |
|---------|----------|--------|-------------|
| F-01 | CRIT | **FIXED** (Phase 1) | Defaults to SQLite — done |
| F-02 | CRIT | **RESOLVED BY DESIGN** | No background spawning — `just dev gateway` runs foreground with full env |
| F-03 | HIGH | **RESOLVED BY DESIGN** | Foreground process — you see it start or crash immediately |
| F-04 | HIGH | **RESOLVED BY DESIGN** | No PID registry needed — foreground uvicorn, Ctrl+C to stop |
| F-05 | HIGH | **RESOLVED BY DESIGN** | Foreground bind fails immediately with "Address already in use" |
| F-07 | MED | **RESOLVED BY DESIGN** | stderr is visible in the terminal (foreground) |
| F-31 | HIGH | **FIXED** (Phase 1) | Defaults to SQLite — done |

**Key insight**: 5 of 7 service lifecycle findings are **resolved by the
architectural decision to use foreground processes via Justfile** instead of
background process management in the CLI. The entire `_service.py` module and
its PID/registry/zombie problems simply disappear.

#### Gap B: Operator Observability

| Finding | Severity | Status | Disposition |
|---------|----------|--------|-------------|
| F-11 | MED | **OPEN** | `team status` must surface rich API data → CLI fix |
| F-12 | MED | **OPEN** | `team overview` must correlate with threads → CLI fix |
| F-13 | MED | **OPEN** | `agent ask` should stream or suggest poll → CLI fix |
| F-22 | MED | **OPEN** | Jaeger auto-detection → `just doctor` check |
| F-23 | MED | **OPEN** | `worker_connected` false positive → backend fix |
| F-38 | HIGH | **OPEN** | Tool call metadata null → backend fix |
| F-40 | GOOD | N/A | Jaeger traces work — gateway/worker not correlated |

#### Gap C: Thread Lifecycle Integrity

| Finding | Severity | Status | Disposition |
|---------|----------|--------|-------------|
| F-17 | HIGH | **OPEN** | Stuck "running" threads → backend investigation |
| F-18 | HIGH | **OPEN** | Stuck "cancelling" → backend fix |
| F-36 | HIGH | **OPEN** | Reconciling threads → backend fix |
| F-37 | HIGH | **OPEN** | Tool call stall → backend investigation |

#### Gap D: Permission Pipeline

| Finding | Severity | Status | Disposition |
|---------|----------|--------|-------------|
| F-34 | CRIT | **FIXED** | Permission pipeline working |
| F-35 | CRIT | **FIXED** | Deterministic permission IDs |
| F-42 | MED | **OPEN** | `team respond` misleading output → CLI fix |

#### Gap E: Configuration & Onboarding

| Finding | Severity | Status | Disposition |
|---------|----------|--------|-------------|
| F-06 | MED | **RESOLVED BY DESIGN** | Foreground uvicorn — pass any args you want |
| F-14 | LOW | **OPEN** | Next-step hints → CLI fix |
| F-15 | LOW | **OPEN** | Suppress httpx INFO logs → CLI fix |
| F-16 | LOW | **OPEN** | Positional `--id` → CLI fix |
| F-32 | MED | **OPEN** | API key masking → CLI fix |
| F-33 | LOW | **OPEN** | `.env.example` → repo root file |

#### Gap F: Operator Assessment Additional Findings

| ID | Description | Severity | Disposition |
|----|-------------|----------|-------------|
| OA-01 | No doctor command | HIGH | → `just doctor` |
| OA-02 | No `team watch` | HIGH | → `team watch` in production CLI |
| OA-03 | `team respond` no context | MED | → CLI fix |
| OA-04 | Zombie processes | HIGH | **RESOLVED BY DESIGN** — foreground processes, no zombies |
| OA-05 | Port blocked by third party | MED | **RESOLVED BY DESIGN** — foreground bind fails visibly |
| OA-06 | CLI too sparse for monitoring | MED | → Enrich `team status` |

### 6.2 Findings Summary After Separation

| Category | Total | Fixed | Resolved by Design | Open |
|----------|-------|-------|-------------------|------|
| Service Lifecycle (Gap A) | 7 | 2 | **5** | 0 |
| Observability (Gap B) | 7 | 0 | 0 | 7 |
| Thread Lifecycle (Gap C) | 4 | 0 | 0 | 4 |
| Permission Pipeline (Gap D) | 3 | 2 | 0 | 1 |
| Configuration (Gap E) | 6 | 0 | 1 | 5 |
| Operator Assessment (Gap F) | 6 | 0 | **3** | 3 |
| **Total** | **33** | **4** | **9** | **20** |

The CLI/Justfile separation **resolves 9 findings by design** — the entire
class of background-process-management bugs simply does not exist when you run
foreground processes.

---

## 7. Implementation Tracks

### Track 1: CLI Purge + Justfile Rewrite (P0)

**Goal**: Strip the CLI to production-only commands. Rebuild the Justfile
following the vaultspec-core target-dispatch pattern.

| Task | Description |
|------|-------------|
| T-01 | Delete `cli/_service.py`, `cli/_test.py`, `cli/_verify.py`, `cli/_run.py`, `cli/_database.py`, `cli/_mcp.py` |
| T-02 | Remove registrations from `cli/__init__.py` — only `team` and `agent` remain |
| T-03 | Add `--verbose`, `--debug`, `--version` root options (align with vaultspec-core) |
| T-04 | Create `src/vaultspec_a2a/control/` module with `doctor.py`, `db.py`, `verify.py` |
| T-05 | Rewrite `Justfile` with target-dispatch pattern: `dev`, `doctor`, `up/down`, `test`, `check`, `fix`, `build`, `run`, `db`, `infra`, `verify` |
| T-06 | Update `_api_client()` fail-fast message to reference `just dev gateway` / `just up` |
| T-07 | Update `.env.example` with all configurable vars |
| T-08 | Delete `cli/tests/` test files that test deleted CLI commands |

### Track 2: CLI Observability Enrichment (P1)

**Goal**: The production CLI must surface the rich data the API provides.

| Task | Finding | Description |
|------|---------|-------------|
| T-09 | F-11 | Enrich `team status`: `next_nodes`, `pause_cause`, `pending_interrupt_count`, agents, elapsed time, plan progress |
| T-10 | F-12, F-43 | Fix `team overview`: use thread-based activity, not heartbeat registration |
| T-11 | F-42, OA-03 | Enrich `team respond`: show permission context (tool name, action), confirm what was approved |
| T-12 | F-13 | `agent ask`: stream response inline or print poll command |
| T-13 | F-15 | Suppress httpx/httpcore INFO logs in CLI context |
| T-14 | F-14 | Add next-step hints to command outputs |
| T-15 | F-16 | Accept thread ID as positional argument for common commands |
| T-16 | F-32 | Improve API key masking in `--show-config` |

### Track 3: Thread Lifecycle Integrity (P1)

**Goal**: Threads must reach terminal states reliably.

| Task | Finding | Description |
|------|---------|-------------|
| T-17 | F-18 | Fix `cancelling` → `cancelled` transition |
| T-18 | F-36 | Fix reconciling thread recovery on gateway restart |
| T-19 | F-17 | Investigate stuck "running" threads |
| T-20 | F-37 | Investigate autonomous tool call stall |

### Track 4: Backend Fixes (P1)

**Goal**: API returns correct data for the CLI to display.

| Task | Finding | Description |
|------|---------|-------------|
| T-21 | F-38 | Fix tool call metadata: name, input, kind populated from checkpoint state |
| T-22 | F-23 | Fix `worker_connected` false negative — active probe on first dispatch |

### Track 5: Doctor Module (P1)

**Goal**: `just doctor` validates the dev environment.

| Task | Description |
|------|-------------|
| T-23 | Implement `control/doctor.py` — port scan, config validation, service health probing |
| T-24 | Port availability check via `socket.bind()` test |
| T-25 | Service health check via HTTP probe to gateway/worker health endpoints |
| T-26 | Config validation: database backend, required API keys, URL derivation |
| T-27 | Pretty-print health dashboard to terminal |

### Track 6: `team watch` (P2)

**Goal**: Live event streaming in the production CLI.

| Task | Finding | Description |
|------|---------|-------------|
| T-28 | OA-02 | WebSocket client — connect to `/ws/threads/{id}`, render events |
| T-29 | — | Interactive permission approval inline |
| T-30 | — | Terminal rendering: timestamps, agent names, event types |

---

## 8. Implementation Priority & Dependencies

```text
Track 1 (CLI Purge + Justfile) ──┐
                                  ├──> Track 5 (Doctor) ──> Track 6 (Watch)
Track 2 (CLI Observability) ─────┤
                                  │
Track 3 (Thread Lifecycle) ──────┤
                                  │
Track 4 (Backend Fixes) ─────────┘
```

**Track 1 is the prerequisite** — everything else depends on the new CLI/Justfile
structure being in place. Tracks 2-4 are independent and can run in parallel
after Track 1.

### Recommended Execution Order

| Phase | Tracks | Goal |
|-------|--------|------|
| **Phase A** | Track 1 | Clean separation — CLI is production-only, Justfile owns dev |
| **Phase B** | Track 2 + Track 3 + Track 4 (parallel) | Rich CLI output + reliable thread lifecycle + correct API data |
| **Phase C** | Track 5 | `just doctor` validates the environment |
| **Phase D** | Track 6 | `team watch` — live streaming with inline permission approval |

---

## 9. Success Criteria

### Phase A Complete (CLI/Justfile separation)

- [ ] Python CLI has only `team` and `agent` command groups
- [ ] Every CLI command fails fast with actionable message if gateway is down
- [ ] `just dev gateway` starts gateway in foreground with reload
- [ ] `just dev worker` starts worker in foreground with reload
- [ ] `just up` starts Docker dev stack
- [ ] `just test unit` runs unit tests
- [ ] `just doctor` runs environment health checks
- [ ] No `_service.py`, `_test.py`, `_run.py`, `_database.py`, `_mcp.py`, `_verify.py` in CLI

### Phase B Complete (Rich CLI + Reliable Threads)

- [ ] `team status` shows agents, phase, plan progress, elapsed time, pending permissions
- [ ] `team respond` shows what is being approved and what happens next
- [ ] Tool call metadata (name, input, kind) populated in API response
- [ ] Cancelled threads reach `cancelled` state
- [ ] Threads survive gateway restart (reconciling → resumed or failed)

### Phase C Complete (Doctor)

- [ ] `just doctor` reports port availability, service health, config validity
- [ ] Pretty-printed dashboard in terminal

### Phase D Complete (Watch)

- [ ] `team watch` streams live events with inline permission approval
- [ ] Interactive prompt for permission decisions

---

## 10. Architecture Considerations

### 10.1 The `control` Module Location

The `control/` module contains Python implementations for Justfile-invoked
commands. It is NOT a CLI command group. It is invoked via `python -m`:

```text
just doctor       →  uv run python -m vaultspec_a2a.control.doctor
just db migrate   →  uv run python -m alembic upgrade head
just db snapshot  →  uv run python -m vaultspec_a2a.control.db snapshot
just verify ...   →  uv run python -m vaultspec_a2a.control.verify ...
```

This keeps the Python implementation available for testing while keeping the
CLI surface clean.

### 10.2 No Background Process Management

The entire `_service.py` approach (background spawning, PID registry, health
polling, zombie detection) is deleted. Foreground processes via `just dev`
eliminate the entire class of problems:

| Problem | Background approach | Foreground approach |
|---------|-------------------|-------------------|
| Dead process reported as started | PID tracking + health poll | You see the crash immediately |
| Port conflict | Pre-spawn port scan | `bind()` fails with visible error |
| Env var propagation | Explicit env dict in Popen | Inherited from shell — just works |
| Zombie processes | PID scanning, taskkill | Ctrl+C — process is gone |
| Log access | Log file path tracking | stdout/stderr in your terminal |
| Service discovery | Port probing for externals | `curl localhost:8000/health` |

### 10.3 Click → Typer Migration

The current CLI uses Click. vaultspec-core uses Typer. This research does NOT
mandate a framework migration — both are functional. However, if a migration
is desired for consistency with vaultspec-core, it should be a separate task
after Track 1 is complete.

### 10.4 WebSocket Client for `team watch`

Options for the WS client:

- `websockets` — lightweight, async-native, pure Python
- `httpx-ws` — matches existing httpx usage
- `aiohttp` — heavyweight, but well-tested

**Recommendation**: `websockets` — minimal dependency, async-native. The CLI
wraps it with `asyncio.run()` (or the `run_async()` helper from vaultspec-core).

---

## 11. References

- `docs/audits/2026-03-19-cli-usability-end-to-end-audit.md` — Primary audit
- `docs/plans/2026-03-19-permission-pipeline-fix-plan.md` — Fixes already shipped
- `docs/research/2026-03-19-langgraph-control-plane-layer-mapping.md` — 8-layer architecture
- `docs/research/2026-03-19-permission-pipeline-architecture-research.md` — Permission system
- `docs/research/2026-03-08-process-supervision-models.md` — Architecture evolution
- `docs/research/2026-03-08-industry-service-stack-ux-patterns.md` — Industry UX benchmarks
- `docs/adrs/031-worker-process-architecture.md` — Gateway/Worker separation
- `docs/adrs/017-containerization-strategy.md` — Docker strategy
- `Y:/code/vaultspec-core-worktrees/main/justfile` — Reference Justfile pattern
- `Y:/code/vaultspec-core-worktrees/main/src/vaultspec_core/cli.py` — Reference CLI structure
- `Y:/code/vaultspec-core-worktrees/main/.vaultspec/docs/cli-reference.md` — Reference CLI docs

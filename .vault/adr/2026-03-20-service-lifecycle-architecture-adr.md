---
tags:
- '#adr'
- '#service-lifecycle-architecture'
date: 2026-03-20
modified: '2026-07-15'
related:
- '[[2026-03-04-worker-process-architecture-adr]]'
- '[[2026-03-19-control-layer-cli-justfile-separation-adr]]'
- '[[2026-02-28-containerization-strategy-adr]]'
- '[[2026-03-31-docs-vault-migration-research]]'
---

# `service-lifecycle-architecture` adr: `adr-039` | (**status:** `accepted`)

## Migration Note

This ADR was migrated from the legacy pre-pipeline documentation tree during the issue #19 cleanup so that the repository no longer depends on the removed `docs/` directory.

- Original ADR number: `ADR-039`
- Original title: `Service Lifecycle Architecture — Container-First with Dev Shim`
- Legacy status at migration time: `Accepted`

## Original ADR

## ADR-039: Service Lifecycle Architecture — Container-First with Dev Shim

**Date:** 2026-03-20
**Status:** Accepted

## 1. Context

VaultSpec A2A runs three cooperating application services (gateway, worker, UI)
plus optional infrastructure (Jaeger, Postgres, VidaiMock). ADR-038 established
the CLI/Justfile separation and resolved 9 service lifecycle audit findings by
adopting foreground processes. What remained undefined was the production
deployment model.

A CLI usability audit documented an operator spending 18 minutes fighting service
startup. The questions this ADR answers:

1. What IS production deployment? (Docker Compose, binary, daemon, system service?)
2. What model do we use in development, and does it match production closely enough?
3. Do we build a custom process manager, or not?

Industry research (2026-03-20) surveyed 8 production multi-service tools —
Ollama, LocalAI, Dify, Open WebUI, LangGraph Platform, Prefect, Temporal, and
Celery — to identify validated patterns.

The three cooperating services and their ports:

| Service | Port | Role |
|---------|------|------|
| gateway | 8000 | FastAPI — HTTP API, WebSocket relay, worker spawn |
| worker | 8001 | LangGraph executor — runs agent graphs |
| ui | 5173 | Vite — React SPA |

Optional infrastructure: Jaeger (:4317/:16686), Postgres (:5432), VidaiMock (:8100).

## 2. Decision

**Option F: Container-First with Dev Shim.**

### 2.1 Production: Docker Compose

Docker Compose is the deployment unit. It is not a convenience wrapper — it IS
production.

```bash
docker compose -f docker-compose.prod.yml up -d
```

This starts gateway + worker + UI with:

- Docker healthchecks on each service
- `restart: unless-stopped` restart policies
- Dependency ordering (`depends_on` with `service_healthy`)
- Log aggregation (`docker compose logs -f`)
- Jaeger traces for distributed observability

This is the same model used by LangGraph Platform (`langgraph up`), Dify, and
Open WebUI — all of which are the closest architectural analogs to VaultSpec A2A.

### 2.2 Development: Foreground Processes via Justfile

Development uses foreground uvicorn processes invoked by `just dev service`.
No daemon, no PID registry, no background spawning.

```bash
just dev service start gateway   # terminal 1 — uvicorn with --reload
just dev service start worker    # terminal 2 — uvicorn with --reload
just dev service start ui        # terminal 3 — Vite dev server
```

Or start all services:

```bash
just dev service start
```

The foreground model gives the developer direct visibility: all output is in the
terminal, all crashes are immediately visible, Ctrl+C stops the process cleanly.
This is the same model used by Prefect (two terminals: server + worker) and
Temporal (`start-dev` for the server, application code for workers).

### 2.3 No Daemon, No Binary, No System Service

These approaches are explicitly rejected:

- **No daemon**: Platform-specific daemon management (systemd, launchd, Windows
  SCM) adds implementation and maintenance complexity with no proportional benefit
  for a developer tool.
- **No single binary**: Python's binary compilation story (PyInstaller, Nuitka)
  cannot handle our dependency graph (LangGraph, LangChain, FastAPI, SQLAlchemy,
  OTel). Estimated 10–15 days initial build, 2–5 days per release for
  platform-specific debugging. Tools that use single-binary patterns (Ollama,
  LocalAI) are Go binaries with fundamentally simpler architectures.
- **No system service**: systemd/launchd/Windows SCM requires three
  platform-specific implementations. Installation requires admin/root. Debugging
  requires reading system logs. Complete overkill for an application-level
  developer tool.
- **No custom Python supervisor**: Duplicates Docker Compose functionality for
  dev, adds new failure modes ("is the supervisor healthy?"), and is fragile on
  Windows (zombie processes, Job Objects, CTRL_BREAK_EVENT edge cases).

### 2.4 Port Management

Fixed ports with pre-flight validation, not auto-increment.

| Service | Default Port | Env Override |
|---------|-------------|--------------|
| gateway | 8000 | `VAULTSPEC_PORT` |
| worker | 8001 | `VAULTSPEC_WORKER_PORT` |
| ui | 5173 | — (Vite standard) |

Auto-incrementing ports would break `VAULTSPEC_GATEWAY_URL` (worker config) and
`VITE_API_URL` (UI config). Industry consensus (Prefect, Temporal, Ollama,
Uvicorn) is to fail fast with a clear error on port conflict, not to
auto-increment.

`just doctor` is the pre-flight validation tool. On port conflict it identifies
the occupying process by PID and name, and suggests the fix command.

### 2.5 The Doctor Module

`src/vaultspec_a2a/control/doctor.py` provides pre-startup validation:

```bash
just doctor              # Full environment check
just doctor ports        # What is listening on 8000, 8001, 5173?
just doctor config       # API keys, DB backend, required env vars
just doctor services     # HTTP probe to /health endpoints
```

`just doctor` is run before `just dev service start` to catch problems before
they become confusing startup failures.

## 3. Rejected Alternatives

### Option A: Docker Compose Only (No Justfile Dev Path)

Dify's approach — Docker is the only supported dev environment. Rejected because
our users run VaultSpec A2A alongside their IDE (Cursor, VS Code). Docker for
frontend development is significantly slower than Vite's native HMR. Dev
experience for Python services is worse in Docker (no `--reload` hot-swap, slower
iteration). Option F (this ADR) IS Option A plus a native dev shim.

### Option B: Python Process Manager (Honcho/Foreman)

A `Procfile` with `honcho start` for single-terminal dev. Rejected because:

- No HTTP health monitoring — only process alive/dead
- No dependency ordering — gateway may start before worker is ready
- No restart on crash — one failure stops everything
- Does not solve port conflicts
- Zero production value (Docker Compose replaces it entirely)
- Adds a dependency for marginal convenience

### Option C: System Service (systemd/launchd/Windows SCM)

Rejected because it requires three platform-specific implementations (5–8 days
initial, HIGH ongoing maintenance), demands admin/root for installation, and
produces a terrible dev experience (modify service, restart service, check system
logs). Appropriate for infrastructure (databases, model servers). Not appropriate
for an application-level developer tool.

### Option D: Single Binary (PyInstaller/Nuitka)

Rejected because Python's compilation tooling cannot reliably handle our
dependency graph. LangGraph and LangChain use dynamic imports and plugin systems
that break static analysis. ADR-031 requires process isolation (gateway spawning
worker) so the binary would still need subprocess management. Estimated 10–15
days initial build with HIGH ongoing maintenance per release. See research doc
for detailed analysis.

### Option E: Python Supervisor Process

A custom asyncio supervisor that spawns gateway + worker, monitors health, and
restarts crashed processes. Conditionally viable but not recommended: it
duplicates Docker Compose for dev, adds a new failure class ("is the supervisor
healthy?"), and is fragile on Windows. The 2026-03-19 research proved that
foreground processes resolve the relevant audit findings by design. If the
two-terminal dev workflow proves to be a genuine pain point after the baseline
is solid, a thin supervisor could be revisited. Building it now would be
premature.

## 4. Consequences

### 4.1 Positive

- **No new infrastructure to build.** Docker Compose files and Justfile recipes
  already exist. Architecture is done. Remaining work is hardening (doctor,
  error messages, documentation): estimated 4 days.
- **Dev experience is foreground processes.** Output is immediately visible,
  crashes are self-announcing, Ctrl+C stops cleanly. Resolves 5 audit findings
  by design (F-02 through F-07 per ADR-038 table).
- **Production is standard Docker Compose.** Validated by LangGraph Platform,
  Dify, Open WebUI. Operators who know Docker know our deployment model.
- **No platform-specific code.** Docker is cross-platform. The Justfile runs on
  Linux, macOS, and Windows (via Git Bash or WSL).
- **Clear boundaries.** Dev path (Justfile foreground) and prod path (Docker
  Compose) are independent and non-overlapping. No confusion about which mode
  is running.

### 4.2 Negative

- **Dev requires 2–3 terminal sessions** (gateway, worker, optionally UI). This
  is the accepted trade-off validated by Prefect and Temporal. The target
  audience (developers) are comfortable with multiple terminal sessions.
- **No single-command desktop experience** (comparable to `ollama serve`).
  Acceptable: our users are developers who run the tool alongside their IDE, not
  end users who want a one-click install.
- **Docker Desktop required for production on Windows.** Docker Desktop is
  standard in the developer community; this is not a significant barrier.

### 4.3 Risks

- **Dev shim must stay synchronized with Docker Compose topology.** If a new
  service is added to `docker-compose.prod.yml`, it must also be added to the
  Justfile `dev service` targets. Mitigation: both are maintained together as
  part of each service addition. The Justfile and Docker Compose files are
  reviewed together in PR.
- **Port defaults must be consistent.** `VAULTSPEC_PORT=8000` and
  `VAULTSPEC_WORKER_PORT=8001` must be consistent across `docker-compose.prod.yml`,
  Justfile recipes, and `doctor.py` port checks. Mitigation: defaults defined
  in `src/vaultspec_a2a/core/config.py` and referenced by all consumers.

## 5. Quality Bar: Alpha to Beta

The following criteria define what "beta-grade" service lifecycle means for this
project. Current state is noted for each.

### 5.1 Service Startup

**Beta requirement**: `just dev service start` works first try after `uv sync`.
Every failure produces an actionable error with a fix command on the next line.

| Criterion | Current State | Target |
|-----------|--------------|--------|
| `just dev service start gateway` works after `uv sync` | Yes (Alpha) | Maintain |
| Port conflict detected before bind attempt | No (Pre-Alpha) | `just doctor ports` |
| Port conflict error names the occupying process and PID | No | `just doctor ports` |
| API key missing → error with `export` command | Partial | `just doctor config` |
| DB migration needed → auto-applied or actionable error | Partial | `just doctor config` |

### 5.2 Crash Recovery

**Beta requirement**: Docker Compose handles prod (already done via
`restart: unless-stopped`). Dev: process crashes are immediately visible in the
terminal; you see it, you restart it. Doctor detects zombie processes from prior
sessions.

| Criterion | Current State | Target |
|-----------|--------------|--------|
| Docker Compose `restart: unless-stopped` on gateway + worker | Yes (Beta) | Maintain |
| Dev process crash is immediately visible | Yes (Beta) | Maintain |
| `just doctor` detects zombie port occupancy from prior session | No (Pre-Alpha) | `just doctor ports` |

### 5.3 Health Monitoring

**Beta requirement**: `just doctor` checks ports, config, and service health in
one command. `/health` on both services returns structured status.
`vaultspec team list` indicates worker connectivity in its output.

| Criterion | Current State | Target |
|-----------|--------------|--------|
| `/health` endpoint on gateway | Yes (Beta) | Maintain |
| `/health` endpoint on worker | Yes (Beta) | Maintain |
| `just doctor` HTTP-probes both health endpoints | Partial (Alpha) | Harden |
| `just doctor` shows structured health dashboard | Partial (Alpha) | Harden |
| Circuit breaker state visible in health output | Yes (Beta) | Maintain |

### 5.4 Port Management

**Beta requirement**: `just doctor ports` shows what is listening on 8000, 8001,
and 5173. If any port is occupied, it shows the PID and process name and suggests
the resolution command (`just dev service kill` or identification of third-party
process).

| Criterion | Current State | Target |
|-----------|--------------|--------|
| Ports configurable via env vars | Yes (Alpha) | Maintain |
| Port conflict → error with PID + process name | No (Pre-Alpha) | `just doctor ports` |
| Port conflict → suggested fix command | No (Pre-Alpha) | `just doctor ports` |
| All service ports visible in one `just doctor` invocation | No (Pre-Alpha) | `just doctor` |

### 5.5 Configuration

**Beta requirement**: Zero env vars needed for SQLite dev. Only LLM provider
key required. `vaultspec --show-config` reveals all resolved settings with
sources.

| Criterion | Current State | Target |
|-----------|--------------|--------|
| SQLite dev works with no env vars | Yes (Alpha) | Maintain |
| LLM provider key is the only required config | Yes (Alpha) | Maintain |
| `.env.example` with all vars documented | Partial | Complete `.env.example` |
| `vaultspec --show-config` prints resolved settings | Yes (Beta) | Maintain |
| Missing required config → actionable error with export command | Partial (Alpha) | `just doctor config` |

### 5.6 Error Messages

**Beta requirement**: Every error the user encounters in the startup path
includes three parts: what went wrong, why it matters, how to fix it (one
command).

| Criterion | Current State | Target |
|-----------|--------------|--------|
| Gateway unreachable → actionable CLI error | Yes (Beta, ADR-038) | Maintain |
| Port conflict → what + why + fix | No | `just doctor ports` |
| Missing API key → what + why + fix | Partial | `just doctor config` |
| Service health fail → what + why + fix | Partial | `just doctor services` |

### 5.7 Documentation

**Beta requirement**: README has a quickstart section (3 commands to a working
system). Troubleshooting section covers the top-5 failure modes.

| Criterion | Current State | Target |
|-----------|--------------|--------|
| ADRs comprehensive | Yes (Beta) | Maintain |
| README quickstart (3 commands) | No (Pre-Alpha) | Write |
| Troubleshooting section (top-5 failure modes) | No (Pre-Alpha) | Write |
| `just help` lists all recipes with descriptions | Partial | Complete |

### 5.8 Production Stack Verification

**Beta requirement**: Docker Compose production stack (`docker-compose.prod.yml`)
starts cleanly and Jaeger confirms distributed traces from a real team operation.

| Criterion | Current State | Target |
|-----------|--------------|--------|
| `docker compose -f docker-compose.prod.yml up` starts cleanly | Yes (Beta) | Maintain |
| Jaeger healthcheck in compose file | Yes (Beta) | Maintain |
| End-to-end trace visible in Jaeger for `team start` | Partial (Alpha) | Verify |
| All services pass healthchecks within 30s | Partial | Verify |

### 5.9 Remaining Work to Reach Beta

| Task | Effort | Priority |
|------|--------|----------|
| `just doctor ports` — show PID/process for occupied ports | 1 day | P0 |
| `just doctor config` — validate API keys, DB backend | 0.5 day | P0 |
| `just doctor services` — HTTP probe to `/health` endpoints | 0.5 day | P0 |
| `.env.example` with all vars documented | 0.5 day | P0 |
| Gateway unreachable errors reference `just dev service start` | Done (ADR-038) | — |
| README quickstart section (3 commands) | 0.5 day | P1 |
| Troubleshooting section (top-5 failure modes) | 0.5 day | P1 |
| Verify prod Docker Compose stack + Jaeger traces end-to-end | 0.5 day | P1 |

**Total remaining effort**: ~4 days to reach beta-grade service lifecycle.

## 6. Compliance Matrix

| ADR | Relationship | Status |
|-----|-------------|--------|
| ADR-016 (Task Runner) | Extends — production deployment added to Justfile | Compliant |
| ADR-017 (Containerization) | Confirms — Docker Compose IS production | Compliant |
| ADR-031 (Worker Process) | Unchanged — gateway/worker process separation preserved | Compliant |
| ADR-038 (CLI/Justfile Separation) | Extends — formalises the production deployment model | Compliant |

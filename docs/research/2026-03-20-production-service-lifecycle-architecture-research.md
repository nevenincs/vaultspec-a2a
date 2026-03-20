# Production Service Lifecycle Architecture — Industry Research

**Date**: 2026-03-20
**Status**: FINAL
**Prior art**: `2026-03-08-process-supervision-models.md`, `2026-03-08-industry-service-stack-ux-patterns.md`, `2026-03-19-service-control-layer-research.md`
**ADRs**: `031-worker-process-architecture.md`, `017-containerization-strategy.md`, `038-control-layer-cli-justfile-separation.md`

---

## Executive Summary

This document researches how production Python multi-service tools manage service
lifecycle, evaluates six viable architecture options for VaultSpec A2A, analyzes
port management patterns, and defines quality bars for beta-grade service
orchestration.

**Recommendation**: Option F (Container-first with dev shim) is the correct
architecture. Docker Compose IS production. The Justfile IS development. Do not
build a process manager, a daemon, or a binary. The prior research (2026-03-19)
already made the right call with the CLI/Justfile separation. The remaining work
is hardening the dev shim (doctor, health checks, port detection) and ensuring
Docker Compose is production-complete.

---

## 1. How Production Python Multi-Service Tools Manage Lifecycle

### 1.1 Ollama — Single Binary Daemon

**Deployment unit**: Single Go binary (`ollama`).

**Architecture**: Client-server over localhost HTTP (:11434). `ollama serve`
starts the HTTP server + GPU scheduler in one process. All CLI commands
(`ollama run`, `ollama pull`, `ollama list`) are HTTP clients talking to the
daemon.

**Start/stop**:

- Linux: systemd unit (`Restart=always`, `systemctl enable ollama`)
- macOS: launchd plist (`RunAtLoad: true`, `KeepAlive: true`)
- Windows: Background service or tray app via Task Scheduler

**Health monitoring**: HTTP endpoint. CLI commands fail with "Ollama is not
running. Run `ollama serve`" if daemon is down.

**Dev experience**: Install binary, `ollama pull <model>`, `ollama run <model>`.
Working in under 2 minutes. Zero configuration.

**Key insight**: Ollama succeeds because it has ONE process that owns everything.
No service coordination, no port conflicts, no multi-process debugging. The Go
single-binary model eliminates Python's packaging/distribution complexity
entirely.

**Relevance to us**: LOW for architecture (we cannot collapse gateway+worker into
one process per ADR-031), HIGH for UX expectations (developers expect single-
command startup).

### 1.2 LocalAI — Single Container with Backend Gallery

**Deployment unit**: Single Docker container or single binary.

**Architecture**: Single REST API process (Go) that loads ML backends as
separate processes on demand. As of July 2025, all backends migrated outside
the main binary — backends are downloaded automatically when a model needs them.

**Start/stop**: `docker run localai/localai` or download the binary and run it.
No multi-service coordination.

**Health monitoring**: Built-in health endpoint. Model loading status via API.

**Dev experience**: `docker run -p 8080:8080 localai/localai`. Drop-in
replacement for OpenAI API.

**Key insight**: LocalAI manages internal complexity (multiple ML backends) but
presents a single-service external interface. The "backend gallery" pattern —
download and activate backends on demand — is elegant for managing optional
components.

**Relevance to us**: MEDIUM. The pattern of presenting a single service
externally while managing internal sub-processes is applicable. Our gateway
already auto-spawns the worker — this is the same pattern.

### 1.3 Dify — Docker Compose Multi-Service

**Deployment unit**: Docker Compose stack (11 containers).

**Architecture**: 5 core services (api, worker, worker_beat, web,
plugin_daemon) + 6 infrastructure components (PostgreSQL, Redis, Weaviate,
nginx, ssrf_proxy, sandbox). The `dify-api` image is reused for multiple
service types, differentiated by the `MODE` environment variable.

**Start/stop**:

```bash
cd docker
cp .env.example .env
docker compose up -d
```

**Health monitoring**: Docker healthchecks on each service. nginx as reverse
proxy handles routing.

**Dev experience**: Clone repo, copy `.env.example`, `docker compose up`. All
configuration via `.env` file. No native dev mode documented — Docker is the
only supported path.

**Key insight**: Dify does NOT attempt to hide multi-service complexity from
operators. The `.env` file has 100+ configuration variables. This is acceptable
for a self-hosted platform product but would be unacceptable for a developer
tool.

**Relevance to us**: HIGH for production deployment pattern. Our
`docker-compose.prod.yml` already follows this model (gateway + worker + jaeger).
LOW for dev experience — Dify's approach of Docker-only dev is not suitable for
a tool that developers run alongside their IDE.

### 1.4 Open WebUI — Single Container, Scale-Out Optional

**Deployment unit**: Single Docker container (FastAPI backend + pre-built
React frontend in one image).

**Architecture**: Monolithic container for simplicity. For scale-out: multiple
stateless containers + Redis (for WebSocket sync) + external PostgreSQL + load
balancer.

**Start/stop**: `docker run -p 3000:8080 ghcr.io/open-webui/open-webui:main`.
Single command.

**Health monitoring**: Docker healthcheck. Application-level health endpoint.

**Dev experience**: Docker for users. Native Python + Node for contributors.

**Key insight**: Open WebUI explicitly chose "single container for simplicity,
multi-container for scale." The limitation they document is that the combined
frontend+backend container cannot scale individual components independently.
This is identical to our ADR-017 constraint (SQLite WAL limits to single
container).

**Relevance to us**: VERY HIGH. Open WebUI IS our closest architectural analog:
FastAPI + React SPA, single container for personal use, multi-container for
teams. Our ADR-017 already references Open WebUI as the model. We should
follow their production deployment pattern exactly.

### 1.5 LangGraph Platform / LangServe

**Deployment unit**: Managed cloud service (LangSmith Deployment) or
self-hosted Docker container.

**Architecture**: The LangGraph Platform (renamed "LangSmith Deployment" in
October 2025) includes a persistence layer, LangGraph Studio (agent IDE), and
managed worker infrastructure. Self-hosted uses Docker with a
`langgraph.json` configuration file.

**Start/stop**:

- Cloud: Deploy from LangSmith UI
- Self-hosted: `langgraph up` (wraps Docker Compose)

**Health monitoring**: Platform-managed in cloud. Docker healthchecks for
self-hosted.

**Dev experience**: `langgraph dev` starts a local development server.
`langgraph up` starts the Docker-based deployment. `langgraph.json` defines
the graph, dependencies, and environment.

**Key insight**: LangChain deprecated LangServe in favor of LangGraph Platform.
Their self-hosted deployment is Docker Compose behind a CLI wrapper
(`langgraph up`). They do NOT attempt a native binary, a daemon, or a system
service. Docker IS their production deployment.

**Relevance to us**: VERY HIGH. LangGraph is our runtime framework. Their own
deployment strategy validates Docker Compose as the production model. Their
`langgraph up` = our `just up prod`. Their `langgraph dev` = our
`just dev gateway`.

### 1.6 Prefect — Server + Worker with Polling

**Deployment unit**: Server (API + scheduler) + Workers (polling processes).

**Architecture**: Server manages state and scheduling. Workers are long-running
processes that poll work pools for scheduled flow runs, provision
infrastructure, and execute flows. Workers register with the server on startup.

**Start/stop**:

- Server: `prefect server start` (single process, SQLite or PostgreSQL)
- Worker: `prefect worker start --pool my-pool` (separate process)
- Production: Docker, Kubernetes, or managed Prefect Cloud

**Health monitoring**: Worker lifecycle includes initialization, backend sync
(register with API, create work pools), main loop (poll for runs, monitor
cancellations), and shutdown (graceful cleanup). Recent improvements added
lifecycle logs and error hints.

**Dev experience**: `prefect server start` in one terminal, `prefect worker
start` in another. Simple but requires two terminal sessions.

**Key insight**: Prefect deprecated "Agents" in favor of "Workers." Workers are
long-running polling processes — exactly like our worker. Their dev experience
(two terminal sessions) mirrors our `just dev gateway` + `just dev worker`
pattern. They did NOT build a process manager to hide this — they accepted
the two-terminal workflow.

**Relevance to us**: HIGH. Prefect validates that the "two terminal sessions"
dev workflow is acceptable for the target audience (developers and platform
engineers). They invested in good lifecycle logs and error hints rather than
hiding the multi-process nature.

### 1.7 Temporal — Server + Worker with Task Queues

**Deployment unit**: Server cluster (4 internal services) + Workers
(application processes).

**Architecture**: Server has 4 services (Frontend, History, Matching, Worker
service) that can run independently or grouped. Production deployments scale
each independently (e.g., 5 Frontend, 15 History, 17 Matching, 3 Worker
services). Application Workers connect via gRPC.

**Start/stop**:

- Dev: `temporal server start-dev` (single binary, all services in one process)
- Production: Docker Compose, Kubernetes with Temporal Helm charts
- Workers: Application code that runs `worker.run()`

**Health monitoring**: Worker Versioning (GA in 2025) pins workflow executions
to specific worker deployment versions. Kubernetes Worker Controller automates
version lifecycle. Rolling, progressive, and manual deployment strategies.

**Dev experience**: `temporal server start-dev` starts everything in one
process. Workers are application code started via standard language tooling
(`go run`, `python main.py`). The dev server is ephemeral (in-memory SQLite).

**Key insight**: Temporal's `start-dev` command is the canonical example of
"collapse everything for dev, separate everything for prod." In dev, it is one
process. In production, it is a distributed cluster. The application workers
are ALWAYS separate processes because they run user code.

**Relevance to us**: MEDIUM. Temporal's scale (distributed cluster with
independent service scaling) is beyond our needs. But their dev/prod split
pattern (`start-dev` vs Kubernetes) is exactly what we should aspire to. The
"user code runs in a separate worker process" pattern matches ADR-031.

### 1.8 Celery — Broker + Worker with Signal-Based Lifecycle

**Deployment unit**: Broker (Redis/RabbitMQ) + Worker processes + optional
Beat scheduler.

**Architecture**: Producers send tasks to broker. Workers poll broker for
tasks. Results stored in backend (Redis, database, etc.). Workers are
independently scalable processes.

**Start/stop**:

- Broker: External service (Redis, RabbitMQ)
- Worker: `celery -A myapp worker --loglevel=info`
- Beat: `celery -A myapp beat`
- Production: systemd units, Docker, Kubernetes

**Health monitoring**: Worker lifecycle has three phases: Startup (bootstep
initialization), Running (task processing + control commands), Shutdown
(warm/cold/soft/hard modes). Signal-based lifecycle (SIGINT = warm shutdown,
SIGTERM = cold shutdown). Soft shutdown is time-limited warm shutdown that
requeues incomplete tasks.

**Dev experience**: Start Redis, start worker, start beat. Three processes.
No hiding of complexity.

**Key insight**: Celery is the granddaddy of Python distributed task systems.
90% of production deployments use Redis as broker. Their worker lifecycle
(bootstep system, 4 shutdown modes, exponential backoff restart) is the most
mature in the Python ecosystem. They require external infrastructure (broker)
and make no attempt to bundle it.

**Relevance to us**: LOW for architecture (we use HTTP IPC, not message broker).
HIGH for worker lifecycle patterns (their shutdown modes and bootstep system
are well-proven).

---

## 2. Viable Production Models — Evaluation

### Option A: Docker Compose Only (Current Production Path)

**What it is**:

- Dev: `just dev gateway` + `just dev worker` (foreground uvicorn)
- Prod: `docker compose -f docker-compose.prod.yml up`
- No native binary, no daemon, no process manager

**What exists**: Everything. The Justfile has full lifecycle recipes
(start/stop/kill/restart/rebuild/health/logs) for all 6 services. Docker
Compose files exist for dev, prod, prod-postgres, and integration.

**What we'd need to build**: Nothing for the architecture. Harden the doctor
module, improve error messages, document the workflow.

**Pros**:

- Already implemented and tested
- Docker Compose is the industry standard for multi-service Python apps
- LangGraph Platform, Dify, Open WebUI all validate this approach
- Zero new dependencies or abstractions
- Dev workflow (foreground processes) is proven by Prefect, Temporal
- Production workflow (Docker Compose) is proven by everyone

**Cons**:

- Dev requires 2-3 terminal sessions
- No crash recovery in dev (foreground processes die, you restart manually)
- Port conflicts in dev require manual resolution
- No startup orchestration — services must be started in dependency order

**Complexity estimate**: 0 days (already done). 2-3 days for doctor hardening.

**Verdict**: This is the correct baseline. Everything else is an optimization
on top of this.

### Option B: Python Process Manager (Honcho/Foreman)

**What it is**:

- A `Procfile` defines all services
- `honcho start` launches everything in one terminal with multiplexed output
- Process monitoring built in

**What exists**: Honcho 2.0 is available on PyPI. The Procfile format is
standardized. No custom code needed.

**What we'd need to build**:

- A `Procfile` (5 lines)
- Health check integration (Honcho does not do HTTP health checks)
- Dependency ordering (Honcho starts all processes simultaneously)

**Pros**:

- Single terminal for all services
- Color-coded, multiplexed output
- Stop-all-on-Ctrl+C
- Battle-tested (Heroku ecosystem)
- Zero custom code

**Cons**:

- No health monitoring — just process alive/dead
- No dependency ordering — gateway might start before worker is ready
- No restart on crash — if a process dies, Honcho stops everything
- Adds a dependency for marginal benefit
- Does not solve port conflicts
- Not useful in production (Docker Compose replaces it entirely)

**Complexity estimate**: 0.5 days to set up. But does not solve the actual
problems (health checks, port conflicts, crash recovery).

**Verdict**: REJECTED. Marginal convenience (one terminal instead of two) does
not justify adding a dependency. The Justfile already provides better UX with
per-service control, and Honcho adds nothing for production.

### Option C: System Service (systemd/launchd/Windows Service)

**What it is**:

- Install gateway + worker as system services
- Auto-start on boot, restart on crash
- Platform-specific: systemd unit files, launchd plist, Windows SCM

**What exists**: systemd and launchd are platform-provided. Windows Service
requires `pywin32` or `NSSM` (Non-Sucking Service Manager).

**What we'd need to build**:

- systemd unit files for gateway and worker (Linux)
- launchd plist for gateway and worker (macOS)
- Windows Service wrapper using pywin32 or NSSM (Windows)
- Install/uninstall commands (`vaultspec service install/remove`)
- Log routing (services log to journal/syslog/Event Log, not terminal)

**Pros**:

- Auto-start on boot
- Auto-restart on crash (systemd `Restart=always`, launchd `KeepAlive`)
- Platform-native lifecycle management
- No custom process manager code

**Cons**:

- Three completely different implementations (Linux, macOS, Windows)
- Windows Service development is notoriously painful (SCM interactions,
  session isolation, no console)
- Debugging is harder (logs in system log, not terminal)
- Installation requires admin/root privileges
- Dev experience is terrible (modify service, restart service, check logs
  in a separate viewer)
- Complete overkill for a developer tool

**Complexity estimate**: 5-8 days (3 platforms x 2 services, plus install/
remove commands, plus testing). Ongoing maintenance cost is HIGH because
platform-specific code rots quickly.

**Verdict**: REJECTED. The complexity/benefit ratio is terrible. System
services are appropriate for infrastructure (databases, message brokers) not
for application-level developer tools. Ollama uses this pattern because it IS
infrastructure (a model server). We are an application.

### Option D: Single Binary with Embedded Services (Like Ollama)

**What it is**:

- Compile gateway + worker into a single executable using PyInstaller or Nuitka
- `vaultspec serve` starts everything
- Distribute as a downloadable binary

**What exists**: PyInstaller and Nuitka both support FastAPI+Uvicorn
compilation. There are proven examples of FastAPI binaries.

**What we'd need to build**:

- PyInstaller/Nuitka build configuration
- Process management within the binary (start worker as subprocess or thread)
- Static asset bundling (React SPA)
- Platform-specific builds (Windows, Linux, macOS)
- CI/CD for binary release artifacts
- Auto-update mechanism

**Pros**:

- Single file distribution — no Python, no uv, no dependencies
- `vaultspec serve` starts everything — matches Ollama UX
- No Docker required for production
- Potentially faster startup (Nuitka compiles to native C)

**Cons**:

- Binary sizes are large (PyInstaller: ~94MB, Nuitka: ~58MB, before models)
- Build times are long (Nuitka: minutes to hours for large projects)
- Debugging compiled binaries is extremely difficult
- Python C extensions (grpcio for OTel, SQLAlchemy) cause build failures
- LangGraph, LangChain, and their transitive dependencies are notoriously
  hard to bundle (dynamic imports, plugin systems, data files)
- THREE platform builds to maintain (Windows, Linux, macOS)
- ADR-031 still requires process isolation — the binary would still need to
  spawn a worker subprocess, defeating much of the simplicity
- Auto-update is a separate, complex system to build

**Complexity estimate**: 10-15 days for initial build. 2-5 days per release
for ongoing platform-specific debugging. HIGH ongoing maintenance.

**Verdict**: REJECTED for the foreseeable future. The Python ecosystem's
binary compilation story is not mature enough for a project with our
dependency graph (LangGraph, LangChain, FastAPI, SQLAlchemy, OTel, etc.).
This becomes viable only if/when the project stabilizes AND there is a clear
distribution need beyond Docker.

### Option E: Supervisor Process (Python-Native)

**What it is**:

- A Python supervisor process manages gateway + worker as child processes
- Health monitoring, restart on crash, log aggregation
- Similar to Gunicorn's master/worker but for our specific services
- `vaultspec serve` or `just serve` starts the supervisor

**What exists**: Supervisor (supervisord) 4.3.0 is production-stable for
UNIX. `supervice` is a modern asyncio alternative. Our own codebase already
has `LazyWorkerSpawner` and `WorkerWatchdog` (from the prod-readiness sprint).

**What we'd need to build**:

- Supervisor entry point that spawns gateway + worker
- Health check integration (HTTP probes to /health endpoints)
- Restart logic (exponential backoff, max retries, FATAL state)
- Log multiplexing (color-coded output from both services)
- Graceful shutdown (CTRL_BREAK_EVENT on Windows per prior research)
- Port conflict pre-check

**Pros**:

- Single command starts everything
- Crash recovery with exponential backoff
- Health monitoring (HTTP, not just process-alive)
- Log aggregation in one terminal
- Python-native — no external dependencies
- Works on all platforms (our Windows subprocess research is comprehensive)

**Cons**:

- Custom code to write and maintain (200-400 lines estimated)
- Duplicates Docker Compose functionality for dev
- The prior research (2026-03-19) explicitly rejected background process
  management in favor of foreground processes
- "You are now debugging the process manager instead of your application"
- Windows process management is fragile (zombie processes, Job Objects,
  CTRL_BREAK_EVENT edge cases)
- Adds a new failure mode: "is the supervisor healthy?"

**Complexity estimate**: 3-5 days for a basic version. 5-8 days for a
production-grade version with all the edge cases.

**Verdict**: CONDITIONALLY VIABLE but not recommended. If the two-terminal
dev workflow proves to be a real pain point (not hypothetical), a thin
supervisor that multiplexes output and restarts crashed processes could be
worthwhile. But this should be built AFTER the baseline (Option A/F) is
solid, not instead of it. The 2026-03-19 research was right: foreground
processes eliminate an entire class of bugs.

### Option F: Container-First with Dev Shim (RECOMMENDED)

**What it is**:

- Production IS Docker Compose. Full stop.
- Dev uses foreground processes via Justfile. No process manager, no daemon.
- `just dev gateway` (terminal 1), `just dev worker` (terminal 2)
- `just up prod` for production Docker stack
- `just doctor` validates environment before starting

**What exists**: Everything. The Justfile, Docker Compose files, doctor module
(in control/), health endpoints on both services, circuit breaker, worker
watchdog.

**What we'd need to build**:

- Harden `just doctor` (port pre-check, config validation, service health)
- Improve error messages (actionable, with fix commands)
- `.env.example` with documented defaults
- Startup documentation (README section or `just help`)

**Pros**:

- Already implemented
- Validated by LangGraph Platform, Dify, Open WebUI, Prefect, Temporal
- Two separate deployment paths with clear boundaries:
  - Dev: foreground processes, hot reload, visible output, Ctrl+C to stop
  - Prod: Docker Compose, healthchecks, restart policies, log aggregation
- No custom process manager code
- No platform-specific code (Docker is cross-platform)
- The 2026-03-19 research already proved this resolves 9 of 33 findings
  "by design" (no zombies, no PID tracking, no background spawning)
- `just doctor` validates preconditions before you waste time debugging

**Cons**:

- Dev requires 2-3 terminal sessions (gateway, worker, optionally UI)
- No crash recovery in dev (process dies, you see it, you restart it)
- Docker Desktop required for production on Windows

**Complexity estimate**: 2-3 days for doctor hardening and documentation.
0 days for architecture.

**Verdict**: THIS IS THE ANSWER. Every successful multi-service Python tool
in the industry uses either Docker Compose (Dify, LangGraph, Open WebUI) or
a two-terminal dev workflow (Prefect, Temporal, Celery). None of them build
custom process managers for development. The ones that have single-command
startup (Ollama, LocalAI) are Go binaries with fundamentally different
architecture constraints.

---

## 3. Port Management in Non-Containerized Environments

### 3.1 How Tools Handle Port Conflicts in Dev

| Tool | Strategy | On Conflict |
|------|----------|-------------|
| Ollama | Fixed port :11434 | "address already in use" error |
| Vite | Auto-increment (:5173, :5174, :5175...) | Transparent |
| Uvicorn | Fixed port, fail on conflict | "address already in use" error |
| Prefect | Fixed port :4200 | Error with message |
| Temporal | Fixed port :7233 | Error with message |
| VS Code | Dynamic port forwarding | Transparent |
| Docker | `-p host:container` binding | "port already allocated" error |

**Industry consensus**: Most server-side tools use FIXED ports and fail with
an error. Only frontend dev servers (Vite, webpack-dev-server) auto-increment.
The reason: server URLs are configuration — clients need to know where to
connect. Auto-incrementing a server port breaks all clients that hardcode the
original port.

### 3.2 Dynamic Port Allocation Patterns

**Bind to :0, read back actual port**:

```python
import socket
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    s.bind(('', 0))
    port = s.getsockname()[1]
```

Race condition window between finding and binding. Acceptable for dev tools.
Uvicorn supports `--port 0` but requires parsing stdout to discover the port.

**Pre-bind socket, pass file descriptor**: Atomic and race-free. Uvicorn
supports `--fd`. More complex but eliminates races. Overkill for dev tools.

**Recommendation for VaultSpec**: Use FIXED ports (8000/8001) with
pre-flight validation via `just doctor`. If port 8000 is in use, tell the
user WHO is using it (PID, process name) and HOW to fix it. Do not
auto-increment — it breaks the worker's `VAULTSPEC_GATEWAY_URL` and the
UI's `VITE_API_URL`.

### 3.3 Service Discovery Patterns for Local Dev

| Pattern | Used By | Complexity | Applicability |
|---------|---------|------------|---------------|
| Hardcoded URLs | Prefect, Temporal, Celery | Zero | Best for us |
| Environment variables | Dify, Docker Compose | Low | Already have this |
| Consul/etcd | Kubernetes-scale systems | High | Overkill |
| mDNS/Bonjour | Apple ecosystem | Medium | Not relevant |
| File-based (PID/port file) | supervisord, PM2 | Low | Considered and rejected |

**Recommendation**: Hardcoded defaults (localhost:8000, localhost:8001) with
environment variable overrides (`VAULTSPEC_PORT`, `VAULTSPEC_WORKER_PORT`).
This is what every comparable tool does. Service discovery is a distributed
systems problem — we are a local dev tool.

### 3.4 How VS Code/Cursor Handle Port Forwarding

VS Code detects listening ports and offers to forward them via a notification.
This is relevant for remote development (SSH, Codespaces) but not for local
dev. Our `.devcontainer/devcontainer.json` already declares `forwardPorts:
[8000, 5173, 16686]`.

### 3.5 What Temporal/Prefect Do About Port Conflicts

**Temporal**: `temporal server start-dev` uses fixed port :7233. If occupied,
it fails with an error. No auto-increment, no detection.

**Prefect**: `prefect server start` uses fixed port :4200. Same behavior.
Recent versions added better lifecycle logs and error hints, not port
auto-detection.

**Conclusion**: Neither Temporal nor Prefect solve port conflicts
programmatically. They fail fast with clear errors. This is the industry
standard approach.

---

## 4. What "Beta-Grade" Means for a Service Orchestrator

### 4.1 Quality Bar Definitions

| Dimension | Pre-Alpha | Alpha | Beta | Production |
|-----------|-----------|-------|------|------------|
| **Service startup** | Manual, may require workarounds | Works with documented steps | Works first try, fails with actionable errors | Zero-config, auto-recovery |
| **Crash recovery** | Manual restart | Known how to recover, documented | Auto-restart in prod (Docker), clear error in dev | Auto-restart everywhere, zero data loss |
| **Health monitoring** | None | Process alive check | HTTP health endpoints, doctor command | Distributed health, alerting, dashboards |
| **Port management** | Hardcoded, no conflict detection | Configurable via env vars | Pre-flight port check with process identification | Dynamic allocation with service discovery |
| **Configuration** | Many env vars, no defaults | Sensible defaults, `.env.example` | Zero-config dev, documented prod config | Auto-discovery, validation, migration |
| **Error messages** | Stack traces | Human-readable errors | Actionable errors with fix commands | Self-healing with operator notification |
| **Documentation** | Code comments only | README with basic setup | Complete setup guide, troubleshooting, architecture | Runbooks, SLO definitions, capacity planning |
| **Test coverage** | Manual testing only | Unit tests for core paths | Integration tests, smoke tests, CI gate | Load tests, chaos tests, canary deploys |

### 4.2 Where VaultSpec A2A Is Today

| Dimension | Current State | Level |
|-----------|---------------|-------|
| Service startup | `just dev gateway` works, but 18min operator experience documented | Pre-Alpha/Alpha |
| Crash recovery | Docker: `restart: unless-stopped`. Dev: manual | Alpha |
| Health monitoring | `/health` endpoints exist, circuit breaker exists, doctor module started | Alpha/Beta |
| Port management | Fixed ports, no conflict detection | Pre-Alpha |
| Configuration | Many env vars, defaults for SQLite | Alpha |
| Error messages | Some actionable (`_api_client`), many not | Alpha |
| Documentation | ADRs comprehensive, user docs sparse | Alpha |
| Test coverage | 966 tests, CI gate, smoke tests | Beta |

### 4.3 What Beta Requires (Target)

To reach **beta-grade** service orchestration:

1. **Service startup**: `just dev gateway` works first try after `uv sync`.
   `just doctor` catches problems before startup. Error on failure includes
   the fix command.

2. **Crash recovery**: Docker Compose handles prod. Dev: foreground process,
   you see the crash, you restart. Doctor detects zombie processes from prior
   sessions.

3. **Health monitoring**: `just doctor` checks ports, config, service health.
   `/health` on both services returns structured status. `team status` in CLI
   shows worker connectivity.

4. **Port management**: `just doctor ports` shows what is listening on 8000,
   8001, 5173. If occupied, shows PID and process name. Suggests `just dev
   service kill <target>` or identifies third-party process.

5. **Configuration**: Zero env vars needed for SQLite dev. Only LLM provider
   key required. `--show-config` reveals all resolved settings.

6. **Error messages**: Every error the user sees includes: what went wrong,
   why it matters, how to fix it (one command).

7. **Documentation**: README has quickstart (3 commands). Troubleshooting
   section covers top-5 failure modes.

8. **Test coverage**: Current level (966 tests + CI) is already beta-grade.

---

## 5. Consolidated Recommendation

### The Decision: Option F — Container-First with Dev Shim

**Production deployment**: Docker Compose. This is validated by LangGraph
Platform, Dify, Open WebUI, and every comparable tool in the industry. Our
`docker-compose.prod.yml` is already production-complete with healthchecks,
restart policies, and dependency ordering.

**Development workflow**: Foreground processes via Justfile. This is validated
by Prefect (two terminals), Temporal (`start-dev`), and Celery (broker +
worker). The 2026-03-19 research proved this resolves 9 of 33 audit findings
by design.

**What NOT to build**:

- No daemon (adds platform-specific complexity for marginal benefit)
- No binary (Python's compilation story cannot handle our dependency graph)
- No custom process manager (duplicates Docker Compose, adds new failure modes)
- No system service (overkill, platform-specific, terrible dev experience)
- No Honcho/Procfile (marginal benefit, no health checks, no production use)

### What TO Build (Remaining Work)

| Task | Effort | Priority |
|------|--------|----------|
| Harden `just doctor ports` — show PID/process on occupied ports | 1 day | P0 |
| Harden `just doctor config` — validate API keys, DB backend | 0.5 day | P0 |
| Harden `just doctor services` — HTTP probe to health endpoints | 0.5 day | P0 |
| `.env.example` with all vars documented | 0.5 day | P0 |
| Fail-fast in CLI with actionable messages referencing `just dev` | 0.5 day | P0 |
| README quickstart section (3 commands to working system) | 0.5 day | P1 |
| Troubleshooting section (top-5 failure modes) | 0.5 day | P1 |

**Total remaining effort**: 4 days to reach beta-grade service lifecycle.

### Why This Is The Right Call

The 2026-03-19 research already made this decision. The industry research
confirms it. Every tool that succeeded with a multi-service Python architecture
uses one of two patterns:

1. **Docker Compose for production** (Dify, LangGraph, Open WebUI)
2. **Foreground processes for dev** (Prefect, Temporal, Celery)

The tools that use single-binary/daemon patterns (Ollama, LocalAI) are
written in Go, have fundamentally simpler architectures (one process), and
target a different use case (model serving, not multi-agent orchestration).

Building a custom process manager, daemon, or binary would be a
**significant engineering investment (5-15 days) that solves a problem the
industry has already solved with Docker Compose**. The investment should go
into the doctor module, error messages, and documentation — the things that
make the existing architecture feel polished.

---

## Sources

### Ollama

- [Ollama Setup Guide 2026](https://www.sitepoint.com/ollama-setup-guide-2026/)
- [Ollama Architecture — DeepWiki](https://deepwiki.com/ollama/ollama/1-overview)
- [Ollama Linux Installation](https://docs.ollama.com/linux)
- [Ollama ArchWiki](https://wiki.archlinux.org/title/Ollama)

### LocalAI

- [LocalAI GitHub](https://github.com/mudler/LocalAI)
- [LM Studio vs LocalAI vs Ollama 2026](https://www.index.dev/skill-vs-skill/ai-ollama-vs-localai-vs-lmstudio)

### Dify

- [Dify Docker Compose Deployment Docs](https://docs.dify.ai/en/self-host/quick-start/docker-compose)
- [Dify Docker Deployment — DeepWiki](https://deepwiki.com/langgenius/dify/3.1-docker-deployment)
- [Dify Service Orchestration — DeepWiki](https://deepwiki.com/langgenius/dify/2.1-service-orchestration-and-docker-compose)
- [Dify docker-compose.yaml](https://github.com/langgenius/dify/blob/main/docker/docker-compose.yaml)

### Open WebUI

- [Open WebUI Docker Deployment — DeepWiki](https://deepwiki.com/open-webui/open-webui/15.2-docker-deployment)
- [Open WebUI Quick Start](https://docs.openwebui.com/getting-started/quick-start/)
- [HA Open WebUI Deployment Architecture](https://taylorwilsdon.medium.com/the-sres-guide-to-high-availability-open-webui-deployment-architecture-2ee42654eced)
- [Open WebUI Docker Options — DeepWiki](https://deepwiki.com/open-webui/open-webui/3.2-docker-deployment-options)

### LangGraph Platform

- [LangGraph Platform GA Announcement](https://blog.langchain.com/langgraph-platform-ga/)
- [LangChain & LangGraph 1.0](https://blog.langchain.com/langchain-langgraph-1dot0/)
- [LangGraph Architecture Guide 2025](https://latenode.com/blog/ai-frameworks-technical-infrastructure/langgraph-multi-agent-orchestration/langgraph-ai-framework-2025-complete-architecture-guide-multi-agent-orchestration-analysis)

### Prefect

- [Prefect Workers Documentation](https://docs.prefect.io/v3/deploy/infrastructure-concepts/workers)
- [Prefect Workers and Work Pools — DeepWiki](https://deepwiki.com/PrefectHQ/prefect/4.3-deployment-cli-and-workers)
- [Prefect Deployments](https://docs.prefect.io/v3/concepts/deployments)

### Temporal

- [Temporal Production Deployments](https://docs.temporal.io/production-deployment)
- [Temporal Worker Deployments](https://docs.temporal.io/production-deployment/worker-deployments)
- [Temporal Server Architecture](https://docs.temporal.io/temporal-service/temporal-server)
- [Temporal Worker Versioning](https://docs.temporal.io/production-deployment/worker-deployments/worker-versioning)
- [Temporal Worker Controller — GitHub](https://github.com/temporalio/temporal-worker-controller)

### Celery

- [Celery Worker Lifecycle — DeepWiki](https://deepwiki.com/celery/celery/5.2-worker-lifecycle-and-shutdown)
- [Celery + Redis + FastAPI Production Guide 2025](https://medium.com/@dewasheesh.rana/celery-redis-fastapi-the-ultimate-2025-production-guide-broker-vs-backend-explained-5b84ef508fa7)
- [Celery Distributed Task Queues](https://oneuptime.com/blog/post/2025-07-02-python-celery-distributed-tasks/view)

### Process Management

- [Honcho Documentation](https://honcho.readthedocs.io/)
- [Honcho GitHub](https://github.com/nickstenning/honcho)
- [Supervisord Documentation](https://supervisord.org/)
- [supervisor_checks — GitHub](https://github.com/vovanec/supervisor_checks)

### Binary Compilation

- [PyInstaller vs Nuitka vs cx_Freeze Comparison](https://x321.org/empirical-pyinstaller-vs-nuitka-vs-cx_freeze/)
- [PyInstaller + FastAPI](https://github.com/iancleary/pyinstaller-fastapi)
- [Python Executable Generators — Sparx Engineering](https://sparxeng.com/blog/software/python-standalone-executable-generators-pyinstaller-nuitka-cx-freeze)

### Internal References

- `docs/research/2026-03-19-service-control-layer-research.md`
- `docs/research/2026-03-08-process-supervision-models.md`
- `docs/research/2026-03-08-industry-service-stack-ux-patterns.md`
- `docs/research/2026-02-25-agent-process-lifecycle-research.md`
- `docs/adrs/031-worker-process-architecture.md`
- `docs/adrs/017-containerization-strategy.md`
- `docs/adrs/038-control-layer-cli-justfile-separation.md`

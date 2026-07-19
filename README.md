# Vaultspec A2A Agent Orchestration

[![Python 3.13+](https://img.shields.io/badge/python-3.13%2B-blue.svg)](https://www.python.org/)
[![Status: Early](https://img.shields.io/badge/status-early-orange.svg)](#status)

Headless A2A orchestration sibling for the
[vaultspec](https://github.com/nevenincs/vaultspec-core) agentic coding
workflow. Provides team-based and subagent-based task dispatch across Claude,
Gemini, and Codex agents via a gateway/worker architecture.

A2A is headless: it ships no bundled UI. The dashboard engine fronts it across a
loopback HTTP edge (a versioned five-verb surface), and every document an agent
produces becomes a human-reviewed proposal in the engine's review lane through
the authoring API — agents never write to the vault directly.

Two modes:

- **Team mode:** A self-orchestrating team (supervisor + coders) works
  concurrently against a task. Preferred for parallelized, long-horizon coding
  work.
- **Subagent mode:** A single agent performs a task on behalf of a client
  application (Claude Code, Gemini CLI, Antigravity). Preferred for
  non-parallelized, sequential handoffs.

## Status

Early and still taking shape: interfaces, presets, and deployment surfaces
change without notice. The rest of this README is developer-facing.

## Documentation

- [Documentation home](docs/index.rst)
- [Architecture navigation](docs/architecture.rst)
- [Operator reference](docs/operations.rst)
- [Python module reference](docs/api/modules.rst)
- [Edge conformance mapping](docs/a2a-edge-conformance-verb-mapping.md)

These pages describe current package ownership without relying on manually
counted modules or components.

## Quickstart

Clone and install dependencies:

```bash
git clone <repo-url>
cd vaultspec-a2a
just dev deps install
```

Copy and edit the environment file (`.env.example` lives under `service/`):

```bash
cp service/.env.example .env
# Set at least one provider key: ANTHROPIC_API_KEY, GEMINI_API_KEY, or OPENAI_API_KEY
```

Start services (each command runs in the foreground — use a separate terminal
for each):

```bash
just dev service start gateway   # terminal 1 — port 8000
just dev service start worker    # terminal 2 — port 8001
```

Verify services are healthy:

```bash
just doctor
```

Start a run and follow its progress (list preset ids with
`vaultspec-a2a presets`):

```bash
vaultspec-a2a run start --preset <preset-id> --message "Create a hello world module"
vaultspec-a2a run status <run_id>
```

## Production Deployment

Docker Compose is the production deployment unit; the Compose files live under
`service/`:

```bash
docker compose -f service/docker-compose.prod.yml up -d
```

This starts gateway and worker with Docker healthchecks, `restart:
unless-stopped` policies, dependency ordering, and Jaeger distributed tracing.
Log aggregation: `docker compose -f service/docker-compose.prod.yml logs -f`.

See `service/.env.example` for all environment variables. The only mandatory
config for a working stack is one provider API key, and
`service/docker-compose.prod.yml` picks up `.env` automatically.

For a source (non-Docker) production install, pull in the `server` extra so the
Postgres driver and OTLP exporter are present:

```bash
uv sync --extra server
```

## Development Workflow

### Service Management

All services run in the foreground. Each requires its own terminal. There is no
background daemon or PID registry.

```bash
just dev service start [target]     # start service(s) — foreground
just dev service stop [target]      # stop service(s)
just dev service kill [target]      # force-kill service(s)
just dev service restart [target]   # stop then start
just dev service rebuild [target]   # rebuild image then start
just dev service health [target]    # HTTP probe to /health endpoints
just dev service logs TARGET        # stream logs
just dev service probe PROVIDER     # probe a specific LLM provider
```

Service targets:

| Target | Services | Ports |
|--------|----------|-------|
| `all` (default) | Everything in dependency order | — |
| `prod` | gateway + worker + postgres | — |
| `dev` | jaeger + vidaimock | — |
| `gateway` | Gateway API server | 8000 |
| `worker` | Worker executor (LangGraph) | 8001 |
| `postgres` | PostgreSQL | 5432 |
| `jaeger` | Jaeger trace collector + UI | 4317, 16686 |
| `vidaimock` | Mock LLM provider | 8100 |

Multiple targets: `just dev service start gateway worker`

Database operations:

```bash
just dev service db migrate [--fix]
just dev service db snapshot [list]
just dev service db restore --name FILE
just dev service db clear --yes
```

### Pre-flight: Doctor

Run before starting services to catch configuration and port problems before
they become confusing startup failures:

```bash
just doctor              # full environment check
just doctor ports        # what is listening on 8000, 8001?
just doctor config       # API keys, DB backend, required env vars
just doctor services     # HTTP probe to /health endpoints
```

If a port is occupied, `just doctor ports` shows the occupying PID and process
name and suggests a fix command.

### Code Quality

```bash
just dev code check [target]    # read-only lint + type check
just dev code fix [target]      # auto-repair
```

Targets: `lint`, `type`, `all` (default)

### Testing

```bash
just dev test unit [*ARGS]              # unit tests
just dev test live [*ARGS]              # live integration tests (services must be running)
just dev test smoke [*ARGS]             # smoke tests against real gateway + worker
just dev test tracing [*ARGS]           # OTel/Jaeger tracing tests
just dev test mock [NAME | --list]      # mock provider tests
just dev test verify docker | provider NAME | endpoints | core
just dev test ci                        # CI gate: unit + tracing
just dev test all                       # full suite
```

Live and smoke tests require a running gateway and worker. Mocks are not used.

### Build Artifacts

```bash
just dev build package       # Python sdist + wheel
just dev build docker        # local dev Docker image
just dev build docker-prod   # production multi-stage image
just dev build clean         # remove dist/, egg-info, __pycache__
```

### Dependency Management

```bash
just dev deps install    # full bootstrap: uv sync + npm install
just dev deps sync       # sync to lockfile
just dev deps upgrade    # upgrade all dependencies
just dev deps lock       # regenerate lockfile
```

## Operator CLI Reference

`vaultspec-a2a` is the operator CLI. It is a thin client of the gateway's
versioned `/v1` edge: every command except `serve` is a plain HTTP call to a
running gateway, so operator and engine exercise one surface. Commands that
reach the gateway take `--url` to target a non-default bind (default: the local
`gateway_url`).

### Gateway lifecycle and health

```bash
vaultspec-a2a serve                  # boot the local gateway app in the foreground
vaultspec-a2a doctor [--url URL]     # report gateway health via the service-state verb
vaultspec-a2a presets [--url URL]    # list available team presets
```

`doctor` also diagnoses a stale resident — a gateway process started before a
route landed still serving the old route table — and encodes the verdict in its
exit code: `0` healthy, `1` unreachable or HTTP error, `3` reachable but stale.

### Runs

```bash
vaultspec-a2a run start --preset ID --message TEXT [--title T] [--autonomous|--supervised] [--url URL]
vaultspec-a2a run status RUN_ID [--url URL]
vaultspec-a2a run cancel RUN_ID [--url URL]
```

`--autonomous/--supervised` overrides the preset's autonomy default; omit it to
inherit the preset. `run cancel` is idempotent.

### Workspace provisioning

```bash
vaultspec-a2a workspace provision [PATH] [--verify-only]
```

Installs the vaultspec framework into `PATH` and verifies its agent harness,
reporting any version skew and each missing surface. `--verify-only` skips the
install and only re-checks an already-provisioned workspace. Exits non-zero when
the harness is incomplete, so a caller can gate on provisioning.

### Dev process registry

`procs` manages machine-global development processes (gateway-dev, worker-dev,
engine-dev) through a shared registry — distinct from the Docker service
lifecycle above.

```bash
vaultspec-a2a procs list                 # every registered process, its liveness, and endpoint
vaultspec-a2a procs up ROLE NAME [...]    # allocate a band port, boot the role, and register it
vaultspec-a2a procs attach NAME          # verify a process is live and print its endpoint
vaultspec-a2a procs rebuild NAME         # run the role's build command from procs.toml
vaultspec-a2a procs rerun NAME           # kill, rebuild, and restart on the same port
vaultspec-a2a procs resume NAME          # restart a died record on its original port
vaultspec-a2a procs kill NAME            # tree-kill a process and remove its record
vaultspec-a2a procs reap                 # kill and clear every stale or dead record
vaultspec-a2a procs allocate ROLE        # reserve and print the next free band port for ROLE
```

### Global options

The command group itself exposes only `--version`/`-V` (print the installed
version and exit) and `--help`. Logging and gateway-target options are
per-command (`--url`).

## Port Layout

Default port assignments. All ports are overridable via environment variables.
In Docker, only the host side of port mappings changes — container-internal
ports are fixed.

| Port | Service | Env Override | Notes |
|------|---------|--------------|-------|
| 8000 | Gateway API | `VAULTSPEC_PORT` | REST + WebSocket |
| 8001 | Worker | `VAULTSPEC_WORKER_PORT` | LangGraph executor |
| 8200 | MCP server | `VAULTSPEC_MCP_PORT` | Streamable HTTP transport |
| 4317 | Jaeger OTLP | `OTEL_EXPORTER_OTLP_ENDPOINT` | Trace collector |
| 16686 | Jaeger UI | — | Trace viewer |
| 5432 | PostgreSQL | (embedded in `DATABASE_URL`) | Only when `backend=postgres` |
| 8100 | VidaiMock | `MOCK_API_BASE` | Mock LLM, dev only |

Auto-derived URLs (no explicit config needed):

- `VAULTSPEC_GATEWAY_URL` derives from `VAULTSPEC_HOST` + `VAULTSPEC_PORT`
- `VAULTSPEC_WORKER_URL` derives from `VAULTSPEC_WORKER_HOST` + `VAULTSPEC_WORKER_PORT`

## Database Backends

SQLite is the local and development default. No configuration needed. The only
required config is one LLM provider key.

For production with Postgres, install the `server` extra (Postgres driver,
checkpoint saver, and OTLP exporter) and set in `.env`:

```bash
uv sync --extra server
```

```bash
VAULTSPEC_DATABASE_BACKEND=postgres
VAULTSPEC_DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/vaultspec
VAULTSPEC_CHECKPOINT_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5432/vaultspec?sslmode=disable
```

Semantic search over the vault (the `vaultspec-rag` bridge and its Torch
dependency) is a separate opt-in extra:

```bash
uv sync --extra rag
```

## Troubleshooting

### Gateway not running / CLI fails immediately

Run `just doctor services` to probe all health endpoints. Then start the missing
service: `just dev service start gateway` or `just dev service start worker`.

### Port already in use

Run `just doctor ports` to see which process is occupying the port. The output
includes PID, process name, and a suggested fix command (`just dev service kill`
or the relevant system command).

### Missing API key

Run `just doctor config` to validate all required environment variables. The
output shows which keys are missing and the exact `export` command to set them.

### Services appear to start but requests fail

Run `just doctor` for a full environment check — it covers ports, config, and
HTTP health probes in one pass.

### Worker crashes on startup

Crash output is visible directly in the terminal (no background process, no log
files to hunt). Read the traceback, fix the issue, and run
`just dev service start worker` again.

### Docker Compose production stack fails to become healthy

Check service logs: `docker compose -f docker-compose.prod.yml logs -f`. All
services have healthchecks and `restart: unless-stopped` policies. Gateway
and worker expose `/health` endpoints — probe them directly to isolate which
service is unhealthy.

## Architecture

- `src/vaultspec_a2a/` — Python package
  - `api/` — FastAPI gateway (HTTP REST, WebSocket relay, worker spawn)
  - `worker/` — LangGraph executor (agent graphs, checkpointing)
  - `thread/`, `context/`, `team/`, `graph/`, `streaming/` — layered domain and orchestration packages
  - `database/` — SQLAlchemy models, Alembic migrations
  - `providers/` — LLM provider adapters (Claude/ACP, Gemini, OpenAI)
  - `authoring/` — loopback client for the engine's authoring API (proposals)
  - `lifecycle/` — machine-global service discovery and heartbeat
  - `cli/` — the `vaultspec-a2a` operator CLI (thin client of the five-verb gateway)
  - `control/` — service orchestration, health, config, and runtime support modules
- `.vault/adr/` — Architecture Decision Records (binding)
- `knowledge/` — implementation notes and repository snippets

Key ADRs:

- ADR-038: Control layer — CLI/Justfile separation
- ADR-039: Service lifecycle architecture — container-first with dev shim
- ADR-031: Worker process architecture
- ADR-017: Containerization strategy

## References

- Project ADRs: `.vault/adr/`
- Knowledge base: `knowledge/`
- Environment variables: `.env.example`
- IDE setup (MCP configuration for Cursor/Claude/Windsurf): `.vault/reference/2026-03-31-ide-mcp-server-setup-reference.md`

## The vaultspec family

vaultspec-a2a is the orchestration layer of the vaultspec family - a set of
tools built around one shared vault:

- [vaultspec-core](https://github.com/nevenincs/vaultspec-core) - the hub: the
  `Research → Decide → Plan → Code → Review` pipeline, the git-tracked
  Markdown vault, and the CLI that drives them.
- [vaultspec-rag](https://github.com/nevenincs/vaultspec-rag) - semantic
  search across the vault and the codebase.
- vaultspec-dashboard - a visual companion for vault health, decision graphs,
  and search activity. In development.

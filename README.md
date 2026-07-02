# Vaultspec A2A Agent Orchestration

[![Python 3.13+](https://img.shields.io/badge/python-3.13%2B-blue.svg)](https://www.python.org/)
[![Status: Early](https://img.shields.io/badge/status-early-orange.svg)](#status)

A2A orchestration backend for the
[vaultspec](https://github.com/nevenincs/vaultspec-core) agentic coding
workflow. Provides team-based and subagent-based task dispatch across Claude,
Gemini, and Codex agents via a gateway/worker architecture.

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

## Quickstart

Clone and install dependencies:

```bash
git clone <repo-url>
cd vaultspec-a2a
just dev deps install
```

Copy and edit the environment file:

```bash
cp .env.example .env
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

Start a team and follow its progress:

```bash
vaultspec team start --preset vaultspec-solo-coder --message "Create a hello world module"
vaultspec team status <thread_id>
vaultspec team watch <thread_id>
```

## Production Deployment

Docker Compose is the production deployment unit:

```bash
docker compose -f docker-compose.prod.yml up -d
```

This starts gateway, worker, and UI with Docker healthchecks, `restart:
unless-stopped` policies, dependency ordering, and Jaeger distributed tracing.
Log aggregation: `docker compose -f docker-compose.prod.yml logs -f`.

See `.env.example` for all environment variables. The only mandatory config for
a working stack is one provider API key and `docker-compose.prod.yml` picks up
`.env` automatically.

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
| `prod` | gateway + worker + ui + postgres | — |
| `dev` | jaeger + vidaimock | — |
| `gateway` | Gateway API server | 8000 |
| `worker` | Worker executor (LangGraph) | 8001 |
| `ui` | Vite frontend dev server | 5173 |
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
just doctor ports        # what is listening on 8000, 8001, 5173?
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

Targets: `lint`, `type`, `ui`, `all` (default)

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

## Production CLI Reference

`vaultspec` is the production CLI. It operates against a running gateway and
fails fast if the gateway is unreachable:

```text
Error: Gateway not running at http://127.0.0.1:8000

  just dev service start gateway    Start the gateway
  just dev service start            Start all services
```

### Team commands

```bash
vaultspec team start --preset NAME --message TEXT [--name NICK] [--autonomous|--supervised]
vaultspec team message THREAD_ID --content TEXT [--agent AGENT_ID]
vaultspec team respond THREAD_ID --request-id ID --option OPTION_ID
vaultspec team resume THREAD_ID [--message TEXT]
vaultspec team cancel THREAD_ID
vaultspec team delete THREAD_ID
vaultspec team archive THREAD_ID
vaultspec team status THREAD_ID [--json]
vaultspec team watch THREAD_ID
vaultspec team list [STATUS_FILTER] [--json]
vaultspec team presets [--json]
```

### Agent commands

```bash
vaultspec agent list [--json]
vaultspec agent show NAME [--json]
```

### Global options

| Option | Short | Effect |
|--------|-------|--------|
| `--verbose` | `-v` | INFO logging |
| `--debug` | `-d` | DEBUG logging |
| `--version` | `-V` | Print version, exit |
| `--show-config` | | Print resolved settings, exit |

### Production CLI passthrough via Justfile

```bash
just prod team [*ARGS]     # equivalent to: uv run vaultspec team ...
just prod agent [*ARGS]    # equivalent to: uv run vaultspec agent ...
```

## Port Layout

Default port assignments. All ports are overridable via environment variables.
In Docker, only the host side of port mappings changes — container-internal
ports are fixed.

| Port | Service | Env Override | Notes |
|------|---------|--------------|-------|
| 8000 | Gateway API | `VAULTSPEC_PORT` | REST + WebSocket |
| 8001 | Worker | `VAULTSPEC_WORKER_PORT` | LangGraph executor |
| 5173 | Vite UI | (Vite default) | Frontend dev server |
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

For production with Postgres, set in `.env`:

```bash
VAULTSPEC_DATABASE_BACKEND=postgres
VAULTSPEC_DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/vaultspec
VAULTSPEC_CHECKPOINT_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5432/vaultspec?sslmode=disable
```

## Frontend Development

Three workflows depending on what you need:

1. **Split-terminal local development** — fastest iteration, native Vite HMR:

   ```bash
   just dev service start gateway    # terminal 1
   just dev service start worker     # terminal 2
   just dev service start ui         # terminal 3
   ```

2. **Frontend-ready Docker stack** — lowest-friction shared stack:

   ```bash
   just dev service start prod
   ```

   Starts gateway, worker, UI, and Postgres via Docker.

3. **Full integration stack** — adds Jaeger tracing and VidaiMock:

   ```bash
   just dev service start all
   ```

Expected URLs:

| Service | URL |
|---------|-----|
| Gateway API | `http://localhost:8000` |
| Worker health | `http://localhost:8001/health` |
| Vite UI | `http://localhost:5173` |
| Jaeger UI | `http://localhost:16686` |

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
  - `control/` — service orchestration, health, config, and runtime support modules
- `src/ui/` — React + Vite frontend
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

# vaultspec-a2a

Headless agent-to-agent orchestration.

[![Tests](https://github.com/nevenincs/vaultspec-a2a/actions/workflows/test.yml/badge.svg)](https://github.com/nevenincs/vaultspec-a2a/actions/workflows/test.yml)
[![Python 3.13+](https://img.shields.io/badge/python-3.13%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Status: Beta](https://img.shields.io/badge/status-beta-blue.svg)](#status-and-license)

[What it does](#what-it-does) ·
[Getting started](#getting-started) ·
[Capabilities](#capabilities) ·
[Family](#the-vaultspec-family) ·
[Documentation](#documentation) ·
[Operating & development](#operating-and-development-reference)

## What it does

vaultspec-a2a is the headless orchestration layer of the vaultspec family. It
dispatches agent work across Claude, Gemini, and Codex through a gateway/worker
architecture, and it fronts that work behind a versioned loopback HTTP edge so a
UI (the dashboard) or an engine can drive it without embedding it.

It ships no bundled UI. Every document an agent produces becomes a human-reviewed
proposal in the review lane through the authoring API — agents never write to the
vault directly.

Two modes:

- **Team mode** — a self-orchestrating team (supervisor + coders) works
  concurrently against a task. Preferred for parallelized, long-horizon coding
  work.
- **Subagent mode** — a single agent performs a task on behalf of a client
  application (Claude Code, Gemini CLI, Antigravity). Preferred for
  non-parallelized, sequential handoffs.

## Getting started

Requires Python 3.13+ and [uv](https://docs.astral.sh/uv/). vaultspec-a2a is not
yet published to a package index; install it from source or run the production
Docker stack. (PyPI publication is planned now that the vaultspec-core dependency
is pinned to a released version.)

**From source:**

```bash
git clone https://github.com/nevenincs/vaultspec-a2a
cd vaultspec-a2a
just dev deps install
cp service/.env.example .env
# Set at least one provider key: ANTHROPIC_API_KEY, GEMINI_API_KEY, or OPENAI_API_KEY
```

Start the gateway and worker (each runs in the foreground, in its own terminal),
then verify:

```bash
just dev service start gateway   # terminal 1 — port 8000
just dev service start worker    # terminal 2 — port 8001
just doctor
```

Start a run and follow it (list preset ids with `vaultspec-a2a presets`):

```bash
vaultspec-a2a run start --preset <preset-id> --message "Create a hello world module"
vaultspec-a2a run status <run_id>
```

**With Docker (production stack):**

```bash
docker compose -f service/docker-compose.prod.yml up -d
```

**Optional extras:** `uv sync --extra server` adds the Postgres driver,
checkpoint saver, and OTLP exporter for a production install; `uv sync --extra
rag` adds the `vaultspec-rag` semantic-search bridge and its Torch dependency.

## Capabilities

| Capability | Detail |
| ---------- | ------ |
| Gateway edge | A versioned `/v1` HTTP surface (service-state, presets, run start/status/cancel) that operator and engine share — one code path, no divergence. |
| Team mode | Self-orchestrating supervisor + coder team for parallel, long-horizon work. |
| Subagent mode | A single agent serving one client application for sequential handoffs. |
| Providers | Claude (ACP), Gemini, and OpenAI/Codex adapters. |
| Review lane | Agent outputs become human-reviewed proposals via the authoring API; agents never write the vault directly. |
| Operator CLI | `vaultspec-a2a` — a thin client of the gateway: `serve`, `doctor`, `presets`, `run`, `workspace`, and the `procs` dev registry. |

## The vaultspec family

vaultspec-a2a is one project in a family built around one shared vault:

- [vaultspec-core](https://github.com/nevenincs/vaultspec-core) — The agent
  harness: the pipeline, the vault, and the CLI that drives them. **(Beta)**
- [vaultspec-rag](https://github.com/nevenincs/vaultspec-rag) — The semantic
  search component for vault and code. **(Beta)**
- [vaultspec-dashboard](https://github.com/nevenincs/vaultspec-dashboard) — The
  application that runs it all as a UI. **(Beta)**
- **vaultspec-a2a** — Headless agent-to-agent orchestration. **(Beta)** — this
  project.

## Documentation

- [Documentation home](docs/index.rst)
- [Architecture navigation](docs/architecture.rst)
- [Operator reference](docs/operations.rst)
- [Python module reference](docs/api/modules.rst)
- [Edge conformance mapping](docs/a2a-edge-conformance-verb-mapping.md)

## Status and license

**Beta.** Interfaces, presets, and deployment surfaces are still taking shape and
may change without notice. The project is usable and under active development;
support is best-effort.

Licensed under the [MIT License](LICENSE).

---

The rest of this document is an operator and contributor reference for running,
developing, and deploying vaultspec-a2a.

## Operating and development reference

vaultspec-a2a runs as two foreground services — a gateway and a worker — either
directly during development or as a Docker Compose stack in production. The
sections below cover both.

## Running services

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

For production, Docker Compose is the deployment unit; the Compose files live
under `service/`:

```bash
docker compose -f service/docker-compose.prod.yml up -d
```

This starts gateway and worker with Docker healthchecks, `restart:
unless-stopped` policies, dependency ordering, and Jaeger distributed tracing.
Log aggregation: `docker compose -f service/docker-compose.prod.yml logs -f`.
See `service/.env.example` for all environment variables; the only mandatory
config for a working stack is one provider API key, and
`service/docker-compose.prod.yml` picks up `.env` automatically.

### Pre-flight: doctor

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

### Code quality

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

### Build artifacts

```bash
just dev build package       # Python sdist + wheel
just dev build docker        # local dev Docker image
just dev build docker-prod   # production multi-stage image
just dev build clean         # remove dist/, egg-info, __pycache__
```

### Dependency management

```bash
just dev deps install    # full bootstrap: uv sync + npm install
just dev deps sync       # sync to lockfile
just dev deps upgrade    # upgrade all dependencies
just dev deps lock       # regenerate lockfile
```

## Operator CLI reference

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

The command group itself exposes only `--version`/`-V` (print the installed
version and exit) and `--help`. Logging and gateway-target options are
per-command (`--url`).

## Port layout

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

## Database backends

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

Check service logs: `docker compose -f service/docker-compose.prod.yml logs -f`.
All services have healthchecks and `restart: unless-stopped` policies. Gateway
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

A few load-bearing decisions shape the design: the operator CLI and the Justfile
stay separate, so automation drives the same gateway edge a human does; the
service lifecycle is container-first with a lightweight development shim; the
worker runs as its own process so agent execution is isolated from the gateway;
and the whole stack ships as containers for reproducible deployment.

## References

- Environment variables: `service/.env.example`
- Editor MCP setup (Cursor, Claude, Windsurf): point your editor's MCP client at
  the `vaultspec-a2a-mcp` console script, or at the MCP server on port 8200 (see
  [Port layout](#port-layout)).

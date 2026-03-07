# CLI Refactor Research — 2026-03-06

## 1. Problem Statement

The CLI (`src/vaultspec_a2a/cli.py`, 236 lines) has 8 commands organized as a
flat grab-bag. The target design (documented in
`docs/audits/2026-03-06-cli-architecture-audit.md`) restructures into 6 domain
groups + 1 global flag. This research captures the backend surface, framework
patterns, and constraints that inform the ADR and plan.

## 2. Current CLI Surface

| Command | Type | Lines |
|---------|------|-------|
| `serve` | command | 36-69 |
| `worker` | command | 72-96 |
| `test` | command | 99-121 |
| `migrate` | group (upgrade, stamp) | 127-170 |
| `config` | command | 176-183 |
| `preps` | command | 189-201 |
| `eval` | group (smoke, nightly) | 207-231 |

Entry point: `pyproject.toml:33` → `vaultspec = "vaultspec_a2a.cli:cli"`

## 3. Target CLI Surface

```
vaultspec --show-config
vaultspec test [unit | smoke | benchmark [smoke|nightly]]
vaultspec run [mock [SCENARIO] | probe [PROVIDER]]
vaultspec team [start | status | resume | stop | delete | archive | list]
vaultspec agent [ask | list]
vaultspec service [start | stop | kill | delete]
vaultspec database [update | clear | snapshot | snapshot list | restore]
```

## 4. Backend Surface Audit

### 4.1 Thread Lifecycle (endpoints.py)

| Endpoint | Method | Line | Notes |
|----------|--------|------|-------|
| `/threads` | POST | 194 | Creates thread, returns 201 |
| `/threads` | GET | 327 | Paginated list (offset, limit) — **no status filter** |
| `/threads/{id}/state` | GET | 470 | State snapshot for reconnection |
| `/threads/{id}/metadata` | GET | 377 | Thread metadata (ADR-014) |
| `/threads/{id}/messages` | POST | 559 | Send message — **no status gate** |
| `/threads/{id}/cancel` | POST | 820 | Cancel running thread |
| `/permissions/{id}/respond` | POST | 727 | Permission resume — **no status gate** |

**Missing**: DELETE endpoint, archive endpoint, status-filtered list.

### 4.2 ThreadStatus Enum (crud.py:36-44)

```python
SUBMITTED = "submitted"
CREATED = "created"
RUNNING = "running"
COMPLETED = "completed"
FAILED = "failed"
CANCELLED = "cancelled"
```

**No ARCHIVED status.** Adding it requires: enum value + Alembic migration (for
any existing CHECK constraints) + endpoint to transition.

### 4.3 CRUD Functions (crud.py)

| Function | Line | Notes |
|----------|------|-------|
| `create_thread()` | 101 | Full creation with metadata |
| `get_thread()` | 162 | By ID |
| `list_threads()` | 178 | Paginated, **no status param** |
| `update_thread_status()` | 207 | Status transition |
| `update_thread_metadata()` | 239 | Metadata JSON update |
| `get_thread_metadata()` | 264 | Metadata only |

**Missing**: `delete_thread()`, `list_threads(status=...)`.

### 4.4 Database Operations

- **init_db()**: `database/session.py:162-200` — creates engine + tables via
  `Base.metadata.create_all`, WAL mode enabled.
- **DB path**: `settings.database_url` default
  `sqlite+aiosqlite:///vaultspec.db`. Path extracted via
  `settings.database_path` property (`core/config.py:165-175`).
- **No truncate/clear/snapshot/restore** mechanisms exist.
- **Alembic**: Configured (`alembic.ini` at repo root), `run_migrations()`
  exported from `database/__init__.py`.

### 4.5 Agent Presets

- **24 agent TOMLs** in `core/presets/agents/` (production + mock variants).
- **17 team TOMLs** in `core/presets/teams/` (production + mock variants).
- **Solo execution**: `vaultspec-solo-coder.toml` — single-agent pipeline
  topology. Always goes through team/graph machinery.
- **No dedicated single-agent runner** — every execution creates a thread + team.

### 4.6 Provider Probes

- Module: `providers/probes/__init__.py` exports `ProbeResult`, `run_probe()`,
  `run_http_probe()`.
- Individual probes: `claude.py`, `gemini.py`, `openai.py`, `zhipu.py`.
- Each has `main()` + `__main__.py`-style entry via argparse.
- CLI invocation: `python -m vaultspec_a2a.providers.probes.claude --backend
  node --debug`.

### 4.7 Service/Process Management

- **Backend**: FastAPI app via `uvicorn.run()` in CLI `serve` command.
- **Worker**: Separate FastAPI app via `uvicorn.run()` in CLI `worker` command.
- **Auto-spawn**: `settings.auto_spawn_worker = True` — gateway spawns
  worker as child process.
- **No PID tracking**, no signal handling, no process registry.
- **Docker**: `docker-compose.dev.yml` (5 services) and
  `docker-compose.prod.yml` (3 services). No CLI wrapper for Docker commands.

## 5. Framework Analysis

### 5.1 Current: Click 8.1+

Standard Click with `@click.group()` and `@click.command()`. No extensions.
Sensitive value masking via `_mask()` helper.

### 5.2 Reference: LangGraph CLI

Uses Click 9.x+ with **reusable option constants**:
```python
OPT_CONFIG = click.option("--config", "-c", help="Config path")
```
Good pattern for shared options across `service` and `team` subcommands.

### 5.3 Reference: MCP Python SDK CLI

Uses Typer. Not applicable — project is committed to Click.

### 5.4 Dispatch Patterns

Two patterns in codebase:
1. **Subprocess dispatch**: `sys.exit(subprocess.run([sys.executable, "-m",
   ...]).returncode)` — used by `test`, `preps`, `eval`.
2. **Direct invocation**: `uvicorn.run(...)` — used by `serve`, `worker`.
3. **Async main**: Probes use `asyncio.run(main(...))` — good for `team` and
   `agent` commands that need async HTTP calls.

## 6. Design Constraints

1. **Click 8.1+** — no version bump needed. Group nesting is native.
2. **Lazy imports** — all heavy imports (uvicorn, alembic, httpx) must stay
   inside command bodies to keep `vaultspec --help` fast.
3. **Exit codes** — subprocess-dispatched commands forward exit codes.
   Direct-invocation commands must also return meaningful codes.
4. **No async Click** — Click doesn't support async natively. Commands needing
   async (team, agent) must use `asyncio.run()`.
5. **Backend gaps** — `team` and `agent` groups require new endpoints/CRUD.
   `database` group requires new utility functions. `service` group requires
   PID tracking or HTTP health checks.
6. **Subprocess dispatch for probes** — probes use argparse internally. CLI
   wrapper dispatches to `python -m vaultspec_a2a.providers.probes.{provider}`.
7. **`--show-config` as eager option** — Click supports `is_eager=True` +
   `expose_value=False` + callback pattern for global flags that print-and-exit.

## 7. Backend Gap Classification

### 7.1 No Backend Work Required (CLI-only restructure)

| Target Command | Source | Change |
|---------------|--------|--------|
| `service start [backend\|worker]` | `serve` + `worker` | Rename + group |
| `test unit [PATH] [-- ARGS]` | `test [TARGET]` | Group + default |
| `test smoke` | (new, runs `pytest -m smoke`) | Trivial |
| `test benchmark [suite]` | `eval smoke/nightly` | Rename + group |
| `run mock [SCENARIO]` | `preps [SCENARIO]` | Rename + group |
| `run probe [PROVIDER]` | (python -m dispatch) | New CLI surface |
| `database update [--target]` | `migrate upgrade` | Rename |
| `--show-config` | `config` | Restructure |

### 7.2 Light Backend Work (CRUD/utility additions)

| Target Command | Backend Gap | Complexity |
|---------------|-------------|------------|
| `team list [status]` | Add `status` param to `list_threads()` + endpoint | Low |
| `team delete` | Add `delete_thread()` CRUD + DELETE endpoint | Low |
| `team archive` | Add `ARCHIVED` to enum + transition endpoint | Low-Med |
| `database clear --yes` | Add `truncate_tables()` utility | Low |
| `database snapshot` | SQLite file copy with timestamp | Low |
| `database snapshot list` | Glob `*.snapshot.*` files | Trivial |
| `database restore` | Copy snapshot back + running check | Low |

### 7.3 Significant Backend Work

| Target Command | Backend Gap | Complexity |
|---------------|-------------|------------|
| `agent ask` | Single-agent execution path (load TOML, wire provider, single-node graph, stream) | Medium-High |
| `agent list` | Glob agent presets, parse TOML, print table | Low |
| `team start` | CLI → POST /threads with team_preset | Low (endpoint exists) |
| `team status` | CLI → GET /threads/{id}/state | Low (endpoint exists) |
| `team resume` | Status gate + re-dispatch for completed/failed | Medium |
| `team stop` | CLI → POST /threads/{id}/cancel | Low (endpoint exists) |
| `service stop/kill` | PID tracking or HTTP-based shutdown | Medium |
| `service delete` | Docker compose wrapper | Low |

## 8. Recommendations

1. **Phase the work**: CLI restructure first (no backend), then backend gaps.
2. **Keep Click**: No framework change needed. Nested groups work well.
3. **Use `asyncio.run()` for async commands**: `team` and `agent` commands call
   the REST API via httpx, wrapped in `asyncio.run()`.
4. **Single-agent via solo-coder preset**: `agent ask` can use the existing
   `vaultspec-solo-coder` team preset with a dynamic agent name override. Avoids
   building a new execution path. The "lightweight" path from the architecture
   audit is over-engineered for the CLI surface.
5. **`database` utilities as sync functions**: SQLite file ops don't need async.
   Use `shutil.copy2` for snapshots, `Path.glob` for listing.
6. **`service stop` via HTTP**: POST `/shutdown` endpoint (new, trivial) + HTTP
   client in CLI. Avoids PID tracking complexity.

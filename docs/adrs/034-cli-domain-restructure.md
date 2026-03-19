---
adr_id: 034
title: CLI Domain Restructure
date: 2026-03-06
status: Proposed
related:
  - docs/adrs/015-dependency-hygiene-cli-entry-point.md
  - docs/adrs/016-task-runner-dev-bootstrap.md
  - docs/adrs/029-database-migration-framework.md
  - docs/audits/2026-03-06-cli-architecture-audit.md
  - docs/audits/2026-03-06-cli-audit.md
  - docs/research/2026-06-03-cli-refactor-research.md
---

# ADR-034: CLI Domain Restructure

**Date:** 2026-03-06
**Status:** Proposed

## 1. Context & Problem Statement

The CLI (`src/vaultspec_a2a/cli.py`) has 8 top-level commands organized as a
flat list. This structure has several problems:

1. **Naming confusion**: `serve` and `worker` are two commands for the same
   concept (starting processes). `preps` sounds like setup. `eval` is vague.
2. **Missing surfaces**: Thread lifecycle, single-agent execution, provider
   probes, database management, and service control have no CLI exposure.
3. **Inconsistent depth**: `migrate` and `eval` are groups; everything else is
   flat. No organizing principle.

The target design (approved in `docs/audits/2026-03-06-cli-architecture-audit.md`)
restructures into 6 domain groups plus 1 global flag.

## 2. Decision

### 2.1 Command Taxonomy

Replace the flat command list with 6 domain groups. Each group completes a
sentence: "I want to ______."

```
vaultspec --show-config

vaultspec test                              # defaults to: test unit
vaultspec test unit        [PATH] [-- PYTEST_ARGS]
vaultspec test smoke
vaultspec test benchmark   [smoke | nightly]

vaultspec run mock         [SCENARIO]       # bare = run all
vaultspec run probe        [PROVIDER]

vaultspec team start       --preset NAME [--name NICKNAME]
vaultspec team status      --id ID
vaultspec team resume      --id ID [--message TEXT]
vaultspec team stop        --id ID
vaultspec team delete      --id ID
vaultspec team archive     --id ID
vaultspec team list        [running | completed | archived]

vaultspec agent ask        --agent NAME --message TEXT
vaultspec agent list

vaultspec service start    [backend | worker]   # bare = backend + worker
vaultspec service stop     [backend | worker]
vaultspec service kill     [backend | worker]
vaultspec service delete   DOCKER_SERVICE

vaultspec database clear   --yes
vaultspec database update  [--target REVISION]
vaultspec database snapshot
vaultspec database snapshot list
vaultspec database restore --name SNAPSHOT
```

### 2.2 CLI Module Structure

Split `cli.py` (monolith) into a `cli/` package with one module per domain
group:

```
src/vaultspec_a2a/cli/
├── __init__.py          # root group, --show-config, imports subgroups
├── _test.py             # test group (unit, smoke, benchmark)
├── _run.py              # run group (mock, probe)
├── _team.py             # team group (start, status, resume, stop, delete, archive, list)
├── _agent.py            # agent group (ask, list)
├── _service.py          # service group (start, stop, kill, delete)
├── _database.py         # database group (clear, update, snapshot, restore)
└── _util.py             # shared helpers (_mask, _api_client, _print_table)
```

Underscore-prefixed module names signal internal implementation. The public API
is `cli/__init__.py` exporting `cli` (the Click group) and `main = cli`.

### 2.3 `--show-config` as Eager Global Flag

```python
@click.group()
@click.option(
    "--show-config",
    is_flag=True,
    is_eager=True,
    expose_value=False,
    callback=_show_config_callback,
    help="Print resolved settings and exit.",
)
def cli() -> None: ...
```

This replaces the `config` subcommand. The eager callback prints settings using
the existing `_mask()` helper and calls `ctx.exit()`.

### 2.4 Default Subcommand Pattern

Click does not natively support default subcommands. For `vaultspec test` →
`vaultspec test unit`, use a Click group with `invoke_without_command=True` and
a fallback:

```python
@cli.group(invoke_without_command=True)
@click.pass_context
def test(ctx: click.Context) -> None:
    if ctx.invoked_subcommand is None:
        ctx.invoke(unit)
```

### 2.5 Team & Agent Commands — REST Client Pattern

Commands in `team` and `agent` groups call the backend REST API. Use a shared
httpx client:

```python
def _api_client() -> httpx.Client:
    from .._core.config import settings
    return httpx.Client(base_url=settings.api_base_url, timeout=30.0)
```

Synchronous httpx (not async) — Click commands are sync. The REST API handles
async internally.

### 2.6 Service Management

`service start [target]`:

- `backend` → `uvicorn.run("vaultspec_a2a.api.app:create_app", ...)`
- `worker` → `uvicorn.run("vaultspec_a2a.worker.app:create_worker_app", ...)`
- bare → start both (backend in main thread, worker via `auto_spawn_worker`)

`service stop [target]`:

- POST `/admin/shutdown` (new lightweight endpoint) with httpx.
- Falls back to "not running" message if connection refused.

`service kill [target]`:

- Like stop but sends SIGTERM/taskkill to the process.
- Requires PID tracking (see §2.8).

`service delete DOCKER_SERVICE`:

- Wraps `docker compose down --rmi local <service>`.
- Errors if target is `backend` or `worker` (native processes, not Docker).

### 2.7 Database Utilities

All sync operations on the SQLite file:

| Command | Implementation |
|---------|---------------|
| `database update` | Alembic `command.upgrade(cfg, target)` (existing) |
| `database clear --yes` | `DELETE FROM` on all application tables, preserving Alembic version |
| `database snapshot` | `shutil.copy2(db_path, db_path.with_suffix(f".snapshot.{timestamp}"))` |
| `database snapshot list` | `db_path.parent.glob("*.snapshot.*")` |
| `database restore --name` | Refuse if service running (HTTP health check), then `shutil.copy2` |

### 2.8 Backend Additions Required

| ID | Scope | Description |
|----|-------|-------------|
| BE-A | CRUD | `delete_thread(session, thread_id)` — hard delete thread + cascading artifacts |
| BE-B | CRUD | `list_threads(session, ..., status=None)` — optional status filter param |
| BE-C | Enum | `ThreadStatus.ARCHIVED` — new terminal state |
| BE-D | Endpoint | `DELETE /threads/{id}` — calls `delete_thread()` |
| BE-E | Endpoint | `POST /threads/{id}/archive` — transitions to ARCHIVED |
| BE-F | Endpoint | `GET /threads?status=running` — status query param |
| BE-G | Endpoint | `POST /admin/shutdown` — graceful shutdown via `os.kill(os.getpid(), signal.SIGTERM)` |
| BE-H | CRUD | Status gate on `send_message`: reject ARCHIVED threads with 409 |

### 2.9 Backward Compatibility

- `pyproject.toml` entry point remains `vaultspec = "vaultspec_a2a.cli:cli"`.
- The old `cli.py` module path is replaced by `cli/__init__.py`. The symbol
  `cli` remains at the same import path: `from vaultspec_a2a.cli import cli`.
- `main = cli` alias preserved for any external consumers.
- Justfile recipes updated in the same PR to use new command names.

## 3. Implementation Phases

### Phase 1 — CLI Restructure (no backend changes)

Restructure existing commands into domain groups. All functionality preserved,
just reorganized:

- `serve` + `worker` → `service start [backend|worker]`
- `test [TARGET]` → `test unit [PATH] [-- ARGS]` (with default)
- `test smoke` (new, `pytest -m smoke`)
- `eval smoke/nightly` → `test benchmark [smoke|nightly]`
- `preps` → `run mock [SCENARIO]`
- `run probe [PROVIDER]` (new CLI surface for existing probe modules)
- `migrate upgrade` → `database update`
- `migrate stamp` → removed (no target equivalent)
- `config` → `--show-config`

### Phase 2 — Database Utilities

New `database` subcommands: `clear`, `snapshot`, `snapshot list`, `restore`.
All sync file operations, no new endpoints needed.

### Phase 3 — Backend Gaps + Team/Agent CLI

Backend additions (BE-A through BE-H) + CLI commands:

- `team start/status/resume/stop/delete/archive/list`
- `agent ask/list`
- `service stop` (via new shutdown endpoint)

### Phase 4 — Service Management

- `service stop/kill` with PID tracking or HTTP shutdown
- `service delete` with Docker compose wrapper

## 4. Consequences

### 4.1 Positive

- **Discoverable CLI**: 6 domain groups with consistent naming. `--help` at
  each level shows relevant commands.
- **Complete surface**: Every backend capability accessible via CLI. No more
  `python -m` incantations for probes or preps.
- **Maintainable**: One module per domain group. Adding a command means editing
  one file.
- **Testable**: Each CLI module can be tested with Click's `CliRunner`.

### 4.2 Negative

- **Breaking change**: All existing `vaultspec` command invocations change.
  Justfile, CI, docs, muscle memory all need updating.
- **More files**: 1 file → 8 files. Justified by the 6x increase in command
  count.
- **Backend coupling**: `team` and `agent` commands depend on a running backend.
  Offline usage limited to `test`, `run`, `database`, and `--show-config`.

### 4.3 Risks

- **`agent ask` complexity**: Single-agent execution via REST (creating a
  thread with solo-coder preset + streaming response) is more complex than a
  direct in-process path. Mitigated by reusing existing team machinery.
- **`service stop` reliability**: HTTP-based shutdown depends on the service
  being responsive. If it's hung, only `service kill` (SIGTERM) works.

## 5. Compliance Matrix

| ADR | Relationship | Status |
|-----|-------------|--------|
| ADR-009 (Module Hierarchy) | `cli/` package follows facade pattern with `__init__.py` exports | Compliant |
| ADR-015 (CLI Entry Point) | Entry point unchanged, extended with domain groups | Extends |
| ADR-016 (Task Runner) | Justfile recipes updated to match new CLI names | Compliant |
| ADR-029 (Migrations) | `database update` wraps existing Alembic integration | Compliant |

## 6. Open Questions

1. Should `vaultspec test benchmark` run both smoke and nightly by default, or
   require explicit suite argument? (Recommended: run both when bare.)
2. Should `agent ask` stream output to stdout, or print the final response?
   (Recommended: stream for interactive use.)
3. Should `service start` with no args launch both processes in the foreground
   (blocking), or background the worker? (Recommended: foreground both using
   the existing `auto_spawn_worker` mechanism.)

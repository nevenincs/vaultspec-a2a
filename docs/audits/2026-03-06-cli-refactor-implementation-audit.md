# CLI Refactor Implementation Audit — 2026-03-06

**Auditor:** codebase-researcher
**Scope:** `src/vaultspec_a2a/cli/` package (Phase 1 completed, Phase 2+ in progress)

---

## Cycle 0 — Pre-implementation Baseline

Phase 1 has already been completed: `cli.py` (236 lines) was converted to `cli/`
package (6 files, ~274 lines total). This baseline documents the current state
as the foundation for auditing Phases 2-5.

### Current CLI Package Structure

```
src/vaultspec_a2a/cli/
  __init__.py     34 lines  Root group, --show-config, subcommand registration
  _util.py        33 lines  _mask(), _show_config_callback()
  _service.py     54 lines  service start [backend|worker]
  _test.py        72 lines  test unit/smoke/benchmark
  _run.py         53 lines  run mock/probe
  _database.py    39 lines  database update
```

### Entry Point

```toml
# pyproject.toml:32-33
[project.scripts]
vaultspec = "vaultspec_a2a.cli:cli"
```

Resolves to `cli/__init__.py:cli` (the Click group). Entry point is valid.

### Click Dependency

```toml
# pyproject.toml:28
"click>=8.1",
```

### `__all__` Declarations

| File | `__all__` | Correct? |
|------|-----------|----------|
| `__init__.py` | `["cli", "main"]` | Yes |
| `_util.py` | `["_mask", "_show_config_callback"]` | Yes (exports private helpers for internal use) |
| `_service.py` | `["service"]` | Yes |
| `_test.py` | `["test"]` | Yes |
| `_run.py` | `["run"]` | Yes |
| `_database.py` | `["database"]` | Yes |

### Consumers of `cli` Module

| Consumer | Import Path | Type |
|----------|-------------|------|
| `pyproject.toml:33` | `vaultspec_a2a.cli:cli` | Entry point (sole external consumer) |

**No other module imports from `vaultspec_a2a.cli`.** The CLI is a leaf module
— it imports from `core`, `api`, `worker`, `providers`, but nothing imports from it.
This makes it safe to refactor without breaking internal dependencies.

### `__init__.py` Re-exports

`src/vaultspec_a2a/__init__.py` is empty (1 line). It does NOT re-export
anything from `cli`.

### Import Graph

#### cli/ outgoing imports (what cli imports)

| File | Import | When |
|------|--------|------|
| `__init__.py:7` | `from ._util import _show_config_callback` | Module load |
| `__init__.py:23-26` | `from ._{database,run,service,test} import ...` | Module load (noqa: E402) |
| `_util.py:28` | `from ..core.config import settings` | Lazy (inside callback) |
| `_service.py:32,34` | `import uvicorn`, `from ..core.config import settings` | Lazy (inside command) |
| `_database.py:16-18` | `from alembic.config import Config`, `from ..core.config import settings` | Lazy (inside `_alembic_cfg()`) |
| `_database.py:34` | `from alembic import command` | Lazy (inside `update` command) |
| `_test.py:29` | `sys.executable, "-m", "pytest"` | subprocess (no import) |
| `_run.py:21-28` | `sys.executable, "-m", "vaultspec_a2a.tests.preps.*"` | subprocess (no import) |
| `_run.py:48-50` | `sys.executable, "-m", "vaultspec_a2a.providers.probes.*"` | subprocess (no import) |

All heavy imports are lazy (inside function bodies). Only `click` is imported
at module level. This is correct — keeps CLI startup fast.

#### cli/ incoming imports (what imports cli)

**None.** CLI is a pure leaf module.

### Invariants the Refactor Must Not Break

| # | Invariant | Evidence | Risk |
|---|-----------|----------|------|
| 1 | `vaultspec_a2a.cli:cli` must resolve to a Click group | `pyproject.toml:33` | Entry point breaks if `cli` symbol moves |
| 2 | `main = cli` alias must exist | `__init__.py:33` | Unknown consumers may call `main()` directly |
| 3 | Lazy imports inside Click command functions | All 4 submodules | Import at module level would slow CLI startup and pull in heavy deps (uvicorn, alembic, settings) |
| 4 | `_REPO_ROOT` must resolve to repo root | `_database.py:11` — 4 parents from `cli/_database.py` | Adding depth (e.g., `cli/groups/_database.py`) would break Alembic path |
| 5 | `subprocess.run` without `shell=True` | `_test.py`, `_run.py` | Security — must never use `shell=True` |
| 6 | `click.echo` for output (not `print`) | `_util.py:31`, `_database.py:38`, `_run.py:45` | Click best practice — respects `--color`/piping |

### Issues Carried Forward from Prior Audit Cycles

These were identified in `docs/audits/2026-03-06-cli-module-audit.md` and
remain relevant for Phases 2-5:

| ID | Severity | Issue | Phase |
|----|----------|-------|-------|
| P1-001 | HIGH | `service start` (bare) only starts backend — `uvicorn.run()` blocks, worker never launches | Phase 4 |
| CM-003 | HIGH | `list_threads()` has no status filter — blocks `team list [status]` | Phase 3 |
| CM-004 | HIGH | `ThreadStatus` missing `ARCHIVED` — blocks `team archive` | Phase 3 |
| CM-005 | HIGH | No `delete_thread()` CRUD — blocks `team delete` | Phase 3 |
| CM-015 | HIGH | No `discover_agent_preset_ids()` — blocks `agent list` | Phase 3 |
| CI-001 | HIGH | CI runs live tests (no `-m "not live"`) | Separate fix |
| P1-003 | MED | `_REPO_ROOT` fragile parent-chain | All phases |
| CM-016 | MED | Stale `lib.providers` docstring | Cleanup |
| CM-017 | MED | Worker `main` may be dead code | Phase 4 |

### Command Tree (Current vs Target)

```
CURRENT (Phase 1 complete):
vaultspec --show-config
vaultspec test [unit|smoke|benchmark]
vaultspec run [mock|probe]
vaultspec service start [backend|worker]
vaultspec database update

TARGET (all phases complete):
vaultspec --show-config                                    [done]
vaultspec test [unit|smoke|benchmark]                      [done]
vaultspec run [mock|probe]                                 [done]
vaultspec service start [backend|worker]                   [done]
vaultspec service stop [backend|worker|DOCKER_SERVICE]     [Phase 4]
vaultspec service kill [backend|worker|DOCKER_SERVICE]     [Phase 4]
vaultspec service delete DOCKER_SERVICE                    [Phase 4]
vaultspec database update                                  [done]
vaultspec database clear --yes                             [Phase 2]
vaultspec database snapshot                                [Phase 2]
vaultspec database snapshot list                           [Phase 2]
vaultspec database restore --name SNAPSHOT                 [Phase 2]
vaultspec team start --preset NAME [--name NICKNAME]       [Phase 3]
vaultspec team status --id ID                              [Phase 3]
vaultspec team resume --id ID [--message TEXT]             [Phase 3]
vaultspec team stop --id ID                                [Phase 3]
vaultspec team delete --id ID                              [Phase 3]
vaultspec team archive --id ID                             [Phase 3]
vaultspec team list [running|completed|archived]           [Phase 3]
vaultspec agent ask --agent NAME --message TEXT            [Phase 3]
vaultspec agent list                                       [Phase 3]
```

---

## Cycle 1 — Phase 2 Implementation Audit (Database Utilities)

Phase 2 adds 4 commands to `_database.py`: `clear`, `snapshot`, `snapshots`, `restore`.
File grew from 39 to 140 lines. Docstring updated to reflect new commands.

### Command Implementation Review

#### `database clear --yes` (lines 51-64)

**Implementation:**
- Requires `--yes` flag (Click `is_flag=True, required=True`) -- correct
- Uses sync `create_engine` with URL replacing `+aiosqlite` with empty string
- Hardcodes table names: `["cost_tracking", "permission_logs", "artifacts", "threads"]`
- Uses `DELETE FROM` (not `TRUNCATE`) -- correct for SQLite (no TRUNCATE)
- FK dependency order: deletes children first (cost_tracking, permission_logs, artifacts) then parent (threads)

**Findings:**

| ID | Severity | Issue |
|----|----------|-------|
| P2-001 | HIGH | **SQL injection via string interpolation.** Line 63: `conn.execute(text(f"DELETE FROM {table}"))` uses f-string to build SQL. While `table` comes from a hardcoded list (not user input), this pattern sets a bad precedent. The `# noqa: S608` suppression acknowledges this. Since the table names are hardcoded constants on line 60, there is no actual injection risk, but the pattern should ideally use parameterized identifiers or at least a comment explaining why it's safe. |
| P2-002 | MED | **Hardcoded table list may drift from models.** If new tables are added (e.g., a future `events` table), this list won't include them. Should derive from `Base.metadata.sorted_tables` for automatic coverage. However, this would also delete LangGraph checkpoint tables which should be preserved. The hardcoded list is actually the right choice for now. |
| P2-003 | LOW | **`database_url.replace("+aiosqlite", "")` is fragile.** Line 59 strips the async driver to get a sync URL. If the URL uses a different async driver (e.g., `+aiosqlite` at different position, or future `+asyncpg`), this would fail silently. |

#### `database snapshot` (lines 67-89)

**Implementation:**
- Uses `sqlite3.backup()` -- correct per task #11 plan correction
- Creates snapshot at `db_path.with_suffix(f".snapshot.{ts}")`
- Timestamp format: `%Y%m%d-%H%M%S` (UTC)
- Properly closes both connections in `finally` block
- Guards against in-memory database via `_get_db_path()`

**Findings:**

| ID | Severity | Issue |
|----|----------|-------|
| P2-004 | MED | **Snapshot suffix creates non-standard extension.** `db_path.with_suffix(f".snapshot.{ts}")` replaces the original extension. E.g., `vaultspec.db` becomes `vaultspec.snapshot.20260306-190700` (loses `.db`). The `snapshots` command globs for `{stem}.snapshot.*` which matches, but the files won't be recognized as SQLite by file managers or tools. Consider `db_path.parent / f"{db_path.name}.snapshot.{ts}"` to preserve the original name. |
| P2-005 | LOW | **No WAL checkpoint before backup.** SQLite `backup()` copies the main database file but may not include WAL (Write-Ahead Log) data that hasn't been checkpointed. If the service is running with WAL mode (which it is per `session.py`), the snapshot may miss recent writes. Calling `src_conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")` before backup would ensure completeness. |

#### `database snapshots` (lines 92-104)

**Implementation:**
- Globs `{stem}.snapshot.*` in parent directory
- Sorts reverse chronological (newest first)
- Shows filename and size in KB
- Clean output format

**Findings:**

| ID | Severity | Issue |
|----|----------|-------|
| P2-006 | LOW | **Command name `snapshots` vs target design `snapshot list`.** The target CLI design says `vaultspec database snapshot list` (a subcommand of `snapshot`). Current implementation uses `snapshots` (a peer command). This is a naming deviation from the approved design in `docs/audits/2026-03-06-cli-architecture-audit.md:53`. |

#### `database restore --name SNAPSHOT` (lines 107-139)

**Implementation:**
- Checks if service is running via `httpx.get(f"{base}/health", timeout=2.0)`
- Uses `sqlite3.backup()` for restore (snapshot -> db_path)
- Properly closes connections in `finally` block
- Validates snapshot file exists

**Findings:**

| ID | Severity | Issue |
|----|----------|-------|
| P2-007 | HIGH | **Running service check only probes backend, not worker.** Line 117-123 checks `http://localhost:{settings.port}/health`. If backend is stopped but worker is still running on port 8001, the restore proceeds while the worker may have the database open. Should also check `http://localhost:{settings.worker_port}/internal/health`. |
| P2-008 | MED | **`httpx.ConnectError` catch is too narrow.** ~~Line 122 only catches `ConnectError`.~~ **PARTIALLY FIXED**: now catches `(httpx.ConnectError, httpx.ConnectTimeout)`. Still missing `httpx.TimeoutException` (read timeout) and `httpx.HTTPStatusError` (non-200). A slow service could still cause an unhandled exception. |
| P2-009 | MED | **Snapshot path traversal possible.** Line 126: `snapshot_path = db_path.parent / name`. If `name` contains `../`, it could resolve outside the database directory. Should validate that `snapshot_path.resolve().parent == db_path.parent.resolve()`. |
| P2-010 | LOW | **No confirmation prompt for destructive restore.** Unlike `clear` which requires `--yes`, `restore` overwrites the database without confirmation. A typo in `--name` could restore the wrong snapshot. |

#### `_get_db_path()` helper (lines 25-32)

**Implementation:**
- Lazy import of settings
- Guards against `:memory:` databases
- Returns resolved Path

**Clean. No issues.**

### Shared Pattern Review

| Pattern | Status | Notes |
|---------|--------|-------|
| Lazy imports | Correct | `settings`, `alembic`, `sqlite3`, `httpx` all imported inside functions |
| `click.echo` for output | Correct | All user-facing output uses `click.echo` |
| Error output to stderr | Correct | Error messages use `click.echo(..., err=True)` |
| `__all__` | Unchanged | `["database"]` still correct |
| `subprocess` avoidance | Correct | Database commands use direct Python APIs, not subprocess |

### Phase 2 Summary

| Severity | Count | Key Issues |
|----------|-------|------------|
| HIGH | 2 | SQL pattern precedent (P2-001), incomplete service check (P2-007) |
| MED | 4 | Hardcoded tables (P2-002), snapshot suffix (P2-004), error catch scope (P2-008), path traversal (P2-009) |
| LOW | 3 | Fragile URL rewrite (P2-003), WAL checkpoint (P2-005), naming deviation (P2-006), no restore confirmation (P2-010) |

### Recommended Fixes

1. **P2-007**: Add worker health check in `restore` command
2. **P2-009**: Add path traversal guard: `if not snapshot_path.resolve().parent == db_path.parent.resolve()`
3. **P2-008**: Catch `httpx.HTTPError` instead of just `ConnectError`
4. **P2-005**: Add `PRAGMA wal_checkpoint(TRUNCATE)` before `backup()`

---

## Orchestrator Triage Decisions

### Phase 3 Backlog (from prior audit cycles)

| ID | Severity | Triage Decision | Notes |
|----|----------|-----------------|-------|
| CM-003 | HIGH | Phase 3 | `list_threads()` status filter — planned in Phase 3 |
| CM-004 | HIGH | Phase 3 | `ThreadStatus.ARCHIVED` — planned in Phase 3 |
| CM-005 | HIGH | Phase 3 | `delete_thread()` — planned in Phase 3 |
| CM-015 | HIGH | Phase 3 | `discover_agent_preset_ids()` — orchestrator decision: coder will implement a simple glob directly in `_agent.py` CLI module. No need for separate function in `team_config.py` for MVP. |
| CM-001/002/018 | HIGH | Phase 3 | Facade violations in endpoints.py — merged into single finding. Fix when touching endpoints. |
| P1-001 | HIGH | Phase 4 | `service start` blocking — deferred to service management phase |

### Deferred (not blocking)

| ID | Severity | Decision | Notes |
|----|----------|----------|-------|
| CM-016 | MED | Defer | Stale `lib.providers` docstring — cosmetic |
| CM-017 | MED | Defer | Worker facade `main` — not CLI-related |
| CM-019 | LOW | Defer | `_ROLE_TO_PHASE` researcher — not CLI-related |
| CM-020 | LOW | Note | factory.py path pattern — noted, not blocking |
| CM-012 | LOW | Post-restructure | CLI tests — add after all phases complete |

### Design Decisions Recorded

- **`agent list`**: Simple glob in CLI module itself. No backend endpoint needed for MVP.
- **`agent ask`**: Use existing `/threads` endpoint with `vaultspec-solo-coder` preset. No new execution path needed.

### Phase 2 Post-Triage Verification

**P2-007 (worker port check): VERIFIED PRESENT**
- `_database.py:117`: `for check_port in (settings.port, settings.worker_port):` — checks both ports
- Both get `/health` with 2s timeout; if either responds, restore is refused

**P2-009 (path traversal guard): VERIFIED PRESENT**
- `_database.py:127`: `snapshot_path.resolve().is_relative_to(db_path.parent.resolve())`
- Resolves symlinks and `../` before containment check. Generic error message (no path leakage).

**Accepted findings (no fix needed):**
- P2-001 (f-string SQL): Tables are constants — noqa is appropriate
- P2-002 (hardcoded table list): Correct design — avoids deleting LangGraph tables
- P2-003 (URL replace): Sufficient for SQLite-only codebase
- P2-004 (snapshot suffix): Files are identifiable via glob pattern
- P2-005 (WAL checkpoint): `sqlite3.backup()` handles this internally
- P2-006 (snapshots naming): Already decided, plan's approach is correct
- P2-008 (exception scope): ConnectError + ConnectTimeout is correct; other errors mean service IS running

**Phase 2 audit status: CLEAN. No remaining issues.**

---

## Cycle 4 — Phase 3 Pre-audit (Backend Gaps)

Pre-audit of backend files that Phase 3 CLI commands (`_team.py`, `_agent.py`) will depend on.
Provides exact file:line targets for the coder.

### 1. Database Models (`database/models.py`)

**All `__tablename__` values:**

| Model | `__tablename__` | Line |
|-------|-----------------|------|
| `ThreadModel` | `threads` | 40 |
| `ArtifactModel` | `artifacts` | 74 |
| `PermissionLogModel` | `permission_logs` | 99 |
| `CostTrackingModel` | `cost_tracking` | 117 |

**Total application tables: 4.** No others exist.

**Cascade delete behavior:**

| Relationship | Cascade | Line |
|-------------|---------|------|
| `ThreadModel.artifacts` → `ArtifactModel` | `cascade="all, delete-orphan"` | 53-55 |
| `ThreadModel.permission_logs` → `PermissionLogModel` | `cascade="all, delete-orphan"` | 56-58 |
| `ThreadModel.cost_records` → `CostTrackingModel` | `cascade="all, delete-orphan"` | 59-61 |

All three child tables use `ForeignKey("threads.id")` and have `cascade="all, delete-orphan"`.
**Deleting a ThreadModel via ORM will cascade-delete all children automatically.**
This means a future `delete_thread()` CRUD function only needs `session.delete(thread)` + flush.

### 2. CRUD Layer (`database/crud.py`)

**`list_threads()` signature (lines 178-204):**
```python
async def list_threads(
    session: AsyncSession,
    *,
    offset: int = 0,
    limit: int = 50,
) -> tuple[Sequence[ThreadModel], int]:
```

**Gap: No `status` filter parameter.** The function queries all threads regardless of status.
Phase 3 `team list [running|completed|archived]` needs a `status: ThreadStatus | None = None`
parameter that adds `.where(ThreadModel.status == status.value)` when provided.

**`delete_thread()`: DOES NOT EXIST.**
No function in `crud.py` handles thread deletion. Grep across the entire codebase confirms
`delete_thread` is never defined. The test file (`database/tests/test_database.py:765`) tests
cascade deletion directly via `session.delete(thread)` — not via a CRUD function.
Phase 3 needs a new `delete_thread(session, thread_id) -> bool` function.

**`ThreadStatus` enum (lines 36-44):**
```python
class ThreadStatus(StrEnum):
    SUBMITTED = "submitted"
    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
```

**Gap: No `ARCHIVED` value.** Phase 3 `team archive` command needs `ARCHIVED = "archived"` added.

**`__all__` (lines 47-64):** Contains 15 exports. Phase 3 additions will need:
- `delete_thread` added to `__all__`
- No change needed for `list_threads` (signature change, not new function)

### 3. Database Facade (`database/__init__.py`)

**Current exports (39 items in `__all__`):**

CRUD functions exposed:
- `create_thread`, `get_thread`, `list_threads`, `update_thread_status`
- `update_thread_metadata`, `get_thread_metadata`
- `create_artifact`, `get_artifact`, `get_artifacts_by_thread`
- `append_permission_log`, `get_permission_logs_by_thread`
- `append_cost_record`, `sum_cost_by_thread`, `sum_cost_by_agent`
- `save_model`, `ThreadStatus`

Models exposed: `Base`, `ThreadModel`, `ArtifactModel`, `PermissionLogModel`, `CostTrackingModel`

Session/DB exposed: `init_db`, `close_db`, `get_db`, `get_engine`, `get_session_factory`, `verify_wal_mode`, `run_migrations`

**Gap:** When `delete_thread` is added to `crud.py`, it must also be added to:
1. `crud.py:__all__` (line 47)
2. `database/__init__.py` imports (add `from .crud import delete_thread as delete_thread`)
3. `database/__init__.py:__all__` (line 39)

### 4. API Endpoints (`api/endpoints.py`)

**All routes (complete inventory):**

| Method | Path | Line | Purpose |
|--------|------|------|---------|
| POST | `/threads` | 203 | Create thread |
| GET | `/threads` | 336 | List threads |
| GET | `/threads/{thread_id}/metadata` | 386 | Get thread metadata |
| GET | `/threads/{thread_id}/state` | 555 | Get thread state snapshot |
| POST | `/threads/{thread_id}/messages` | 647 | Send message to thread |
| GET | `/team/status` | 732 | Get team status |
| GET | `/teams` | 781 | Get team presets |
| POST | `/permissions/{request_id}/respond` | 815 | Respond to permission |
| POST | `/threads/{thread_id}/cancel` | 917 | Cancel thread |

**Gaps for Phase 3 CLI:**

| CLI Command | Needed Endpoint | Exists? |
|-------------|-----------------|---------|
| `team start` | `POST /threads` | Yes (existing) |
| `team status` | `GET /threads/{id}/state` | Yes (existing) |
| `team resume` | `POST /threads/{id}/messages` | Yes (existing) |
| `team stop` | `POST /threads/{id}/cancel` | Yes (existing) |
| `team list` | `GET /threads` | Yes, but no status filter query param |
| `team delete` | `DELETE /threads/{id}` | **NO — missing** |
| `team archive` | `PATCH /threads/{id}/status` or `POST /threads/{id}/archive` | **NO — missing** |
| `agent list` | N/A (glob, no backend) | N/A |
| `agent ask` | `POST /threads` (with solo-coder preset) | Yes (existing) |

**Summary: 2 new endpoints needed, 1 existing endpoint needs a query param.**

### Phase 3 Pre-audit Summary

| Gap | Severity | File:Line | Action Required |
|-----|----------|-----------|-----------------|
| No `status` filter on `list_threads()` | HIGH | `crud.py:178` | Add `status: ThreadStatus | None = None` param |
| No `ARCHIVED` in `ThreadStatus` | HIGH | `crud.py:36` | Add `ARCHIVED = "archived"` |
| No `delete_thread()` function | HIGH | `crud.py` (new) | Add function + facade exports |
| No `DELETE /threads/{id}` endpoint | HIGH | `endpoints.py` (new) | Add route |
| No archive/status-update endpoint | HIGH | `endpoints.py` (new) | Add `PATCH /threads/{id}/status` or similar |
| No `status` query param on `GET /threads` | MED | `endpoints.py:336` | Add optional query param, pass to `list_threads()` |

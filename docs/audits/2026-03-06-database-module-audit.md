# Database Module Audit — 2026-03-06

**Auditor:** codebase-researcher (automated)
**Scope:** `src/vaultspec_a2a/database/` — all 12 source files (models.py, crud.py, session.py, migrate.py, __init__.py, migrations/env.py, migrations/__init__.py, migrations/versions/0001_initial_schema.py, tests/)
**Baseline:** Last audited 2026-03-04 (ADR-029 Alembic Migration Sprint)

---

## Cycle 1 — Full Module Scan

### CRITICAL Findings

*None identified.* The database module is well-structured with proper async patterns, TOCTOU race handling, and WAL mode configuration.

---

### HIGH Findings

#### HIGH-01: Dual schema management — `init_db()` uses `create_all` + inline ALTER TABLE alongside Alembic

**File:** `session.py:187-198`

```python
async with engine.begin() as conn:
    await conn.run_sync(Base.metadata.create_all)
    try:
        await conn.execute(
            text("ALTER TABLE threads ADD COLUMN team_preset TEXT")
        )
    except OperationalError:
        pass
```

With Alembic migrations in place (ADR-029), `init_db()` should NOT use `Base.metadata.create_all` for production databases. The Alembic migration `0001_initial_schema.py` already creates all tables including `team_preset`. Running both `create_all` AND Alembic migrations means:
1. `create_all` creates tables that Alembic doesn't know about (Alembic thinks it still needs to run 0001)
2. The ALTER TABLE is redundant — 0001 already has `team_preset`
3. Future schema changes must be reflected in both Alembic migrations AND models.py + init_db() ALTER blocks

This was already tracked as task #12.

#### HIGH-02: `backfill_teamstate_sdd_fields` not exported from database facade

**File:** `migrations/__init__.py:26` (defined), `database/__init__.py` (not exported)

`api/app.py:45` deep-imports: `from ..database.migrations import backfill_teamstate_sdd_fields`. Per ADR-009 facade pattern, this should be re-exported from `database/__init__.py` so consumers import from the facade.

#### HIGH-03: `backfill_teamstate_sdd_fields` uses synchronous `sqlite3` directly

**File:** `migrations/__init__.py:42-80`

Uses `sqlite3.connect()` (blocking) to manipulate LangGraph checkpoint tables. Called from `api/app.py:241` inside the async lifespan. This blocks the event loop during startup. Should use `asyncio.to_thread()` wrapper like `migrate.py` does, or use `aiosqlite`.

---

### MEDIUM Findings

#### MED-01: `__init__.py:3` docstring references stale `lib.database` path

**File:** `database/__init__.py:3`

```
Facade re-exporting all public types from the ``lib.database`` subpackage.
```

Should be `vaultspec_a2a.database`.

#### MED-02: `models.py:9` docstring references stale `lib/database/` path

**File:** `models.py:9`

```
- ADR-009: Module hierarchy (``lib/database/``)
```

Should be `vaultspec_a2a/database/`.

#### MED-03: `crud.py:29-31` cross-module import comment references stale `lib/` paths

**File:** `crud.py:29-31`

```python
# NOTE (DB-M1): This cross-module import (lib/database -> lib/core) is intentional
```

Should say `vaultspec_a2a.database -> vaultspec_a2a.core`.

#### MED-04: `0001_initial_schema.py:5` docstring references stale `lib/database/models.py` path

**File:** `migrations/versions/0001_initial_schema.py:5`

```
``lib/database/models.py``.
```

Should be `vaultspec_a2a/database/models.py`.

#### MED-05: `migrations/__init__.py` `backfill_teamstate_sdd_fields` manipulates LangGraph checkpoint data directly

**File:** `migrations/__init__.py:50-76`

Directly manipulates LangGraph's `checkpoints` table `channel_values` JSON. This is fragile -- LangGraph's internal checkpoint format is not a stable API. If LangGraph changes the `channel_values` schema (e.g., moves to binary serialization or renames the column), this backfill will silently corrupt data or fail.

#### MED-06: `session.py:27` module-level `settings` import couples database to core config at import time

**File:** `session.py:27`

```python
from ..core.config import settings  # noqa: TID252
```

Module-level import means `import vaultspec_a2a.database.session` requires `core.config` to resolve settings (including env vars). Tests that want to use the session module must have a valid settings environment. The `settings` object is only used as a default fallback in `get_engine()` and `init_db()` -- both accept explicit `db_path` parameters. Could be deferred to inside those functions.

---

### LOW Findings

#### LOW-01: `migrate.py:25` -- `_ALEMBIC_INI` path resolution uses fragile parent chain

**File:** `migrate.py:25`

```python
_ALEMBIC_INI = Path(__file__).resolve().parent.parent.parent.parent / "alembic.ini"
```

Four `.parent` calls to reach the repo root. If `migrate.py` is moved to a different depth, this silently resolves to the wrong path. The `cli.py:13` uses a similar pattern but from a different depth.

#### LOW-02: `list_threads` does not support status filtering

**File:** `crud.py:178-204`

`list_threads` accepts only `offset` and `limit`. The CLI architecture audit (target CLI) calls for `team list [running | completed | archived]` which would need a `status` filter parameter.

#### LOW-03: No `ThreadStatus.ARCHIVED` enum value

**File:** `crud.py:36-44`

The `ThreadStatus` enum has 6 values: SUBMITTED, CREATED, RUNNING, COMPLETED, FAILED, CANCELLED. The CLI architecture audit calls for `team archive` which would need an ARCHIVED status. Noted for future CLI implementation sprint.

---

## Summary

| Severity | Count | Key Themes |
|----------|-------|------------|
| CRITICAL | 0     | -- |
| HIGH     | 3     | Dual schema management, facade gap, sync blocking |
| MEDIUM   | 6     | Stale path references (4), fragile checkpoint manipulation, import coupling |
| LOW      | 3     | Fragile path resolution, missing status filter/enum |

### Assessment

The database module is solid and well-documented. The CRUD functions are clean async with proper typing. WAL mode configuration is thorough with fallback warnings. The TOCTOU race handling for nickname uniqueness is correctly implemented with both pre-check SELECT and IntegrityError catch.

The main concern is **HIGH-01**: the dual schema management path where `init_db()` uses both `create_all` and inline ALTER TABLE alongside Alembic migrations. This was already identified as task #12.

### Recommended Fix Priority

1. **HIGH-01**: Remove `create_all` and ALTER TABLE from `init_db()` for production; keep only for test helper. (task #12)
2. **HIGH-02**: Export `backfill_teamstate_sdd_fields` from `database/__init__.py` facade.
3. **HIGH-03**: Wrap `backfill_teamstate_sdd_fields` call in `asyncio.to_thread()` in `api/app.py`.
4. **MED-01/02/03/04**: Batch update stale `lib.*` path references in docstrings.

---

## Cycle 2 — Deep Re-audit (2026-03-06)

Focus: Migration file integrity, model vs schema drift, CRUD correctness, thread lifecycle state machine, Alembic env.py health.

### Migration File Integrity

**0001_initial_schema.py** — VERIFIED CORRECT.
- All 4 tables match model definitions exactly (columns, types, nullability, indexes, foreign keys)
- Downgrade correctly drops in reverse FK-dependency order (cost_tracking, permission_logs, artifacts, threads)
- `render_as_batch=True` in env.py enables SQLite ALTER TABLE emulation
- `include_name` filter correctly excludes LangGraph `checkpoints`/`writes` tables
- `NullPool` used for async engine (aiosqlite v0.22+ compatibility)
- `disable_existing_loggers=False` in `fileConfig` (worker isolation fix from INFRA sprint)

**Stale path in migration docstring** (already MED-04): line 4 references `lib/database/models.py`.

### Model vs Schema Drift Check

**ZERO DRIFT.** All 4 models match their migration counterparts exactly:

| Table | Model Columns | Migration Columns | Status |
|-------|--------------|-------------------|--------|
| threads | 8 + 3 relationships | 8 + 1 index | MATCH |
| artifacts | 7 + 1 relationship | 7 + 1 FK + 1 index | MATCH |
| permission_logs | 7 + 1 relationship | 7 + 1 FK + 1 index | MATCH |
| cost_tracking | 9 + 1 relationship | 9 + 1 FK + 2 indexes | MATCH |

### CRUD Operations Correctness

All CRUD functions verified:
- `save_model`: Generic typed with PEP 695 syntax `[M: (...)]` — correct for Python 3.13
- `create_thread`: Proper TOCTOU handling (SELECT pre-check + IntegrityError catch)
- `_coerce_status`: Correctly rejects invalid status strings (DB-HIGH-02)
- `update_thread_status`: Explicitly sets `updated_at` to avoid stale in-memory values (DB-H2)
- `list_threads`: Uses `func.count()` separate from paginated query — correct for total count
- Cost aggregation: Uses `func.coalesce` for zero-safe sums — correct

### Alembic env.py Health

**HEALTHY.** Key characteristics:
- Absolute import `from vaultspec_a2a.database.models import Base` with `# noqa: TID252` — accepted exception (Alembic CLI loader)
- `disable_existing_loggers=False` — worker isolation fix applied
- `pool.NullPool` — prevents connection pool issues with aiosqlite async sessions
- `render_as_batch=True` — required for SQLite ALTER TABLE emulation
- `include_name` allowlist correctly scoped to `Base.metadata.tables`

### NEW CRITICAL Finding

#### CRIT-01: ThreadStatus.COMPLETED and ThreadStatus.FAILED are NEVER SET

**Files:** `crud.py:36-44` (enum), `api/endpoints.py` (only consumer)

Thread lifecycle state machine:

```
SUBMITTED → RUNNING → ??? (never transitions to COMPLETED or FAILED)
         → CANCELLED (via cancel endpoint)
```

Evidence:
- `create_thread()` at `endpoints.py:237`: sets `ThreadStatus.SUBMITTED`
- `send_message_endpoint()` at `endpoints.py:675`: sets `ThreadStatus.RUNNING`
- `cancel_thread_endpoint()` at `endpoints.py:955`: sets `ThreadStatus.CANCELLED`
- **NOWHERE** in the entire codebase is `ThreadStatus.COMPLETED` or `ThreadStatus.FAILED` ever written

The only references to COMPLETED/FAILED are:
1. Read-only guard in `cancel_thread_endpoint` (endpoints.py:928-929) — checks if thread is already terminal
2. MCP server instructions (server.py:104) — tells users to "poll until status is 'completed' or 'failed'"

**Impact:** Threads remain in RUNNING status forever after execution completes. MCP clients polling for completion will poll indefinitely. The `cancel_thread_endpoint` guard at line 927-931 will never match COMPLETED/FAILED because those statuses are never reached.

**Root cause:** The ADR-019 service separation moved graph execution to the worker process. The worker emits events (via internal relay) when execution completes, but no handler in the API process translates those events into `update_thread_status(COMPLETED)` or `update_thread_status(FAILED)` calls.

**Severity:** CRITICAL — the thread lifecycle state machine is fundamentally broken. No thread ever reaches a terminal success/failure state.

### NEW HIGH Findings

#### HIGH-04: `ThreadStatus.CREATED` is never used

**File:** `crud.py:40`

```python
CREATED = "created"
```

Searching for `ThreadStatus.CREATED` or `status.*created` yields zero results outside the enum definition. No code path ever sets or checks for this status. It's dead code in the enum.

#### HIGH-05: `backfill_teamstate_sdd_fields` still not exported from facade

**File:** `database/__init__.py`

Re-verified: `backfill_teamstate_sdd_fields` is imported directly at `api/app.py:45`:
```python
from ..database.migrations import backfill_teamstate_sdd_fields
```

Still a deep import violating the facade pattern. HIGH-02 from Cycle 1 remains OPEN.

### Cycle 2 Summary

| Finding | Severity | Status |
|---------|----------|--------|
| CRIT-01 (NEW) | CRITICAL | **NEW** — COMPLETED/FAILED never set, broken state machine |
| HIGH-01 | HIGH | OPEN — dual schema management (task #12) |
| HIGH-02 | HIGH | OPEN — backfill not in facade |
| HIGH-03 | HIGH | OPEN — sync sqlite3 in async lifespan |
| HIGH-04 (NEW) | HIGH | **NEW** — CREATED status never used |
| HIGH-05 (NEW) | HIGH | **NEW** — facade deep import confirmed |
| MED-01 through MED-06 | MEDIUM | OPEN (4 stale paths = task #19 scope) |
| LOW-01 through LOW-03 | LOW | OPEN |

**Updated totals: 1 CRIT, 5 HIGH, 6 MED, 3 LOW**

### Recommended Fix Priority (Updated)

1. **CRIT-01**: Wire thread completion/failure status updates. The internal relay (`api/internal.py`) or aggregator must detect graph execution completion events and call `update_thread_status(COMPLETED)` or `update_thread_status(FAILED)`. This likely requires a new event type from the worker (e.g., `execution_complete`) or detecting the final `updates` event in the aggregator.
2. **HIGH-01**: Remove `create_all` / ALTER TABLE from `init_db()` (task #12)
3. **HIGH-04**: Remove `CREATED` from ThreadStatus or document its intended use

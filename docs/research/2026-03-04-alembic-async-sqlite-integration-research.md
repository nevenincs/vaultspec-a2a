---
title: "ADR-029: Alembic + Async SQLAlchemy + SQLite — Technical Integration Research"
date: 2026-03-04
author: docs-researcher
relevance: 10
related:
  - docs/adrs/029-database-migration-framework.md
  - src/vaultspec_a2a/database/session.py
  - src/vaultspec_a2a/database/models.py
  - src/vaultspec_a2a/database/migrations/__init__.py
---

# ADR-029: Alembic + Async SQLAlchemy + SQLite — Technical Integration Research

## 1. Executive Summary

This document provides the technical grounding for implementing ADR-029
(Database Migration Framework). It covers four areas: (1) the canonical async
`env.py` pattern for Alembic + aiosqlite; (2) how to exclude LangGraph
checkpoint tables from autogenerate using `include_name`; (3) the
autogenerate / upgrade / downgrade workflow for SQLite; and (4) known
pitfalls with aiosqlite and Alembic batch mode.

The prior research doc (`2026-03-04-database-migration-research.md`)
established the *why*. This document establishes the *how*.

---

## 2. Current State Baseline

### 2.1 App-owned tables (tracked by `Base.metadata`)

From `src/vaultspec_a2a/database/models.py`:

| Table name       | Purpose                                        |
|------------------|------------------------------------------------|
| `threads`        | Top-level orchestration threads                |
| `artifacts`      | File artifacts produced by agent runs          |
| `permission_logs`| Audit log of permission grant/deny decisions   |
| `cost_tracking`  | Token usage and cost per LLM invocation        |

These four tables are all that Alembic should own. `Base.metadata` contains
exactly these four — confirmed by reading `src/vaultspec_a2a/database/models.py`.

### 2.2 LangGraph-owned tables (must be excluded)

From reading `langgraph-checkpoint-sqlite` source and `src/vaultspec_a2a/database/migrations/__init__.py`:

| Table name    | Owner                        | Created by         |
|---------------|------------------------------|--------------------|
| `checkpoints` | `langgraph-checkpoint-sqlite`| `AsyncSqliteSaver` |
| `writes`      | `langgraph-checkpoint-sqlite`| `AsyncSqliteSaver` |

Both are created with `CREATE TABLE IF NOT EXISTS` via `executescript()` in
`AsyncSqliteSaver.setup()`. They are structurally managed by LangGraph, not by
our ORM. Alembic must never touch them.

Note: the `backfill_teamstate_sdd_fields()` function in
`src/vaultspec_a2a/database/migrations/__init__.py` directly patches `checkpoints` rows via
raw `sqlite3` — this is an accepted one-off data migration, not a schema change.

### 2.3 Current schema fragility

`session.py:init_db()` uses `Base.metadata.create_all` (no-op on existing
tables) plus a raw `ALTER TABLE threads ADD COLUMN team_preset TEXT` wrapped in
`try/except OperationalError`. This is the anti-pattern ADR-029 replaces.

---

## 3. Canonical Async env.py Pattern

Alembic ships an `async` template since v1.12. Generate it with:

```bash
alembic init -t async migrations
```

The canonical `env.py` for `sqlite+aiosqlite` is:

```python
# migrations/env.py
import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# ── Alembic config object ─────────────────────────────────────────────────────
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ── Point to app metadata ─────────────────────────────────────────────────────
from lib.database.models import Base
target_metadata = Base.metadata

# ── LangGraph table exclusion (include_name) ──────────────────────────────────
_LANGGRAPH_TABLES = {"checkpoints", "writes"}

def include_name(name: str, type_: str, parent_names: dict) -> bool:
    """Exclude LangGraph checkpoint tables from autogenerate.

    include_name fires BEFORE reflection, which avoids the cost of fully
    reflecting the excluded tables.  include_object would fire after full
    reflection — more expensive for large tables.
    """
    if type_ == "table":
        return name not in _LANGGRAPH_TABLES
    return True


# ── Offline mode ──────────────────────────────────────────────────────────────
def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting to the DB."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_name=include_name,
        render_as_batch=True,   # required for SQLite ALTER TABLE emulation
    )
    with context.begin_transaction():
        context.run_migrations()


# ── Sync migration runner (called inside run_sync) ────────────────────────────
def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_name=include_name,
        render_as_batch=True,   # required for SQLite ALTER TABLE emulation
    )
    with context.begin_transaction():
        context.run_migrations()


# ── Async migration runner ────────────────────────────────────────────────────
async def run_async_migrations() -> None:
    """Create an async engine and bridge to sync Alembic context."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,   # IMPORTANT: NullPool for migrations
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """Entry point for online migrations."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

### 3.1 alembic.ini minimal config

```ini
[alembic]
script_location = src/vaultspec_a2a/database/migrations
sqlalchemy.url = sqlite+aiosqlite:///vaultspec.db

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console
qualname =

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
```

**Key point:** `sqlalchemy.url` uses `sqlite+aiosqlite:///`. At runtime the
actual path comes from `settings.database_url`; override via programmatic
config injection (see §5 on programmatic usage).

---

## 4. LangGraph Table Exclusion Strategy

### 4.1 Why `include_name` over `include_object`

Two hooks are available:

| Hook             | Fires                        | Cost                          |
|------------------|------------------------------|-------------------------------|
| `include_name`   | Before reflection (by name)  | Low — no reflection overhead  |
| `include_object` | After full reflection        | Higher — table is reflected first |

For excluding tables we know by name, `include_name` is strictly better. The
Alembic docs confirm: "when it reports on objects in the database, it will have
fully reflected that object, which can be expensive if a large number of objects
will be omitted."

### 4.2 Known LangGraph table names

```python
_LANGGRAPH_TABLES = {"checkpoints", "writes"}
```

Source: `langgraph-checkpoint-sqlite` `AsyncSqliteSaver.setup()` creates
`checkpoints` and `writes` tables via `CREATE TABLE IF NOT EXISTS`.

### 4.3 Guarding against future LangGraph table additions

LangGraph may add tables in future versions. The safest long-term approach is
exclusion-by-metadata: only include tables that are in `Base.metadata`:

```python
def include_name(name: str, type_: str, parent_names: dict) -> bool:
    if type_ == "table":
        return name in target_metadata.tables
    return True
```

This is the most robust form — it automatically scopes Alembic to *exactly*
the tables our ORM declares, regardless of what else is in the database file.

---

## 5. Migration Workflow

### 5.1 Initial baseline migration

After Alembic is wired up, generate a baseline from the current live schema:

```bash
# Stamp the current DB as being at the baseline (skip applying initial migration)
uv run alembic revision --autogenerate -m "initial_schema"
# Review the generated file — verify it only covers threads/artifacts/permission_logs/cost_tracking
uv run alembic upgrade head
```

For an already-deployed database, use `alembic stamp head` to record that
the schema is already current without running the initial migration DDL:

```bash
uv run alembic stamp head
```

### 5.2 Adding a column (typical workflow)

1. Add the column to the model in `src/vaultspec_a2a/database/models.py`
2. Generate migration: `uv run alembic revision --autogenerate -m "add_foo_to_threads"`
3. Review `src/vaultspec_a2a/database/migrations/versions/<hash>_add_foo_to_threads.py`
4. Apply: `uv run alembic upgrade head`
5. Rollback if needed: `uv run alembic downgrade -1`

### 5.3 Programmatic upgrade on app startup

To run migrations automatically at startup (replacing `init_db`'s
`create_all`), inject the runtime DB path into Alembic config:

```python
from alembic import command
from alembic.config import Config

async def run_migrations(db_path: str) -> None:
    """Apply any pending Alembic migrations at startup."""
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_path}")
    # run_migrations_online uses asyncio.run() internally — call from sync context
    await asyncio.to_thread(command.upgrade, cfg, "head")
```

**Important:** `alembic.command.upgrade` is synchronous. Use
`asyncio.to_thread` to avoid blocking the event loop.

Alternatively, the CLI-only approach (CI/CD or Docker entrypoint):

```bash
uv run alembic upgrade head && uv run python -m lib.api
```

This is the simpler and more explicit option. The programmatic approach is
preferred for development convenience; the CLI approach is preferred for
production deployments where schema changes should be explicit and auditable.

### 5.4 Downgrade

```bash
uv run alembic downgrade -1        # one step back
uv run alembic downgrade base      # all the way back to empty
uv run alembic history             # view migration history
uv run alembic current             # view current revision
```

---

## 6. Known Pitfalls: aiosqlite + Alembic

### 6.1 NullPool is mandatory

Alembic migrations must use `pool.NullPool`. Connection pools hold connections
open between uses; when Alembic disposes the engine after migration, an open
pooled connection will attempt to `ALTER TABLE` while another connection is
still active, which SQLite rejects.

```python
connectable = async_engine_from_config(
    config.get_section(config.config_ini_section, {}),
    prefix="sqlalchemy.",
    poolclass=pool.NullPool,   # ← mandatory
)
```

### 6.2 `render_as_batch=True` is mandatory for SQLite

SQLite does not support `ALTER TABLE ... ADD CONSTRAINT`, `DROP COLUMN`
(< SQLite 3.35), or any constraint modification. Alembic's batch mode
works around this by: (1) creating a new temp table with the desired schema,
(2) copying data, (3) dropping the old table, (4) renaming the temp table.

Set globally in `context.configure()`:

```python
context.configure(
    connection=connection,
    target_metadata=target_metadata,
    render_as_batch=True,
)
```

**Batch mode pitfalls with SQLite:**
- **Foreign keys**: disable `PRAGMA foreign_keys` before running batch
  migrations that touch referenced tables, then re-enable after. Batch mode
  drops and recreates the table; if another table has a FK referencing it,
  the drop will fail with FK enforcement enabled.
- **Views**: if a view references the table being altered, SQLite < 3.35 will
  raise an error during the rename step. We have no views currently, but this
  is a risk to track.
- **`sqlite_autoincrement`**: tables with `sqlite_autoincrement=True` lose that
  setting after batch operations because the temp table is created without
  it. None of our current models use this — `mapped_column(primary_key=True)`
  on a string PK (UUID) does not trigger autoincrement.
- **WAL mode and batch**: batch mode creates a temp table and drops the
  original within a transaction. WAL mode handles this correctly; no special
  handling needed.

### 6.3 aiosqlite connection closure bug (v0.22.0+)

SQLAlchemy issue #13039: the `aiosqlite` dialect never calls/awaits the
underlying connection's `.close()` method. With `aiosqlite>=0.22.0`, the
connection class is no longer a thread, and this results in the program hanging
while waiting for the connection to close.

**Mitigation:** Use `NullPool` (connections are closed immediately after use,
not returned to a pool). This sidesteps the pooled-connection closure issue
entirely. Alembic already requires NullPool (see §6.1), so this is free.

For the app's main engine (which uses the default pool), monitor for upgrades
to `aiosqlite` past 0.21.x in `pyproject.toml` — the hanging bug may affect
long-running connections in the async session factory.

### 6.4 Table reflection does not work with `aiosqlite`

Calling `Table("...", metadata, autoload_with=async_engine)` fails when the
engine uses `aiosqlite`. Alembic's autogenerate uses internal sync reflection
via `run_sync`, which works correctly. This is only a concern if any app code
tries to dynamically reflect tables — avoid this pattern.

### 6.5 Alembic `--autogenerate` does not detect all changes

Alembic autogenerate for SQLite detects: added tables, dropped tables, added
columns, dropped columns (SQLite 3.35+). It does NOT detect: column type
changes (SQLite is weakly typed), constraint additions/removals on existing
tables, index changes in some edge cases.

Always manually review generated migrations before applying.

---

## 7. Migration Directory Structure

Recommended layout under `src/vaultspec_a2a/database/`:

```
src/vaultspec_a2a/database/
├── __init__.py
├── models.py           # SQLAlchemy ORM models (Base.metadata)
├── session.py          # Engine / session factory
├── migrations/
│   ├── __init__.py     # backfill_teamstate_sdd_fields (existing — keep)
│   ├── env.py          # NEW — Alembic async env.py
│   ├── script.py.mako  # NEW — Alembic migration template
│   └── versions/       # NEW — generated migration files
│       └── 0001_initial_schema.py
alembic.ini             # NEW — at repo root (or src/vaultspec_a2a/database/alembic.ini)
```

**Note:** `alembic.ini` can live at the repo root (conventional) or inside
`src/vaultspec_a2a/database/`. If placed inside `src/vaultspec_a2a/database/`, the `script_location`
is `migrations` (relative). If at repo root, use `src/vaultspec_a2a/database/migrations`.

---

## 8. `init_db` Refactor Plan

Current `init_db()` in `session.py` must be simplified once Alembic is wired:

**Before (current):**
```python
async def init_db(db_path, *, echo=False):
    engine = get_engine(db_path, echo=echo)
    get_session_factory(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)        # ← remove
        try:
            await conn.execute(text("ALTER TABLE threads ADD COLUMN team_preset TEXT"))
        except OperationalError:
            pass                                              # ← remove
    return engine
```

**After (post-ADR-029):**
```python
async def init_db(db_path, *, echo=False):
    engine = get_engine(db_path, echo=echo)
    get_session_factory(engine)
    # Schema managed by Alembic: run `alembic upgrade head` before starting app
    return engine
```

The `init_db` function retains the engine/session-factory wiring but drops all
DDL. Schema is entirely owned by Alembic.

---

## 9. Open Questions for ADR-029

1. **Startup behaviour**: Should the app call `alembic upgrade head`
   programmatically on startup (development convenience), or require an
   explicit pre-start command (production discipline)? Recommendation: explicit
   CLI for production; programmatic for dev (controlled by a `settings.auto_migrate`
   flag).

2. **Test database isolation**: Tests currently use `:memory:` databases or
   temp-file databases. Alembic migrations must also run against these. The
   standard pattern is to call `Base.metadata.create_all(conn)` in test
   fixtures (skipping Alembic) since test DBs are ephemeral. This is an
   accepted exception — tests do not test migrations themselves.

3. **`backfill_teamstate_sdd_fields`**: This existing function (`migrations/__init__.py`)
   directly patches LangGraph `checkpoints` rows via raw `sqlite3`. It is a
   data migration, not a schema migration. It should remain as-is — it is not
   in scope for Alembic, which manages schema only.

4. **Alembic version**: Use `alembic>=1.13.0` (introduced `async_engine_from_config`
   in the core API; async template stabilised). Current latest stable is 1.18.x.

---

## 10. Sources

- [Alembic Async Template env.py](https://github.com/sqlalchemy/alembic/blob/main/alembic/templates/async/env.py)
- [Alembic Cookbook — Async Migrations](https://alembic.sqlalchemy.org/en/latest/cookbook.html)
- [Alembic Autogenerate — include_name / include_object](https://alembic.sqlalchemy.org/en/latest/autogenerate.html)
- [Alembic Batch Migrations for SQLite](https://alembic.sqlalchemy.org/en/latest/batch.html)
- [SQLAlchemy Async I/O (aiosqlite)](https://docs.sqlalchemy.org/en/21/orm/extensions/asyncio.html)
- [SQLAlchemy aiosqlite connection closure bug #13039](https://github.com/sqlalchemy/sqlalchemy/issues/13039)
- [langgraph-checkpoint-sqlite source](https://github.com/langchain-ai/langgraph/blob/main/libs/checkpoint-sqlite/langgraph/checkpoint/sqlite/__init__.py)
- [Prior research: Database Schema Fragility](./2026-03-04-database-migration-research.md)

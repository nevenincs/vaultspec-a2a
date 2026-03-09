# 2026-03-09 Postgres Persistence Grounding

## Slice

Phase 1: persistence posture flip from SQLite-shaped runtime wiring to a
backend-selectable runtime with Postgres as the default and SQLite as an
explicit fallback.

## Current local implementation

- The app DB engine in `src/vaultspec_a2a/database/session.py` is hard-coded to
  `sqlite+aiosqlite`.
- The gateway and worker lifespans in
  `src/vaultspec_a2a/api/app.py` and
  `src/vaultspec_a2a/worker/app.py` open
  `AsyncSqliteSaver` directly from a SQLite file path.
- `settings.database_path` is treated as the canonical runtime persistence
  primitive, which makes Postgres impossible without broad call-site changes.
- Startup checkpoint backfill is currently a SQLite file mutation path in
  `src/vaultspec_a2a/database/migrations/__init__.py`.
- The live subprocess harness in `src/vaultspec_a2a/tests/conftest.py` still
  provisions a temporary SQLite database.

## Libraries and components grounded

- SQLAlchemy async engine/session configuration
- Alembic async migration environment
- LangGraph checkpoint persistence
- Gateway and worker lifespan startup wiring

## Context7 findings

### SQLAlchemy

Library: `/websites/sqlalchemy_en_20`

Confirmed:

- `create_async_engine("postgresql+asyncpg://...")` is the standard async
  Postgres engine path.
- `create_async_engine("sqlite+aiosqlite:///...")` remains the SQLite path.
- Connection events must be attached to `engine.sync_engine`.
- Backend-specific initialization at the engine factory boundary is the normal
  pattern.
- For a unified cross-backend schema, SQLAlchemy recommends either:
  - a database-native timezone-aware timestamp type such as
    `TIMESTAMP(timezone=True)` where supported, or
  - a `TypeDecorator` that stores timezone-aware UTC datetimes as naive UTC and
    restores UTC on read.
- When the physical column remains timezone-naive, sending timezone-aware
  `datetime` values directly to Postgres drivers such as `asyncpg` is not safe.

Rejected hypothesis:

- Keeping SQLite-only engine construction and swapping just the URL later.
  This would leave SQLite-specific PRAGMAs and path assumptions spread through
  runtime startup.
- Leaving the existing timezone-aware `datetime.now(UTC)` defaults untouched
  while keeping `DateTime()` / `TIMESTAMP WITHOUT TIME ZONE` columns.
  That shape is tolerated in SQLite but fails on the Postgres path.

### LangGraph

Library: `/websites/langchain_oss_python_langgraph`

Confirmed:

- Production persistence is expected to use database-backed checkpointers.
- Async Postgres checkpointing uses
  `langgraph.checkpoint.postgres.aio.AsyncPostgresSaver`.
- Recommended usage is:

  - `async with AsyncPostgresSaver.from_conn_string(DB_URI) as checkpointer`
  - `await checkpointer.setup()`

- The Postgres saver examples use a plain `postgresql://...` connection string,
  not a SQLAlchemy async dialect URL.

Rejected hypothesis:

- Reusing the SQLAlchemy async URL unchanged for the LangGraph Postgres
  checkpointer. The checkpointer should own its own normalized DSN.

## Official-source fallback research

Not needed for this slice. Context7 coverage was sufficient for the factory
boundary and connection-string decisions.

## Supported constraints

- The app-owned schema remains unified under Alembic.
- Backend abstraction belongs at the engine/checkpointer factory boundary, not
  in divergent ORM models.
- Timestamp semantics must remain UTC-aware at the Python boundary even if the
  storage representation is normalized for backend portability.
- SQLite-specific PRAGMAs and file-path helpers must be gated behind an explicit
  SQLite backend check.
- The checkpoint backfill helper is SQLite-only and must not run for Postgres.

## Chosen implementation direction

- Add explicit `database_backend` and `checkpoint_backend` settings.
- Keep one Alembic-managed app schema.
- Normalize connection handling in config:

  - SQLAlchemy app DB keeps backend-specific SQLAlchemy URLs.
  - LangGraph checkpointer gets a backend-specific connection string derived
    from config.

- Introduce a runtime checkpointer factory module used by both gateway and
  worker lifespans.
- Update session initialization to support both SQLite and Postgres without
  changing call sites outside the persistence boundary.
- Normalize ORM timestamp fields through a shared UTC `TypeDecorator` so the
  codebase keeps timezone-aware UTC values while persisting portable naive UTC
  values underneath.
- Treat SQLite-only operational helpers as explicitly unsupported for Postgres
  rather than silently pretending they work.

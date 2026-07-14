---
tags:
- '#adr'
- '#postgres-dual-backend'
date: 2026-03-10
modified: '2026-03-10'
related:
- '[[2026-03-31-database-migration-framework-adr]]'
- '[[2026-03-04-worker-process-architecture-adr]]'
- '[[2026-03-31-docs-vault-migration-research]]'
---

# `postgres-dual-backend` adr: `adr-29` | (**status:** `accepted`)

## Migration Note

This ADR was migrated from the legacy pre-pipeline documentation tree during the issue #19 cleanup so that the repository no longer depends on the removed `docs/` directory.

- Original ADR number: `ADR-29`
- Original title: `Dual-Backend Database — SQLite (dev) + PostgreSQL (production)`
- Legacy status at migration time: `Accepted`

## Original ADR

## ADR-035: Dual-Backend Database — SQLite (dev) + PostgreSQL (production)

**Date:** 2026-03-10
**Status:** Accepted

## 1. Context & Problem Statement

ADR-007 §3.3 explicitly deferred PostgreSQL for v1, opting for SQLite with
`aiosqlite` and `langgraph-checkpoint-sqlite`. That decision was appropriate for
a single-process prototype, but the system has grown to require:

- **Multi-process durability**: The worker (ADR-031) runs as a separate process.
  SQLite WAL mode handles concurrent readers well, but write contention between
  the gateway and worker under load produces `SQLITE_BUSY` errors.
- **Production scalability**: Horizontal scaling, replicated deployments, and
  Docker-compose environments with named volumes cannot rely on a shared
  SQLite file path.
- **LangGraph alignment**: The LangGraph documentation explicitly recommends
  `AsyncPostgresSaver` for production persistence.
- **Checkpoint and app DB independence**: The checkpoint backend (LangGraph) and
  the app-owned schema (Alembic) can now point to separate databases, enabling
  advanced deployment topologies (e.g., separate checkpoint DB for Postgres
  durability without migrating the app schema).

The previous decision is superseded. This ADR records the new dual-backend
architecture and its constraints.

## 2. Decision

Introduce explicit `database_backend` and `checkpoint_backend` configuration
fields, default both to `"postgres"` for production readiness, and maintain
SQLite as a first-class development and test fallback.

The backend abstraction lives entirely at the engine/checkpointer factory
boundary (`database/session.py`, `database/checkpoints.py`). ORM models,
CRUD operations, and application logic are backend-agnostic.

## 3. Key Components

### 3.1 Config (`core/config.py`)

Two new fields:

```python
database_backend: Literal["sqlite", "postgres"] = Field(default="postgres")
checkpoint_backend: Literal["sqlite", "postgres"] = Field(default="postgres")
```text

Validation properties (`resolved_database_backend`, `resolved_checkpoint_backend`)
fail fast when the declared backend contradicts the configured URL — preventing
silent misconfiguration at startup.

`validate_postgres_requirement()` enforces that both backends are Postgres when
`VAULTSPEC_POSTGRES_REQUIRED=true`.

SQLite-specific derived properties (`database_path`, `checkpoint_path`) raise
`ValueError` when called on a non-SQLite backend.

`checkpoint_connection_string` strips SQLAlchemy dialect prefixes to produce the
plain DSN expected by `AsyncPostgresSaver` / `AsyncSqliteSaver`.

### 3.2 Engine factory (`database/session.py`)

`get_engine()` is backend-aware at the construction site:

- **SQLite**: attaches `_set_wal_mode` listener, sets WAL + busy_timeout +
  foreign_keys PRAGMAs on every new connection.
- **Postgres**: sets `pool_pre_ping=True` for pessimistic disconnect handling.

All call sites outside the factory boundary are unchanged.

### 3.3 Checkpointer factory (`database/checkpoints.py`)

`open_checkpointer()` is an `@asynccontextmanager` that yields either:

- `AsyncSqliteSaver` (from `langgraph-checkpoint-sqlite`) for SQLite backend.
- `AsyncPostgresSaver` (from `langgraph-checkpoint-postgres`) for Postgres
  backend.

#### Windows selector-thread bridge

`AsyncPostgresSaver` uses `psycopg`'s async API, which requires a
`SelectorEventLoop`. On Windows the default event loop policy is
`ProactorEventLoop` (required for subprocess support used by the ACP provider
layer). Running psycopg on the main Proactor loop causes `RuntimeError`.

Resolution: `_SelectorThreadPostgresCheckpointer` wraps `AsyncPostgresSaver` by
running it on a dedicated daemon thread with its own `SelectorEventLoop`. All
checkpointer methods are proxied via `asyncio.run_coroutine_threadsafe`, making
the wrapper a drop-in `BaseCheckpointSaver` implementation to the rest of the
runtime.

Key design constraints for this bridge:

- `_loop_ready.wait()` must be awaited with `asyncio.to_thread()` to avoid
  blocking the Proactor loop while the selector thread initialises.
- `close()` uses try/except/finally — exceptions from the inner
  `AsyncPostgresSaver.__aexit__` are logged as warnings but do **not** prevent
  the selector loop from stopping.
- `_collect_alist` materialises the `AsyncIterator` on the selector thread
  before returning to the Proactor thread, since async generators cannot be
  iterated across loop boundaries.

### 3.4 Alembic migration environment (`database/migrations/env.py`)

`render_as_batch` is dialect-conditional:

```python
render_as_batch=connection.dialect.name == "sqlite",
```text

`render_as_batch=True` on PostgreSQL would recreate FK-linked tables for every
column change, causing data loss in production migrations. SQLite still requires
batch mode for DDL operations.

### 3.5 Docker compose

All compose files (`docker-compose.prod.yml`, `docker-compose.dev.yml`,
`docker-compose.integration.yml`) carry explicit `VAULTSPEC_DATABASE_BACKEND`
and `VAULTSPEC_CHECKPOINT_BACKEND` environment variables so deployments do not
silently inherit the `"postgres"` default when running against a SQLite volume.

## 4. Consequences

### 4.1 Positive

- SQLite remains the local development and test default — no Docker Postgres
  dependency for day-to-day development.
- Postgres is opt-in via two environment variables; existing SQLite-based
  deployments are unaffected.
- The factory boundary is a single, auditable abstraction point. There are no
  backend-specific branches in application logic or ORM models.
- `validate_postgres_requirement()` + `resolved_database_backend` property
  provide loud startup failures for misconfigured deployments.
- Windows development is fully supported via the selector-thread bridge without
  constraining the main runtime to the wrong event loop policy.

### 4.2 Negative / Trade-offs

- `_SelectorThreadPostgresCheckpointer` adds operational complexity on Windows
  — it is a bridge between two event loops and its correctness depends on
  careful lifecycle management.
- `pool_size` and `max_overflow` for the Postgres SQLAlchemy engine are not yet
  configurable via environment variables (tracked as MED-01 in the companion
  audit).
- There is no production `docker-compose.prod.yml` Postgres service template yet
  — operators who opt in to Postgres must provide their own Postgres deployment
  (tracked as MED-03).
- `with_allowlist()` on `_SelectorThreadPostgresCheckpointer` returns the raw
  inner `AsyncPostgresSaver` result, bypassing the selector-thread bridge
  (tracked as HIGH-02 in the companion audit).

### 4.3 Supersession

This ADR supersedes:

- ADR-007 §3.3 — "Rejected: PostgreSQL for v1"
- ADR-007 §4.1 — SQLite as the sole persistence backend

ADR-007 §§ 1–2 and all non-persistence sections remain in force.

## 5. Alternatives Considered

### 5.1 Keep SQLite for everything

Rejected. WAL concurrency limits hit under worker+gateway write contention. No
path to horizontal scaling without architectural rework.

### 5.2 Hard-switch to Postgres only

Rejected. Breaks local development workflows and CI environments without
Docker. SQLite-only tests are faster and have zero external dependencies.

### 5.3 Single URL, swap dialect prefix

Rejected (see research doc §2.1). Leaves SQLite-specific PRAGMAs, file-path
helpers, and `render_as_batch` logic scattered through the codebase without a
clear abstraction point.

### 5.4 Use asyncpg directly (no psycopg)

Rejected for the checkpointer. `AsyncPostgresSaver` officially targets psycopg3.
The SQLAlchemy engine uses `asyncpg` for app-owned queries — the two backends
coexist at different abstraction levels.

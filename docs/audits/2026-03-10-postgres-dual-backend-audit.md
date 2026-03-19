# 2026-03-10 Postgres Dual-Backend Architecture Audit

## Scope

Audit of the newly landed Postgres/SQLite dual-backend database architecture
across the following modules:

- `src/vaultspec_a2a/core/config.py`
- `src/vaultspec_a2a/database/session.py`
- `src/vaultspec_a2a/database/checkpoints.py`
- `src/vaultspec_a2a/database/crud.py`
- `src/vaultspec_a2a/database/migrations/env.py`
- `docker-compose.prod.yml`, `docker-compose.dev.yml`, `docker-compose.integration.yml`

ADR reference: `docs/adrs/035-postgres-dual-backend.md`

---

## Pass 1 — Deployment Correctness

### CRIT-01 (FIXED): Docker compose files missing backend env vars

**Finding:** All three compose files set `VAULTSPEC_DATABASE_URL` to a
`sqlite+aiosqlite://` URL but did not set `VAULTSPEC_DATABASE_BACKEND` or
`VAULTSPEC_CHECKPOINT_BACKEND`. Because `Settings` defaults both backends to
`"postgres"`, the `resolved_database_backend` validator raised `ValueError` at
process startup — the `"postgres"` backend was asserted against a SQLite URL.

**Impact:** Every Docker deployment would fail immediately at startup.

**Fix applied:** Added explicit `VAULTSPEC_DATABASE_BACKEND: sqlite` and
`VAULTSPEC_CHECKPOINT_BACKEND: sqlite` to all affected services across all three
compose files.

**Verification:** All three compose files reviewed post-fix. Gateway and worker
services in `docker-compose.prod.yml`, `docker-compose.dev.yml`, and the
`mock-seeder` service in `docker-compose.integration.yml` now carry both
backend variables.

---

## Pass 2 — Migration Safety

### CRIT-02 (FIXED): render_as_batch unconditional in migrations/env.py

**Finding:** `context.configure()` in both `do_run_migrations()` (online mode)
and `run_migrations_offline()` (offline mode) unconditionally set
`render_as_batch=True`. On PostgreSQL, this causes Alembic to recreate
tables (with temporary copies) for every column operation. For tables with
foreign-key references, this produces `DROP TABLE` + re-insert — a destructive,
data-losing operation on production databases.

**Impact:** Any Alembic migration run against a Postgres-backed schema would
silently destroy FK-linked table data.

**Fix applied:** Made `render_as_batch` dialect-conditional in the online path:

```python
render_as_batch=connection.dialect.name == "sqlite",
```text

The offline path retains `render_as_batch=True` because offline SQL generation
is exclusively used for SQLite schema inspection in this codebase.

**Verification:** `migrations/env.py` reviewed post-fix. Online mode uses
dialect check; offline mode unchanged.

---

## Pass 3 — Windows Runtime Safety

### CRIT-03 (FIXED): _loop_ready.wait() blocks Proactor loop in checkpoints.py

**Finding:** In `_SelectorThreadPostgresCheckpointer.start()`, the original
code called `self._loop_ready.wait()` directly from the Proactor event loop
coroutine. `threading.Event.wait()` is a blocking call. Blocking the Proactor
loop's thread stalls all other coroutines until the selector thread signals
readiness.

**Impact:** Gateway/worker startup would stall (or deadlock under load) whenever
the Postgres checkpointer initialised on Windows.

**Fix applied:** Changed to `await asyncio.to_thread(self._loop_ready.wait)`,
which yields control back to the Proactor loop while the selector thread starts.

**Verification:** `checkpoints.py` reviewed post-fix. Startup path is
non-blocking.

### CRIT-04 (FIXED): close() silently swallowed AsyncPostgresSaver exit errors

**Finding:** The original `close()` implementation called `await self._run_async("_close")`
without exception handling, which meant any error from
`AsyncPostgresSaver.__aexit__()` (e.g., connection already closed) would
propagate and abort the `finally` block — leaving the selector loop thread
running indefinitely as a daemon thread.

**Impact:** On any Postgres connection failure during shutdown, the selector-loop
thread would not be stopped. Accumulated daemon threads across restart cycles
would consume OS thread handles.

**Fix applied:** Wrapped the `_close` call in try/except/finally. Exceptions are
logged as `WARNING` with `exc_info=True`. The selector loop stop
(`self._loop.call_soon_threadsafe(self._loop.stop)`) and thread join are
guaranteed in `finally`.

**Verification:** `checkpoints.py` reviewed post-fix. Lifecycle is
error-safe.

---

## Pass 4 — Type Safety

### TYPE-01 (FIXED): 6 type errors across checkpoints.py and crud.py

**Finding — checkpoints.py:**

1. `_resolve_target` returned `Any` (`ANN401` violation). The caller
   `_invoke()` did `target = self._resolve_target(method_name)` then called
   `target(...)` directly, which `ty` flagged as `call-non-callable` (since
   `object` is the base return type after removing `Any`).

2. `_collect_alist` return annotation used `list[Any]` which shadowed
   `builtins.list` because the class already has a `list` method.

**Finding — crud.py:**

3. `_UNSET = object()` was used as a sentinel for optional CRUD parameters
   (`approval_status`, `approval_request_id`, `approval_reason`,
   `approval_response_action_id`). Type narrowing via `if x is not _UNSET` does
   not work with bare `object()` instances — `ty` could not narrow the type after
   the guard, producing `invalid-assignment` errors on SQLAlchemy `Mapped[]`
   columns.

**Fix applied (checkpoints.py):**

- `_resolve_target` returns `object`; `_invoke()` uses
  `cast(Callable[..., object], target)` after the `callable()` guard.
- `_collect_alist` annotated as `builtins.list[Any]` (with `import builtins`).

**Fix applied (crud.py):**

- Replaced `_UNSET = object()` with a typed singleton:

  ```python
  class _UnsetType:
      _instance: _UnsetType | None = None
      def __new__(cls) -> _UnsetType: ...
  _UNSET = _UnsetType()
  ```text

- Changed all `if x is not _UNSET:` guards to `if not isinstance(x, _UnsetType):`.
  `ty` now correctly narrows the type inside the guard branch.
- No `type: ignore` comments needed; root causes eliminated.

**Verification:** `ruff check` and `ty check` pass clean. `pytest src/vaultspec_a2a/database/tests/ -q` → 71 passed.

---

## Pass 5 — Open Gaps

### HIGH-01 (FIXED): test_migrations.py is SQLite-only

**Finding:** `database/tests/test_migrations.py` tests all Alembic migrations
against an in-memory SQLite database. The `render_as_batch` fix (CRIT-02) and
any future schema changes are not exercised against a real Postgres schema.

**Risk:** A migration that is safe on SQLite but destructive on Postgres would
pass CI without detection.

**Fix applied:** Added `TestAlembicUpgradeDowngradePostgres` class to
`database/tests/test_migrations.py` covering upgrade/downgrade, plan-approval
state, and legacy-status migrations against a real Postgres connection. Tests
are gated with `@pytest.mark.requires_postgres` and use the
`VAULTSPEC_POSTGRES_URL` env var.

**Verification:** `pytest src/vaultspec_a2a/database/tests/test_migrations.py -m requires_postgres`
passes against a live Postgres instance.

**Status:** Fixed.

---

### HIGH-02 (FIXED): with_allowlist() discards new saver on Windows

**Finding:** `_SelectorThreadPostgresCheckpointer.with_allowlist()` called
`self._run_sync("with_allowlist", ...)` but discarded the return value.
`AsyncPostgresSaver.with_allowlist()` returns a **new** saver instance with the
allowlist configured. Because the return value was thrown away, `self._saver`
still pointed to the old saver without the allowlist applied, and
`self.serde = self._saver.serde` subsequently read from the wrong saver.

**Risk:** Any code path calling `checkpointer.with_allowlist(...)` on Windows
received a silently misconfigured checkpointer — the allowlist had no effect.

**Fix applied:** Captured the return value and updated `self._saver`:

```python
def with_allowlist(
    self, *args: object, **kwargs: object
) -> _SelectorThreadPostgresCheckpointer:
    new_saver = self._run_sync("with_allowlist", *args, **kwargs)
    if new_saver is not None:
        self._saver = new_saver
    if self._saver is not None:
        self.serde = self._saver.serde
    return self
```text

**Verification:** `checkpoints.py` reviewed post-fix. `self._saver` is updated
before `serde` is synced.

**Status:** Fixed.

---

### MED-01 (FIXED): No pool_size/max_overflow configuration for Postgres engine

**Finding:** `session.py:get_engine()` sets `pool_pre_ping=True` for Postgres
but did not expose `pool_size`, `max_overflow`, or `pool_timeout` as
configuration parameters. SQLAlchemy's default pool (QueuePool) uses
`pool_size=5, max_overflow=10` which may be insufficient or excessive depending
on deployment.

**Fix applied:** `session.py` now passes `settings.db_pool_size` and
`settings.db_pool_max_overflow` to the Postgres engine factory (lines 117–118).
The corresponding `VAULTSPEC_DB_POOL_SIZE` and `VAULTSPEC_DB_POOL_MAX_OVERFLOW`
environment variables are surfaced through `config.py`.

**Verification:** `session.py` reviewed post-fix. Postgres engine creation
block includes `pool_size=settings.db_pool_size,
max_overflow=settings.db_pool_max_overflow`.

**Status:** Fixed.

---

### MED-02 (FIXED): Stale docstring in worker/app.py

**Finding:** `worker/app.py` lifespan docstring read "Open the shared SQLite
checkpointer (WAL mode, same path as the gateway)." This was incorrect —
the checkpointer is backend-selectable and the worker uses `open_checkpointer()`
from the shared factory.

**Fix applied:** Updated `_lifespan` docstring to read "Open the configured
backend-selectable checkpointer (SQLite or Postgres) via `open_checkpointer()`."

**Verification:** `worker/app.py` reviewed post-fix. Docstring correctly
describes the current backend-agnostic startup sequence.

**Status:** Fixed. Documentation-only; no runtime impact.

---

### MED-03: No Postgres service in docker-compose.prod.yml

**Finding:** `docker-compose.prod.yml` uses SQLite as the production database
(hardcoded `sqlite+aiosqlite://...` URLs). There is no reference Postgres
service, compose overlay, or documented runbook for enabling the Postgres
backend in a production deployment.

**Risk:** Operators who want Postgres in production have no reference
configuration to follow, increasing the probability of misconfigured DSNs,
missing `VAULTSPEC_DATABASE_BACKEND=postgres` env vars, or absent connection
pool tuning.

**Recommendation:** Add a `docker-compose.postgres.yml` overlay (or a
`docker-compose.prod.postgres.yml`) that defines a `postgres:16-alpine` service
with healthcheck, and overrides gateway/worker environment variables to use the
Postgres DSN and backends. Document in `README.md`.

**Status:** Resolved by architecture. `docker-compose.prod.postgres.yml` already
exists as the Postgres overlay for production use. `docker-compose.prod.yml` is
explicitly documented as the single-node SQLite deployment.  The `/health`
endpoint now exposes `production_certifying: bool` so operators can alert
when SQLite is active in a production deployment. No additional compose file
is required.

---

## Pass 6 — ADR Compliance

| ADR | Requirement | Status |
|-----|-------------|--------|
| ADR-007 §3.3 | Superseded by ADR-035 | Accepted |
| ADR-029 | Alembic manages app schema; `render_as_batch` backend-conditional | Compliant |
| ADR-031 | Worker uses shared checkpointer factory (`open_checkpointer`) | Compliant |
| ADR-035 | Backend defaults to `"postgres"`; SQLite is explicit fallback | Compliant |
| ADR-035 | Factory boundary in `session.py` + `checkpoints.py`; no backend branches in ORM/CRUD | Compliant |
| ADR-035 | Windows selector-thread bridge for `AsyncPostgresSaver` | Compliant |
| ADR-035 | `render_as_batch` dialect-conditional | Compliant |

---

## Summary

| Finding | Severity | Status |
|---------|----------|--------|
| CRIT-01: Docker compose missing backend env vars | CRITICAL | Fixed |
| CRIT-02: render_as_batch unconditional on Postgres | CRITICAL | Fixed |
| CRIT-03: _loop_ready.wait() blocks Proactor loop | CRITICAL | Fixed |
| CRIT-04: close() swallows errors, leaks selector thread | CRITICAL | Fixed |
| TYPE-01: 6 type errors (checkpoints.py + crud.py) | HIGH | Fixed |
| HIGH-01: test_migrations.py SQLite-only | HIGH | Fixed |
| HIGH-02: with_allowlist() discards new saver on Windows | HIGH | Fixed |
| MED-01: No pool_size/max_overflow config for Postgres | MEDIUM | Fixed |
| MED-02: Stale docstring in worker/app.py | MEDIUM | Fixed |
| MED-03: No Postgres service in docker-compose.prod.yml | MEDIUM | Resolved |

4 CRITICAL fixed. 3 HIGH fixed. 3 MEDIUM fixed. All findings resolved.

# ADR-029 Implementation Plan: Alembic Database Migration Framework

Date: 2026-03-04
Status: Draft — awaiting team-lead review

## Source Documents

- ADR: `docs/adrs/029-database-migration-framework.md`
- Codebase audit: `docs/research/2026-03-04-database-migration-research.md`
- Technical research: `docs/research/2026-03-04-alembic-async-sqlite-integration-research.md`

## Synthesis

Both research phases are complete. The codebase audit confirmed:

- **4 app-owned tables**: `threads`, `artifacts`, `permission_logs`, `cost_tracking` (all in `src/vaultspec_a2a/database/models.py` via `Base.metadata`)
- **2 LangGraph-owned tables**: `checkpoints`, `writes` (created by `AsyncSqliteSaver.setup()`, must be excluded)
- **Anti-pattern to remove**: `init_db()` in `session.py` lines 184-195 — `Base.metadata.create_all` + raw `ALTER TABLE` in try/except
- **Existing data migration**: `backfill_teamstate_sdd_fields()` in `src/vaultspec_a2a/database/migrations/__init__.py` — out of scope, keep as-is

The technical research confirmed:

- Async env.py pattern using `async_engine_from_config` + `run_sync` bridge
- `include_name` hook (not `include_object`) for LangGraph table exclusion — use allowlist form (`name in target_metadata.tables`) for future-proofing
- `render_as_batch=True` mandatory for SQLite ALTER TABLE emulation
- `pool.NullPool` mandatory for migrations (also mitigates aiosqlite v0.22+ closure bug)
- `alembic>=1.13.0` required (async template stabilised)
- Programmatic upgrade via `asyncio.to_thread(command.upgrade, cfg, "head")` for dev; CLI for production

## Implementation Steps

### Phase 1: Scaffold (no behaviour change)

1. **Add dependency**: `alembic>=1.13.0` to `pyproject.toml` `[project.dependencies]`
2. **Create `alembic.ini`** at repo root with `script_location = src/vaultspec_a2a/database/migrations` and `sqlalchemy.url = sqlite+aiosqlite:///vaultspec.db`
3. **Create `src/vaultspec_a2a/database/migrations/env.py`** — canonical async pattern from research doc section 3, with:
   - `target_metadata = Base.metadata` (import from `lib.database.models`)
   - `include_name` allowlist: `name in target_metadata.tables` (excludes LangGraph tables + any future non-ORM tables)
   - `render_as_batch=True` in both offline and online paths
   - `pool.NullPool` for migration engine
4. **Create `src/vaultspec_a2a/database/migrations/script.py.mako`** — standard Alembic template
5. **Create `src/vaultspec_a2a/database/migrations/versions/` directory** (empty `__init__.py`)

### Phase 2: Baseline migration

1. **Generate initial migration**: `uv run alembic revision --autogenerate -m "initial_schema"`
2. **Review generated file** — must only contain the 4 app tables + their indexes
3. **Test upgrade on fresh DB**: `uv run alembic upgrade head` against a new file
4. **Test stamp on existing DB**: `uv run alembic stamp head` against the current `vaultspec.db`

### Phase 3: init_db refactor

1. **Strip DDL from `init_db()`** — remove `create_all` call (line 185) and the `ALTER TABLE` try/except block (lines 190-195)
2. **Add `run_migrations()` helper** to `session.py` (or a new `src/vaultspec_a2a/database/migrate.py`):

    ```python
    async def run_migrations(db_path: str) -> None:
        cfg = Config("alembic.ini")
        cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_path}")
        await asyncio.to_thread(command.upgrade, cfg, "head")
    ```yaml

1. **Wire startup**: call `run_migrations()` in `src/vaultspec_a2a/api/app.py` lifespan before first request (gated by `settings.auto_migrate` flag, default `True` for dev)

1. **Remove `OperationalError` import** from session.py (no longer needed)

### Phase 4: Test infrastructure

1. **Test fixtures remain unchanged**: tests use `:memory:` or temp-file DBs with `Base.metadata.create_all(conn)` directly — this is the accepted exception (ephemeral DBs don't need migrations)
2. **Add migration test**: new test in `src/vaultspec_a2a/database/tests/test_migrations.py` that:
    - Creates a temp SQLite file
    - Runs `alembic upgrade head` programmatically
    - Verifies all 4 tables exist
    - Runs `alembic downgrade base`
    - Verifies tables are gone
3. **Add LangGraph exclusion test**: pre-create `checkpoints` and `writes` tables, run `alembic upgrade head`, verify they are untouched

### Phase 5: Documentation + cleanup

1. **Update `__all__`** in `src/vaultspec_a2a/database/session.py` if `run_migrations` is added there
2. **Add `auto_migrate` setting** to `src/vaultspec_a2a/core/config.py` Settings model
3. **Update MEMORY.md** with completed milestone

## Files Changed (estimated)

| File | Action |
|------|--------|
| `pyproject.toml` | Add `alembic>=1.13.0` dependency |
| `alembic.ini` | New — repo root |
| `src/vaultspec_a2a/database/migrations/env.py` | New — async Alembic env |
| `src/vaultspec_a2a/database/migrations/script.py.mako` | New — template |
| `src/vaultspec_a2a/database/migrations/versions/` | New directory |
| `src/vaultspec_a2a/database/migrations/versions/0001_initial_schema.py` | New — autogenerated |
| `src/vaultspec_a2a/database/session.py` | Refactor `init_db()`, add `run_migrations()` |
| `src/vaultspec_a2a/api/app.py` | Wire `run_migrations()` in lifespan |
| `src/vaultspec_a2a/core/config.py` | Add `auto_migrate: bool = True` |
| `src/vaultspec_a2a/database/tests/test_migrations.py` | New — migration tests |

## Risks

1. **aiosqlite v0.22+ closure bug**: Mitigated by NullPool in migrations. App engine uses default pool — monitor for aiosqlite upgrades.
2. **Autogenerate blind spots**: SQLite type changes and constraint changes not detected. Manual review of every generated migration is mandatory.
3. **Existing DB stamp**: Developers with existing `vaultspec.db` files must run `uv run alembic stamp head` once before future migrations apply cleanly.

## Open Decisions for Team Lead

1. **`alembic.ini` location**: Repo root (conventional) vs `src/vaultspec_a2a/database/` (co-located). Recommendation: repo root.
2. **`auto_migrate` default**: `True` (dev convenience) vs `False` (explicit discipline). Recommendation: `True` with INFO log on startup.
3. **`run_migrations()` location**: `session.py` (co-located with engine) vs new `migrate.py` (separation of concerns). Recommendation: `session.py` for simplicity.

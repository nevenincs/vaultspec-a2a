# ADR 029: Database Migration Framework
Date: 2026-03-04
Status: Accepted

## Context
The `vaultspec-a2a` orchestrator employs a local `sqlite` database via `aiosqlite` and `SQLAlchemy`. As the application scope has expanded, tables like `threads`, `artifacts`, `permission_log`, and `token_usage` undergo continuous iterations.

Currently, database schema configuration (`lib/database/session.py`) relies entirely on the synchronous execution of `Base.metadata.create_all`. While adequate for creating tables on an empty database file, this method explicitly ignores structural updates (adding columns, dropping foreign keys) to existing tables.

To bypass this limitation, earlier developers implemented a fragile pattern wherein raw SQL strings (e.g., `ALTER TABLE threads ADD COLUMN team_preset TEXT`) were forcibly executed inside broad `try/except OperationalError` blocks. This arbitrary patching is untrackable, non-transactional, and unable to perform complex SQLite migrations (such as table-rebuilds required for dropping columns).

Detailed problem specifics were established in `docs/research/2026-03-04-database-migration-research.md`.

## Decision
We will integrate **Alembic** as the strict dependency for asynchronous SQLite database schema evolution.

1. **Dependency Core**: `alembic` (min: `1.13.0`) will be definitively added to `pyproject.toml` targeting the exact aiosqlite connection variables.
2. **Autogeneration Baseline**: `lib/database/migrations/` will house the environment logic. A `001_initial_schema.py` script will be committed to establish the existing SQLite baseline representing the current SQLAlchemy declarations.
3. **Application Decoupling**: We will completely purge the usage of `create_all` and manual patching from `session.py/init_db()`.
4. **Execution Strategy**: Upon application entry, migrations must either be statically applied using the `alembic upgrade head` CLI loop or programmatically triggered using the Alembic config object before the orchestrator binds to its first thread.

## Consequences

### Positive
- **Safeguarding Dev States**: Developers checking out different feature branches with divergent table architectures will not instantly corrupt their local workspace databases.
- **Traceability**: All structural changes to underlying tables are mapped directly into a git-tracked, sequential DAG.
- **Advanced Changes**: Re-architecting relationships and renaming columns becomes legally permissible in SQLite through Alembic's batch operations (temp-table swapping).

### Negative
- **Overhead**: Trivial column additions now mandate standard developer hygiene (generating a revision file and testing upgrade/downgrade logic).
- **Subprocess Complications**: Invoking an isolated Alembic CLI context necessitates precise environment variable management to ensure the pipeline identifies the correct `VAULTSPEC_WORKSPACE_ROOT` SQLite path.

## References
- Codebase gap finding: `docs/research/2026-03-04-database-migration-research.md`.
- Original workaround file: `y:/code/vaultspec-a2a-worktrees/main/lib/database/session.py`.
- [ADR-021](021-persistent-task-queue-schema.md) - Note: The task queue relies on `.vault/` file persistence, separating its schema cleanly from the SQLite databases governed by this ADR.

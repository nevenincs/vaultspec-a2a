---
tags:
- '#adr'
- '#database-migration-framework'
date: 2026-03-31
modified: '2026-10-07'
body_hash: 'sha256:92ae003cbac440a128ebc01926818fc93064e886678bfc3b147cf22d5538fd53'
related:
- '[[2026-03-31-docs-vault-migration-research]]'
- '[[2026-10-06-codebase-remediation-audit]]'
- '[[2026-10-07-codebase-remediation-task-queue-retirement-adr]]'
- '[[2026-10-07-codebase-remediation-sqlite-only-adr]]'
---

# `database-migration-framework` adr: `adr-029` | (**status:** `accepted`)

Accepted 2026-10-07 under the owner's remediation direction (drop unrequired code, remove duplication, delegate ADR amendments).

## Migration Note

This ADR was migrated from the legacy pre-pipeline documentation tree during the issue #19 cleanup so that the repository no longer depends on the removed `docs/` directory.

- Original ADR number: `ADR-029`
- Original title: `ADR 029: Database Migration Framework`
- Legacy status at migration time: `Proposed`

## Original ADR

# ADR 029: Database Migration Framework

Date: 2026-03-04
Status: Accepted

## Context

The `vaultspec-a2a` orchestrator employs a local `sqlite` database via `aiosqlite` and `SQLAlchemy`. As the application scope has expanded, tables like `threads`, `artifacts`, `permission_log`, and `token_usage` undergo continuous iterations.

Currently, database schema configuration (`src/vaultspec_a2a/database/session.py`) relies entirely on the synchronous execution of `Base.metadata.create_all`. While adequate for creating tables on an empty database file, this method explicitly ignores structural updates (adding columns, dropping foreign keys) to existing tables.

To bypass this limitation, earlier developers implemented a fragile pattern wherein raw SQL strings (e.g., `ALTER TABLE threads ADD COLUMN team_preset TEXT`) were forcibly executed inside broad `try/except OperationalError` blocks. This arbitrary patching is untrackable, non-transactional, and unable to perform complex SQLite migrations (such as table-rebuilds required for dropping columns).

Detailed problem specifics were established in `legacy-research/2026-03-04-database-migration-research.md`.

## Decision

We will integrate **Alembic** as the strict dependency for asynchronous SQLite database schema evolution.

1. **Dependency Core**: `alembic` (min: `1.13.0`) will be definitively added to `pyproject.toml` targeting the exact aiosqlite connection variables.
2. **Autogeneration Baseline**: `src/vaultspec_a2a/database/migrations/` will house the environment logic. A `001_initial_schema.py` script will be committed to establish the existing SQLite baseline representing the current SQLAlchemy declarations.
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

- Codebase gap finding: `legacy-research/2026-03-04-database-migration-research.md`.
- Original workaround file: `y:/code/vaultspec-a2a-worktrees/main/src/vaultspec_a2a/database/session.py`.
- ADR-021 - Note: The task queue relies on `.vault/` file persistence, separating its schema cleanly from the SQLite databases governed by this ADR.

## Amendment (2026-10-07): status reconciled and one migrate entry point

Code paths are under `src/vaultspec_a2a/`.

**Status.** The heading said `proposed`, but the original body says "Status: Accepted", and the decision is implemented:

- Alembic owns schema evolution (`database/migrate.py`, `database/migrations/versions/`).
- CI runs a SQLite round trip (`.github/workflows/migrations.yml:66-72`).

The heading now records `accepted`. The migration note's legacy status stays as history.

**One migrate entry point.** Two paths apply revisions:

- `vaultspec-a2a migrate` (`cli/service.py:520-546`, through `desktop/migration.migrate_stores`);
- gateway-boot migration (`database/session.py:404-407`).

Both go through `database/migrate.run_migrations`, which holds `_MIGRATION_LOCK` (`database/migrate.py:93-96`).

`database/admin.py` is removed (D19 and R3-F21 in `2026-10-06-codebase-remediation-audit`):

- Its `_migrate_to_head` called `command.upgrade` without that lock (`database/admin.py:70-74`), a duplicate of the locked path.
- Its snapshot and restore verbs duplicated the snapshot and rollback that the dashboard owns (`cli/service.py:20-23`).
- Its `clear` verb had no consumer.

Its one unique capability, WAL truncate plus `VACUUM` (`migrate --fix`), becomes `vaultspec-a2a migrate --compact`:

- It runs after the revisions, on stores that `migrate_stores` has already proved quiesced with a zero-timeout `BEGIN IMMEDIATE` (`desktop/migration.py:191-213`).
- A blocked compaction is a failed stage.
- The option is additive on the dashboard-spawnable verb.

The restore guard fixed at e19c501d (R7-F30) goes with the verbs it guarded. A real-subprocess test re-proves the same refusal on `migrate --compact` against a live gateway.

Bare `alembic` stays a developer tool that takes an explicit URL. Its missing-URL hint (`database/migrations/env.py:72-82`) names `vaultspec-a2a migrate`.

**Replaces.** Decision item 4 is narrowed: "programmatically triggered" means `run_migrations` under its lock, and no other programmatic path exists. The ADR-021 reference is historical, because `2026-10-07-codebase-remediation-task-queue-retirement-adr` retires that task queue.

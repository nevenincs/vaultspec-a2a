---
tags:
  - "#adr"
  - "#codebase-remediation"
date: '2026-10-07'
related:
  - "[[2026-10-06-codebase-remediation-audit]]"
  - "[[2026-03-10-postgres-dual-backend-adr]]"
  - "[[2026-10-04-container-release-native-production-adr]]"
  - '[[2026-03-31-database-migration-framework-adr]]'
  - '[[2026-02-26-orchestration-topology-pipeline-adr]]'
  - '[[2026-03-20-service-lifecycle-architecture-adr]]'
  - '[[2026-03-04-worker-process-architecture-adr]]'
  - '[[2026-07-14-a2a-edge-conformance-adr]]'
supersedes:
  - '2026-03-10-postgres-dual-backend-adr'
modified: '2026-10-07'
body_schema: 'body-v2'
body_hash: 'sha256:a971b51f56cbcac2e534df83687a385649b186a876d2c0815b2858e8558d9c9a'
---
# `codebase-remediation` adr: `SQLite is the only store` | (**status:** `accepted`)

Accepted 2026-10-07 under the owner's remediation direction (drop unrequired code, remove duplication, delegate ADR amendments).

## Problem Statement

`2026-03-10-postgres-dual-backend-adr` makes PostgreSQL the production backend for the application database and the LangGraph checkpointer, with SQLite as a development fallback. The product no longer has that topology. Its only production deliverable is the native SQLite binary that the dashboard bundles, and nothing in the implementation requires a second dialect (R3-F12 in `2026-10-06-codebase-remediation-audit`). Every migration and repository change is still written for two dialects, and no deployment or CI job runs one of them. The remediation's next migrations need this settled first.

## Considerations

Code paths are under `src/vaultspec_a2a/` unless they start with a repository-root entry.

- The shipped binary excludes the Postgres drivers: `asyncpg`, `psycopg` and `langgraph.checkpoint.postgres` (`packaging/pyinstaller/vaultspec-a2a.spec:76-78`). The `server` extra that carries them stays out of the base and `freeze` dependencies (`pyproject.toml:57-72`).
- Application containers are retired, and production consumes native binaries (`2026-10-04-container-release-native-production-adr`). Compose was the only topology that ran a Postgres server.
- No CI job provisions Postgres. `rg -i postgres .github` is empty. CI installs the `server` extra but migrates a `sqlite+aiosqlite` URL (`.github/workflows/migrations.yml:66-72`).
- The Postgres-only code is large and untested in CI (R3-F12). It includes:
  - the pool, the selector-thread bridge and the advisory-lock setup (`database/checkpoints.py:134-570,694-722`);
  - checkpoint retention (`database/checkpoint_retention.py:180-283`);
  - backend resolution and `validate_postgres_requirement` (`control/config.py:397-527`);
  - the backend, pool and requirement settings (`control/infra_config.py:50-56,179-223`).
- The settings models ignore unknown fields (`control/infra_config.py:164`). Deleting the backend fields alone would therefore silently ignore a configured `postgres`.
- Health still frames SQLite as a non-certifying fallback:
  - `/health` reports `production_certifying` as true only when both backends are Postgres (`api/app.py:987-990`).
  - `build_sqlite_fallback_diagnostics` reports `sqlite_fallback_not_production_certifying` (`control/health.py:129-152`).
  - The dashboard main tree reads none of `production_certifying`, `sqlite_fallback`, `postgres_required`, `database_backend` or `checkpoint_backend`.
- The `server` extra also carries the OTLP gRPC exporter (`pyproject.toml:70`). Telemetry loads that exporter lazily (`telemetry/instrumentation.py:126-133,419,473`). It does not depend on Postgres.

## Considered options

- **Keep both dialects.** Rejected. No deployment or CI lane runs Postgres, and every migration pays for it.
- **Keep Postgres dormant, with no CI lane.** Rejected. About 1,000 lines of untested dialect code would sit under every new migration, against the mandate to drop code the implementation does not require.
- **SQLite only, with all Postgres code and the `server` extra removed.** Chosen.

## Constraints

- SQLite is the only application database and the only checkpoint store in every profile: desktop, development and test.
- No product module, test or fixture opens a Postgres connection, imports a Postgres driver or `langgraph.checkpoint.postgres`, or branches on dialect.
- New schema code passes no `postgresql_*` arguments.
- Settings load refuses each of these inputs with a typed configuration error that names SQLite as the only store:
  - a `postgres` value for `VAULTSPEC_A2A_DATABASE_BACKEND` or `VAULTSPEC_A2A_CHECKPOINT_BACKEND`;
  - a `postgresql` database or checkpoint URL;
  - `VAULTSPEC_A2A_POSTGRES_REQUIRED=true`.
- These inputs are never silently ignored and never translated. A `sqlite` backend value stays accepted.
- Historical Alembic revisions keep their frozen text, dialect arguments included. New revisions are SQLite-only and use batch operations.
- The `server` optional-dependency group is removed. The OTLP gRPC exporter keeps an optional install home outside it. Telemetry still starts in a base-only installation.
- Health and service-state payloads stop calling SQLite a non-certifying fallback. Any change to a served field is a contract event under `2026-07-14-a2a-edge-conformance-adr` R6.

## Implementation

We will remove PostgreSQL from the product and keep SQLite as the only store.

- **Store code.** Delete these Postgres paths:
  - in `database/checkpoints.py`: the pool, `_SelectorThreadPostgresCheckpointer`, the advisory-lock setup and `_open_postgres_checkpointer`;
  - the Postgres branches of `database/checkpoint_retention.py`, `database/write_authority_schema.py`, `database/runtime_identity_repository.py` and `database/run_event_repository.py`;
  - the pool arguments in `database/session.py`;
  - every `postgresql_where` and `postgresql_using` in `database/models.py`.
- **Settings.** Replace the backend, pool and requirement settings and `validate_postgres_requirement` with the typed refusal. Two mechanisms are acceptable, and the choice is left to implementation: keep single-valued fields, or remove the fields and refuse the retired values explicitly. `.env.example` drops the Postgres block.
- **Dependencies.** Remove the `server` extra and every `--extra server` sync in the `Justfile` and `.github/workflows/`. Move the OTLP gRPC exporter to its own optional group. The group's name is not fixed by this record.
- **Tests.** Collapse `database/tests/_backends.py` to SQLite. Delete the Postgres-only tests and fixtures: `pooled_postgres_saver` in `conftest.py`, the Postgres stack in `service_tests/test_run_continuation_live.py`, and `postgres_url` in `service_tests/harness.py`.
- **Checkpoint schema setup.** On SQLite, setup is idempotent `CREATE TABLE IF NOT EXISTS` under the store's write lock. The desktop profile runs it only from the migration entrypoint (`database/checkpoints.py:654-666`). This replaces the Postgres advisory lock as the owner of concurrent schema setup.
- **Health.** Remove `postgres_required` and `production_certifying`. Turn the SQLite fallback block into plain storage diagnostics. `ServiceStateResponse.database_backend` and `checkpoint_backend` (`api/schemas/gateway.py:993-994`) keep their shape and always read `sqlite` until a contract event retires them.
- **Proof.**
  - A real settings load fails with the typed error for each refused input.
  - The packaged-binary artifact proof and the SQLite migration round trip still pass.
  - Telemetry still starts in a base-only installation (`just test-clean-base`).

## Rationale

The deciding fact is that nothing the product ships or tests requires Postgres:

- the binary cannot load the drivers;
- the server topology that hosted Postgres is retired;
- CI never starts a Postgres server.

The 2026-03-10 rationale assumed a server deployment: multi-host scaling, Compose named volumes and LangGraph's production recommendation. `2026-10-04-container-release-native-production-adr` removed that deployment. `2026-03-04-worker-process-architecture-adr` already bounds the product to one host through its WAL constraint. Keeping a dialect that no deployment runs contradicts the mandate to drop code the implementation does not require, and it doubles the cost of every migration. Grounding: R3-F12 in `2026-10-06-codebase-remediation-audit`.

## Consequences

- About 1,000 lines of dialect code are removed, together with the Windows selector-thread bridge and the Postgres test lane.
- Migrations and repository SQL are written and tested once.
- A configured Postgres backend now refuses to start instead of running. No supported deployment configures one.
- Multi-host and replicated deployment are unsupported. Reconsider only if a product profile needs a shared server store. That needs a new decision and a CI lane that provisions the server.
- This record supersedes `2026-03-10-postgres-dual-backend-adr`. Clauses in other records that name that ADR as the backend or schema-setup owner are now historical.
- Acceptance does not mean the removal is done.

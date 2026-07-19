---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S07'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

# Resolve Alembic configuration and migration scripts from installed package resources

## Scope

- `src/vaultspec_a2a/database/migrate.py`

## Description

- Replace the repo-root `alembic.ini` read in `run_migrations` with a
  programmatic `alembic.config.Config` built by a new `build_migration_config`.
- Resolve the migration script directory from the installed
  `vaultspec_a2a.database.migrations` package through `importlib.resources` in a
  new `migration_script_location` helper.
- Drop the `settings.project_root` dependency from the migration runner.
- Expose `build_migration_config` and `migration_script_location` through the
  database package facade.
- Extend the migration tests with real package-resolution and end-to-end upgrade
  assertions.

## Outcome

The runtime migration path no longer reads a checkout-relative `alembic.ini`.
`build_migration_config` assembles an Alembic `Config` with no attached config
file: `script_location` is set to the installed migrations package directory and
`sqlalchemy.url` carries the caller's database URL. Because no config file is
attached, `env.py` skips its `fileConfig` branch and the application's own
logging configuration stays authoritative, while the async engine still reads
`sqlalchemy.url` from the main section. The script directory is resolved from the
`vaultspec_a2a.database.migrations` package via `importlib.resources`, so it is
valid from a source checkout and from a clean installed wheel alike; wheels
install unzipped, so the traversable is a real directory Alembic can read. A
missing package raises `FileNotFoundError` naming the absent resource.

The repo-root `alembic.ini` is retained untouched for the developer CLI workflow;
it already points `script_location` at the same in-package script directory, so
the developer `alembic` command and the runtime path share one set of scripts.

Two real resolution tests were added. One asserts that
`migration_script_location` equals the migrations package path and contains
`env.py` and the `versions` directory. Another asserts that the runtime config
attaches no config file (`config_file_name is None`), binds `script_location` to
the packaged directory, and carries the supplied URL — a direct proof that no
repo-root file is consulted at runtime. A real end-to-end test upgrades a temp
SQLite database through the package-resolved scripts and asserts the recorded
`alembic_version` reaches `0007`.

## Tests

- `.venv/Scripts/python.exe -m pytest src/vaultspec_a2a/database/tests/test_migrations.py -q`
  reported 15 passed after remediation, covering the retained `alembic.ini`
  developer-CLI tests, package resolution, exact percent-encoded URL round
  trips, three real programmatic upgrades, and concurrent upgrades of two
  distinct databases.
- `.venv/Scripts/python.exe -m pytest src/vaultspec_a2a/database/tests -q`
  reported 118 passed after remediation; the earlier implementation run
  reported 114. The migration changes did not regress the session, checkpoint,
  or reconciliation suites that depend on `run_migrations`.
- `uv run --no-sync pytest src/vaultspec_a2a/desktop_tests -q` reported 5 passed,
  keeping the S05 dependency-closure gate green.
- Ruff check and format, and scoped `ty check`, passed for the migration runner,
  the test module, and the database facade.

## Reopened review finding and remediation

The post-implementation review found a high-severity correctness defect in the
programmatic configuration: Alembic stores main options in an interpolating
parser, so raw percent signs in `script_location` or `sqlalchemy.url` were not
valid option values. This prevented legitimate percent-encoded database URLs
and installation paths from being read back or used for an upgrade.

The review also found a high-severity concurrency defect. Alembic's command and
environment proxy state is process-global, so concurrent upgrades dispatched to
different worker threads could cross-wire their configurations, fail with
proxy-state errors, or leave one database only partially migrated.

Both values are now escaped for Alembic when written. Alembic removes that
storage escape when read, so `get_main_option` returns the original package path
and database URL. `build_migration_config` is also included in the migration
module's declared public API. Missing or incomplete migration package data now
raises a stable, actionable `FileNotFoundError` that recommends reinstalling a
complete distribution without exposing an installation path or database URL.
The synchronous Alembic upgrade is now serialized under a process-wide lock
that is acquired inside the worker thread. Concurrent async callers therefore
remain non-blocking to the event loop while Alembic's global command context is
protected.

The regression coverage constructs real configurations for a Windows-style
SQLite URL and a percent-encoded PostgreSQL URL, asserting exact round trips.
It also performs a real SQLite upgrade where the database lives below a
directory containing a literal percent sign and verifies that Alembic reaches
the current head revision. A real `asyncio.gather` regression upgrades two
distinct SQLite databases concurrently and verifies that both contain the
current revision and the complete application table set.

## Notes

The end-to-end proof runs from the source tree rather than a freshly installed
venv. This is honest and sufficient: `importlib.resources.files` uses the same
resolution mechanism in both cases, and the explicit `config_file_name is None`
assertion proves the runtime path is checkout-independent without paying for a
full clean install here. The clean-installed-capsule migration proof is the
declared job of the later capsule-install certification Steps. No mock, stub,
patch, monkeypatch, or skip was introduced.

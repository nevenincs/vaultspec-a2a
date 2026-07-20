---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S24'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

# Run package-local migrations from a clean installed capsule and reject incompatible or live-store attempts

## Scope

- `src/vaultspec_a2a/desktop_tests/test_migration_entrypoint.py`

## Description

- Add a certification gate that builds the real wheel, exports the locked base
  closure, and installs both into a clean interpreter, mirroring the dependency
  closure and capsule build harnesses.
- Drive the internal migrate command from the installed environment against a
  fresh application home with a real descriptor file, asserting the head revision
  is reached and the machine-readable result JSON shape.
- Add the rejection cases: an incompatible claimed migration range, an
  already-consumed descriptor replayed, and a store held under a real
  cross-process SQLite write lock, each asserting the failed result and exit code.
- Mark the build-and-install cases `service`, consistent with the capsule build
  gate, since they run `uv build` and provision a clean environment.

## Outcome

The desktop migration entrypoint is certified end to end from a clean installed
capsule: the installed command migrates a fresh store to the packaged Alembic
head, initialises the checkpointer, and backfills SDD; and it refuses an
incompatible range, a consumed descriptor, and a live locked store. Service suite
4/4 green (25.5s); the file passes ruff and ty.

## Notes

The service cases are deselected from the default and desktop-baseline runs and
must be run with `-m service`; they were executed and are green.

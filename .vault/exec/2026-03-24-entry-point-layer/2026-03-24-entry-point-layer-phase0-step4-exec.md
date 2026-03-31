---
tags:
  - '#exec'
  - '#entry-point-layer'
date: '2026-03-24'
related:
  - '[[2026-03-24-entry-point-layer-plan]]'
---

# `entry-point-layer` `phase-0` `step-4`

Updated test imports and verified baseline.

- Modified: `src/vaultspec_a2a/worker/tests/test_app.py`
- Modified: `src/vaultspec_a2a/worker/tests/test_executor.py`

## Description

Changed both test files to import `DispatchRequest` from `ipc.schemas` instead
of `api.schemas.internal`.

## Tests

- `pytest -m core` (ignoring pre-existing `api/tests` collection error): **425 passed**
- Full suite (ignoring pre-existing broken tests): **997 passed**, 9 pre-existing failures in `test_factory.py` (provider factory tests, unrelated to D-01)
- Worker tests specifically: **28 passed**
- Zero remaining imports from `api.schemas.internal` in `src/`

---
tags:
  - '#exec'
  - '#entry-point-layer'
date: '2026-03-24'
modified: '2026-07-15'
body_hash: 'sha256:48d8773a5f49836b3f9fe6e85f2c74f7319d76d6900eff1807212bf658c18783'
related:
  - '[[2026-03-24-entry-point-layer-plan]]'
---

# `entry-point-layer` `phase-6` `step-4`

Deleted `endpoints.py`, rewired `app.py`, updated test logger references.

- Deleted: `src/vaultspec_a2a/api/endpoints.py`
- Modified: `src/vaultspec_a2a/api/app.py`
- Modified: `src/vaultspec_a2a/api/__init__.py`
- Modified: `src/vaultspec_a2a/api/tests/test_endpoints.py`
- Modified: `pyproject.toml`

## Description

Removed `endpoints.py` with no re-export shim. Updated `app.py` to call
`register_routes(app)` from `api.routes` instead of
`app.include_router(router, prefix="/api")`. Updated `api/__init__.py`
docstring to point to `api.dependencies` for `get_aggregator`. Updated
test logger reference from `vaultspec_a2a.api.endpoints` to
`vaultspec_a2a.api.routes.permissions`. Updated `pyproject.toml` ruff
per-file-ignores to cover `api/routes/*.py` and `api/dependencies.py`
instead of the deleted `endpoints.py`.

## Tests

Full suite: 1041 passed, 9 pre-existing failures, 43 deselected.
All API tests: 99 passed.
Ruff lint + format: clean.

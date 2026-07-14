---
tags:
  - '#exec'
  - '#entry-point-layer'
date: '2026-03-24'
modified: '2026-03-24'
related:
  - '[[2026-03-24-entry-point-layer-plan]]'
---

# `entry-point-layer` `phase-6` `step-3`

Split `endpoints.py` into 8 per-resource route modules under `api/routes/`.

- Created: `src/vaultspec_a2a/api/routes/__init__.py` (33 lines)
- Created: `src/vaultspec_a2a/api/routes/health.py` (82 lines)
- Created: `src/vaultspec_a2a/api/routes/threads.py` (425 lines)
- Created: `src/vaultspec_a2a/api/routes/thread_state.py` (142 lines)
- Created: `src/vaultspec_a2a/api/routes/messages.py` (201 lines)
- Created: `src/vaultspec_a2a/api/routes/cancel.py` (160 lines)
- Created: `src/vaultspec_a2a/api/routes/teams.py` (102 lines)
- Created: `src/vaultspec_a2a/api/routes/permissions.py` (308 lines)
- Created: `src/vaultspec_a2a/api/routes/admin.py` (15 lines)

## Description

Each route module creates its own `APIRouter` and imports from
`api.dependencies` for DI providers. `_process_metadata` stays in
`routes/threads.py` as a route-local helper. `routes/__init__.py` provides
`register_routes(app)` which includes all sub-routers under `/api`.
All files are well under the 500-line ceiling.

## Tests

All 99 API tests pass. All 1041 tests pass (9 pre-existing failures in
`test_factory.py` unrelated to this change).

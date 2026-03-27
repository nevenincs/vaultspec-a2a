---
tags:
  - '#exec'
  - '#entry-point-layer'
date: '2026-03-24'
related:
  - '[[2026-03-24-entry-point-layer-plan]]'
---

# `entry-point-layer` `phase4` `step3`

Rewired internal routes to use `relay_event()` and updated test imports.

- Modified: `src/vaultspec_a2a/api/internal.py`
- Modified: `src/vaultspec_a2a/api/tests/test_internal.py`
- Modified: `src/vaultspec_a2a/api/app.py` (added missing `subprocess` import -- pre-existing Phase 1 issue)

## Description

All 3 call sites (`_relay_worker_event`, `receive_worker_event`, `receive_worker_event_batch`) now call `relay_event()` from `control.event_handlers` instead of directly invoking the 4 handlers. Each call site retains its pre-relay responsibilities (execution_state_projection early-return, WS broadcast, aggregator sync).

Updated `test_internal.py` to import `_handle_terminal_event` from `control.event_handlers` instead of `api.internal` (3 test methods in `TestAggregatorGCOnTerminal`).

Fixed a pre-existing missing `import subprocess` in `app.py` that was blocking test collection (Phase 1 extraction left `subprocess.Popen` references without the import).

## Tests

- `test_internal.py`: 26/26 passed
- Full suite (excluding pre-existing `test_app.py` import error from Phase 1): 1030 passed, 10 failed (all pre-existing: npm deps, OTEL, repo hygiene)
- `internal.py` is 369 lines (target: ~400, well under 500 ceiling)
- `event_handlers.py` is 472 lines (under 500 ceiling)

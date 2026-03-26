---
tags:
  - '#exec'
  - '#entry-point-layer'
date: '2026-03-24'
related:
  - '[[2026-03-24-entry-point-layer-plan]]'
---

# `entry-point-layer` `phase4` `step1`

Extracted 4 event handlers and consolidated relay orchestration into `control/event_handlers.py`.

- Created: `src/vaultspec_a2a/control/event_handlers.py` (472 lines)
- Modified: `src/vaultspec_a2a/api/internal.py` (reduced from 813 to 369 lines)

## Description

Moved `_handle_terminal_event`, `_handle_permission_event`, `_handle_progress_event`, and `_handle_execution_state_event` from `api/internal.py` to `control/event_handlers.py`. These functions perform DB writes, state machine transitions, permission expiry, and aggregator GC -- business logic that does not belong in the protocol translation layer.

Consolidated the 3x duplicated relay orchestration sequence (previously in `_relay_worker_event`, `receive_worker_event`, and `receive_worker_event_batch`) into a single `relay_event()` function. Callers remain responsible for the execution_state_projection early-return, WS broadcast, and aggregator sync, while `relay_event()` handles the 4-handler DB-side processing sequence.

Also moved the module-level constants `_PLAN_APPROVAL_PAUSE_CAUSES`, `_TERMINAL_STATUS_MAP`, and the `_time_now_utc()` helper.

## Tests

All 26 tests in `test_internal.py` pass. Logger name changed from `vaultspec_a2a.api.internal` to `vaultspec_a2a.control.event_handlers` for the moved functions -- tests still capture the log records correctly.

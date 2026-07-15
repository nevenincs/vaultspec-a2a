---
tags:
  - '#exec'
  - '#entry-point-layer'
date: '2026-03-24'
modified: '2026-07-15'
related:
  - '[[2026-03-24-entry-point-layer-plan]]'
---

# `entry-point-layer` `phase-2` `step-2`

Refactored all 7 dispatch call sites to use `dispatch_to_worker()`.

- Modified: `src/vaultspec_a2a/api/endpoints.py`
- Modified: `src/vaultspec_a2a/api/app.py`

## Description

Each dispatch site replaced 50-80 lines of duplicated dispatch logic with a
call to `dispatch_to_worker()`, keeping caller-specific post-dispatch policy.

**REST sites (endpoints.py):**

- `create_thread_endpoint` — catches `WorkerCircuitOpenError` (503),
  `WorkerAtCapacityError` (503 + mark FAILED), `WorkerUnreachableError`
  (502 + mark FAILED)
- `send_message_endpoint` — same pattern, no mark FAILED on 429
- `respond_to_permission_endpoint` — catches circuit open (503), capacity
  and unreachable errors set `dispatched=False` (silent failure flag)
- `cancel_thread_endpoint` — uses `bypass_circuit_breaker=True`, capacity
  and unreachable set `dispatched=False`

**WS sites (app.py):**

- `_dispatch_message` — removed redundant `ensure_worker` + `pre_dispatch`
  calls (now handled by `dispatch_to_worker`). Catches `WorkerCircuitOpenError`
  and converts to `WebSocketCommandRejectedError`, catches `WorkerAtCapacityError`
  and converts to WS rejected command, catches `WorkerUnreachableError` and
  marks FAILED + broadcasts terminal event
- `_dispatch_control` — uses `bypass_circuit_breaker=True`, wraps raw dict
  in `DispatchRequest` (was previously sending unvalidated dict)
- `_redispatch_reconciling` — catches `WorkerCircuitOpenError` (skip with
  `continue`), capacity and unreachable logged and continued

**Cleanup:**

- Removed unused `from fastapi import HTTPException` from `app.py`
- Removed unused `from pathlib import Path` from `app.py`
- Import ordering fixed by `ruff --fix`

## Tests

1026 passed, 425 core passed. Only pre-existing factory failures excluded
(missing npm module).

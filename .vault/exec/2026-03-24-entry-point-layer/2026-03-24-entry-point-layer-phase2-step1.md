---
tags:
  - '#exec'
  - '#entry-point-layer'
date: '2026-03-24'
related:
  - '[[2026-03-24-entry-point-layer-plan]]'
---

# `entry-point-layer` `phase-2` `step-1`

Implemented consolidated `dispatch_to_worker()` function in `control/dispatch.py`.

- Created: `src/vaultspec_a2a/control/dispatch.py`
- Modified: `src/vaultspec_a2a/control/__init__.py`

## Description

The module defines `dispatch_to_worker()` which handles the common dispatch
sequence: `ensure_worker` -> circuit breaker check (optional) -> HTTP POST
`/dispatch` -> `record_success/failure` -> error handling.

Three domain error classes replace protocol-specific exceptions:

- `WorkerCircuitOpenError` — circuit breaker is open
- `WorkerAtCapacityError` — worker returned HTTP 429
- `WorkerUnreachableError` — httpx transport error (wraps cause)

The function does NOT raise `HTTPException` — callers translate domain errors
into protocol-specific responses (HTTP 503, WS rejected command, silent
continue, etc.).

`WorkerCircuitBreaker` import is behind `TYPE_CHECKING` to satisfy TC001.

## Tests

All files compile. Lint clean (only pre-existing TC002 on `RunnableConfig`).

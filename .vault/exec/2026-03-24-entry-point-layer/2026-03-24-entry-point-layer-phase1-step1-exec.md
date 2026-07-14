---
tags:
  - '#exec'
  - '#entry-point-layer'
date: '2026-03-24'
modified: '2026-03-24'
related:
  - '[[2026-03-24-entry-point-layer-plan]]'
---

# `entry-point-layer` `phase1` `step1`

Extracted `WorkerCircuitBreaker` from `api/app.py` to `control/circuit_breaker.py` with protocol decoupling.

- Created: `src/vaultspec_a2a/control/circuit_breaker.py`
- Modified: `src/vaultspec_a2a/api/app.py`
- Modified: `src/vaultspec_a2a/api/endpoints.py`

## Description

Moved the `WorkerCircuitBreaker` class (~80 lines) from `api/app.py` to `control/circuit_breaker.py`. Refactored `pre_dispatch()` from raising `HTTPException(503)` directly to returning `bool` (True = allowed, False = rejected). Added a `rejection_detail` property for callers to use in their error responses.

Updated all 4 call sites (1 in `app.py` WS dispatch, 3 in `endpoints.py` REST dispatch) to check the return value and raise `HTTPException(503)` at the call site instead of inside the circuit breaker. This decouples the circuit breaker from FastAPI.

## Tests

All 10 `api/tests/test_app.py` tests pass. Full suite: 1026 passed. Core: 425 passed.

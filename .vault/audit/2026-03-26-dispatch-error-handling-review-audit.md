---
tags:
  - "#audit"
  - "#entry-point-layer"
date: 2026-03-26
modified: '2026-07-15'
related:
  - "[[2026-03-24-entry-point-decomposition-adr]]"
  - "[[2026-03-24-entry-point-layer-plan]]"
---

# `entry-point-layer` dispatch error handling review

Status: **PASS** (no CRITICAL, two MED)

## Dispatch caller coverage (DISP)

DISP-001 | LOW | `ws_dispatch.py` control handler silently swallows `WorkerDispatchRejectedError` without marking thread FAILED or notifying WS client. Acceptable for cancel fire-and-forget semantics but inconsistent with message handler which marks FAILED.

DISP-002 | INFO | `routes/cancel.py` returns 200 `cancelled=False` on rejection. Correct idempotent cancel semantics.

DISP-003 | MED | `routes/permissions.py` silently swallows `WorkerDispatchRejectedError`, thread stays stuck in `INPUT_REQUIRED`. Client cannot distinguish transient capacity from persistent worker failure. Should either mark FAILED or return 502.

DISP-004 | LOW | `dispatch.py` `redispatch_reconciling_threads` leaves thread in RECONCILING state on rejection. Background task, acceptable but thread may remain stuck.

DISP-005 | LOW | `dispatch_to_worker` docstring missing `WorkerDispatchRejectedError` in `Raises:` section (line 122-126), though it is raised at line 174.

## HTTP response handling patterns (HTTP)

HTTP-000 | OK | **Zero instances** of the "assume success on non-specific-error" anti-pattern found across the entire codebase. Every production HTTP call site validates responses via `raise_for_status()`, `is_success`, or explicit status code checks.

HTTP-001 | INFO | `cli/_team.py:119-127` advisory state fetch uses `is_success` guard with bare except. Intentional graceful degradation for non-critical UX data.

HTTP-002 | INFO | `cli/_team.py:301-309` advisory permissions fetch same pattern. Intentional.

## Circuit breaker integration (CB)

CB-001 | OK | `record_success()` correctly gated behind confirmed 2xx response.

CB-002 | OK | `record_failure()` covers both transport errors and non-2xx responses.

CB-003 | MED | HTTP 429 does not call `record_failure()`. Sustained 429 loops will never trip the breaker. Design decision needed on whether capacity exhaustion should contribute to failure count.

CB-004 | OK | `pre_dispatch()` return value always checked before proceeding.

CB-005 | OK | `bypass_circuit_breaker=True` used only for cancel/terminate. All other dispatches go through the breaker.

CB-006 | OK | Watchdog `force_open()`/`record_success()` lifecycle correct. Success recorded only after confirmed restart.

CB-007 | OK | No rogue `WorkerCircuitBreaker` construction outside `app.py` and test fixtures.

CB-008 | OK | All callers handle `WorkerCircuitOpenError` and translate to HTTP 503 or WS rejection.

CB-009 | LOW | `routes/permissions.py` swallows dispatch failure type info (UX concern, not a CB integration bug).

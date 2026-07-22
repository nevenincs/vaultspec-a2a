---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S57'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

# Apply the drain gate to run start cancellation and administrative stop paths

## Scope

- `src/vaultspec_a2a/api/routes/gateway.py`

## Description

- Add an `admission_gate(app)` helper to `api/routes/gateway.py` that
  get-or-creates one process-wide `DrainGate` on `app.state.drain_gate`, the
  single authority the run verbs and the administrative stop path share.
- Gate `run-start`: after eligibility and profile validation, admit the run id;
  refuse a draining gateway with 503 before `create_and_dispatch_thread` creates
  any durable state.
- Release the admission on a nickname-conflict (no durable run was created);
  leave an admitted run whose durable row exists (integrity replay, dispatch
  failure) tracked so a drain still accounts for it.
- Keep `run-cancel` un-gated (cancellation is the drain's tool) and release the
  run from the gate when a cancel settles it terminally here.
- Prove the wiring live in `api/tests/test_gateway_drain.py`: a real gateway
  over a socket admits and dispatches while open, refuses with 503 without
  reaching the worker once admission is closed, keeps cancel available, and does
  not double-count a client-run-id replay.

## Outcome

Admission close refuses new runs at the gateway before dispatch; cancel stays
available under drain. Gates: `ruff check`/`format` clean, `ty check` clean on
`gateway.py` and the test. New tests: `test_gateway_drain.py` = 2 passed.
Closeout suite `pytest api control worker providers` = 857 passed, 16 deselected
(the two new drain tests over the 855 baseline).

## Notes

REVIEW REMEDIATION (P11 HIGH-2): the drain gate is now engaged by the production
stop paths. The gateway lifespan shutdown (`api/app.py`) closes admission as its
first shutdown action, and the receipt-bound administrative shutdown
(`api/routes/admin.py`) closes admission before its deferred process stop
(composed with the existing attach + lifecycle-capability gates); a
`test_gateway_drain.py` case proves a run-start after an admin stop is refused
503. This supersedes the original deferral note below, which incorrectly left
the stop-path wiring to a later Step. The drain gate is still seated lazily on
first run-start (or on the stop path's `admission_gate` get-or-create).
Steady-state release of a completed long-running run from the gate is driven by
execution-state terminal settlement (`W04.P12`); this Step wires the release
points observable at the gateway verbs (nickname conflict,
terminal cancel).

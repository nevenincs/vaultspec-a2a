---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S56'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

# Implement a bounded drain gate that atomically closes admission tracks active runs and reports quiescence

## Scope

- `src/vaultspec_a2a/control/drain.py`

## Description

- Add `control/drain.py` with a `DrainGate` that serialises run admission
  against an atomic admission close and reports drained quiescence.
- Model typed results: `AdmissionState` (open/draining), `AdmissionResult`
  (admitted flag, live state, active count, refusal reason), and `DrainResult`
  (quiescent flag, residual active count, waited seconds).
- Guard the active-run set with an `asyncio.Lock` so `admit`, `release`, and
  `close_admission` mutate it atomically on the single worker event loop; a
  quiescence `asyncio.Event` tracks the empty transition for a bounded
  `wait_quiescent`/`drain`.
- Make `admit` idempotent, refuse admission once closed, and assert quiescence
  when a close finds no active run so a following drain returns immediately.
- Export the module through the `control` package facade `__all__`.
- Add co-located pure-logic unit coverage in `control/tests/test_drain.py`
  (real `asyncio` semantics; no external service).

## Outcome

Admission, close, release, and bounded drain behave per the state machine; the
close is atomic against a concurrent admit burst (every admit fully granted or
fully refused). Gates: `ruff check`/`format` clean, `ty check` clean on the new
module. `pytest control/tests/test_drain.py` = 9 passed. Closeout suite `pytest
api control worker providers` = 855 passed, 16 deselected. Desktop baseline
`pytest desktop_tests -m "not service" --ignore=test_dependency_closure.py` =
24 passed, 26 deselected.

## Notes

The gate holds only the active-run id set: it neither cancels runs nor reaps
processes. Cancellation of the runs it reports active belongs to the run-cancel
verb; reaping owned descendants belongs to the process-containment reaper. The
gate is instantiated and wired onto the gateway request path in the next Step;
release-on-terminal from execution-state settlement is `W04.P12` scope.

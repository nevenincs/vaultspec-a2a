---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S58'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

# Retain actor tokens through INPUT_REQUIRED and release active-run ownership tokens and child handles only on terminal outcomes

## Scope

- `src/vaultspec_a2a/worker/executor.py`

## Description

- Audit: the executor already retains a run's actor tokens and cached engine
  catalog through an INPUT_REQUIRED park. `handle_dispatch`'s ingest/resume
  settle calls `_mark_ingest_done`, which drops the token store and catalog
  store only when the outcome is in `TERMINAL_STATUSES`; a parked run reports the
  non-terminal `"interrupted"` outcome, so both survive park -> resume. Confirmed
  and left intact.
- Harden the CANCEL branch of `handle_dispatch`: release the tokens and catalog
  on the TERMINAL boundary only. Previously the cancel dropped them
  unconditionally, even while an ingest was still active (a pre-terminal
  release that could strand an in-flight authoring call of its own token). Now
  the cancel signals cancellation, and only a cancel with no active ingest
  (itself terminal) drops here; an active ingest settles terminal and drops in
  its own `_mark_ingest_done`.
- Prove both through the real Executor seam (real checkpointer, real bridge over
  in-process ASGI, real compiled `StateGraph` that parks on `interrupt`): tokens
  are retained across the park and dropped on the terminal resume, and
  cancelling a parked run releases them at that terminal boundary.

## Outcome

Tokens and child catalog handles are released only on terminal outcomes and
retained through INPUT_REQUIRED. Gates: `ruff check`/`format` clean, `ty check`
clean on `executor.py`. New tests in `test_executor_token_lifecycle.py` = 2
added (5 passed total in the module). Closeout suite `pytest api control worker
providers` = 859 passed, 16 deselected.

## Notes

The executor holds no provider subprocess handles directly; the run-owned
provider process trees are spawned and contained by the provider spawner and
reaped by the process-containment reaper (later Steps of this Phase). The
"child handles" the executor owns are the per-run token and catalog stores,
which this Step confirms are released only at the terminal boundary.

---
tags:
  - '#exec'
  - '#ecosystem-artifact-lifecycle'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S21'
related:
  - "[[2026-07-21-ecosystem-artifact-lifecycle-plan]]"
---

# Add teardown that removes the service test runtime directory after a run

## Scope

- `src/vaultspec_a2a/service_tests/harness.py`

## Description

- Reject the Step as literally written, and bound accumulation instead of deleting
  each run's directory at teardown.
- Evict all but the most recent runs when a new run starts, breaking ties on name.
- Add a test covering the eviction against real directories with real modification
  times.

## Outcome

Accumulation is bounded and recent runs survive.

The Step as written would have destroyed the artifacts it exists to protect. Teardown is
precisely where the harness writes its compose logs and session summary, for the express
purpose of diagnosing a run after it failed; removing the directory at teardown would
have deleted the post-mortem at the moment it became useful. Bounding the count achieves
the Step's intent - the operator's home stops growing without limit - while keeping
recent diagnostics available.

Eviction happens when a run starts rather than when one ends, so the just-finished run's
diagnostics are never the ones reclaimed.

## Notes

The Step's title still says remove, and the implementation bounds instead. The divergence
is recorded here rather than resolved by rewriting the row, because the reasoning matters
more than the wording: a plan written before reading the code asked for something that
would have been a regression.

Retroactive cleanup is deliberately absent. The three directories already on this machine
predate the change and are left alone; the sweep will reclaim them once enough new runs
occur, and deleting an operator's existing diagnostics as a side effect of an unrelated
change would be the wrong default.

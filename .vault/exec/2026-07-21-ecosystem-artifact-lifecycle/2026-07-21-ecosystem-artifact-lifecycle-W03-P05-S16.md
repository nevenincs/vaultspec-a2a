---
tags:
  - '#exec'
  - '#ecosystem-artifact-lifecycle'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S16'
related:
  - "[[2026-07-21-ecosystem-artifact-lifecycle-plan]]"
---

# Add a sweeper for orphaned isolated config homes left by a crash

## Scope

- `src/vaultspec_a2a/providers/_acp_config_home.py`

## Description

- Add a sweep that reclaims per-run config homes a crashed process never tore
  down, confined to the module's own naming prefix.
- Use age as the liveness substitute, since a home carries no owning process id,
  and set the threshold generously.
- Run the sweep once per home creation, matching the cadence the worker-log sweep
  already uses.
- Declare the home as an artifact, naming both the teardown path and the sweep.
- Add tests covering reclaim, and every case the sweep must refuse.

## Outcome

Abandoned homes are now reclaimed. Six tests pass, and four of them assert on what the
sweep must not touch: a recent home, the caller's own home regardless of age, a directory
outside the naming scheme however stale, and a non-directory sharing the prefix.

Age stands in for liveness because there is nothing better available here. The worker-log
sweep can cross-reference a process registry because its filenames carry a port; a config
home carries only a random suffix. The threshold is a day, chosen so the cost of the
wrong decision falls on the safe side - deleting a live run's configuration is far worse
than carrying residue for another cycle.

Gates: `ruff check` and `ty check` report all checks passed, and the combined provider and
artifacts suites report three hundred seventy-four passed with ten deselected.

## Notes

The sweep runs at home creation rather than on a schedule, which means a machine that
stops starting runs stops reclaiming. That is the same limitation the worker-log sweep
carries and is recorded here rather than presented as fully solved; closing it properly
needs a supervisor, which this service does not have.

The threshold is a constant rather than a setting. Making it configurable would invite an
operator to set it low enough to delete live homes, and no evidence yet suggests a day is
wrong. If a legitimately long-running agent ever exceeds it, the failure is visible and
loud rather than silent, because the run loses its configuration mid-flight.

This closes the Phase. Between the preceding Steps and this one, a config home is now
created in a declared location, its transcript is carried out before teardown, and what a
crash leaves behind is reclaimed. The residual exposure is the interval between a crash
and the next run, during which an armed install accumulates homes no system sweep reaches.

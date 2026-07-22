---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S52'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

# Keep desktop boot and redispatch reconciliation from spawning a worker while preserving Compose startup behavior

## Scope

- `src/vaultspec_a2a/api/app.py`

## Description

- Introduce a per-boot `worker_demand_ready` event in the gateway lifespan and
  publish it on the application state.
- Under the armed desktop profile, park reconciliation of durable RECONCILING
  runs behind that event instead of eagerly starting the worker at boot: a local
  deferred coroutine awaits the event, then runs the existing reconciliation.
- Hand the same event to the worker spawner so the demand path can fire it once
  the first authenticated execution demand has driven the single-flight worker
  start to readiness.
- Leave the Compose and development profiles on the eager boot reconciliation
  path unchanged: their worker is either standalone (no auto-spawn) or
  foreground-spawned, so their startup behavior is preserved.

## Outcome

- The only boot-time worker start path was reconciliation calling the spawner's
  ensure step; the armed profile now no longer traverses it at boot, so an idle
  armed gateway starts no worker while Compose and development boot exactly as
  before. The demand-driven fire of the event and the spawner field that carries
  it are completed in the sibling worker-management and dispatch Steps.
- Gates: `ty` and `ruff` clean on the changed module. Suites:
  `pytest src/vaultspec_a2a/api src/vaultspec_a2a/control src/vaultspec_a2a/worker`
  504 passed, 8 deselected; desktop baseline
  (`desktop desktop_tests -m "not service"`, dependency-closure ignored)
  351 passed, 1 skipped, 26 deselected.

## Notes

- The one skipped desktop case is a pre-existing POSIX permission-bit assertion
  owned by a separate open Step; it is not affected by this change.
- The spawner attribute the lifespan sets here is declared as a real field in the
  sibling worker-management Step; the lifespan assigns it through an explicit
  dynamic-typed alias to keep the type check clean at this Step's boundary.

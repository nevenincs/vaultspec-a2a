---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S54'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

# Trigger deferred reconciliation only after authenticated execution demand has completed worker single-flight readiness

## Scope

- `src/vaultspec_a2a/control/dispatch.py`

## Description

- After the single-flight worker start completes on the dispatch demand path,
  fire the spawner's demand-readiness signal exactly once, and only when the
  worker is genuinely up.
- Leave the signal untouched for the Compose and development profiles, where it
  is unset and boot reconciliation stays eager.

## Outcome

- The authenticated execution demand path now releases the parked desktop boot
  reconciliation the moment the worker first reaches single-flight readiness:
  concurrent demand still starts exactly one worker (the existing spawn lock),
  and reconciliation of durable RECONCILING runs proceeds against the
  already-started worker rather than starting one at boot. The fire is idempotent
  and predicated on real readiness, so a failed start never wakes reconciliation
  onto a dead worker.
- Gates: `ty` and `ruff` clean on the changed module. Suites:
  `pytest src/vaultspec_a2a/api src/vaultspec_a2a/control src/vaultspec_a2a/worker`
  504 passed, 8 deselected; top-level `desktop_tests` (`-m "not service"`,
  dependency-closure ignored) 23 passed, 26 deselected.

## Notes

- The combined desktop baseline still cannot collect the same five module-local
  capsule and package archive test files broken by a separate uncommitted
  closure-inventory work stream; that failure is outside this Step's scope
  (control only) and is not touched here. The top-level `desktop_tests` suite is
  fully green.

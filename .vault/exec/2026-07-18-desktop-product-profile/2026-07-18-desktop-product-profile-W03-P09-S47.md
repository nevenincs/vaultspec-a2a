---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S47'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

# Define separate liveness gateway readiness worker state provider eligibility and run-admission fields

## Scope

- `src/vaultspec_a2a/api/schemas/gateway.py`

## Description

- Add five bounded `StrEnum` facts to the gateway wire schema: `LivenessState`,
  `GatewayReadiness`, `WorkerLifecycleState`, `ProviderEligibility`, and
  `RunAdmission`. Each documents its own axis so no consumer collapses process
  liveness, gateway readiness, worker state, provider eligibility, and run
  admission into a single boolean.
- Add `LivenessResponse`, a deliberately minimal model carrying only the
  liveness fact for the unauthenticated liveness surface.
- Add `DesktopReadiness`, the authenticated projection carrying process identity
  (`gateway_pid`), product identity (`generation`, `profile`), the five facts,
  the bounded eligible-provider list, and bounded path-free reasons.
- Extend `ServiceStateResponse` with an optional nested `readiness` so the
  service-state verb can serve the same projection, and rebuild the model to
  resolve the forward reference.

## Outcome

Schema layer compiles, imports, and constructs cleanly; `ruff` and `ty` pass on
the file. The `WorkerLifecycleState` ladder (`cold` to `starting` to `ready`,
with `unavailable` for post-demand degradation) and the `RunAdmission` triad
(`ready`/`deferred`/`blocked`) together let a cold, startable worker read as
gateway-ready yet not execution-ready. No behaviour change lands in this Step;
the assembler and endpoints that populate the new fields follow.

## Notes

The shared desktop baseline suite shows 15 pre-existing failures confined to the
concurrently-owned untracked closure-inventory and lock-reconciliation work
(`artifacts.py`, `closure_inventory.py`, `lock_reconciliation.py` and their
tests); those files are outside this Step and were neither read nor staged. The
remaining baseline is green.

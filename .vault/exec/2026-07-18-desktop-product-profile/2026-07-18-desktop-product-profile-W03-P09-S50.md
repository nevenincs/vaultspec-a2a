---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S50'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

# Serve the same authenticated readiness facts through service-state and discovery probes

## Scope

- `src/vaultspec_a2a/api/routes/gateway.py`

## Description

- Build the readiness projection in the service-state verb from the shared
  readiness authority, feeding it the live database and worker probe verdicts the
  verb already computes, and attach it to the service-state response.
- Reuse the single authority rather than recomputing the facts, so the same
  projection a discovery contender probes to validate readiness before attach is
  the one service-state serves - one computation, no drift with the liveness
  surface.

## Outcome

`ruff` and `ty` pass on the module. The api suite passes: 321 passed. The
service-state verb now carries the separated readiness facts (gateway readiness,
worker state, provider eligibility, run admission) alongside its existing
probe-backed status, and the doctor route signature is unchanged because only a
response field was added, not a route.

## Notes

Readiness on this authenticated verb is fed the real probe verdicts, so its
worker and database facts are probe-truthful here while the cheap liveness
surface derives them from seated state; both paths funnel through the one
assembler.

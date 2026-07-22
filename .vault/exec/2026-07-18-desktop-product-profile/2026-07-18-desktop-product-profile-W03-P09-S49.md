---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S49'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

# Return only a minimal alive or not-alive signal from unauthenticated HTTP liveness and return process and product identity plus state only from authenticated readiness responses

## Scope

- `src/vaultspec_a2a/api/app.py`

## Description

- Split the top-level liveness endpoint under the armed desktop profile: an
  unauthenticated caller receives only the minimal liveness body (the single
  liveness fact and nothing else - no version, process id, profile, or state);
  an attach-authenticated caller additionally receives the readiness projection
  from the single readiness authority.
- Add `_http_attach_authorized`, a constant-time attach check mirroring the
  existing WebSocket attach gate, so the liveness boundary reuses the P08 attach
  credential without weakening it.
- Leave the Compose and development profiles on their existing aggregate liveness
  body so their probes stay green; readiness there remains on the separate
  aggregate endpoint.

## Outcome

`ruff` and `ty` pass on the module. The api suite passes: 321 passed. The armed
credential-boundaries certification, which drives a real armed child gateway and
reads unauthenticated liveness over real HTTP, passes: 1 passed - confirming the
minimal body still answers 200 and leaks no secret. Process and product identity
and the separated state facts now cross only the attach-authenticated boundary.

## Notes

The readiness projection is computed by the shared authority rather than
recomputed here, so the liveness surface and the service-state verb cannot
disclose divergent readiness. No Compose consumer of the aggregate readiness
endpoint is touched.

Follow-up closing a review finding: the aggregate liveness route was a second
ungated surface that still disclosed process identity and worker, circuit-breaker,
and backend state to unauthenticated callers. It now returns the same minimal
liveness body under the armed desktop profile, with the full aggregate body
retained for the Compose and development profiles their gateway healthchecks
consume. Every ungated liveness surface is now minimal under the armed profile.

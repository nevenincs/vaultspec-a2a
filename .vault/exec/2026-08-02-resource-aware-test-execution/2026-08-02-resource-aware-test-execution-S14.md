---
tags:
  - '#exec'
  - '#resource-aware-test-execution'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:24d3f62441c12d03b284941dd01bad631f3cf3025323dc9ed498aeda88541467'
step_id: 'S14'
related:
  - "[[2026-08-02-resource-aware-test-execution-plan]]"
---
# Move reservation-backed allocation inside the shared spawning primitives with candidate fallback

## Scope

- `src/vaultspec_a2a/tests/gateway_boot.py`

## Description

- Route the shared boot module's port allocation through held registry
reservations over the scratch band: standalone acquisitions hold for the
process lifetime (atexit tidy, pid-death reclaim), a ready gateway's marker
returns to the band once its bind is proven, and the lazily-bound worker
port's marker is held; the OS ephemeral candidate path remains as the
graceful fallback for a missing config or an exhausted band.

## Outcome

Committed as db41d2cd. Every spawning fixture that routes through the shared module - gateway boots, worker spawns, the compose harness - is default-safe with no declaration anywhere. Consuming suites green (82 tests across registry, process utils, and manager).

## Notes

Proving this live surfaced a real allocator defect (see the audit's reservation-race finding), fixed in eaa416ba with a lifecycle regression test: liveness judged on a stale clock snapshot reclaimed a peer's fresh marker.

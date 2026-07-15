---
tags:
  - '#exec'
  - '#a2a-edge-conformance'
date: '2026-07-15'
modified: '2026-07-15'
step_id: 'S28'
related:
  - "[[2026-07-14-a2a-edge-conformance-plan]]"
---

# Write live tests for discovery freshness, stale-pid detection, single-resident-service semantics, and health-while-degraded

## Scope

- `src/vaultspec_a2a/lifecycle/tests/`

## Description

Live tests for the discovery contract: freshness, stale-pid detection,
single-resident semantics, and health-while-degraded. Commit `5f01de9`.

Created: `src/vaultspec_a2a/lifecycle/tests/test_discovery.py`.

Modified: `src/vaultspec_a2a/lifecycle/tests/conftest.py`.

- Real filesystem, real process-liveness, and a real `/health` server on a real
  socket — no mocks. The classifier is exercised across
  ABSENT/FRESH/STALE/MALFORMED; a fresh heartbeat with a dead pid is proven NOT a
  live resident (the Crashed case attach-never-own guards); single-resident
  liveness holds only when the record is FRESH, the pid is alive, and `/health`
  answers; a degraded gateway (`ready=false`) still answers `/health` and so
  still counts as a live resident; only Absent licenses a start.
- The discovery tests are marked `middleware` (they drive real fs/process/HTTP
  infrastructure) rather than the `core`+`unit` the rest of the lifecycle package
  carries, keeping the marker selections a clean partition.

## Outcome

Complete. Six discovery tests pass; the full lifecycle package passes (24
passed). `ruff` and `ty` clean. A `-m unit` selection deselects the discovery
tests, confirming the partition holds.

## Notes

The single-resident and health-while-degraded tests run a minimal real uvicorn
`/health` server on an ephemeral port, so the pid-plus-health resident check is
proven against an actual answering process, not a stub.

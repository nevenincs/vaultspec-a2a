---
tags:
  - '#exec'
  - '#resource-aware-test-execution'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:9f151e370477b2f8d4b056f130ade21eaa3787e98a09d112c177d57e5483c2a3'
step_id: 'S03'
related:
  - "[[2026-08-02-resource-aware-test-execution-plan]]"
---
# Implement machine-global exclusive and shared resource leases

## Scope

- `src/vaultspec_a2a/testing/leases.py`

## Description

- Implement machine-global leases in `src/vaultspec_a2a/testing/leases.py`: `O_EXCL` markers stamped with holder pid, dead-pid reclaim, mtime TTL as pid-reuse backstop, and a daemon refresher thread heartbeating the marker.
- Support shared claims via per-holder markers with a mutual re-check against the exclusive path; jittered retry prevents lockstep livelock.
- Export `is_pid_alive` from the lifecycle facade for the lease liveness check.

## Outcome

Committed as fae661c5, hardened in d7d026f2 (token-guarded release so a displaced holder cannot delete its successor's marker; injectable refresh interval).

## Notes

Liveness demands pid AND heartbeat together, per the engine precedent of a live process with a dead heartbeat writer.

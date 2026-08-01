---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-25'
modified: '2026-07-25'
body_hash: 'sha256:49566aab12f7d30a65fe004a8d37d2b92de1587c2886a8eb8e6594cdeec6dd80'
step_id: 'S142'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Run the canonical A2A unit gate with just dev test unit

## Scope

- `Justfile`
- `just/dev/test.just`
- `src`
- `tests`

## Description

- Ran the canonical unit gate against a settled tree.

## Outcome

PASS. 2604 passed, 111 deselected, in 17m15s.

## Notes

An earlier run of this same gate reported 2602 passed and was DISCARDED rather
than counted. It overlapped a mutation experiment on the worker, and the suite
spawns real subprocesses that re-read the module from disk, so a mid-flight edit
could reach tests collected after it. A certification gate whose inputs changed
under it certifies nothing, and the difference between the two figures is only
the two tests added meanwhile - which is exactly the kind of coincidence that
would have made the confound invisible had it been accepted.

---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-25'
modified: '2026-07-25'
step_id: 'S156'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Prove failed owner-authorized eviction returns conflict without adoption with real processes

## Scope

- `src/vaultspec_a2a/desktop_tests/test_worker_provenance.py`

## Description

- Drove a real two-gateway, one-worker scenario against the authenticated
  pairing classifier as it is consumed at worker adoption.
- Asserted that an eviction the owner authorized but which then fails is
  reported as a conflict, and that the occupant is not adopted as a fallback.

## Outcome

Closed. The invariant that matters is the negative one: a failed eviction must
not degrade into an adoption. The classifier already ruled on one health read so
that adoption and eviction share a single verdict; this Step supplies the
real-process evidence that the failure branch honours it.

## Notes

Commit `3d31735b`, carrying a `Refs:` trailer. Executed by a dispatched agent;
the closure here rests on the orchestrator's own reading of the landed test and
a green whole-tree gate, because that agent delivered no written report.

---
tags:
  - '#exec'
  - '#control-action-leases'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:4f31faa31e4b2d1e74f6b9214170709990e4b1719fa1c53aa8f74e5598630e43'
step_id: 'S18'
related:
  - "[[2026-08-02-control-action-leases-plan]]"
---

# Prove permission message cancel and verdict race safety

## Scope

- `src/vaultspec_a2a/control/tests`
- `src/vaultspec_a2a/api/tests`

## Description

Exercised permission, message, cancellation, and verdict races plus definite and ambiguous dispatch failures.

## Outcome

The post-fix integrated suite passed 373 tests across database, worker, control, API, lifecycle, graph, thread, and streaming clusters.

## Notes

All new tests import production behavior and use real stores and transports.

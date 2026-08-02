---
tags:
  - '#exec'
  - '#control-action-leases'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:f773a840e2e1dc9d4e6c1747273e83e04233ca6399b50386d2416db202362370'
step_id: 'S08'
related:
  - "[[2026-08-02-control-action-leases-plan]]"
---

# Reduce clarification route to the leased service adapter

## Scope

- `src/vaultspec_a2a/api/routes/gateway.py`
- `src/vaultspec_a2a/api/schemas/gateway.py`

## Description

Reduced the clarification endpoint to validation and translation around the leased orchestration service; exposed the deterministic action key.

## Outcome

The route no longer performs read-then-dispatch orchestration and returns explicit accepted, applied, and action status.

## Notes

One stale exact-response assertion was updated for the additive idempotency key.

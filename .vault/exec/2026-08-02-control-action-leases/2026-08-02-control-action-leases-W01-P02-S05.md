---
tags:
  - '#exec'
  - '#control-action-leases'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:ba59d4d19322e11dca12dbbb9b25e77bcd6d1a70f7dae13212b0f5a7e04665e3'
step_id: 'S05'
related:
  - "[[2026-08-02-control-action-leases-plan]]"
---

# Prove duplicate dispatch ids schedule one executor task

## Scope

- `src/vaultspec_a2a/worker/tests`

## Description

Drove duplicate HTTP dispatches through the real worker application and Executor task boundary.

## Outcome

The worker test proves one executor task for one stable dispatch identity.

## Notes

The integrated deterministic suite includes this proof.

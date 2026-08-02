---
tags:
  - '#exec'
  - '#control-action-leases'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:ec4a8cf5d70659ef4d5ae278e49be1e8be02fe62935f7783c7e9e1ceb9dc0075'
step_id: 'S17'
related:
  - "[[2026-08-02-control-action-leases-plan]]"
---

# Prove lost acknowledgement expired lease and restart redrive

## Scope

- `src/vaultspec_a2a/api/tests`
- `src/vaultspec_a2a/lifecycle/tests`

## Description

Exercised lost acknowledgement, expired lease, worker restart, gateway startup reconciliation, and checkpoint settlement.

## Outcome

Recovery converges on the stored dispatch identity without a second graph effect.

## Notes

The file-backed restart proof uses the production checkpointer and Executor.

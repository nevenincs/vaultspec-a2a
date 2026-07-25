---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-25'
modified: '2026-07-25'
step_id: 'S11'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Hide deleting threads from normal run lookup and list operations while retaining cleanup visibility

## Scope

- `src/vaultspec_a2a/control/thread_service.py`
- `src/vaultspec_a2a/control/thread_state_service.py`

## Description

- Excluded threads in the deleting state from product lookup and list reads.
- Kept them visible to the cleanup path, which must still find them to finish.

## Outcome

Closed. The two halves are equally load-bearing: hiding them from product reads
is what stops a half-deleted thread reappearing to a user, and keeping them
visible to cleanup is what stops a hidden thread becoming unreachable debris.

## Notes

Commit `d4506894`.

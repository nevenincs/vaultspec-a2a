---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-25'
modified: '2026-07-25'
step_id: 'S09'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Implement the idempotent repository operation that creates one deletion saga

## Scope

- `src/vaultspec_a2a/control/repositories`

## Description

- Added `create_deletion_saga` to the deletion-saga repository.
- Made it idempotent: a repeated create transitions the thread once and keeps
  the first manifest rather than recapturing scope.

## Outcome

Closed. Keeping the FIRST manifest is the substantive part. Recapturing scope on
a retry would let the deletion set drift between attempts, which is exactly the
duplicated-source-of-truth failure this phase exists to remove.

## Notes

Commit `37f2b4c0`. Covered by `test_create_is_idempotent_and_keeps_the_first_manifest`
against a real store.

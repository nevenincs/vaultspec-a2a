---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-25'
modified: '2026-07-25'
step_id: 'S109'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Implement the idempotent repository operation that advances one deletion cleanup item

## Scope

- `src/vaultspec_a2a/control/repositories`

## Description

- Added `advance_deletion_cleanup_item`, recording one item's result
  idempotently.
- A later success supersedes a prior failure for the same item.

## Outcome

Closed. Supersession is the part that makes retry meaningful: without it a
transient failure would pin an item as failed forever and the saga could never
reach a finalizable state.

## Notes

Commit `37f2b4c0`. Covered by `test_advance_records_and_is_idempotent` and
`test_advance_supersedes_a_prior_failure`.

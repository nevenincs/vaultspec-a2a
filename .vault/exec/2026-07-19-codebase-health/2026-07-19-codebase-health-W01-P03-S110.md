---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-25'
modified: '2026-07-25'
step_id: 'S110'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Implement the idempotent repository operation that finalizes one completed deletion saga

## Scope

- `src/vaultspec_a2a/control/repositories`

## Description

- Added `finalize_deletion_saga`, which refuses until every manifest item is
  done and only then removes the control rows.

## Outcome

Closed, and this is the guard that makes the whole phase safe. Removing control
rows while an item is outstanding is precisely the nonatomic hard delete the
originating finding named: the rows would be gone, the artifacts would not, and
nothing would remain to say so.

## Notes

Commit `37f2b4c0`. Covered by `test_finalize_refuses_until_every_item_is_done`
and `test_finalize_removes_rows_only_when_complete`.

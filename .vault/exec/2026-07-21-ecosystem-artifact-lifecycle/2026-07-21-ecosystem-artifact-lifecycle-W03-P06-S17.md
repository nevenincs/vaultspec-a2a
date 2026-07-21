---
tags:
  - '#exec'
  - '#ecosystem-artifact-lifecycle'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S17'
related:
  - "[[2026-07-21-ecosystem-artifact-lifecycle-plan]]"
---

# Extend the clear action to cover control actions and permission requests

## Scope

- `src/vaultspec_a2a/control/db.py`

## Description

- Replace the hand-listed truncation set with an explicit ordered sequence
  covering every application table, control actions and permission requests
  among them.
- Order children ahead of the thread they reference so the deletion is valid
  wherever foreign keys are enforced.
- Replace the allowlist assertion with a raised error, since assertions are
  removed under optimised interpretation and this one guards an interpolated
  table name.

## Outcome

Control actions and permission requests are now cleared. Both carry a foreign key to the
thread table and are sequenced ahead of it.

The assertion replacement is the part worth noting beyond the Step's stated scope. The
allowlist check was the only thing standing between an interpolated identifier and the
executed statement, and an assertion is not present under optimised interpretation - so
the guard could be absent exactly where it was most needed. It now raises.

## Notes

The ordered sequence is derived by hand rather than from the metadata's own topological
sort. A generated order would be self-maintaining, but it would also silently reorder if
a relationship changed, and this operation deletes everything a machine holds. A test
asserts the hand-written order agrees with the declared foreign keys, which keeps the
explicitness without letting it drift.

---
tags:
  - '#exec'
  - '#ecosystem-artifact-lifecycle'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S19'
related:
  - "[[2026-07-21-ecosystem-artifact-lifecycle-plan]]"
---

# Extend the clear action to cover the checkpoint store

## Scope

- `src/vaultspec_a2a/control/db.py`

## Description

- Clear the checkpoint tables, resolving them through a dedicated synchronous
  URL so the store is reached whether it shares the application database or has
  one of its own.
- Add that URL accessor, falling back to the application database exactly as the
  runtime savers do.
- Skip a checkpoint table that does not exist, since the store is created by the
  graph library on first use rather than by this project's migrations.
- Order checkpoint writes ahead of the checkpoints they reference.

## Outcome

The checkpoint store is now cleared. This is the substantive half of the Phase: those
tables hold the only durable copy of agent conversation content in the service, so a
clear that spared them left the overwhelming majority of the data behind while reporting
success.

The store is reached through its own resolved URL rather than the application one. By
default the two share a file, but they split when configured, and a truncation that
silently cleared only the shared case would fail exactly on the installations large
enough to have split them.

A missing checkpoint table is skipped rather than treated as an error, because a fresh
installation that has never run a graph legitimately has none. A test asserts that
condition against a real database built from the production metadata.

Gates across the Phase: `ruff check` and `ty check` report all checks passed, the new
suite reports five passed, and the control suite reports one hundred nineteen passed with
six deselected.

## Notes

The count printed on completion now includes checkpoint tables only when they were
present, so the number varies between installations. That is honest but slightly
surprising, and it is preferred to printing a fixed count that overstates what happened.

This Phase does not add retention to the checkpoint store, only truncation. Checkpoints
still accumulate without pruning, depth cap, or vacuum for the lifetime of a thread, and
archiving a thread retains them in full. The operator can now clear everything, which is
not the same as the store being bounded, and no Step in this plan closes that.

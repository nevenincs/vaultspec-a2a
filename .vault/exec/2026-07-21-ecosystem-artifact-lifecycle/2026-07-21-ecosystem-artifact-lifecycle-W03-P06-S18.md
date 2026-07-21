---
tags:
  - '#exec'
  - '#ecosystem-artifact-lifecycle'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S18'
related:
  - "[[2026-07-21-ecosystem-artifact-lifecycle-plan]]"
---

# Extend the clear action to cover task queue entries and thread execution state

## Scope

- `src/vaultspec_a2a/control/db.py`

## Description

- Include queued tasks, execution state, and the authoring event cursor in the
  truncation sequence.
- Add a test asserting the sequence covers every table the production metadata
  declares, so a table added later cannot be quietly omitted.

## Outcome

All nine application tables are now covered, and the coverage is enforced rather than
asserted in prose: a test compares the truncation sequence against the metadata's own
table set and fails on any difference in either direction.

That test is the durable part of this Step. The original defect was not that someone
chose the wrong four tables, but that nothing connected the list to the schema, so the
list stayed correct only until the next table was added. It now cannot.

The authoring cursor is included despite carrying no foreign key. It is monotonic state
describing how far the authoring stream has been consumed, and a database cleared of
threads while retaining a cursor pointing far into that stream would resume mid-history
against rows that no longer exist.

## Notes

Ordering for the cursor is arbitrary since nothing references it; it sits immediately
before the thread table for readability rather than for correctness.

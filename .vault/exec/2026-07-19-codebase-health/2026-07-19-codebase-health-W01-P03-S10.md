---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-25'
modified: '2026-07-25'
step_id: 'S10'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Coordinate checkpoint artifact and control-row deletion from the durable cleanup manifest

## Scope

- `src/vaultspec_a2a/control/thread_service.py`
- `src/vaultspec_a2a/control/cleanup`

## Description

- Drove checkpoint, artifact, and control-row deletion from the persisted
  manifest rather than from a scope computed at call time.
- Added artifact-path containment so an artifact path that escapes the recorded
  workspace root is refused instead of removed.

## Outcome

Closed, and it closes the cross-store half of
`hard-delete-cross-store-nonatomic`: every store is now driven from one durable
record, so an interrupted deletion resumes against the same set it started with.

The containment guard is a genuine safety addition beyond the Step's wording -
deletion executes filesystem removal, and a path that escapes the workspace is
the one case where being wrong is unrecoverable.

## Notes

Commit `5ad477f5`. Containment covered by real-filesystem tests for absolute
escape, parent traversal, and symlink escape.

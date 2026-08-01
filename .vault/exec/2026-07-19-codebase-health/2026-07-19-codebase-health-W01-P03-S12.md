---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-25'
modified: '2026-07-25'
body_hash: 'sha256:0da0fd610d8fb576fb809e3c86fc12c80b4bc0a23ade572990bbc5bb3b85dfce'
step_id: 'S12'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Run checkpoint and artifact cleanup independently so one failure cannot skip later cleanup items

## Scope

- `src/vaultspec_a2a/control/cleanup`
- `src/vaultspec_a2a/checkpointer`

## Description

- Made `execute_cleanup_item` never raise, and `execute_cleanup_manifest`
  execute every not-yet-done item independently.
- Recorded each item's result so a later pass resumes from the manifest rather
  than from the start.

## Outcome

Closed, and it closes `silent-partial-deletion`. Previously one failing item
aborted the remainder, leaving stores inconsistent while the operation reported
nothing useful. Independence is what makes the saga resumable at all: an item
that fails is a recorded failure, not a lost sequence.

## Notes

Commit `f40bf075`. Covered by tests proving an earlier failure does not skip a
later item and a later failure does not undo an earlier one.

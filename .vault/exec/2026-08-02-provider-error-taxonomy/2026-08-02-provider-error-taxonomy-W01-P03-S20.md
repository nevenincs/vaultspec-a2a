---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-02'
modified: '2026-08-03'
body_schema: 'body-v1'
body_hash: 'sha256:fdf697076945a5ae4e6df13342f568ece5ea34bbe22da33f9b5560db4573581c'
step_id: 'S20'
related:
  - "[[2026-08-02-provider-error-taxonomy-plan]]"
---

# Read the condition into the thread state snapshot

## Scope

- `src/vaultspec_a2a/control/thread_state_service.py`

## Description

- Declare the condition on the domain thread-state snapshot beside the reason.
- Read it from the durable row when the snapshot is captured.

## Outcome

The snapshot is what a reload reads, so the condition has to be in it. It is
read from the same durable row, in the same capture, as the reason it sits
beside - not from a live frame and not from a second query - so the two can
never disagree about the run they describe.

The field is optional and defaults to nothing, because a run that never failed
genuinely has no condition, and so does one whose record predates the column.
Neither is a defect; asserting a classification for a run nobody classified
would be.

## Notes

None.

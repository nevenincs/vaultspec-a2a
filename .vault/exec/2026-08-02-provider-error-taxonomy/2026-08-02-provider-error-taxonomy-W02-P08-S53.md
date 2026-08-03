---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-03'
modified: '2026-08-03'
body_schema: 'body-v1'
body_hash: 'sha256:6c5b759987496db422ebc89600b5c9219cde290b9e8e46737bb76140f6301ba3'
step_id: 'S53'
related:
  - "[[2026-08-02-provider-error-taxonomy-plan]]"
---
# Expose the condition on the agent panel view store

## Scope

- `frontend/src/stores/view/agentPanel.ts`

## Description

- Resolve one classification from the authoritative snapshot and the live frames.
- Open a refusal only for a run the authoritative snapshot says FAILED.

## Outcome

Landed with the lifecycle authority in the right place. Only a failed
authoritative snapshot can open a refusal, so a transient live fault cannot make
a running run look refused - which is the failure a frame-first reading would
have produced.

Within a failure the precedence is served-classification first, live frame
filling a snapshot that carries none, floor member if neither. That is the same
authoritative-first, relay-fills-the-gap reading an existing surface in this
package already uses, so it extends a pattern rather than introducing a rival one.

## Notes

One case is documented rather than defended as ideal: the newest error frame
wins, so an unrecognised newest code resolves to the floor and stops the scan
while an older frame carrying a recognised code goes unread. It is the single
place the fallback can return the floor with better evidence one frame back.
Recorded as a known bound rather than a defect, since preferring older evidence
would be its own kind of wrong.

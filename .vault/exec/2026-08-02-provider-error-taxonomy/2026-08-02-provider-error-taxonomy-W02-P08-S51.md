---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-03'
modified: '2026-08-03'
body_schema: 'body-v1'
body_hash: 'sha256:7eb9ecb309f074662725f786aa7ab521d591e20a8ec5b1aaaf7ed583ca4bbd9d'
step_id: 'S51'
related:
  - "[[2026-08-02-provider-error-taxonomy-plan]]"
---
# Read the condition from the a2a run-status payload

## Scope

- `frontend/src/stores/server/agent/a2aTeam.ts`

## Description

- Declare the closed vocabulary and a tolerant reader in their own module.
- Read the classification inside the EXISTING status adapter, beside the fields
  it already reads, rather than opening a second parsing path.

## Outcome

Landed. The reader is deliberately tolerant in an asymmetric way: absence stays
absence, while a value that is PRESENT but outside the vocabulary degrades to the
floor member. Those are different cases and conflating them would be a real
defect - one means the run reported nothing, the other means it reported
something this side has no presentation for. Neither dropping an unrecognised
value nor forwarding it raw to a person is honest.

The vocabulary went into its own module rather than inline, partly for clarity
and partly under real pressure: the adapter's file sits two lines under a hard
module-size ceiling.

## Notes

The producing side was checked BEFORE the consumer was written - both emission
sites put the classification on the frame, live and on replay - so the reader
consumes a field that demonstrably exists rather than one assumed into being.
That check is what separates this from the dead-capability failure the campaign
exists to undo.

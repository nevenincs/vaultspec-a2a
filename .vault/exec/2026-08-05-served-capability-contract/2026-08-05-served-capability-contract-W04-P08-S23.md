---
tags:
  - '#exec'
  - '#served-capability-contract'
date: '2026-08-05'
modified: '2026-08-05'
body_schema: 'body-v1'
body_hash: 'sha256:223e4e71c1b6ba314815c5352e2e5f991ac1adb4f896f0e0525f16786bfcebf0'
step_id: 'S23'
related:
  - "[[2026-08-05-served-capability-contract-plan]]"
---

# F17 two breaks not one, and the file attribution was wrong - the live half drops terminal status because the stream transformer reads only chunk content and never inspects tool_call_chunks, while the snapshot half infers COMPLETED only when a matching ToolMessage exists, which provider-internal actions never produce, so every call falls to PENDING permanently. COMPLETION CRITERION - a REST read of a SETTLED run must show terminal status with locations and content populated where the provider supplied them, because the aggregator state is pruned at settle and fixing the live half alone would leave the audited symptom unchanged. Also give the emitters a way to carry status and locations, which the event type already declares

## Scope

- `src/vaultspec_a2a/streaming/transformer.py`
- `src/vaultspec_a2a/streaming/emitters.py`
- `src/vaultspec_a2a/control/snapshot.py`

## Description

- Advance tool-call status to a terminal value and populate the location and
  content fields, on the live stream and on the settled-run snapshot.

## Outcome

Closes in full, across two commits and TWO INDEPENDENT BREAKS. Either alone
would have left the audited symptom in place, which is why the completion
criterion for this Step was written to require the settled-run read specifically.

THE LIVE HALF. The stream translator now reads the provider's tool-call chunks,
which it previously ignored entirely. Status maps CONSERVATIVELY: anything not a
recognised success spelling becomes failed, never a silent completed - so a
policy rejection cannot be misreported as success, which is the exact shape of
the original finding. The update emitter gained the locations parameter its
domain event already declared but had no way to reach. Proven a FIX: five new
tests were run against reverted pre-fix code and all five failed.

THE SNAPSHOT HALF - THE ONE THAT CLOSES THE CRITERION. Snapshot enrichment now
reads a provider action's own terminal status, content and locations off the
message arguments instead of inferring from tool-message correlation. That
correlation assumed a dispatch style provider-internal actions never use, so
every such call fell to pending permanently.

The classification helpers were RELOCATED INTO A SHARED MODULE so the live
stream and the settled snapshot classify through ONE definition and cannot drift
into disagreeing about the same call. That is the durable part: the two halves
were not merely both fixed, they were made incapable of diverging.

Proven a FIX through the REAL SEAM: six tests driven from the provider's own
completed-action chunk through a genuine message merge into state, with no
hand-built fake state. Reverting the snapshot module ALONE made four of six fail
with pending against completed and pending against failed - the exact audited
shape - while TWO REGRESSION GUARDS PASSED IN BOTH STATES, confirming the
already-correct dispatch path was not broken. Combined run 245 passed.

## Notes

A follow-up check returned clean and the author DECLINED to raise a finding for
it, which is the right call and worth recording. The item-completion and
turn-completion branches are structurally separate, reading different fields, so
the turn branch cannot see or override what the item branch yielded - no fold is
possible. Confirmed independently by the provider agent's live trace, where a
declined call is distinguishable from success on three separate fields.

Declining to raise a finding on a clean result is as much a part of an honest
audit as raising one on a dirty result.

This record was authored by the vault writer from the implementing agent's
report relayed by the routing lead, not from direct observation of the work.

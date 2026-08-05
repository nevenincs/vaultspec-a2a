---
tags:
  - '#exec'
  - '#served-capability-contract'
date: '2026-08-05'
modified: '2026-08-05'
body_schema: 'body-v1'
body_hash: 'sha256:9b07d6a2fc385cea7d63fc9ece2c8e3b19fc083d4ec1c9d7841fd1c2449179e3'
step_id: 'S03'
related:
  - "[[2026-08-05-served-capability-contract-plan]]"
---

# F16 - make the document editor submit its authored output as an engine proposal so the review lane has something to apply

## Scope

- `src/vaultspec_a2a/authoring/submitter.py`

## Description

- Wire the bridged authoring rung so the document editor can submit its authored
  output as an engine proposal, and prove it end to end.

## Outcome

Closes in full, and it completes the chain. A changeset created by the model's
own bridged propose call exists in the engine's authoring plane, verified
INDEPENDENTLY OF THE TEST'S OWN READER by a direct query under the engine
bearer.

TWO DETAILS MAKE IT PROOF RATHER THAN A GREEN, and both are the reason this
closes rather than merely passing.

The actor is an AGENT PRINCIPAL carrying the run's own identity. A call made by
the test harness would have carried a different principal, so the changeset
cannot be the test proving itself - the most common way an end-to-end claim is
really a self-assertion.

And the run identifier is EMBEDDED IN THE CHANGESET IDENTIFIER, with its
timestamp falling inside the test window: the worker restarted, the test ran for
ninety seconds, and the changeset was created inside that span. The only other
changeset sharing the prefix predates the restart. So it is not a leftover from
an earlier attempt, which is the other common way such a claim fails.

Proven a FIX rather than preservation: the same test, same command, same lane
FAILED BEFORE THE WORKER RESTART AND PASSED AFTER, with the worker's start time
confirmed to postdate both fixed modules. The restart is what made the fix
reachable, and the before-and-after straddles exactly that.

THE CHAIN IS NOW COMPLETE END TO END for this lane: the model authors, the
bridged propose call creates an engine changeset, approval and apply move it,
and a file reaches disk. The two halves were proven by different agents against
different parts of the path and they now meet.

## Notes

Landed across two commits - the rung with its tests and the acceptance case,
then a correlation hardening pass with tests for the miss path. The miss path
matters: identity is recovered by correlating with a preceding notification, so
a correlation miss must fail closed rather than fall open, and that behaviour is
tested rather than assumed.

A SEPARATE DEFECT WAS EXPOSED BY THIS PROOF AND IS NOT CLOSED BY IT. The run
projection served empty proposal and changeset identifiers, and a null authoring
session, for the very run whose changeset the engine was simultaneously serving.
That is recorded as its own finding, and it is the same shape as the defect this
Step fixed, inverted - a surface reporting nothing-produced while work
demonstrably happened.

It also retroactively vindicates an earlier retraction: the null authoring
session identifier was once read as evidence that the bridge was unarmed. It is
still null on a run where the bridge provably worked end to end, so that field
never meant what it was taken to mean, and the inference was wrong in exactly
the way its author withdrew it for - before this evidence existed.

This record was authored by the vault writer from the implementing agent's
report relayed by the routing lead, not from direct observation of the work.

---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-02'
modified: '2026-08-03'
body_schema: 'body-v1'
body_hash: 'sha256:daacca29e4fa046a2dda6a8501c81760f0296be3537045ca5c1884d1abf29d2f'
step_id: 'S33'
related:
  - "[[2026-08-02-provider-error-taxonomy-plan]]"
---

# Record a durable reason when a clarification resume is not delivered

## Scope

- `src/vaultspec_a2a/control/clarification_service.py`

## Description

- Record why a resume never reached the parked node, on the arm that knows it did not.
- Commit that account, since the released-claim path previously committed nothing.
- Prove it from a real parked checkpoint driven through the real graph.

## Outcome

Structurally the same problem as the follow-up Step and settled the same way,
through the same named transition rather than a second implementation of it. The
lease migration moved this path out of the route and left it releasing the claim
and returning an error body; on the arm where the claim is released, nothing
durable survived the response.

What differs is what the run is doing at the time. A follow-up that fails leaves
a running run running; a resume that fails leaves the run PARKED on the same
questionnaire, still answerable and still holding the interrupt. That makes the
prohibition on the failure columns sharper rather than weaker: the question is
live, the client can answer it again, and a failure stamp would tell a reloading
panel the run is dead while the checkpoint still holds an open interrupt.

The account is committed explicitly here. The failure arm previously reached its
return without a commit of its own, relying on the release primitive's internal
commit, so a write appended after it would otherwise have been discarded when the
session closed.

## Notes

The account's lifetime is honest but shorter-lived than the follow-up path's.
This path has no pre-dispatch repair transition, so the next attempt does not
clear the reason the way a follow-up attempt clears its own; the reason is
overwritten by a later failed attempt and cleared when the run reaches a terminal
state. A resume that is later redriven successfully and then parks on a second
question can therefore carry a stale account until the run ends. Recorded rather
than fixed by writing repair state on the success path, which would clobber
reasons that other subsystems legitimately own.

The gap first recorded on the shared dispatch-failure transition Step applies
unchanged to both of these paths and is worth restating, because it now has three
call sites: the condition vocabulary has no member for an infrastructure failure,
so a client cannot distinguish "our worker is down, retry shortly" from "we
genuinely do not know", and those want different user actions. Closing it means a
separate infrastructure axis beside the provider one - an amendment to the
governing decision, not an executor's call, and explicitly not a widening of the
frozen enum.

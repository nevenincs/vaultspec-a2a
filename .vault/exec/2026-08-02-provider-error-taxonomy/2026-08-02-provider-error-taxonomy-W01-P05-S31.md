---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-02'
modified: '2026-08-03'
body_schema: 'body-v1'
body_hash: 'sha256:ddecbcd8b67a06ed10a3a5fb5e998b55d842a6f2e097b9241988db906b9875ff'
step_id: 'S31'
related:
  - "[[2026-08-02-provider-error-taxonomy-plan]]"
---

# Record a durable reason where an undelivered follow-up settles

## Scope

- `src/vaultspec_a2a/control/message_service.py`

## Description

- Add a named transition that records why a control dispatch never reached the worker.
- Record it from the follow-up arm that certainly did not deliver, and only that arm.
- Prove the definite arm records its account and the ambiguous arm still records none.

## Outcome

The Step's original wording is obsolete: a concurrent control-action lease
migration re-designed this path, so it no longer drives a failure transition and
no longer writes a thread status. What it does now is release the claim and
return `dispatched=False`, leaving the account of why delivery failed in an HTTP
response body that no reload can recover.

The load-bearing decision is WHICH arm may speak. The lease is released only
where the worker certainly scheduled no task, so that arm knows the message did
not arrive and is the only one entitled to say so durably. The ambiguous arm
retains its lease precisely because delivery is undecided - the worker may have
scheduled the task before its acknowledgement was lost - and recording a
non-delivery there would assert something the gateway cannot observe. The
existing coverage for that arm now asserts the silence is deliberate rather than
incidental.

Neither failure column is touched. A message that did not arrive did not fail the
run, and `failure_reason` and `provider_condition` are both defined as describing
a run that FAILED; stamping either would make a reloading client report a failure
that never happened. The account lands on the repair reason, which is what a
still-live run can honestly carry, and the repair status is left exactly as the
pre-dispatch transition set it - a released claim stays redrivable, so escalating
to the terminal operator-intervention state would contradict the design that
released it. The record is self-clearing: every pre-dispatch transition rewrites
the repair state without a reason, so the next attempt erases the last one's.

## Notes

The Step's scope grew by one file. The repair-state write belongs in the named
transition module that already owns every such write for the route handlers, not
inline in a service, and the clarification Step needs the identical transition -
one authority rather than two parallel implementations.

One honest limit, carried to the feature's queue rather than papered over: the
repair reason is durable but no client-facing projection reads it. The run-status
snapshot carries repair status, execution readiness, and the failure reason, and
none of the three is this. Operators and restart reconciliation see the account;
a reloading panel still does not. Closing that means projecting the repair reason
onto the snapshot, which is concurrently owned work in the durable-carriage
Phase.

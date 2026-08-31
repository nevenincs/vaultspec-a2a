---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-02'
modified: '2026-08-03'
body_schema: 'body-v1'
body_hash: 'sha256:292e0ee70d6aa6bff5c8dc815c29df44de2e6cc3f10ccfaabaa81417b4f626e4'
step_id: 'S40'
related:
  - "[[2026-08-02-provider-error-taxonomy-plan]]"
---

# Prove no failed run persists without a condition across dispatch and executor paths

## Scope

- `src/vaultspec_a2a/api/tests/test_internal.py`

## Description

- Drive a real worker rejection through a real relay into the durable row.
- Assert a dispatch that never left the gateway also records a condition.
- Assert an undelivered resume is not a failed run and records none.
- Mutate each write the sweep depends on and confirm the sweep fails.

## Outcome

The sweep covers the two paths that fail a run WITHOUT any provider being
engaged - a dispatch that never left the gateway, and a worker rejection before
the graph ran. Those are the paths that used to leave a client with a bare
failed status and nothing to act on, and they are the ones the ingest coverage
never reached.

The worker arm is driven end to end rather than asserted at the emitter: a real
executor refuses a real dispatch, reports it through a real bridge posting real
HTTP into the real gateway, and the assertion is on the row the gateway wrote.
Nothing about the condition is checked at the worker, because what the worker
meant to send is not the question - what survived the hop is.

The assertion is deliberately that SOMETHING was recorded rather than that a
particular member was. The floor is the correct value on both these paths, but
pinning the member would turn a test of the invariant into a test of a constant,
and the failure mode being guarded against is a null.

The exception is asserted rather than glossed. An undelivered permission resume
settles the run to INPUT_REQUIRED: the answer did not arrive, but the run is
alive and still parked on its question. It is not a failed run, so it correctly
persists no condition and no reason, and its account survives on the repair
reason instead. A sweep phrased as "every dispatch failure has a condition"
would have been false, and making it true would have meant stamping a failure on
a live run.

Mutation-checked three times. Removing the gateway's condition write failed the
worker arm; removing the dispatch transition's condition failed the dispatch
arm; and forcing that transition to treat every outcome as a failure failed the
exception arm - which is what shows the third assertion is not vacuous. All
three were restored and the sweep returned to green.

## Notes

A latent gap was found and queued rather than fixed here, because closing it
belongs to the Step that owns that transition: the dispatch transition writes
its condition only when a reason is also present, so a caller failing a run with
no reason would persist a null. It is not reachable today - both production
callers substitute a default reason - so the sweep passes honestly, but the
guard is one condition too strong.

The worker arm exercises the missing-graph refusal. The executor path that
carries a LANE-resolved condition rather than the floor is still not wired: the
reader exists on the ingest facade and the terminal emitter accepts the value,
but the executor call site joining them lives in a file another agent holds, and
has been requested from them. Until it lands, a real provider failure records
the floor durably while the live frame carries the finer member.

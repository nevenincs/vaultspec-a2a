---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-02'
modified: '2026-08-03'
body_schema: 'body-v1'
body_hash: 'sha256:e4b63820c2530377e9ec7cf169a7878343baf62e114a8a3cb63a2339f4c16d75'
step_id: 'S24'
related:
  - "[[2026-08-02-provider-error-taxonomy-plan]]"
---

# Prove the condition survives a reload through run-status alone

## Scope

- `src/vaultspec_a2a/api/tests/test_internal.py`

## Description

- Relay a failed terminal carrying a condition over the real internal hop.
- Read the run back through the real product route on a separate connection.
- Assert the condition and the reason both survive with no stream attached.
- Assert a run that never failed discloses no condition.
- Mutate each production write in turn and confirm the proof fails.

## Outcome

The proof is deliberately shaped around the client that was NOT listening. The
error frame carrying the condition is droppable and a reconnecting subscriber
gets a fresh empty queue, so a run's classification is only as recoverable as
this read makes it. Nothing in the test subscribes to a stream: the terminal
arrives over the real worker-to-gateway relay, and the answer is read over the
real product route on a second connection that retains nothing from the first.

Both fields are asserted together. They answer different questions and a client
needs both, so recovering one without the other would be a half-fix that reads
as a pass.

The negative case matters as much: a run that never failed discloses nothing
rather than a floor. An absent condition has to mean no failure, otherwise a
consumer cannot tell an unclassified failure from a healthy run.

Mutation-checked twice, once per production write the claim depends on.
Deleting the projection argument from the response constructor - the exact shape
of the historic loss - turned the served value to null and failed the proof.
Dropping the condition from the durable status write failed the reload proof and
three sibling persistence assertions with it. Both were restored byte-for-byte
and the suite returned to green.

## Notes

The run is seeded directly in the database rather than started through the
public start route, because that route's request model is mid-refactor in the
working tree under a concurrent, unrelated campaign. Seeding the row exercises
every hop this Step actually claims - relay, persist, capture, project, serve -
and avoids binding the proof to a request shape that is in flux.

The first mutation's file also carries that concurrent campaign's in-flight
work. The restore was verified by comparing the exact block against the
committed one rather than by trusting a whole-file diff, whose alignment is
disturbed by the surrounding rewrite.

---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-02'
modified: '2026-08-03'
body_schema: 'body-v1'
body_hash: 'sha256:ae5b8d1dc28d5bf1c5f4497862ba399940c5f0dc6f55b1ac21aa641b49823f38'
step_id: 'S38'
related:
  - "[[2026-08-02-provider-error-taxonomy-plan]]"
---

# Carry status and condition on the terminal replay frame

## Scope

- `src/vaultspec_a2a/api/thread_stream.py`

## Description

- Read the durable reason and condition of the run being attached to.
- Replay the coded error frame before the terminal, as a live client received it.
- Carry the reason on the replayed terminal itself.
- Prove a replayed failure reports both, and a replayed success reports neither.

## Outcome

There is no replay buffer anywhere in this stream: every subscriber gets a fresh
empty queue, so a client that attaches after a run has ended receives exactly the
frames the replay path hand-builds and nothing else. That frame carried the
status alone, which meant a reconnecting client learned that a run failed and
could learn nothing about why without issuing a second, different request.

The fix reproduces what a live client saw rather than inventing a replay-only
shape: the coded error frame first, the terminal second, in that order. The
condition rides the error frame's code, which is where the governing decision put
it and which reuses a catalogued field instead of widening the terminal frame to
carry the same value twice. The reason rides the terminal's detail, which the
frame catalog already admits and which no producer was filling on this path.

Three judgements are load-bearing. The frames are emitted only for a FAILED
terminal, because a replay that reported an error unconditionally would tell
every reconnecting client that a finished run had failed - the guard has its own
test for exactly that inversion. A row that carries a reason but no condition -
one written before the column existed - replays the vocabulary's floor rather
than being suppressed, because the reason is still true and the floor is an
honest statement about what was observed. And the frame reports non-recoverable
regardless of what recoverability meant while the run was alive, because the run
is over: nothing about it can be retried now.

## Notes

Mutation-checked twice against the committed tests. Disabling the error-frame
guard failed both replay cases on the frame-order assertion; dropping the
terminal's detail failed both on the missing key. Both mutations were reverted
byte for byte and the file's diff returned to its pre-mutation shape.

The neighbouring stream suites were run alongside this one. Two clarification
relay tests fail there for an unrelated reason - the run-creation body acquired
required fields under concurrent work and those two callers were not migrated -
which is a failure at run creation, before any stream is opened. Queued for its
owner rather than touched here. The whole-tree type check reports two
diagnostics, both in files this Step does not touch and both already known.

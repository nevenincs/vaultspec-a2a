---
tags:
  - '#exec'
  - '#ecosystem-artifact-lifecycle'
date: '2026-08-05'
modified: '2026-09-03'
body_schema: 'body-v1'
body_hash: 'sha256:50a2c3fe327e847945efe15fed209ea05693194bdc0824cae784660ca4b61c2b'
step_id: 'S29'
related:
  - "[[2026-07-21-ecosystem-artifact-lifecycle-plan]]"
---

# Choose the action-event capture seam and bound it, or record why capture is refused

## Scope

- `src/vaultspec_a2a/streaming/aggregator.py`
- `src/vaultspec_a2a/artifacts/retention.py`

## Description

- Obtain the provider's action-event vocabulary from its own generated protocol
  schema rather than inferring it from the repository or from recall.
- Choose the seam and the mechanism, reusing what one lane already proves
  durable instead of introducing a store.
- Project only the action variants, reading only the fields the schema marks
  required.
- Prove the capture fails without the change before accepting that it works
  with it.

## Outcome

**Capture chosen, bounded, and implemented as PARITY - not as a new store.**

The preceding Step established that one lane already records an agent's actions
durably and the other has no handler for them at all, which inverted the design
this Step was expected to produce. Building an action log would have created a
third at-rest copy of material one lane already checkpoints. So the seam is the
Codex turn consumer, and the mechanism is the one the ACP lane already uses: a
tool-call chunk rides the model's own stream, aggregates into the response
message, and the worker node returns that message as state, which is
checkpointed.

The bound comes with the mechanism rather than being invented. Capture inherits
the existing stream's flow control, and no new channel means no new unbounded
queue - which is also why no retention declaration accompanies it: nothing new
is created that a reaper would need to find.

The event vocabulary was obtained from the app-server's own generated protocol
schema, which the installed CLI emits on request. That mattered: the repository
knew four notification methods and the real surface has fourteen, of which three
are action-shaped. Guessing the names would have produced a handler that silently
matched nothing, and a capture that captures nothing is worse than an absent one
because it looks like coverage.

Two judgements are recorded in the code because they are not obvious:

Completion rather than start. A completed item carries its outcome; a record that
a command BEGAN, which never says whether it succeeded, answers the question
worse than not recording it.

Unrecognised kinds are ignored rather than best-effort captured. The item union
carries eighteen variants and will gain more, and inventing structure for a kind
this lane does not understand would put fiction into a checkpoint - worse than
the silence it replaces.

## Notes

Verified red before green: disabling the type gate fails three of the new tests
with a message naming the consequence rather than the symptom, and restoring it
passes all seven. Without that check the tests would have proved only that the
function is callable.

The projection is unit-verified against schema-shaped payloads, NOT against a
live Codex turn. The schema is authoritative for the wire shape, so the mapping
is sound, but nothing here proves the app-server actually emits these
notifications under this project's exact invocation - one live turn that executes
a command would settle it. Stated rather than implied, because "the schema says
so" and "the provider does so" are different claims and this campaign has been
caught by that distinction before.

Sensitivity, carried forward rather than resolved: this makes command text and
tool arguments durable on the Codex lane, matching what the ACP lane already
does. The preceding Step recorded that the ACP exposure is CURRENT and was never
weighed; this Step extends it deliberately rather than by accident, and the
question of whether either should be redacted at rest belongs to the confinement
trail.

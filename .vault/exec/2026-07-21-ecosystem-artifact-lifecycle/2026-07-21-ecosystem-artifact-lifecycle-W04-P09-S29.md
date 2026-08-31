---
tags:
  - '#exec'
  - '#ecosystem-artifact-lifecycle'
date: '2026-08-05'
modified: '2026-08-05'
body_schema: 'body-v1'
body_hash: 'sha256:cda90f0dd9092954498f903acd5bfc551cd41012add9f5078feb2c6218b624ed'
step_id: 'S29'
related:
  - "[[2026-07-21-ecosystem-artifact-lifecycle-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace ecosystem-artifact-lifecycle with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S29 and 2026-07-21-ecosystem-artifact-lifecycle-plan placeholders are machine-filled by
     `vaultspec-core vault add exec`; do not fill them by hand.

     Related: use wiki-links as '[[yyyy-mm-dd-foo-bar-plan]]' and link the
     parent plan.

     DO NOT add fields beyond those scaffolded; metadata lives
     only in the frontmatter. -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

<!-- STEP RECORD:
     This file represents one Step from the originating plan. Identified
     by its canonical leaf identifier (S##) and ancestor display path.
     The Choose the action-event capture seam and bound it, or record why capture is refused and ## Scope

- `src/vaultspec_a2a/streaming/aggregator.py`
- `src/vaultspec_a2a/artifacts/retention.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Choose the action-event capture seam and bound it, or record why capture is refused

## Scope

- `src/vaultspec_a2a/streaming/aggregator.py`
- `src/vaultspec_a2a/artifacts/retention.py`

## Description

<!-- Succinct line-by-line list of steps executed. Use imperative language, mirroring git commit summary lines. -->

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

<!-- Incidents. Data loss. Difficulties; persistent failures. Skipped work. Scaffolds left in code. Failures. -->

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

---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:280722c187689b44a7f8257a5f2775e02532109ec7b6d40e3e637691a69623e5'
step_id: 'S24'
related:
  - "[[2026-08-02-provider-error-taxonomy-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace provider-error-taxonomy with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S24 and 2026-08-02-provider-error-taxonomy-plan placeholders are machine-filled by
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
     The Prove the condition survives a reload through run-status alone and ## Scope

- `src/vaultspec_a2a/api/tests/test_internal.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

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

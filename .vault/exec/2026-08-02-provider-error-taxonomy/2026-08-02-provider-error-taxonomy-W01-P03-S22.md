---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:d8f17d250f59aa27f7a12ad761fb1585dd8e55f439bb7f79d1cd1c8a9fd46a6a'
step_id: 'S22'
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
     The S22 and 2026-08-02-provider-error-taxonomy-plan placeholders are machine-filled by
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
     The Declare the condition on the run-status response schema and ## Scope

- `src/vaultspec_a2a/api/schemas/gateway.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Declare the condition on the run-status response schema

## Scope

- `src/vaultspec_a2a/api/schemas/gateway.py`

## Description

- Declare the condition on the run-status response beside the failure reason.

## Outcome

This response is where the condition becomes authoritative. The repository's
disclosure discipline is already settled for the pending questionnaire on the
same model: durable state answers the reload, and a relay frame is a
non-authoritative nudge to come and read it. The condition follows that rule
unchanged, and it has to - the error frame carrying it is droppable, so a client
that reloaded, or that never received the frame, has no other source.

Typed as an optional string rather than the enum. The field is a wire contract
consumed by a second repository which validates the value against its own copy
of the closed vocabulary; serving a strict enum here would turn a member that
repository has not adopted yet into a serialization failure on OUR side, when
the honest outcome is for it to receive a value it can decide about. The set is
additive-only by decision, so a reader can rely on old members never changing
meaning.

None for a run that never failed, and for one whose failure predates the durable
column - both are honest absences rather than defects.

## Notes

None.

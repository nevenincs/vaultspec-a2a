---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:b0e125d5360cdc90f6d28fda54f10b0d774f401ab34de8b8f82d702208e43818'
step_id: 'S20'
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
     The S20 and 2026-08-02-provider-error-taxonomy-plan placeholders are machine-filled by
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
     The Read the condition into the thread state snapshot and ## Scope

- `src/vaultspec_a2a/control/thread_state_service.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Read the condition into the thread state snapshot

## Scope

- `src/vaultspec_a2a/control/thread_state_service.py`

## Description

- Declare the condition on the domain thread-state snapshot beside the reason.
- Read it from the durable row when the snapshot is captured.

## Outcome

The snapshot is what a reload reads, so the condition has to be in it. It is
read from the same durable row, in the same capture, as the reason it sits
beside - not from a live frame and not from a second query - so the two can
never disagree about the run they describe.

The field is optional and defaults to nothing, because a run that never failed
genuinely has no condition, and so does one whose record predates the column.
Neither is a defect; asserting a classification for a run nobody classified
would be.

## Notes

None.

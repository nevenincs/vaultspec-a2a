---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:d83d78c7ca6d7a73a9d0cb093c09d09f0ac9aefa2fcc5a3b21a837bf4d69ccef'
step_id: 'S15'
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
     The S15 and 2026-08-02-provider-error-taxonomy-plan placeholders are machine-filled by
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
     The Declare the provider condition column on the thread model and ## Scope

- `src/vaultspec_a2a/database/models.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Declare the provider condition column on the thread model

## Scope

- `src/vaultspec_a2a/database/models.py`

## Description

- Declare the provider condition column beside the durable failure reason.

## Outcome

The typed counterpart to the reason text: the reason says what happened, the
condition says what the reader should do about it. Kept nullable with no default
and no back-fill, because a run that failed before the column existed genuinely
carries no classification and writing one for it would assert we classified runs
we never observed.

The not-null-on-new-failures invariant lives at the write sites rather than in
the schema, deliberately. A database constraint would turn a classification bug
into a write crash that loses the run outcome altogether, which is worse than
persisting an honest floor value.

## Notes

Landed as one commit with the migration and the repository write. Splitting them
would have left the ORM expecting a column the database lacks, so the
intermediate commits could not have run.

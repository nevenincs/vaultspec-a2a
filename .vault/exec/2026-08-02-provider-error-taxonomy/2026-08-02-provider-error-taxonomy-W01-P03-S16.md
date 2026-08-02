---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:27c3116c292c4cbcdb934cda54faddc152428a13db92ba67ce890681f2456b4e'
step_id: 'S16'
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
     The S16 and 2026-08-02-provider-error-taxonomy-plan placeholders are machine-filled by
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
     The Add the provider condition migration revision and ## Scope

- `src/vaultspec_a2a/database/migrations/versions` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Add the provider condition migration revision

## Scope

- `src/vaultspec_a2a/database/migrations/versions`
- `src/vaultspec_a2a/database/tests/test_migrations.py`

## Description

- Add the additive nullable column revision on top of the control-action lease head.
- Advance the four head assertions that pin the expected revision.

## Outcome

Verified forward on a real SQLite database rather than by inspection: alembic
reported `Running upgrade 0012 -> 0013`. The column is an unconstrained string
rather than a native enum, because the vocabulary is a wire contract shared with
a second repository and is additive-only - a new member must never require a
schema migration before it can be stored.

The head assertions were advanced rather than rewritten to derive the head from
the script directory. Deriving it would have been more robust to the next
migration and strictly weaker: pinning is what forces each new revision to be
acknowledged by a human instead of changing the head silently.

## Notes

Two `upgrade(cfg, "0012")` calls were deliberately left alone - they exercise the
lease migration specifically and are not head assertions.

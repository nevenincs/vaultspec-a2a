---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:cdf3a9998093d37d8d96a847d5996f6cf3944e0fafa17d5af8aac4c2e2d8ef7d'
step_id: 'S21'
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
     The S21 and 2026-08-02-provider-error-taxonomy-plan placeholders are machine-filled by
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
     The Declare the condition on the domain snapshot dataclass and ## Scope

- `src/vaultspec_a2a/api/schemas/snapshots.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Declare the condition on the domain snapshot dataclass

## Scope

- `src/vaultspec_a2a/api/schemas/snapshots.py`

## Description

- Declare the condition on the wire snapshot model beside the reason.

## Outcome

One field, and the whole point is which side of a seam it sits on. The
projection between the domain snapshot and this model is a validating
conversion, and it DROPS any field this model does not name - silently, without
raising, and without any signal that a value went missing. That is exactly how
the failure reason was lost once already, after it had been persisted correctly.

Naming the condition on both sides is what stops it following. A value that is
persisted, carried as far as this seam, and then quietly discarded is
indistinguishable from one that was never recorded at all - and the whole
campaign is about not being in that position.

## Notes

None.

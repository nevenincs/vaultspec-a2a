---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:e44d1cb8c391d69c8d849ac431b1c3d8d8e3ac5d842a624141b73fb2f27e0f2b'
step_id: 'S32'
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
     The S32 and 2026-08-02-provider-error-taxonomy-plan placeholders are machine-filled by
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
     The Pass the dispatch failure reason from permission resume and ## Scope

- `src/vaultspec_a2a/control/permission_service.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Pass the dispatch failure reason from permission resume

## Scope

- `src/vaultspec_a2a/control/permission_service.py`

## Description

- Pass the dispatch outcome's own detail as the durable failure reason on permission resume.

## Outcome

Same shape as the run-creation site, with one difference worth stating: this path
fails the thread to INPUT_REQUIRED rather than FAILED, because a permission
resume that could not be delivered leaves the run still parked on its question
rather than dead. The reason is recorded on that transition all the same, so a
reloading panel can say why the answer did not take.

## Notes

This file is concurrently owned by the control-action lease migration. The edit
was confined to the existing failure arm and took none of that work; the
previously-failing applied-stamp test in this area now passes, having been fixed
by its own author.

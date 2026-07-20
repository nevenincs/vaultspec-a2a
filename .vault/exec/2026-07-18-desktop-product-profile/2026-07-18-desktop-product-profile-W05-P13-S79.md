---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-20'
modified: '2026-07-20'
step_id: 'S79'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace desktop-product-profile with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S79 and 2026-07-18-desktop-product-profile-plan placeholders are machine-filled by
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
     The Certify x86-64 Linux capsule closure and upload its pinned component contract and ## Scope

- `.github/workflows/desktop-capsule.yml` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Certify x86-64 Linux capsule closure and upload its pinned component contract

## Scope

- `.github/workflows/desktop-capsule.yml`

## Description

- Publish the capsule workflow on the default branch and dispatch it.
- Build the x86-64 Linux capsule from pinned inputs on a hosted runner.
- Verify the built capsule with the checkout-free verifier.
- Upload the capsule archive and its pinned component contract.

## Outcome

The x86-64 Linux leg completed successfully on a hosted runner. The build
assembled the target capsule from the pinned interpreter, runtime, and
adapter inputs, the verifier accepted it without a source checkout, and the
job uploaded the archive with its pinned component contract as a
digest-stamped artifact of roughly 174.2 megabytes, identified by the
content digest `21f0153dd6caf3f6`.

This is the first execution of this target on real hardware; every earlier
claim for it was metadata-level only.

## Notes

The certification runs on hosted runners because the development host is
Windows-only. Landing the workflow required two fixes found only once
continuous integration executed: whole-tree formatting drift inherited from
the campaign branch, and Windows-only foreign-function helpers that carried
no in-body platform guard and therefore failed type checking on Linux.

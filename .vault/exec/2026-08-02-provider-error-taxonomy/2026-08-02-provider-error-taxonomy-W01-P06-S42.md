---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:d9d8567cbb58fa27f10f22b79a77439b96551a735b760fb4fbdd1b31757f3fd2'
step_id: 'S42'
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
     The S42 and 2026-08-02-provider-error-taxonomy-plan placeholders are machine-filled by
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
     The Withdraw the removed vocabulary from the thread package surface and ## Scope

- `src/vaultspec_a2a/thread/__init__.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Withdraw the removed vocabulary from the thread package surface

## Scope

- `src/vaultspec_a2a/thread/__init__.py`

## Description

- Drop the two re-export statements that carried the removed vocabulary out of
  the errors module and onto the thread package facade.
- Drop the two corresponding entries from the package's `__all__`.

## Outcome

The thread package no longer offers a name the errors module does not define,
which is what makes the tree importable again after the preceding Step deleted
the definitions. The removal reaches the public surface deliberately rather than
incidentally: the governing decision records that removing this vocabulary
touches the package's exported API, and this is where that cost is paid.

Nothing outside the package consumed either name, so no importer had to be
adapted. That was established before the deletion by an AST scan over every
module in the source, development, and script trees, and is confirmed after it
by a whole-tree type check and by whole-tree test collection: collection imports
every module in the package, and a withdrawn export is exactly the defect it
surfaces first. Collection reported 3649 tests collected with no import error.

## Notes

This Step and the preceding one are two halves of one removal, split by file.
The preceding commit deletes the definitions while this facade still re-exported
them, so that commit alone does not import; the tree is green again only as of
this one. Both halves were edited and verified together before either was
committed, so no unverified state was landed, but the intermediate commit is
knowingly non-importable and a bisect landing exactly on it will fail to collect.

A pre-existing import-sorting lint failure in the testing package's default
safety test appeared in the whole-tree lint run partway through this Step,
introduced by concurrent work in this shared worktree. It is outside this Step's
surface and was left alone. Lint over the surfaces this Step touches is clean.

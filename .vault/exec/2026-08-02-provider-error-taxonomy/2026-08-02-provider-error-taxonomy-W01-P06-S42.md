---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-02'
modified: '2026-08-03'
body_schema: 'body-v1'
body_hash: 'sha256:ecea9cb7faec83eaefbf0313828f2c1a4336d97b7a96e8ca4cef2516beebbb5b'
step_id: 'S42'
related:
  - "[[2026-08-02-provider-error-taxonomy-plan]]"
---

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

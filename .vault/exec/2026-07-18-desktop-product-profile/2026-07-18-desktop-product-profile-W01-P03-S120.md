---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S120'
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
     The S120 and 2026-07-18-desktop-product-profile-plan placeholders are machine-filled by
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
     The Carry the dropped-member audit trail from the closure layout onto the installed inventory and the pinned descriptor so the build stage surfaces the data-headers and data-scripts omissions into published evidence as a read-only consumer without re-deriving the layout and ## Scope

- `src/vaultspec_a2a/desktop/installed_inventory.py`
- `src/vaultspec_a2a/desktop/artifacts.py`
- `src/vaultspec_a2a/desktop/capsule_descriptor.py`
- `src/vaultspec_a2a/desktop/capsule_preparation.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Carry the dropped-member audit trail from the closure layout onto the installed inventory and the pinned descriptor so the build stage surfaces the data-headers and data-scripts omissions into published evidence as a read-only consumer without re-deriving the layout

## Scope

- `src/vaultspec_a2a/desktop/installed_inventory.py`
- `src/vaultspec_a2a/desktop/artifacts.py`
- `src/vaultspec_a2a/desktop/capsule_descriptor.py`
- `src/vaultspec_a2a/desktop/capsule_preparation.py`

## Description

- Add a record type for one verified archive member the layout deliberately
  omits from the installed tree (the build-time headers and third-party scripts
  a frozen library runtime never uses), carrying its source member, source
  digest, size, content digest, and drop reason.
- Add an inventory-level field holding those records, sorted and distinct,
  populated by the installed-inventory builders from the closure layout they
  already compute and previously discarded.
- Version the installed-inventory schema forward, since the shape changed.
- Bind the audit trail into the inventory's own content digest (hence the
  descriptor identity that pins it) but never into the placed-tree digest, so a
  closure that omits a member yields the same tree digest as one that never
  carried it.
- Prove the whole seam: the records survive the build-then-load round-trip
  through the real consumer, a real archive carrying both omission kinds yields
  a non-empty trail through the production builder, the tree digest is unchanged
  by the trail, and the new schema version rejects the superseded one.

Modified: `src/vaultspec_a2a/desktop/installed_inventory.py`,
`src/vaultspec_a2a/desktop/artifacts.py`, and the installed-inventory tests.

## Outcome

The build stage now consumes the omission audit trail read-only off the loaded
installed inventories and surfaces it into published installed-tree evidence,
without re-deriving the layout it is forbidden to recompute. The record is
minimal - the consumer supplies the closure discriminator from which inventory
it reads - and the change touches only the inventory model and its builders: no
descriptor, capsule-descriptor, or dashboard-manifest surface changed, so there
is no dashboard-visible churn. Type checks pass on the default and Linux
platforms; formatting and lint are clean; the inventory-consuming suites stay
green across the schema-version bump because they reconcile by round-trip rather
than against frozen digests.

## Notes

- The effective change surface was narrower than the originating row's four
  files: only the inventory model and its builders needed editing, because the
  descriptor already pins the whole inventory by its content digest, so the
  audit trail rides that binding with no descriptor or preparation change.
- A concurrent whole-tree stage from another session captured part of this
  step's uncommitted test edits into an unrelated commit while the build was in
  flight; the fix was to commit the production forward to restore a coherent
  tip rather than rewrite history. The proofs all exist and the tip is green;
  the split attribution is cosmetic. The lesson is to commit each proven
  increment immediately rather than hold a working set on a hot shared tree.

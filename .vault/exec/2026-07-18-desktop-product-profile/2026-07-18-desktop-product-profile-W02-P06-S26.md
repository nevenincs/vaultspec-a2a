---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S26'
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
     The S26 and 2026-07-18-desktop-product-profile-plan placeholders are machine-filled by
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
     The Bind mutable-store membership derivability and schema versions into the component manifest and ## Scope

- `src/vaultspec_a2a/desktop/manifest.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Bind mutable-store membership derivability and schema versions into the component manifest

## Scope

- `src/vaultspec_a2a/desktop/manifest.py`

## Description

- Add a mutable consistency-group declaration to the component-manifest contract:
  a `MutableStoreKind` enum (primary and checkpoint databases), a
  `StoreSchemaAuthority` enum, a `MutableStore` model carrying kind, derivability,
  and schema authority, and a `ConsistencyGroup` model that validates the
  membership is complete and each kind is declared once.
- Bind a required `consistency_group` field into `ComponentManifest`, so each
  generation declares which mutable schema-bearing stores snapshot and restore
  together and whether each may be omitted because it is provably derivable.
- Reconcile schema-version facts rather than duplicate them: the primary store's
  schema authority points at the manifest's existing `compatibility.migration_range`
  (single authority, base and head not restated); the checkpoint store declares
  the checkpointer schema authority the migration range does not cover.
- Declare the canonical `DESKTOP_CONSISTENCY_GROUP` (both stores non-derivable,
  therefore mandatory) and emit it from the deterministic manifest emitter.
- Bump `contract_version` 1.0 to 1.1 per the contract's own directional rule:
  adding a required field means an older 1.0 parser must refuse the document.
- Regenerate the committed `schemas/desktop-capsule-manifest.json` from the
  production exporter, and derive the cross-language golden vector and its
  digest from the settled model (never hand-copied from a failing run): the
  existing golden manifest gains the consistency group and the version bump, and
  its canonical bytes and SHA-256 are recomputed through the canonical serializer.
- Update the affected tests to the new shape: the golden-vector digest and a new
  group assertion in the manifest test; the manifest payload plus completeness,
  duplicate, membership, and reconciliation tests in the contract test, including
  one binding the manifest membership and derivability to the snapshot module's
  runtime `consistency_group_members` so the two cannot silently diverge.

## Outcome

The component manifest now declares its mutable consistency-group membership,
per-store derivability, and schema authority as a versioned 1.1 contract,
reconciled with the migration section as a single authority and grounded in the
S25 snapshot membership. `ruff` and `ty` pass; the full contract and manifest
suites (141) and the schema/golden regeneration pass; the packaged-schema gate
passes against the committed generation.

## Notes

- The manifest membership is declared in the dashboard-facing contract module,
  which stays self-contained (it imports no internal runtime module); a
  reconciliation test binds it to the snapshot module's runtime authority instead
  of a code-level import, keeping the cross-repository boundary clean.
- This Step was deferred to phase-last and landed only after the concurrent
  session's migration-head work (`test_manifest.py` 0007 to 0008 and migration
  0008) settled at HEAD, so the golden vector was derived against a stable head.

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
     The Bind single-authority mutable-store membership, explicit schema versions, derivability evidence, compatibility rules, and exact generated-schema constraints into the component manifest and ## Scope

- `src/vaultspec_a2a/desktop/snapshot.py`
- `src/vaultspec_a2a/desktop/contract.py`
- `src/vaultspec_a2a/desktop/manifest.py`
- `src/vaultspec_a2a/desktop/migration.py`
- `src/vaultspec_a2a/database/checkpoint_schema.py`
- `src/vaultspec_a2a/database/compatibility.py`
- `src/vaultspec_a2a/database/migrations/__init__.py`
- `schemas/desktop-capsule-manifest.json`
- `src/vaultspec_a2a/desktop/tests/fixtures/component-manifest-canonical-v1.b64`
- `src/vaultspec_a2a/desktop/tests/fixtures/component-manifest-canonical-v1.sha256`
- `src/vaultspec_a2a/desktop/tests/test_contract.py`
- `src/vaultspec_a2a/desktop/tests/test_manifest.py`
- `src/vaultspec_a2a/desktop/tests/test_migration.py`
- `src/vaultspec_a2a/database/tests/test_checkpoint_schema.py`
- `src/vaultspec_a2a/database/tests/test_checkpoint_state_migration.py`
- `src/vaultspec_a2a/database/tests/test_compatibility.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Bind single-authority mutable-store membership, explicit schema versions, derivability evidence, compatibility rules, and exact generated-schema constraints into the component manifest

## Scope

- `src/vaultspec_a2a/desktop/snapshot.py`
- `src/vaultspec_a2a/desktop/contract.py`
- `src/vaultspec_a2a/desktop/manifest.py`
- `src/vaultspec_a2a/desktop/migration.py`
- `src/vaultspec_a2a/database/checkpoint_schema.py`
- `src/vaultspec_a2a/database/compatibility.py`
- `src/vaultspec_a2a/database/migrations/__init__.py`
- `schemas/desktop-capsule-manifest.json`
- `src/vaultspec_a2a/desktop/tests/fixtures/component-manifest-canonical-v1.b64`
- `src/vaultspec_a2a/desktop/tests/fixtures/component-manifest-canonical-v1.sha256`
- `src/vaultspec_a2a/desktop/tests/test_contract.py`
- `src/vaultspec_a2a/desktop/tests/test_manifest.py`
- `src/vaultspec_a2a/desktop/tests/test_migration.py`
- `src/vaultspec_a2a/database/tests/test_checkpoint_schema.py`
- `src/vaultspec_a2a/database/tests/test_checkpoint_state_migration.py`
- `src/vaultspec_a2a/database/tests/test_compatibility.py`

## Description

- Make `snapshot.consistency_group_specifications` the sole production
  declaration of mutable-store membership, wire kinds, schema authority, and
  current non-derivability. Runtime seating and manifest emission consume it.
- Publish contract `2.0`. The required consistency group is a breaking change,
  so legacy 1.x manifests are not claimed as readable.
- Require exactly one primary and one checkpoint store. Both carry
  `derivable=false`, an authority, and an explicit schema version.
- Derive the primary schema version from the packaged Alembic head. Require the
  generated schema's migration head and primary store version to equal it.
- Define checkpoint schema `1.0.0` over the complete normalized SQLite object
  closure, column facts, and primary-key positions. Store its structural digest
  in a project-owned singleton marker.
- Decode real LangGraph checkpoint blobs with the production serializer. Add
  missing state-driven-development fields before installing the schema marker.
- Make ordinary compatibility validation read-only. Validate checkpoint schema
  identity and serialized state through one already-open SQLite connection.
- Regenerate the committed JSON Schema and cross-language canonical fixture.
  Exercise Pydantic and the real Draft 2020-12 validator independently.

## Outcome

Local S26 implementation passes. The component manifest now carries enforceable
membership, derivability, authority, and schema-version evidence under contract
`2.0`. Staged migration writes checkpoint identity only after real state
migration, and ordinary boot validates without mutation.

The desktop and database campaign passes 378 tests. Focused CLI migration tests
pass four tests. Ruff, scoped type checking, generated-schema equality, and diff
hygiene pass.

## Notes

- Formal review of the first implementation found five high-severity defects.
  S26 was reopened, its scope expanded through the plan CLI, and every local
  defect was repaired before closure.
- A later review found the old SDD backfill was a no-op on current LangGraph
  storage. It also found incomplete schema identity and writable split reads.
  Those findings are resolved in this pass.
- The last review found corrupt SQLite files escaped as bare database errors.
  Both store paths now retain context and the staged-migration remedy.
- The dashboard parser still ignores contract `2.0` safety fields. Dashboard
  `S06` owns parser enforcement, and `S145` owns the real producer-consumer
  workflow. Dashboard `S49` remains blocked until both close.

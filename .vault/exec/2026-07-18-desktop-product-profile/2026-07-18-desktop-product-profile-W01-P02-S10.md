---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S10'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

# Define the versioned desktop component manifest contract consumed by dashboard packaging

## Scope

- `schemas/desktop-capsule-manifest.json`

## Description

- Create the `desktop` package as a facade over `contract.py`, exposing the public contract types through `__all__`.
- Define the Pydantic authority `ComponentManifest` carrying an explicit `contract_version` whose compatibility rule is major-version equality (`contract_versions_compatible`).
- Model component identity, target triple, compatibility, entrypoints, per-asset digests, assets, licenses, and dependency-lock identity as bounded, extra-forbidding, frozen models.
- Declare the five accepted targets as Rust-style triples in `TargetTriple`, matching the platform vocabulary already used by the locked dependency closure.
- Declare the base-closure asset kinds in `ComponentAssetKind` and pin CPython `3.13`, Node.js `22`, and ACP `0.59.0` as documented version constants.
- Type both launch surfaces in `ComponentEntrypoints`: the dashboard-owned gateway launch and the caller-owned standalone MCP launch, each a capsule-relative invocation validated against its declared kind.
- Constrain every hash to a lowercase SHA-256 hex digest and carry a single `digest_algorithm` field governing all asset and lock digests.
- Export the JSON Schema snapshot through `export_component_manifest_schema` and commit it as the cross-repo contract, matching the repository's other exported `schemas` snapshots (`json.dumps(schema, indent=2)` plus a trailing newline).

## Outcome

The versioned component contract is the single boundary the dashboard reads about an A2A generation; the committed schema snapshot equals the Pydantic authority's exported schema. Modules are pure and under the size limit, and imports are relative within the package. Lint, format, and type checks pass on the new package, and the `test_dependency_closure` wheel gate remains green (5 passed), confirming the new package adds no dependency drift.

## Notes

The manifest permits a subset of asset kinds (unique kinds, at least one) rather than hard-requiring all four; complete four-asset capsule manifests are produced at capsule assembly. This keeps the emitter honest against the artifacts actually available at each stage. No mocks, skips, or type-ignores were used.

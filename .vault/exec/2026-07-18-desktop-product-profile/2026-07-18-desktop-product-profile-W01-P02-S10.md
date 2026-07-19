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
- Define the Pydantic authority `ComponentManifest` carrying a bounded, canonical `MAJOR.MINOR` `contract_version`; make compatibility consumer-directional so the major must match and the declared minor cannot exceed the consumer's supported minor.
- Model component identity, target triple, compatibility, entrypoints, per-asset digests, assets, licenses, and dependency-lock identity as bounded, extra-forbidding, frozen models.
- Declare the five accepted targets as Rust-style triples in `TargetTriple`, matching the platform vocabulary already used by the locked dependency closure.
- Require exactly one of each of the four production base-closure asset kinds and pin CPython `3.13`, Node.js `22`, and ACP `0.59.0` in both production validation and the exported schema.
- Type both launch surfaces in `ComponentEntrypoints`: the dashboard-owned gateway launch and the caller-owned standalone MCP launch, each a bounded capsule-relative invocation validated against its declared kind; reject rooted paths, separators inside segments, empty and dot segments, NUL, excessive segment counts, and excessive segment lengths.
- Constrain the served gateway API range to ordered canonical `vN` values.
- Constrain every hash to a lowercase SHA-256 hex digest and carry a single `digest_algorithm` field governing all asset and lock digests.
- Export the JSON Schema snapshot through `export_component_manifest_schema`, including collection, path-segment, exact-closure, runtime-pin, and string bounds, and commit it as the cross-repo contract (`json.dumps(schema, indent=2)` plus a trailing newline).

## Outcome

The versioned component contract is the single boundary the dashboard reads about an A2A generation. It now rejects partial or duplicate base closures, unpinned managed runtimes, malformed or consumer-incompatible version assumptions, unordered API ranges, and commands that could escape or ambiguously resolve against a capsule root. The committed schema snapshot exactly equals the production exporter and carries the cross-repository structural constraints. Focused production-model tests pass without test doubles, and scoped lint, format, and type checks pass.

## Notes

The accepted desktop-product-profile ADR places component identity, target, compatibility, digests, dependency-lock identity, migration range, and launch surfaces in this A2A manifest. It places immutable dashboard/A2A selection in the later complete release-set receipt. Therefore this component contract does not invent a dashboard source commit, dashboard archive, or cross-component release identity. No fakes, mocks, stubs, patches, monkeypatches, skips, expected failures, or type ignores were used.

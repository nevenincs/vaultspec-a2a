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
- Type both launch surfaces with distinct Literal-discriminated models so the production validator and Draft 2020-12 schema independently require gateway kind `gateway` and standalone MCP kind `standalone-mcp`.
- Bound capsule-relative commands and reject rooted paths, embedded separators, empty and dot segments, ASCII controls, Windows-invalid characters and reserved device basenames (including legacy `COM¹`/`²`/`³` and `LPT¹`/`²`/`³` spellings), trailing dot/space, excessive segment counts, and excessive segment lengths in both validation authorities.
- Constrain the served gateway API range to the schema-visible supported-version enum, currently exactly `v1` as implemented by the production gateway router, while retaining ordered runtime semantics for future enum additions.
- Bind component identity version to the A2A distribution asset version in the production model and state this cross-field invariant explicitly without claiming Draft 2020-12 can enforce cross-instance equality.
- Define every asset digest as the digest of immutable source artifact bytes used for assembly; installed-tree integrity remains owned by later SBOM and release-set steps.
- Export the JSON Schema snapshot through `export_component_manifest_schema`, including collection, path-segment, exact-closure, runtime-pin, and string bounds, and commit it as the cross-repo contract (`json.dumps(schema, indent=2)` plus a trailing newline).
- Force-include the root schema snapshot at stable installed resource path `vaultspec_a2a/desktop/schemas/desktop-capsule-manifest.json` and inspect/read that resource from a real working-tree wheel installation; clean immutable-artifact proof remains the S12 gate.

## Outcome

The versioned component contract is the single boundary the dashboard reads about an A2A generation. It rejects partial or duplicate base closures, contradictory A2A identities, unpinned managed runtimes, malformed or consumer-incompatible contract versions, unsupported API versions, crossed launch-surface kinds, and non-portable commands. The committed Draft 2020-12 snapshot exactly equals the production exporter and enforces every structural cross-repository constraint. A real working-tree wheel carries the byte-exact snapshot at the stable package-resource path and exposes it through `importlib.resources`; S12 still owns clean immutable-artifact installation proof. Focused production-model and Draft 2020-12 behavioral tests pass without test doubles, and scoped lint, format, type, TOML, lock-consistency, and diff checks pass.

## Notes

The accepted desktop-product-profile ADR places component identity, target, compatibility, digests, dependency-lock identity, migration range, and launch surfaces in this A2A manifest. It places immutable dashboard/A2A selection in the later complete release-set receipt. Therefore this component contract does not invent a dashboard source commit, dashboard archive, or cross-component release identity. Draft 2020-12 has no standard keyword for equality between two instance locations, so Python consumers receive the binding validator and schema-only consumers receive an explicit `x-vaultspec-invariants` declaration; this record does not overstate schema enforcement. The concurrent S11 emitter suite must supply the exact four-asset closure and the new typed entrypoint models before it can become a downstream green gate. No fakes, mocks, stubs, patches, monkeypatches, skips, expected failures, or type ignores were used.

Independent final review found no unresolved critical, high, or medium issue. It
reproduced 111 focused contract passes, including runtime and Draft 2020-12
rejection of all six superscript Windows device names, and independently passed
Ruff checking, Ruff formatting, and scoped type checking. S11 remains open and
is not represented as green by this contract-only closure.

---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S12'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

# Prove a clean built wheel contains package assets excludes tests and satisfies a real dashboard release-manifest fixture by pinned identity

## Scope

- `src/vaultspec_a2a/desktop_tests/test_component_contract.py`

## Description

- Add a certification gate that builds the real distribution wheel with `uv build --wheel --no-sources` in a module fixture and unpacks it for inspection.
- Assert the wheel ships production presets and the package-owned migrations (`env.py`, `script.py.mako`, `versions`) while carrying zero mock-preset, test, or `conftest` entries, and never embeds the component schema.
- Assert the committed `schemas/desktop-capsule-manifest.json` still equals the Pydantic authority's exported schema.
- Emit a real component manifest through the S11 emitter from the built wheel: identity and entrypoints from the wheel's own `.dist-info`, the Alembic range from the wheel's own migration scripts, real SHA-256 digests of four real on-disk assets, and the real repository lock files.
- Source four real asset bytes: the built wheel as the A2A distribution, the running CPython 3.13 interpreter as the Python runtime, the checkout ACP adapter file as the ACP asset with its version read from the real `package-lock.json`, and the resolvable `node` executable as the Node runtime.
- Prove the Node pin as an explicit real negative and positive pair: the contract rejects the host's real Node version string, and accepts the manifest when the Node asset declares the capsule spec pin.
- Author the A2A-owned dashboard release-set fixture and prove the binding: the fixture's pinned identity matches the emitted manifest, a pin carrying the freshly emitted manifest digest binds, and the fixture's prior-generation digest, a mismatched version, and a mismatched target all fail.

## Outcome

The gate certifies the whole component boundary end to end from real artifacts: a clean wheel with the correct closure, a schema snapshot that matches its authority, a manifest emitted from real wheel and asset bytes, and a real cross-repository release-set binding that accepts the pinned generation and rejects drift. The full desktop suite is green: 67 passed across the emitter unit tests, the dependency-closure gate, and this component-contract gate; `ruff check`, `ruff format --check`, and `ty check` pass on both desktop trees.

## Notes

Two honest gaps are recorded rather than faked. The build host's `node` is v24, not the pinned 22, so the positive manifest's Node asset declares the capsule spec pin (`22`) while digesting the real host `node` bytes; the true Node 22 binary is bound at capsule assembly. The A2A distribution declares no SPDX license in its metadata, so the A2A asset records an explicit `LicenseRef` placeholder. The manifest-digest binding is proven non-tautologically by hashing the serialized manifest bytes the dashboard would receive and asserting equality with `component_manifest_digest`. No mocks, monkeypatches, skips, xfails, or type ignores were used. Ruff and ty were briefly unavailable in the shared venv mid-step (a concurrent re-sync) and were run through `uvx ruff@0.15.22`; both later resolved through the project environment and passed.

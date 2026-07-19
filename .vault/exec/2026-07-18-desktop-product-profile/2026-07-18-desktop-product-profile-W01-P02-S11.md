---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S11'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

# Emit pinned component identity target compatibility gateway and standalone MCP entrypoints digests assets licenses and dependency-lock identity

## Scope

- `src/vaultspec_a2a/desktop/manifest.py`

## Description

- Implement `emit_component_manifest` as a pure, deterministic emitter that produces a component manifest from explicit real inputs with no network, no wall-clock, and no working-directory discovery.
- Derive component identity and both console-script entrypoints from the supplied `importlib.metadata` distribution, mapping `vaultspec-a2a` to the gateway surface and `vaultspec-mcp` to the standalone surface.
- Compute the capsule-relative launch invocation per target, using the bundled environment's `Scripts` directory on Windows and `bin` elsewhere.
- Read the Alembic base and head revisions from the package-owned migration script directory through `ScriptDirectory`, rejecting ambiguous multi-head or multi-base trees.
- Compute real SHA-256 digests of every provided asset path and of the `uv.lock` and `package-lock.json` locks, sorting assets by kind for deterministic output.
- Add `component_manifest_digest`, hashing the manifest's canonical JSON serialization so a release-set receipt can pin a generation by digest.
- Define `AssetSource` and `ManifestEmissionError`, and export the emitter surface through the desktop facade.
- Prove the emitter with in-package unit tests over real `.dist-info` distributions, the real package migration scripts, and real asset files whose digests are recomputed independently.

## Outcome

The emitter turns the built distribution plus pinned assets and locks into a deterministic, self-describing manifest. Unit tests pass (15 passed across `test_contract.py` and `test_manifest.py`), including negative paths for a missing standalone entrypoint, a missing asset file, and duplicate asset kinds. Lint, format, and type checks pass on the package; the wheel carries the desktop production modules and excludes `desktop/tests`; the `test_dependency_closure` gate remains green (5 passed).

## Notes

The gateway API version range is an explicit emitter input rather than an import of a private gateway constant, keeping the emitter decoupled and pure. Tests build real on-disk distribution metadata via `PathDistribution` instead of any mock or monkeypatch, so every expectation derives from the same real sources the emitter reads. No skips, xfails, or type-ignores were introduced.

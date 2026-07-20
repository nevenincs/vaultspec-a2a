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
- `src/vaultspec_a2a/desktop/__init__.py`
- `src/vaultspec_a2a/desktop/tests/test_manifest.py`
- `src/vaultspec_a2a/desktop/tests/fixtures/component-manifest-canonical-v1.b64`
- `src/vaultspec_a2a/desktop/tests/fixtures/component-manifest-canonical-v1.sha256`

## Description

- Implement `emit_component_manifest` as a deterministic emitter over explicit immutable source artifacts and lock paths, with no network, wall-clock, working-directory discovery, or installed-distribution authority.
- Require the exact built A2A wheel to be the `a2a-distribution` source. Copy and SHA-256 hash it in one bounded pass through one source handle, then parse only that private snapshot so the digest, identity, entrypoints, and migration range cannot observe different wheel bytes.
- Bound wheel source size, archive entry count, expanded size, compression amplification, metadata, entrypoint, and `WHEEL` documents, and the migration subtree. Reject duplicate archive members, unsafe paths, migration symlinks, and oversized migration members without extracting the archive wholesale.
- Require exactly one root-level wheel `.dist-info` directory containing the single `METADATA`, `entry_points.txt`, and `WHEEL` members. Bind that directory's wheel-normalized distribution and version identity to `METADATA`, rejecting nested, mixed-root, or misnamed metadata documents.
- Derive normalized component name, version, and MIT `License-Expression` from the snapshot's `METADATA`. Parse `entry_points.txt` with duplicate-strict, case-preserving semantics and require exactly one `vaultspec-a2a` gateway and one `vaultspec-a2a-mcp` standalone MCP console script, each bound to its committed production reference, before any dictionary collapse.
- Compute the capsule-relative launch invocation per target, using the bundled environment's `Scripts` directory on Windows and `bin` elsewhere.
- Materialize only the bounded package migration subtree from the private wheel snapshot and read its `0001` base and `0007` head through `ScriptDirectory`; an independent checkout migration path is not accepted. Reject Windows device basenames, alternate data stream colons, invalid characters, trailing dots or spaces, ASCII controls including DEL, overlong segments, excessive depth, and case-insensitive path collisions before writing. Normalize syntax, import, revision, and runtime failures while loading the graph.
- Validate the bounded asset container, `AssetSource` members, enum kinds, `Path` values, source strings through the production `ComponentAsset` model, target, API range, digest enum, and dependency-lock paths before artifact content reads. Exactly four unique kinds and the CPython 3.13, Node.js 22, and ACP 0.59.0 pins win before path access. The caller cannot supply an A2A version or license; the wheel constructs both component identity and A2A asset facts.
- Resolve every wheel, asset, and lock path to an ordinary regular file before streaming it. Each opened descriptor is checked again with `fstat`, and nonblocking input flags prevent named pipes or devices from hanging the emitter.
- Record every asset digest as the SHA-256 of its immutable source artifact bytes and hash the real `uv.lock` and `package-lock.json` bytes. Installed-tree integrity is outside this manifest authority.
- Define and publicly export `vaultspec-canonical-json-v1`: recursively sorted object keys, compact separators, no insignificant whitespace, unescaped Unicode, UTF-8 bytes, no byte-order mark, and no trailing newline. The profile rejects numeric values. `component_manifest_digest` hashes exactly these bytes with the manifest's declared digest algorithm and accepts no independent algorithm override.
- Add a stable base64 canonical-byte vector with nested objects, non-ASCII text, quote and backslash escaping, plus a literal SHA-256 golden value for later Rust and dashboard consumers.
- Construct the schema-visible `GatewayEntrypoint` and `StandaloneMcpEntrypoint` types and normalize expected archive, metadata, file, Alembic, and Pydantic failures to path-safe `ManifestEmissionError` results.

## Outcome

The emitter now binds all A2A-owned manifest facts to one immutable wheel snapshot and emits a deterministic, cross-language manifest identity. The focused contract and emitter suite passes 137 tests, including a real working-tree wheel build, same-root and metadata-identity binding, MIT license derivation, exact wheel digest binding, wheel-contained migration discovery, duplicate and redirected console-script rejection, Windows device and alternate-data-stream rejection, case-collision and resource-bound enforcement, regular-file preflight, migration exception normalization, typed target commands, path-safe failures, and the canonical JSON golden vector. Ruff lint and format checks and `ty` pass on the changed production and test modules. The independent dependency-closure gate remains green with five tests, for 142 passing tests across the requested suites.

An explicit working-tree build produced one 608,058-byte wheel with 235 entries and one `vaultspec_a2a-0.1.0.dist-info` root containing exactly one `METADATA`, one `entry_points.txt`, and one `WHEEL`. Its `License-Expression` is `MIT`; it carries 11 packaged migration files, both required console scripts, the production manifest module, and no desktop test modules.

## Notes

The gateway API range remains an explicit typed input. The A2A license is now a wheel-owned fact derived from the same bounded `METADATA` as name and version. Licenses for the CPython, Node.js, and ACP source artifacts remain explicit bounded inputs; S13 must bind those declarations to acquired source-artifact licensing evidence.

S12 still owns clean immutable-artifact and dashboard fixture proof. S13 owns acquisition and verification of the real target runtime source archives and their licensing evidence. S14 owns capsule assembly, SBOM, executable-mode, and installed-tree integrity. This step does not prove a clean installed capsule, complete target closure, SBOM, dashboard release set, or release-set receipt.

No fake, mock, stub, patch, monkeypatch, skip, xfail, or type-ignore was introduced. The positive emitter evidence builds and reads the actual working-tree wheel; negative archive cases mutate copies of that wheel only to exercise fail-closed parsing.

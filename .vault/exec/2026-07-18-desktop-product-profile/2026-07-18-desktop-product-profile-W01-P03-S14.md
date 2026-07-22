---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S14'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

# Verify capsule identity target closure entrypoints digests licenses and software bill of materials without a source checkout

## Scope

- `scripts/verify_desktop_capsule.py`

## Description

Reworked `scripts/verify_desktop_capsule.py` from the legacy assets-ZIP verifier into
the generation-layout, producer-side, source-free verifier. It opens the same
digest-pinned descriptor + content-addressed cache the build consumed (read-only, through
the production verified-input session) and reconciles what is actually on disk in the
caller-owned generation against that authority and against the generation's own
machine-readable evidence. No source checkout, no re-materialization.

`verify` checks (all read-only, fail-closed):
- **Structure**: the generation holds exactly the `capsule/` tree and its `capsule.zip`
  sibling, nothing else.
- **Manifest**: the on-disk manifest triple (`component-manifest.json` +
  `.canonical.bin` + `.digest.sha256`) equals the manifest re-emitted from the retained
  session evidence; schema-valid; contract-compatible; target matches.
- **Closures**: every declared Python and ACP `InstalledFileRecord` is present at
  `capsule/<install_root>/<relative_path>` with the exact size and SHA-256 its inventory
  records; each console-script entrypoint is placed and recorded `0755`.
- **Licenses**: every dependency and first-party license the inventories record is placed
  with its exact bytes.
- **Dropped evidence**: the installed-tree evidence's `vaultspec:dropped-members` equals
  the inventory-bound `.dropped` records of both closures (the S120 accessor), tagged by
  closure - every declared omission recorded, nothing extra.
- **Installed-tree evidence**: every file the evidence enumerates exists on disk with the
  recorded digest, size, and mode (this covers the verbatim interpreter subtrees, the
  launchers, and the dependency locks) and binds the component-manifest digest.
- **Archive**: `capsule.zip` is well formed (`testzip`) and every entry's bytes match the
  corresponding materialized file exactly, and the entry set equals the on-disk tree.

`sbom` emits a minimal JSON SBOM (v2) from the verified generation: identity, target,
contract version, the four base-closure components, entrypoints, installed-file count,
and the dropped-member trail.

### A real S13 build bug this verifier caught

While proving S14 end-to-end, the installed-tree-evidence reconciliation failed closed on
`cpython/bin/python3.13` being absent: the S13 build recorded the two verbatim interpreter
subtrees in `installed-tree.cdx.json` at `cpython/...`/`node/...` instead of
`runtime/cpython/...`/`runtime/node/...`. The projector roots its returned evidence at the
leased `runtime` directory it claims into, so the paths were missing the `runtime/`
segment. The files land correctly on disk (the deterministic archive, which scans the
tree, was always right), but the evidence mis-recorded their paths - a real defect the
S13 test never caught because it only checked on-disk existence, not evidence-vs-disk
reconciliation. Fixed in `scripts/build_desktop_capsule.py` by re-rooting each
interpreter-subtree `ProjectedFile` under `runtime/` so every emitted evidence path is
capsule-relative, matching the closures, launchers, and locks. This is the verifier
earning its keep.

### Tests

Added `src/vaultspec_a2a/desktop/tests/test_verify_desktop_capsule.py`:
- Offline unit tests over the pure structure check (accept, missing-archive, unexpected
  entry).
- `service`-marked end-to-end tests that reuse the S13 build fixture to assemble a real
  generation, verify it passes, and prove every integrity check fails closed under a real
  on-disk tamper: a flipped closure byte (`digest does not match`), a doctored
  drop-audit-trail (`drop-audit-trail` mismatch), and a corrupted archive; plus an SBOM
  emission reflecting the verified generation.

## Outcome

- Real end-to-end proof (LINUX_X86_64, real generation from the S13 build): faithful
  generation verifies clean; three independent tampers each fail closed; SBOM reflects
  the generation.
- `ruff format` + `ruff check` clean; `ty check` clean on default and
  `--python-platform linux` (both the verifier and the build fix).
- Service suite: 5 verify + 2 build tests green together (the build fix keeps the build's
  determinism + drop-trail tests green while making the verifier's evidence reconciliation
  pass). Full desktop offline suite green.
- Boundary self-grep clean.

## Notes

- The verifier consumes the SAME inputs the build did (descriptor + cache + locks); it is
  an independent second consumer proving the generation matches the pinned inputs, not a
  self-referential check. The dropped evidence is asserted against the inventory-bound
  `session.{python,acp}_installed.dropped` accessor, never a descriptor field.
- Residual for the set: the legacy `src/vaultspec_a2a/desktop_tests/test_capsule_build.py`
  and `test_capsule_verify.py` (old assets/*-ZIP contract + removed `--cache-dir` CLI,
  both `service`-marked) still target the old contract; they are reworked/retired with S15
  (the workflow re-chain) so the set does not leave a red cert. Left untouched here.

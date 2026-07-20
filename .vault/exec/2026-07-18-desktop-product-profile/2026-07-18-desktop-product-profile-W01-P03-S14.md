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

- Created `scripts/verify_desktop_capsule.py`: standalone capsule verifier CLI with
  `verify` and `sbom` subcommands. Operates on a capsule ZIP alone — no source checkout
  or git required. Runs seven checks in sequence: required-entry presence, JSON Schema
  validation, contract-version compatibility, per-asset digest re-derivation, canonical-
  bytes round-trip consistency, canonical-digest file correctness. `--quiet` flag
  suppresses progress output. Imports from the installed package for schema and manifest
  types; stdlib-only for digest computation (hashlib, tomllib, zipfile, json).
- Added `sbom` subcommand emitting a minimal JSON SBOM: component identity, four
  base-closure assets with versions/licenses/digests, entrypoints, and the full Python
  dependency closure parsed from the embedded `a2a/pylock.toml`.
- Created `src/vaultspec_a2a/desktop_tests/test_capsule_verify.py`: 11 `@pytest.mark.service`
  tests covering: exit-0 on valid capsule, `--quiet` suppresses progress, exit non-zero on
  truncated archive, missing entry, and tampered asset byte-flip; SBOM four-component
  coverage, target/contract-version correctness, non-empty python closure, entrypoint
  presence, and hex-SHA256 canonical digest format.

## Outcome

`verify` and `sbom` commands run against the local Windows x86-64 capsule (74.1 MiB)
built in S13. All 11 service tests exercised real ZIP bytes and real subprocess
invocations of the verifier. The tampered-asset test confirmed single-byte corruption
detection. Non-service baseline (140 tests, 22 deselected) unchanged. `ruff check`,
`ruff format`, and `ty check` all clean.

Note: 5 pre-existing errors in `test_dependency_closure.py` are unrelated to this step
(confirmed by stash isolation — errors appear without S14 files present).

## Notes

The `capsule_zip` fixture is module-scoped but not marked `@pytest.mark.service`; pytest
forbids marks on fixtures. The service-marked tests that consume the fixture are excluded
from the default suite by the `-m "not service"` deselection filter.

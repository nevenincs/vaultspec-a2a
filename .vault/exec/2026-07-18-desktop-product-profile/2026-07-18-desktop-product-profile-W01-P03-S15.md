---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S15'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

# Create the artifact workflow that publishes deterministic component archives and manifests for dashboard consumption

## Scope

- `.github/workflows/desktop-capsule.yml`

## Description

Reworked `.github/workflows/desktop-capsule.yml` from the legacy assets-ZIP
build-then-verify workflow into the full prepare -> build -> verify -> publish re-chain,
across the four-target matrix (aarch64-apple-darwin/macos-14, aarch64-linux/ubuntu-arm,
x86_64-linux/ubuntu, x86_64-windows/windows-2022). Each matrix leg:

- **Prepare** (the only network-bound stage): `scripts/prepare_desktop_capsule.py` mints
  the digest-pinned descriptor into `dist/inputs/capsule-inputs.toml` and populates the
  content-addressed cache `.capsule-cache`; its two stdout lines (descriptor path,
  `sha256:<digest>`) are captured into step outputs.
- **Donor** (Windows only): downloads the pinned `[launcher_stub]` console-stub donor
  wheel from `scripts/desktop_capsule_inputs.toml`, verifies its SHA-256 against the
  pinned digest (fails closed on mismatch), and exposes its path. Preparation-class
  network access acquires it; the build stays a pure consumer that only reads the passed
  path.
- **Build**: `scripts/build_desktop_capsule.py` consumes the descriptor + cache read-only
  and assembles the deterministic generation `dist/capsules/<target>/` (the capsule tree
  plus `capsule.zip`); the Windows leg passes `--launcher-stub-donor`.
- **Verify**: `scripts/verify_desktop_capsule.py verify` reconciles the generation
  source-free against the pinned inputs; a non-zero exit fails the job before any publish
  step, so only a verified generation is ever published.
- **SBOM + digest**: the SBOM and the detached archive digest are written beside the
  generation (not inside it, so the generation stays exactly the capsule tree plus its
  archive).
- **Publish**: uploads only the verified generation's `capsule.zip`, its `.sha256`, the
  SBOM, and the installed-tree evidence + component manifest the dashboard consumes.

Retired the two legacy service certs that asserted the dead assets-ZIP contract and the
removed `--cache-dir`/`<target>.zip` CLI (`git rm`
`src/vaultspec_a2a/desktop_tests/test_capsule_build.py` and `test_capsule_verify.py`),
superseded by the new real-generation, tamper-fails-closed tests
(`src/vaultspec_a2a/desktop/tests/test_build_desktop_capsule.py` and
`test_verify_desktop_capsule.py`). The rest of `desktop_tests/` is left untouched.

The donor pin follows the workflow-only acquisition path: preparation and the workflow
own network access; build/verify/publish stay pure consumers. Prepare acquiring the donor
into the cache (so it flows prepare -> cache -> build like every other input) is logged as
a clean post-set follow-up.

## Outcome

- Workflow parses (Python `yaml.safe_load`: 12 steps in the correct sequence) and passes
  `actionlint` cleanly (exit 0, including shellcheck of every `run` block).
- All third-party actions remain pinned to commit SHAs (`actions/checkout` v4.3.1,
  `astral-sh/setup-uv` v7, `actions/cache` v4.2.3, `actions/upload-artifact` v4.6.2).
- The synced `--group tooling` environment carries the stage dependencies (jsonschema for
  verify, tomlkit for prepare, packaging; click is a base dependency), so the sync line
  is unchanged.
- Boundary self-grep clean.

## Notes

- The workflow cannot be executed on this host; it is validated structurally
  (`yaml.safe_load` + `actionlint`) and each stage's CLI contract is proven by the
  service end-to-end tests that assemble and verify a real generation.
- `fail-fast: false` keeps one flaky runner from aborting the other targets. The cache key
  now also hashes `uv.lock` and `package-lock.json` so a lock change invalidates the
  cached inputs.
- The build reads `source_date_epoch` from the descriptor, so no epoch is threaded through
  the workflow; determinism is anchored in the pinned descriptor.

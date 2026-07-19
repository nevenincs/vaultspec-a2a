---
tags:
  - '#audit'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
  - "[[2026-07-18-desktop-product-profile-adr]]"
---

# `desktop-product-profile` audit: `w01 p03 capsule review`

## Scope

Code review for W01.P03 S13-S15 (commits 7df84b1d, 5323b167, 2c525cca on
`fix/ecosystem-health`). Files audited: `scripts/build_desktop_capsule.py`,
`scripts/desktop_capsule_inputs.toml`, `scripts/verify_desktop_capsule.py`,
`src/vaultspec_a2a/desktop_tests/test_capsule_build.py`,
`src/vaultspec_a2a/desktop_tests/test_capsule_verify.py`,
`.github/workflows/desktop-capsule.yml`.

## Findings

### S13 | revision required

Four high-severity findings remain. The determinism evidence contradicts the
manifest's wheel-digest binding. Malformed SHA-256 pins disable verification,
the build mixes `HEAD` wheel bytes with live-worktree locks and behavior, and
the capsule omits the transitive Python and ACP payloads required for offline
installation. One medium finding covers checkout-free lock, license, and SBOM
evidence that the artifact does not carry.

### S14 | revision required

Five high-severity findings remain. The verifier accepts the incomplete S13
payload as a target closure, does not verify dependency-lock identity, and
trusts manifest target, entrypoint, and license claims without deriving them
from artifacts. Its SBOM omits material transitive evidence, and every test
runs through the source checkout. Duplicate-member and archive-resource safety
and the missing rejection matrix add two medium findings.

### S15 | revision required

The workflow-specific findings are resolved. It uses a current Intel macOS
runner, creates a locked environment, and retains read-only repository
permission. Tag-triggered release publication and its unsupported notes are
removed while S13 and S14 remain open. Manual artifacts carry the outer ZIP
SHA-256 in their name and include a checksum file. S15 remains open because its
inputs are not yet certifiable release artifacts.

The lower-severity observations from the first pass remain useful: downloads
and ZIP assembly buffer whole assets, and the Python inventory drops extras,
markers, hashes, and relationships. They do not reduce the blocking findings.

## Verified strengths

- The service gates use real subprocesses and archive bytes without prohibited
  doubles, skips, or expected failures.
- Static Python checks pass and all deliverable modules remain below 1,000 lines.
- Workflow actions are pinned to full commit hashes.
- The builder and verifier command-line entrypoints load successfully.

## Status

**REVISION REQUIRED** — S13, S14, and S15 remain open. The complete
severity-classified queue is recorded in
`2026-07-19-desktop-product-profile-audit`.

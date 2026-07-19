---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

# `desktop-product-profile` `W01.P03` summary

Phase P03 delivered the capsule assembly, verification, and publication
tooling, completing Wave W01: the desktop capsule boundary is closed and the
dashboard can consume deterministic, pinned, verifiable component artifacts.
All three Steps (S13, S14, S15) are closed with an independent code review
returning PASS with only low findings.

- Created: `scripts/desktop_capsule_inputs.toml`,
  `scripts/build_desktop_capsule.py`, `scripts/verify_desktop_capsule.py`,
  `.github/workflows/desktop-capsule.yml`,
  `src/vaultspec_a2a/desktop_tests/test_capsule_build.py`,
  `src/vaultspec_a2a/desktop_tests/test_capsule_verify.py`

## Description

S13 implemented the deterministic capsule builder: a pinned-inputs manifest
records SHA-256 digests for the CPython 3.13.5 standalone runtime, Node.js
22.17.0, and the ACP 0.59.0 adapter tarball for all five accepted target
triples; the builder downloads through a digest-verified content-addressed
cache, assembles the documented capsule layout, emits the component manifest
through the real desktop emitter, and produces the capsule archive with a
detached manifest. A real Windows x86-64 build was proven end to end twice:
74.1 MiB capsule, byte-identical canonical manifest digest across both runs.
The archive itself is not byte-identical between builds (wheel-internal
timestamps vary); determinism is claimed and proven at the canonical manifest
level only.

S14 implemented the standalone verifier and software bill of materials
emitter: schema validation, contract-version compatibility, per-asset digest
re-derivation from real archive bytes, canonical-bytes round-trip, and
canonical-digest agreement, with proven tamper rejection (a single flipped
asset byte fails verification with a digest mismatch). The SBOM lists the
four capsule components with versions, licenses, and digests plus the locked
Python closure. The verifier runs without a source checkout.

S15 authored the five-target publication workflow: a fail-open-free matrix
across the accepted triples with SHA-pinned actions, digest-keyed download
caching, build-then-verify per leg, artifact upload of capsule, manifest, and
SBOM, and a tag-triggered release publication job for dashboard consumption.

## Tests

Twenty-two real-artifact certification tests cover the builder and verifier
behind the established service marker, exercising real downloads, real
archives, and real tamper cases; the default desktop surface stays green
(145 passed with service tests deselected). Ruff, formatting, and ty checks
pass on all new files; workflow YAML parses cleanly. Honest gaps recorded:
the workflow has not executed on hosted runners (no push occurred), non-local
targets are pinned and digest-verified at metadata level only, and the
dependency-closure gate was red at review time solely from an uncommitted
concurrent lockfile drift outside this phase's scope. Independent review
passed with three low findings (whole-file buffering in the builder and a
deliberately minimal SBOM closure).

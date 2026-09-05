---
tags:
  - '#exec'
  - '#embedded-runtime-remediation'
date: '2026-09-05'
modified: '2026-09-05'
body_schema: 'body-v2'
body_hash: 'sha256:f7db65aafb674f82fc90ac473699e92de7e1864866a0404d32325b769d7ce619'
step_id: 'S02'
related:
  - "[[2026-09-05-embedded-runtime-remediation-plan]]"
---

# Resolve the intended consumer's lifecycle, discovery, broker and schema contract and record the coordinated change boundary before either repository changes wire behavior

## Scope

- `Dashboard engine/crates/vaultspec-product/src`

## Changes

- `M` `.vault/audit/2026-09-05-embedded-runtime-remediation-implementation-review-audit.md`
- `A` `.vault/exec/2026-09-05-embedded-runtime-remediation/2026-09-05-embedded-runtime-remediation-W01-P01-S02.md`
- `M` `.vault/index/embedded-runtime-remediation.index.md`
- `M` `.vault/plan/2026-09-05-embedded-runtime-remediation-plan.md`
- `verify:` `uv run --locked python -m pytest src/vaultspec_a2a/lifecycle/tests/test_discovery_desktop.py src/vaultspec_a2a/api/tests/test_engine_edge_bounds_agreement.py src/vaultspec_a2a/api/tests/test_admin_shutdown_auth.py src/vaultspec_a2a/api/tests/test_lifecycle_capability_dependency.py src/vaultspec_a2a/api/tests/test_v1_attach_whitelist.py -q` -> `pass`
- `verify:` `cargo test -p vaultspec-product discovery` -> `pass`
- `verify:` `cargo test -p vaultspec-api a2a_lifecycle` -> `pass`
- `verify:` `cargo test -p vaultspec-api ops::a2a` -> `pass` (70 tests)
- `verify:` `uv run --locked python -` contract assertion over Dashboard ADR/reference -> `pass` (4 operations, routes, bounds, envelopes, mutual link, producer-first provenance)

## Notes

The authoritative coordinated contract is Dashboard reference `2026-09-05-a2a-integration-verification-embedded-runtime-coordinated-contract-reference` at Dashboard commit `02101b52d15e31a23b9c5cb181c9f6e648b25261`. Runtime wire behavior remains assigned to `S43`-`S50`.

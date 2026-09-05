---
tags:
  - '#exec'
  - '#embedded-runtime-remediation'
date: '2026-09-05'
modified: '2026-09-05'
body_schema: 'body-v2'
body_hash: 'sha256:2a6e8f072286b23788065e5d9174201f13565a93de61eef1d85aebc53500f7cc'
step_id: 'S01'
related:
  - "[[2026-09-05-embedded-runtime-remediation-plan]]"
---

# Record the intended A2A commit/binary identity, Dashboard generation, A01-A34 applicability, supported-mode inventory and pre-test queue/deadline/host limits without changing the frozen acceptance thresholds

## Scope

- `qualification evidence`

## Changes

- `A` `.vault/audit/2026-09-05-embedded-runtime-remediation-implementation-review-audit.md`
- `A` `.vault/exec/2026-09-05-embedded-runtime-remediation/2026-09-05-embedded-runtime-remediation-W01-P01-S01.md`
- `M` `.vault/index/embedded-runtime-remediation.index.md`
- `M` `.vault/plan/2026-09-05-embedded-runtime-remediation-plan.md`
- `A` `.vault/reference/2026-09-05-embedded-runtime-remediation-qualification-inputs-reference.md`
- `verify:` `uv run --locked --group freeze python scripts/build_binary.py --dist tmp/embedded-runtime-remediation-s01-binary` -> `pass`
- `verify:` `ProviderFactory().catalog_registrations(Path.cwd(), serve_in_process_lanes=False)` plus `is_catalog_lane_admissible` under `uv run --locked python` -> `pass`
- `verify:` resolved settings whitelist under `uv run --locked python` -> `pass`
- `verify:` `uv run --locked python -m pytest src/vaultspec_a2a/providers/tests/test_lane_admission.py src/vaultspec_a2a/desktop_tests/test_component_contract.py -q` -> `pass` (35 passed)
- `verify:` `vaultspec-core vault check all` -> `pass`

## Correction pass

- Added exact replay commands, canonical raw observations, SHA-256 output digests, and material source hashes for repository/binary identity, host/toolchain, runtime configuration, external catalog disposition, conditional in-process posture, and Dashboard consumer bounds.
- Added the active Dashboard broker read/control/catalog limits (`15s`/`60s`/`45s`), product discovery freshness and stop-plan limits (`30s`/`5s`), and drain connect/max limits (`5s`/`600s`) at Dashboard commit `330b2efe294c8ab134fff2142f9fae98afd14fec`.
- Separated SQLite busy-timeout and observed library pool behavior from the PostgreSQL-only configured QueuePool size `5` plus overflow `10`.
- Recorded `deterministic/in-process-deterministic` and `mock/in-process-mock`, their current hidden posture, conditional serving requirements, and exclusion from external-provider proof.
- Appended resolution evidence to all four formal-review findings and queued the Dashboard Cargo launch limitation without deleting review history.
- `verify:` `uv run --locked python -m pytest src/vaultspec_a2a/providers/tests/test_in_process_catalog.py src/vaultspec_a2a/providers/tests/test_lane_admission.py -q` -> `pass` (73 passed in 3.70s)
- `verify:` locked Python SQLite engine assertion -> `pass` (`AsyncAdaptedQueuePool` observed; 5/10 settings confirmed PostgreSQL-branch-only; busy timeout `5,000ms`)
- `verify:` exact Dashboard source-constant assertions plus SHA-256 recomputation for `a2a.rs`, `a2a_lifecycle.rs`, and `gateway_drain.rs` -> `pass` (all nine bounds present; hashes match the frozen manifest)

- `verify:` `vaultspec-core vault check all` after Core-managed S01 closure -> `pass` (0 errors, 0 warnings)

## Notes

- `cargo test -p vaultspec-product gateway_drain` and `cargo test -p vaultspec-api a2a_lifecycle` could not start because Cargo resolves to `C:\ci-shared\cargo\bin\cargo.exe` and Windows reports that no application is associated with the specified file. This is queued as `dashboard-rust-toolchain-unlaunchable` (low, validation environment, open/non-blocking) for repair and rerun before S02 consumer-contract verification; it is not recorded as a product-test failure.

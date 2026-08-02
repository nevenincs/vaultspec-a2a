---
tags:
  - '#exec'
  - '#repository-tooling-hardening'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:86f6a49abaac6a9d96507cbd46408d44562d78c976f0edabdf2a17402b89e4aa'
step_id: 'S24'
related:
  - "[[2026-07-19-repository-tooling-hardening-plan]]"
---
# Repair strict types in the control and repository production domains.

## Scope

- `src/vaultspec_a2a/control`
- `src/vaultspec_a2a/control/repositories`
- `src/vaultspec_a2a/authoring/discovery.py`
- `src/vaultspec_a2a/api/routes/gateway.py`
- `src/vaultspec_a2a/desktop_tests/test_worker_health_decode_contract.py`

## Description

- Repaired strict production contracts in dispatch, event relay, run-state capture, health probing, and worker lifecycle boundaries.
- Replaced private health probes with one public immutable result contract and migrated all assigned consumers directly.
- Removed duplicate checkpoint reads from run status and proved one captured tuple over a real TCP and SQLite path.
- Added real loopback, SQLite, subprocess, and gateway regressions for malformed payloads, terminal cleanup, pairing redaction, and token-present health eviction.
- Completed independent audit cycles and repaired every review finding before closing the step.

## Outcome

The source-only control census reports 0 Basedpyright errors and 0 warnings across every non-test control Python module. Ty passes across the same census. Focused real behavior lanes passed for dispatch, event relay, checkpoint capture, worker health, discovery, watchdog, pairing redaction, and public no-competitor behavior.

## Notes

The broad test-tree checker retains historical diagnostics outside the production S24 contract, including 10 in app and redispatch test scope, 32 in broader gateway scope, and 267 in two event test files. These are explicitly bounded in their audit records and are not claimed clean. The planned S24 scope expansion to discovery, gateway, and desktop health decoding was necessary to remove a real private health-probe contract without compatibility aliases. Existing Python 3.13 `importlib.metadata` deprecation warnings occurred in focused gateway lanes.

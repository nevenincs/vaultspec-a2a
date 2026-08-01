---
tags:
  - '#exec'
  - '#repository-tooling-hardening'
date: '2026-08-01'
modified: '2026-08-01'
body_schema: 'body-v1'
body_hash: 'sha256:416ef74c25baa1e69880f95ff5caf384f7f8a201072c8c6020262ea337dabf83'
step_id: 'S18'
related:
  - "[[2026-07-19-repository-tooling-hardening-plan]]"
---
# Prove exact root, workflow, sentinel, platform, advisory, blocking, and duplication anti-drift invariants from the real registry.

## Scope

- `dev/toolchain.py`
- `dev/tests/test_ci_contract.py`

## Description

- Added a real registry-and-tracked-file anti-drift guard.
- Inserted the existing harness test lane into canonical CI after Vault validation.
- Asserted exact hosted sentinel, advisory, duplication, and cross-platform Ty contracts.

## Outcome

The guard passes both directly and through `just test harness`. It proves the canonical CI path executes the guard, root and hosted dispatch do not drift, and the strict sentinel contract is exact. Independent review initially found two coverage gaps; the corrected test now asserts the exact hosted sentinel set and full Ty command prefix, and re-review cleared the blocker.

## Notes

No live service, provider, GPU, or full unit certification claim is made. The test is a static repository-contract guard; canonical full CI evidence remains a later settled-tree obligation.

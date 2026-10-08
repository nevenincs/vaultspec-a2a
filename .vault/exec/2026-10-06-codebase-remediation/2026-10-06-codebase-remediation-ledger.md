---
tags:
  - '#exec'
  - '#codebase-remediation'
date: '2026-10-06'
modified: '2026-10-08'
body_schema: 'body-v2'
body_hash: 'sha256:506f4e8905029c5432ef2297dddccaa07b5448216651f6cddeef811a40fb4c71'
related:
  - "[[2026-10-06-codebase-remediation-plan]]"
---

# `codebase-remediation` ledger

## Changes

- `S116` `M` `src/vaultspec_a2a/api/tests/test_harness_gateway.py`
- `S116` `M` `src/vaultspec_a2a/control/tests/test_direct_control_leases.py`
- `S116` `M` `.vault/audit/2026-10-06-codebase-remediation-audit.md`
- `S116` `verify:` `uv run --no-sync --frozen --no-default-groups --group tooling python -m vaultspec_a2a.testing.runner -- src/vaultspec_a2a/api/tests/test_harness_gateway.py src/vaultspec_a2a/control/tests/test_direct_control_leases.py -q` -> `pass`
- `S116` `verify:` `uv run --no-sync --frozen --no-default-groups --group tooling basedpyright src/vaultspec_a2a/api/tests/test_harness_gateway.py src/vaultspec_a2a/control/tests/test_direct_control_leases.py` -> `pass`
- `S116` `verify:` `uv run --no-sync --frozen --no-default-groups --group tooling python -m dev.quality.types` -> `pass`
- `S116` `verify:` `uv run --no-sync vaultspec-core vault check all` -> `pass`
- `S116` `verify:` `PYTEST_ADDOPTS=--require-prerequisite=docker just test-service-path src/vaultspec_a2a/service_tests/test_permissions_resume.py` -> `pass`

## Notes

- `S116` S116 remains open: full non-service baseline and functional gates are pending; this checkpoint records only the strict-type correction and its 16 passing focused tests.
- `S116` Fresh tool-cores S15 verification repaired the missing checkpoint; metadata-only maintenance reviewed. Permissions service coverage gap recorded; S116 remains open.

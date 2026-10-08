---
tags:
  - '#exec'
  - '#codebase-remediation'
date: '2026-10-06'
modified: '2026-10-08'
body_schema: 'body-v2'
body_hash: 'sha256:5e7436d2a29c0b7e43124f5339f2d95a5008c6e890a785bc4de589be28e3e4b3'
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
- `S116` `M` `docs/api/modules.rst`
- `S116` `M` `src/vaultspec_a2a/api/__init__.py`
- `S116` `M` `src/vaultspec_a2a/streaming/__init__.py`
- `S116` `M` `src/vaultspec_a2a/streaming/aggregator.py`
- `S116` `verify:` `just docs-build` -> `pass`
- `S116` `verify:` `just test-harness` -> `pass`
- `S116` `verify:` `just deps-check` -> `pass`
- `S116` `verify:` `just audit-deps` -> `pass`
- `S116` `verify:` `uv run --no-sync --frozen --no-default-groups --group tooling python -m vaultspec_a2a.testing.runner -- packaging/tests/test_build_artifact_contents.py -k not_frozen_placeholder -q` -> `pass`
- `S116` `verify:` `uv run --no-sync --frozen --no-default-groups --group tooling python -m vaultspec_a2a.testing.runner -- packaging/tests/test_build_artifact_contents.py -k 'not frozen_onedir' -q` -> `pass`
- `S116` `M` `Justfile`
- `S116` `M` `src/vaultspec_a2a/control/tests/test_provider_eligibility_credentials.py`
- `S116` `verify:` `just test-provider-gates --junitxml=.pytest-tmp/green-20261008/provider-gates-current.xml` -> `pass`
- `S116` `verify:` `just check-workflow` -> `pass`
- `S116` `verify:` `uv run --no-sync --frozen --no-default-groups --group tooling basedpyright src/vaultspec_a2a/control/tests/test_provider_eligibility_credentials.py` -> `pass`

## Notes

- `S116` S116 remains open: full non-service baseline and functional gates are pending; this checkpoint records only the strict-type correction and its 16 passing focused tests.
- `S116` Fresh tool-cores S15 verification repaired the missing checkpoint; metadata-only maintenance reviewed. Permissions service coverage gap recorded; S116 remains open.
- `S116` Correction: the earlier wheel verification row containing `not_frozen_placeholder` is a transcription error, not an executed command, and must not be used as evidence. The following correctly transcribed selection passed three tests with one deselected; wheel-contents.log records the actual run.

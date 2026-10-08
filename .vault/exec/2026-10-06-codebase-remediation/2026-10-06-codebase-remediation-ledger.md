---
tags:
  - '#exec'
  - '#codebase-remediation'
date: '2026-10-06'
modified: '2026-10-08'
body_schema: 'body-v2'
body_hash: 'sha256:2c1d161392b8cfe89855e08c82d69522932cb08e7f9ac489cda4b1009a15070c'
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
- `S99` `M` `src/vaultspec_a2a/control/graph_definition.py`
- `S99` `M` `src/vaultspec_a2a/control/leased_dispatch.py`
- `S99` `M` `src/vaultspec_a2a/control/tests/test_graph_definition.py`
- `S99` `M` `src/vaultspec_a2a/testing/seeding.py`
- `S99` `verify:` `uv run --no-sync --frozen --no-default-groups --group tooling python -m vaultspec_a2a.testing.runner -- src/vaultspec_a2a/control/tests/test_graph_definition.py --junitxml=.pytest-tmp/green-20261008/autonomy-final.xml --no-showlocals -q` -> `pass`
- `S99` `verify:` `uv run --no-sync --frozen --no-default-groups --group tooling python -m vaultspec_a2a.testing.runner -- -m service --require-prerequisite=docker src/vaultspec_a2a/service_tests/test_run_continuation_live.py --junitxml=.pytest-tmp/green-20261008/continuation-fixed.xml --no-showlocals` -> `pass`
- `S116` `M` `src/vaultspec_a2a/service_tests/test_worker_attach_provenance.py`
- `S116` `verify:` `uv run --no-sync --frozen --no-default-groups --group tooling python -m vaultspec_a2a.testing.runner -- -m service src/vaultspec_a2a/service_tests/test_worker_attach_provenance.py --junitxml=.pytest-tmp/green-20261008/attachment-fixed.xml --no-showlocals` -> `pass`
- `S116` `M` `src/vaultspec_a2a/desktop_tests/test_worker_provenance.py`
- `S116` `M` `src/vaultspec_a2a/testing/tests/test_default_safety.py`
- `S116` `M` `src/vaultspec_a2a/testing/graph.py`
- `S116` `M` `src/vaultspec_a2a/testing/__init__.py`
- `S116` `M` `src/vaultspec_a2a/api/tests/test_clarification_loop_live.py`
- `S116` `M` `src/vaultspec_a2a/control/tests/test_permission_reask.py`
- `S116` `verify:` `uv run --no-sync --frozen --no-default-groups --group tooling python -m dev test parallel` -> `fail`
- `S116` `verify:` `uv run --no-sync --frozen --no-default-groups --group tooling python -m vaultspec_a2a.testing.runner -- src/vaultspec_a2a/desktop_tests/test_worker_provenance.py src/vaultspec_a2a/testing/tests/test_default_safety.py --junitxml=.pytest-tmp/green-20261008/provenance-reservation-fixed.xml --no-showlocals -q` -> `pass`
- `S116` `verify:` `uv run --no-sync --frozen --no-default-groups --group tooling python -m vaultspec_a2a.testing.runner -- src/vaultspec_a2a/tests/test_structural_duplication.py src/vaultspec_a2a/api/tests/test_clarification_loop_live.py src/vaultspec_a2a/control/tests/test_permission_reask.py --junitxml=.pytest-tmp/green-20261008/graph-helper-fold.xml --no-showlocals -q` -> `pass`
- `S116` `verify:` `uv run --no-sync --frozen --no-default-groups --group tooling python -m dev lint all` -> `pass`
- `S83` `M` `packaging/pyinstaller/vaultspec-a2a.spec`
- `S83` `M` `packaging/tests/test_build_artifact_contents.py`
- `S83` `M` `.github/workflows/release.yml`
- `S83` `M` `dev/toolchain.py`
- `S83` `M` `Justfile`
- `S83` `verify:` `just test-frozen-contents` -> `pass`
- `S83` `verify:` `uv run --no-sync --frozen --no-default-groups --group tooling python -m dev lint all` -> `pass`

## Notes

- `S116` S116 remains open: full non-service baseline and functional gates are pending; this checkpoint records only the strict-type correction and its 16 passing focused tests.
- `S116` Fresh tool-cores S15 verification repaired the missing checkpoint; metadata-only maintenance reviewed. Permissions service coverage gap recorded; S116 remains open.
- `S116` Correction: the earlier wheel verification row containing `not_frozen_placeholder` is a transcription error, not an executed command, and must not be used as evidence. The following correctly transcribed selection passed three tests with one deselected; wheel-contents.log records the actual run.
- `S99` Correction checkpoint only: S99 remains unchecked pending broader historical execution reconciliation.
- `S83` Corrected real Windows onedir excludes Core test fixtures; build smoke and actual bundled Core help pass. Independent review PASS. Broader S83 historical closure is not inferred from this correction.

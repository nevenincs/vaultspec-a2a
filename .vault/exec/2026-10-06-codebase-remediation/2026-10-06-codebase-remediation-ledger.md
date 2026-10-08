---
tags:
  - '#exec'
  - '#codebase-remediation'
date: '2026-10-06'
modified: '2026-10-08'
body_schema: 'body-v2'
body_hash: 'sha256:0e3357e241c17c12124b4694a06f221860dd4cd96ba8a352faa3e5af4077c16b'
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
- `S116` `M` `src/vaultspec_a2a/control/tests/test_verdict_loop_live.py`
- `S116` `M` `src/vaultspec_a2a/service_tests/_dashboard_engine.py`
- `S116` `M` `src/vaultspec_a2a/service_tests/test_dashboard_provider_catalog_live.py`
- `S116` `M` `src/vaultspec_a2a/service_tests/test_engine_broker_lost_ack_live.py`
- `S116` `verify:` `uv run --no-sync --frozen --no-default-groups --group tooling python .pytest-tmp/green-20261008/engine_verdict_probe.py` -> `pass`
- `S116` `verify:` `uv run --no-sync --frozen --no-default-groups --group tooling python -m dev test parallel` -> `fail`
- `S15` `verify:` `uv run --no-sync --frozen --no-default-groups --group tooling python -m vaultspec_a2a.testing.runner -- src/vaultspec_a2a/control/tests/test_worker_provenance.py --junitxml=.pytest-tmp/green-20261008/worker-provenance-s15.xml --no-showlocals` -> `pass`
- `S116` `M` `.env.example`
- `S116` `M` `.vault/plan/2026-10-06-codebase-remediation-plan.md`
- `S116` `M` `dev/tests/test_harness_env_names.py`
- `S116` `M` `src/vaultspec_a2a/conftest.py`
- `S116` `M` `src/vaultspec_a2a/graph/tests/nodes/test_harness_mcp_wiring.py`
- `S116` `M` `src/vaultspec_a2a/graph/tests/test_harness_topology_reach.py`
- `S116` `M` `src/vaultspec_a2a/graph/tests/test_persona_web_composition.py`
- `S116` `M` `src/vaultspec_a2a/providers/tests/test_codex_config_home.py`
- `S116` `M` `src/vaultspec_a2a/providers/tests/test_harness_interpreter_pin.py`
- `S116` `M` `src/vaultspec_a2a/providers/tests/test_mcp_contract.py`
- `S116` `M` `src/vaultspec_a2a/providers/tests/test_mcp_probe_security.py`
- `S116` `M` `src/vaultspec_a2a/providers/tests/test_native_launch_context.py`
- `S116` `M` `src/vaultspec_a2a/providers/tests/test_registry_launch_identity.py`
- `S116` `M` `src/vaultspec_a2a/testing/markers.py`
- `S116` `M` `src/vaultspec_a2a/testing/purity.py`
- `S116` `verify:` `uv run --no-sync --frozen --no-default-groups --group tooling python -m vaultspec_a2a.testing.runner -- -m not-service -n auto --dist=loadgroup (actual marker: not service; nonservice-isolated.xml; 5872 passed, 3 failed, 11 skipped)` -> `fail`
- `S116` `verify:` `uv run --no-sync --frozen --no-default-groups --group tooling python -m vaultspec_a2a.testing.runner -- src/vaultspec_a2a/control/tests/test_env_example_drift.py dev/tests/test_harness_env_names.py --junitxml=.pytest-tmp/green-20261008/env-harness-final.xml --no-showlocals` -> `pass`
- `S116` `verify:` `uv run --no-sync --frozen --no-default-groups --group tooling python -m vaultspec_a2a.testing.runner -- src/vaultspec_a2a/desktop_tests/test_worker_provenance.py --junitxml=.pytest-tmp/green-20261008/provenance-post-isolation.xml --no-showlocals` -> `pass`
- `S116` `verify:` `uv run --no-sync python -m dev lint python` -> `pass`
- `S116` `verify:` `uv run --no-sync vaultspec-core vault check all --feature codebase-remediation` -> `pass`
- `S116` `verify:` `uv run --no-sync --frozen --no-default-groups --group tooling python -m vaultspec_a2a.testing.runner -- -m "not service" -n auto --dist=loadgroup --junitxml=.pytest-tmp/green-20261008/nonservice-isolated.xml --no-showlocals` -> `fail`

## Notes

- `S116` S116 remains open: full non-service baseline and functional gates are pending; this checkpoint records only the strict-type correction and its 16 passing focused tests.
- `S116` Fresh tool-cores S15 verification repaired the missing checkpoint; metadata-only maintenance reviewed. Permissions service coverage gap recorded; S116 remains open.
- `S116` Correction: the earlier wheel verification row containing `not_frozen_placeholder` is a transcription error, not an executed command, and must not be used as evidence. The following correctly transcribed selection passed three tests with one deselected; wheel-contents.log records the actual run.
- `S99` Correction checkpoint only: S99 remains unchecked pending broader historical execution reconciliation.
- `S83` Corrected real Windows onedir excludes Core test fixtures; build smoke and actual bundled Core help pass. Independent review PASS. Broader S83 historical closure is not inferred from this correction.
- `S116` Contained local engine probe: live verdict and receipt-role tests 2 passed. Full nonservice 5859 passed/16 RAG-version failures/11 skipped. Independent review PASS with low mutable-buffer observation queued. Engine source pin/CI provisioning remains open S115; shared RAG choice pending.
- `S15` Fresh verification at ca0a690a: 10 passed in 12.87s, including no requests/credentials to a foreign subprocess and no unarmed eviction. Original implementation c401d7bf is on main. Current source review confirms ancestry precedes credentialed readiness and eviction. S15 remains unchecked: reconcile B5 pre-spawn unauthenticated wording against accepted descendant-first behavior and full audit/closure requirements; do not invent historical verification.
- `S116` Isolated real MCP tests from ambient RAG discovery; 156 focused plus 8 first-probe plus 3 review cases passed. Production compatibility checks and shared RAG service unchanged. Full run failures: frozen harness documentation fixed (12 passed); two gateway readiness timeouts passed full provenance rerun (5 passed), root cause still under investigation. Unit collection/JUnit identity join: 2192 matched, 2187 passed, 5 skipped. Broader S116 remains open; see rolling audit for evidence and review findings.
- `S116` Command transcription correction: the preceding nonservice-isolated verification label used the shorthand not-service and an explanatory parenthesis; the actual executed command is the quoted not service marker command recorded immediately above. Result unchanged: 5872 passed, 3 failed, 11 skipped.

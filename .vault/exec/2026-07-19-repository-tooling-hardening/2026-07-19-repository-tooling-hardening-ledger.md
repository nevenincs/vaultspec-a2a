---
tags:
  - '#exec'
  - '#repository-tooling-hardening'
date: '2026-07-19'
modified: '2026-10-01'
body_schema: 'body-v2'
body_hash: 'sha256:188cea99b8e76d7ac94576d208989360575880225dd524a00d835437733d05e8'
related:
  - "[[2026-07-19-repository-tooling-hardening-plan]]"
---

# `repository-tooling-hardening` ledger

## Changes

- `S01` `T` `pyproject.toml`
- `S01` `T` `uv.lock`
- `S02` `T` `just/dev/deps.just`
- `S02` `T` `just/dev/vault.just`
- `S02` `T` `just/dev/rag.just`
- `S03` `T` `src/vaultspec_a2a/cli/provision.py`
- `S03` `T` `src/vaultspec_a2a/providers/_acp_mcp.py`
- `S03` `T` `tests`
- `S04` `T` `.gitignore`
- `S05` `T` `.vaultspec/rules`
- `S05` `T` `generated provider projections`
- `S06` `T` `Justfile`
- `S06` `T` `just/dev`
- `S07` `T` `just/dev/service.just`
- `S07` `T` `just/dev/stack.just`
- `S08` `T` `.pre-commit-config.yaml`
- `S08` `T` `hook integration tests`
- `S09` `T` `pyproject.toml`
- `S09` `T` `affected source and tests`
- `S10` `T` `.github/workflows`
- `S10` `T` `repository health configuration`
- `S11` `T` `README.md`
- `S11` `T` `docs`
- `S12` `T` `.vault/audit`
- `S12` `T` `.vault/exec`
- `S13` `T` `dev/toolchain.py`
- `S14` `T` `dev/toolchain.py`
- `S14` `T` `pyproject.toml`
- `S15` `T` `dev/toolchain.py`
- `S15` `T` `justfile`
- `S16` `T` `.github/workflows/test.yml`
- `S17` `T` `.github/workflows/test.yml`
- `S18` `T` `dev/toolchain.py`
- `S18` `T` `dev/tests/test_ci_contract.py`
- `S19` `T` `src/vaultspec_a2a/control/tests/test_spawn_containment_ownership.py`
- `S19` `T` `src/vaultspec_a2a/streaming/tests/test_sse_frames.py`
- `S19` `T` `src/vaultspec_a2a/utils/process.py`
- `S20` `T` `dev/health/report.py`
- `S21` `T` `src/vaultspec_a2a/api/tests/conftest.py`
- `S22` `T` `src/vaultspec_a2a/api/tests/test_endpoints.py`
- `S23` `T` `src/vaultspec_a2a/api/tests/test_gateway_live.py`
- `S23` `T` `src/vaultspec_a2a/api/tests/test_clarification_loop_live.py`
- `S23` `T` `src/vaultspec_a2a/api/tests/test_clarification_endpoint.py`
- `S23` `T` `src/vaultspec_a2a/api/tests/test_acceptance_five_verb.py`
- `S23` `T` `src/vaultspec_a2a/api/tests/clarification_harness.py`
- `S23` `T` `src/vaultspec_a2a/control/tests/test_verdict_loop_live.py`
- `S23` `T` `src/vaultspec_a2a/worker/executor.py`
- `S23` `T` `src/vaultspec_a2a/worker/graph_lifecycle.py`
- `S23` `T` `src/vaultspec_a2a/worker/tests/test_executor.py`
- `S23` `T` `src/vaultspec_a2a/worker/tests/test_executor_token_lifecycle.py`
- `S24` `T` `src/vaultspec_a2a/control`
- `S24` `T` `src/vaultspec_a2a/control/repositories`
- `S24` `T` `src/vaultspec_a2a/authoring/discovery.py`
- `S24` `T` `src/vaultspec_a2a/api/routes/gateway.py`
- `S24` `T` `src/vaultspec_a2a/desktop_tests/test_worker_health_decode_contract.py`
- `S25` `T` `src/vaultspec_a2a/providers`
- `S25` `T` `src/vaultspec_a2a/desktop/profile.py`
- `S25` `T` `src/vaultspec_a2a/desktop/tests/test_profile.py`
- `S25` `T` `src/vaultspec_a2a/desktop_tests/test_profile_paths.py`
- `S25` `T` `src/vaultspec_a2a/cli/tests/test_desktop_serve.py`
- `S25` `T` `src/vaultspec_a2a/desktop_tests/test_owned_process_tree.py`
- `S30` `A` `src/vaultspec_a2a/providers/_acp_native_commands.py`
- `S30` `A` `src/vaultspec_a2a/providers/_acp_session_admin.py`
- `S30` `A` `src/vaultspec_a2a/providers/_acp_stderr.py`
- `S30` `A` `src/vaultspec_a2a/providers/_acp_teardown.py`
- `S30` `A` `src/vaultspec_a2a/providers/_acp_turn_failures.py`
- `S30` `M` `src/vaultspec_a2a/providers/_harness_mcp_registry.py`
- `S30` `M` `src/vaultspec_a2a/providers/_mcp_contract.py`
- `S30` `M` `src/vaultspec_a2a/providers/_native_read_tools.py`
- `S30` `M` `src/vaultspec_a2a/providers/acp_chat_model.py`
- `S30` `M` `src/vaultspec_a2a/providers/tests/test_acp_session_ownership.py`
- `S30` `verify:` `python -m dev lint all` -> `pass`
- `S30` `verify:` `pytest src/vaultspec_a2a/providers` -> `pass`
- `S30` `by:` `vaultspec-high-executor`
- `S31` `M` `src/vaultspec_a2a/streaming/aggregator.py`
- `S31` `M` `src/vaultspec_a2a/streaming/ingest.py`
- `S31` `M` `src/vaultspec_a2a/worker/tests/test_executor.py`
- `S31` `verify:` `python -m dev lint all` -> `pass`
- `S31` `verify:` `pytest src/vaultspec_a2a/streaming src/vaultspec_a2a/worker src/vaultspec_a2a/api` -> `pass`
- `S31` `by:` `vaultspec-high-executor`
- `S34` `A` `src/vaultspec_a2a/graph/_compiler_models.py`
- `S34` `A` `src/vaultspec_a2a/graph/_compiler_prompts.py`
- `S34` `M` `src/vaultspec_a2a/graph/_compiler_research.py`
- `S34` `M` `src/vaultspec_a2a/graph/compiler.py`
- `S34` `A` `src/vaultspec_a2a/graph/nodes/_worker_permissions.py`
- `S34` `A` `src/vaultspec_a2a/graph/nodes/_worker_tool_calls.py`
- `S34` `M` `src/vaultspec_a2a/graph/nodes/supervisor.py`
- `S34` `M` `src/vaultspec_a2a/graph/nodes/worker.py`
- `S34` `M` `src/vaultspec_a2a/graph/tests/nodes/test_worker.py`
- `S34` `verify:` `python -m dev lint all` -> `pass`
- `S34` `verify:` `pytest src/vaultspec_a2a/graph src/vaultspec_a2a/worker src/vaultspec_a2a/team` -> `pass`
- `S34` `by:` `vaultspec-high-executor`
- `S29` `verify:` `python -m dev lint cyclomatic` -> `pass`
- `S29` `verify:` `python -m dev lint shape` -> `pass`
- `S29` `by:` `vaultspec-high-executor`
- `S35` `verify:` `python -m dev lint cyclomatic` -> `pass`
- `S35` `verify:` `python -m dev lint shape` -> `pass`
- `S35` `by:` `vaultspec-high-executor`
- `S36` `verify:` `python -m dev lint cyclomatic` -> `pass`
- `S36` `verify:` `python -m dev lint shape` -> `pass`
- `S36` `by:` `vaultspec-high-executor`

## Notes

- `S30` Scope correction: also moved the MCP and native-tool composition an ACP session advertises `(_harness_mcp_registry.py,` `_mcp_contract.py,` `_native_read_tools.py);` the operator-home deletion invariant now reads the whole ACP lane module set.
- `S31` Merged over architecture-review P06.S49: the signal path sets the same unwinding flag the cancellation path does, carried into the new `_IngestProgress` value.
- `S34` Scope correction: `graph/_compiler_research.py` moved with the compiler split.
- `S29` Measured green at f72a99a: zero cyclomatic, shape, limits, size, complexity and nesting findings in the Step paths; their hotspots were resolved before this wave, so no change was made.
- `S35` Measured green at f72a99a: zero cyclomatic, shape, limits, size, complexity and nesting findings in the Step paths; their hotspots were resolved before this wave, so no change was made.
- `S36` Measured green at f72a99a: zero cyclomatic, shape, limits, size, complexity and nesting findings in the Step paths; their hotspots were resolved before this wave, so no change was made.

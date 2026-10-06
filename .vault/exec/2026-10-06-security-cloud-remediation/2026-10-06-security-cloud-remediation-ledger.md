---
tags:
  - '#exec'
  - '#security-cloud-remediation'
date: '2026-10-06'
modified: '2026-10-06'
body_schema: 'body-v2'
body_hash: 'sha256:9e2a22e578c49a8528e77130eb0b841c0020bb6c4142e412923e77d5bc7d7da1'
related:
  - "[[2026-10-06-security-cloud-remediation-plan]]"
---

# `security-cloud-remediation` ledger

## Changes

- `S01` `M` `src/vaultspec_a2a/workspace/environment.py`
- `S01` `M` `src/vaultspec_a2a/workspace/tests/test_environment.py`
- `S01` `M` `src/vaultspec_a2a/workspace/tests/test_workspace.py`
- `S01` `M` `src/vaultspec_a2a/providers/factory.py`
- `S01` `M` `src/vaultspec_a2a/providers/tests/test_claude_auth_channel.py`
- `S01` `verify:` `focused pytest environment workspace claude_auth_channel (51 tests)` -> `pass`
- `S01` `verify:` `Ruff lint and format five S01 files` -> `pass`
- `S01` `verify:` `ty check five S01 files` -> `pass`
- `S01` `verify:` `independent OAuth candidate review` -> `pass`
- `S01` `by:` `supervisor`
- `S01` `M` `src/vaultspec_a2a/providers/tests/test_acp_catalog_live.py`
- `S01` `M` `src/vaultspec_a2a/providers/tests/test_acp_authoring_bridge.py`
- `S01` `verify:` `live ACP catalog and authoring bridge service pytest (4 tests)` -> `pass`
- `S01` `verify:` `Ruff and ty on live credential test fixtures` -> `pass`
- `S02` `M` `src/vaultspec_a2a/providers/_acp_rpc_terminal_handlers.py`
- `S02` `M` `src/vaultspec_a2a/providers/_acp_session.py`
- `S02` `A` `src/vaultspec_a2a/providers/tests/_terminal_process.py`
- `S02` `A` `src/vaultspec_a2a/providers/tests/test_terminal_isolation.py`
- `S02` `M` `src/vaultspec_a2a/providers/tests/test_acp_terminal_output.py`
- `S02` `M` `src/vaultspec_a2a/providers/tests/test_acp_callback_ownership.py`
- `S02` `M` `src/vaultspec_a2a/providers/tests/test_acp_fs_read_limits.py`
- `S02` `M` `src/vaultspec_a2a/providers/tests/test_native_launch_context.py`
- `S02` `M` `src/vaultspec_a2a/providers/tests/test_resource_lifetimes.py`
- `S02` `M` `src/vaultspec_a2a/providers/tests/test_terminal_containment.py`
- `S02` `M` `.vault/adr/2026-10-04-workspace-root-authority-desktop-native-admission-adr.md`
- `S02` `verify:` `Windows focused terminal suites and corrected security validation` -> `pass`
- `S02` `verify:` `SDK and terminal containment service tests (2)` -> `pass`
- `S02` `verify:` `Linux locked-environment isolated terminal private-state workspace output-cap stale binding controls` -> `pass`
- `S02` `verify:` `Ruff lint format and ty ten terminal Python files` -> `pass`
- `S02` `verify:` `independent terminal boundary review` -> `pass`
- `S02` `by:` `supervisor`
- `S09` `M` `src/vaultspec_a2a/workspace/environment.py`
- `S09` `M` `src/vaultspec_a2a/workspace/tests/test_workspace.py`
- `S09` `M` `src/vaultspec_a2a/providers/_factory_commands.py`
- `S09` `M` `src/vaultspec_a2a/providers/acp_chat_model.py`
- `S09` `M` `src/vaultspec_a2a/providers/binary_version.py`
- `S09` `M` `src/vaultspec_a2a/providers/tests/test_mcp_probe_security.py`
- `S09` `A` `src/vaultspec_a2a/providers/tests/test_zai_auth_environment.py`
- `S09` `verify:` `Windows combined credential and factory pytest (131 pass; baseline Codex proof-range failure)` -> `fail`
- `S09` `verify:` `focused Zai factory pytest (6 tests)` -> `pass`
- `S09` `verify:` `real MCP security pytest (3 tests)` -> `pass`
- `S09` `verify:` `Linux locked Zai and isolated version authority pytest (16 tests)` -> `pass`
- `S09` `verify:` `Ruff lint format and ty seven S09 files` -> `pass`
- `S09` `verify:` `independent candidate review with supervisor verification` -> `pass`
- `S09` `by:` `supervisor`
- `S10` `M` `src/vaultspec_a2a/providers/lane_admission.py`
- `S10` `M` `.github/workflows/test.yml`
- `S10` `M` `src/vaultspec_a2a/providers/tests/test_lane_admission_current.py`
- `S10` `M` `src/vaultspec_a2a/providers/tests/test_binary_proof_admission.py`
- `S10` `M` `src/vaultspec_a2a/providers/tests/test_binary_version.py`
- `S10` `M` `src/vaultspec_a2a/providers/tests/test_codex_chat_model.py`
- `S10` `M` `src/vaultspec_a2a/graph/tests/test_runtime_identity_graph_live.py`
- `S10` `M` `src/vaultspec_a2a/worker/tests/test_runtime_identity_port.py`
- `S10` `verify:` `real Codex direct certification then cited factory live turn and SQL identity` -> `pass`
- `S10` `verify:` `combined credential factory admission pytest (145 tests)` -> `pass`
- `S10` `verify:` `final factory admission version worker identity pytest (62 tests)` -> `pass`
- `S10` `verify:` `final live provider and graph identity pytest (2 tests)` -> `pass`
- `S10` `verify:` `corrected boundary pytest (5 tests)` -> `pass`
- `S10` `verify:` `Ruff lint format ty seven S10 Python files` -> `pass`
- `S10` `verify:` `CI pins agree with proof` -> `pass`
- `S10` `by:` `supervisor`
- `S10` `verify:` `independent S10 actual diff and correction review` -> `pass`
- `S11` `D` `src/vaultspec_a2a/desktop/_linux_runtime_assets.py`
- `S11` `M` `scripts/build_linux_isolation.py`
- `S11` `M` `src/vaultspec_a2a/desktop/tests/test_native_isolation.py`
- `S11` `M` `src/vaultspec_a2a/providers/tests/_native_mcp_capsule.py`
- `S11` `verify:` `Windows native pytest (9 tests)` -> `pass`
- `S11` `verify:` `Linux clean native filesystem locked full dependency profile pytest (14 tests)` -> `pass`
- `S11` `verify:` `Ruff lint format and ty focused files` -> `pass`
- `S11` `verify:` `staging function AST unchanged and build CLI help` -> `pass`
- `S11` `verify:` `Windows and Linux unreachable-module coverage` -> `pass`
- `S11` `verify:` `independent S11 review` -> `pass`
- `S11` `by:` `supervisor`
- `S11` `verify:` `Linux full lint checks with actionlint and CI contract rerun after temp git init` -> `pass`
- `S12` `M` `uv.lock`
- `S12` `verify:` `uv locked full-profile sync` -> `pass`
- `S12` `verify:` `dependency audit all lock coordinates` -> `pass`
- `S12` `verify:` `migration pytest (19 tests)` -> `pass`
- `S12` `verify:` `real Windows template traversal normal render and Alembic revision generation` -> `pass`
- `S12` `verify:` `semantic lock diff only Mako package` -> `pass`
- `S12` `by:` `supervisor`
- `S12` `verify:` `independent Mako lock and compatibility review` -> `pass`
- `S12` `verify:` `uv lock --check` -> `pass`
- `S13` `M` `src/vaultspec_a2a/providers/factory.py`
- `S13` `M` `src/vaultspec_a2a/providers/_codex_config_home.py`
- `S13` `M` `src/vaultspec_a2a/providers/codex_chat_model.py`
- `S13` `M` `.vault/audit/2026-10-06-security-cloud-remediation-audit.md`
- `S13` `M` `.vault/plan/2026-10-06-security-cloud-remediation-plan.md`
- `S13` `verify:` `Linux python -m dev test harness (157 tests)` -> `pass`
- `S13` `verify:` `ruff check and format changed files` -> `pass`
- `S13` `verify:` `ty check changed files` -> `pass`
- `S13` `verify:` `Windows storage anchors (18 tests)` -> `pass`
- `S13` `verify:` `Windows provider auth home factory tests (117 tests)` -> `pass`
- `S13` `verify:` `independent S13 code review` -> `pass`
- `S13` `verify:` `Linux full CI unit stage` -> `fail`
- `S14` `M` `src/vaultspec_a2a/tests/gateway_boot.py`
- `S14` `M` `src/vaultspec_a2a/acceptance/tests/_harness.py`
- `S14` `M` `src/vaultspec_a2a/acceptance/tests/conftest.py`
- `S14` `M` `src/vaultspec_a2a/acceptance/tests/test_dashboard_contract.py`
- `S14` `M` `src/vaultspec_a2a/api/tests/test_catalog_restart_redispatch.py`
- `S14` `M` `src/vaultspec_a2a/desktop_tests/test_run_admission.py`
- `S14` `M` `openapi.json`
- `S14` `M` `.vault/audit/2026-10-06-security-cloud-remediation-audit.md`
- `S14` `M` `.vault/plan/2026-10-06-security-cloud-remediation-plan.md`
- `S14` `verify:` `Linux acceptance restart OpenAPI 17 tests` -> `pass`
- `S14` `verify:` `Windows desktop readiness and broker admission 9 tests` -> `pass`
- `S14` `verify:` `ruff check and format six changed Python files` -> `pass`
- `S14` `verify:` `ty check six changed Python files` -> `pass`
- `S14` `verify:` `independent S14 code review` -> `pass`
- `S14` `verify:` `Linux python -m dev build all` -> `pass`
- `S14` `verify:` `Linux base-only telemetry probe` -> `pass`

## Notes

- `S09` The combined suite has one unrelated Codex 0.160.0 proof-range failure reproduced on clean baseline 64fb0ea2; recorded in audit.
- `S11` Initial WSL mounted checkout MCP permission and copy-timeout failures resolved by clean /tmp archive plus patch. Incomplete verification environment replaced with CI full locked dependency profile.
- `S13` Full CI reached unrelated desktop fixture contract drift and stale OpenAPI artifact; queued for next Step.
- `S14` Full Linux unit verification is running; remote CI remains to be checked.

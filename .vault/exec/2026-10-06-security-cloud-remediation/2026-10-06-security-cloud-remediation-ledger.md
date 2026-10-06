---
tags:
  - '#exec'
  - '#security-cloud-remediation'
date: '2026-10-06'
modified: '2026-10-06'
body_schema: 'body-v2'
body_hash: 'sha256:55da683e1aafbd5fe923eba4be147368c5eb3a2cdd74b01a16f4bb9ed0156e12'
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

## Notes

- `S09` The combined suite has one unrelated Codex 0.160.0 proof-range failure reproduced on clean baseline 64fb0ea2; recorded in audit.

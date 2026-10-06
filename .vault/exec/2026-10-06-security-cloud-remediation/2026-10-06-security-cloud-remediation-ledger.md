---
tags:
  - '#exec'
  - '#security-cloud-remediation'
date: '2026-10-06'
modified: '2026-10-06'
body_schema: 'body-v2'
body_hash: 'sha256:b3d9831513924efe05ec5a5e2328f59c7e43b93b17faae27b675c6cdfce5a9de'
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

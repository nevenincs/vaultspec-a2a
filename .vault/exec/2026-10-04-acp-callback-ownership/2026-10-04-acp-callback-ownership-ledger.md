---
tags:
  - '#exec'
  - '#acp-callback-ownership'
date: '2026-10-04'
modified: '2026-10-04'
body_schema: 'body-v2'
body_hash: 'sha256:31bd43c483c7960c54832bffa2829679a0a2a2193d7a4751f88ac17ffab07ab6'
related:
  - "[[2026-10-04-acp-callback-ownership-plan]]"
---

# `acp-callback-ownership` ledger

## Changes

- `S01` `A` `src/vaultspec_a2a/providers/_acp_client_requests.py`
- `S01` `A` `src/vaultspec_a2a/providers/tests/test_acp_callback_ownership.py`
- `S01` `M` `src/vaultspec_a2a/providers/_acp_fs_read.py`
- `S01` `M` `src/vaultspec_a2a/providers/_acp_rpc_handlers.py`
- `S01` `M` `src/vaultspec_a2a/providers/tests/conftest.py`
- `S01` `M` `src/vaultspec_a2a/providers/tests/test_acp_fs_read_limits.py`
- `S01` `M` `src/vaultspec_a2a/providers/tests/test_acp_vault_deny.py`
- `S01` `M` `src/vaultspec_a2a/providers/tests/test_acp_authoring.py`
- `S01` `M` `src/vaultspec_a2a/providers/tests/test_project_confinement.py`
- `S01` `M` `src/vaultspec_a2a/providers/tests/test_desktop_workspace_boundary.py`
- `S01` `M` `src/vaultspec_a2a/service_tests/test_compose_provider_service_state_isolation.py`
- `S01` `A` `.vault/audit/2026-10-04-acp-callback-ownership-audit.md`
- `S01` `A` `.vault/plan/2026-10-04-acp-callback-ownership-plan.md`
- `S01` `verify:` `real-file negative trigger 10 failures before fix` -> `fail`
- `S01` `verify:` `Windows focused filesystem suites 192 tests` -> `pass`
- `S01` `verify:` `native Linux secure callback suites 64 tests` -> `pass`
- `S01` `verify:` `installed SDK negotiated read and write traffic` -> `pass`
- `S01` `verify:` `Docker provider filesystem boundary three tests` -> `pass`
- `S01` `verify:` `full Ruff lint and format and Ty` -> `pass`
- `S01` `verify:` `scoped Basedpyright` -> `pass`
- `S01` `verify:` `independent candidate and corrective review` -> `pass`
- `S01` `by:` `root`

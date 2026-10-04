---
tags:
  - '#exec'
  - '#acp-callback-ownership'
date: '2026-10-04'
modified: '2026-10-04'
body_schema: 'body-v2'
body_hash: 'sha256:1fd0c1daf5f54a4522d76641f6b2af8bd32774f0ba90beb6a9d80e1ac53f6efe'
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
- `S02` `M` `src/vaultspec_a2a/providers/_acp_client_requests.py`
- `S02` `M` `src/vaultspec_a2a/providers/_acp_rpc_terminal_handlers.py`
- `S02` `M` `src/vaultspec_a2a/providers/_acp_teardown.py`
- `S02` `M` `src/vaultspec_a2a/providers/tests/test_acp_callback_ownership.py`
- `S02` `M` `src/vaultspec_a2a/providers/tests/test_acp_fs_read_limits.py`
- `S02` `M` `src/vaultspec_a2a/providers/tests/test_acp_security.py`
- `S02` `M` `src/vaultspec_a2a/providers/tests/test_resource_lifetimes.py`
- `S02` `M` `src/vaultspec_a2a/providers/tests/test_terminal_containment.py`
- `S02` `M` `src/vaultspec_a2a/desktop_tests/test_owned_process_tree.py`
- `S02` `M` `.vault/audit/2026-10-04-acp-callback-ownership-audit.md`
- `S02` `verify:` `Windows terminal ownership lifecycle and security 112 tests` -> `pass`
- `S02` `verify:` `native Linux terminal ownership lifecycle and security 104 tests` -> `pass`
- `S02` `verify:` `installed SDK real callback wire and terminal grandchild two service tests` -> `pass`
- `S02` `verify:` `full Ruff lint and format and Ty` -> `pass`
- `S02` `verify:` `scoped Basedpyright six files` -> `pass`
- `S02` `verify:` `independent terminal candidate review` -> `pass`
- `S02` `by:` `root`

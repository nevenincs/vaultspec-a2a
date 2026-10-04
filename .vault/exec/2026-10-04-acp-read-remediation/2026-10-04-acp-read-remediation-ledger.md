---
tags:
  - '#exec'
  - '#acp-read-remediation'
date: '2026-10-04'
modified: '2026-10-04'
body_schema: 'body-v2'
body_hash: 'sha256:d1cad324545d6f74ee049aa3472cbc9909d4e430f7ae38aeef090e616cc5a7f1'
related:
  - "[[2026-10-04-acp-read-remediation-plan]]"
---

# `acp-read-remediation` ledger

## Changes

- `S01` `A` `.vault/plan/2026-10-04-acp-read-remediation-plan.md`
- `S01` `A` `.vault/audit/2026-10-04-acp-read-remediation-audit.md`
- `S01` `verify:` `hook removal and absence check` -> `pass`
- `S01` `verify:` `full Ruff lint and format` -> `pass`
- `S01` `verify:` `full Ty` -> `pass`
- `S01` `verify:` `engine and worker regression suites, 16 tests` -> `pass`
- `S02` `A` `src/vaultspec_a2a/providers/_acp_fs_read.py`
- `S02` `A` `src/vaultspec_a2a/providers/tests/test_acp_fs_read_limits.py`
- `S02` `M` `src/vaultspec_a2a/providers/_acp_rpc_handlers.py`
- `S02` `M` `src/vaultspec_a2a/providers/_acp_types.py`
- `S02` `M` `src/vaultspec_a2a/providers/_acp_session.py`
- `S02` `M` `src/vaultspec_a2a/control/infra_config.py`
- `S02` `M` `src/vaultspec_a2a/providers/tests/conftest.py`
- `S02` `M` `src/vaultspec_a2a/providers/tests/test_acp_vault_deny.py`
- `S02` `M` `src/vaultspec_a2a/providers/tests/test_project_confinement.py`
- `S02` `M` `src/vaultspec_a2a/providers/tests/test_claude_permission_posture.py`
- `S02` `M` `src/vaultspec_a2a/service_tests/test_compose_provider_service_state_isolation.py`
- `S02` `M` `.vault/audit/2026-10-04-acp-read-remediation-audit.md`
- `S02` `verify:` `Ruff lint and format full configured scope` -> `pass`
- `S02` `verify:` `Ty full configured scope and Basedpyright changed read surfaces` -> `pass`
- `S02` `verify:` `Windows focused provider suites 156 passed, three Linux-only skips` -> `pass`
- `S02` `verify:` `native Linux secure read and confinement 113 tests` -> `pass`
- `S02` `verify:` `installed ACP SDK callback and real Claude adapter handshake` -> `pass`
- `S02` `verify:` `Docker provider boundary three tests` -> `pass`
- `S02` `verify:` `independent candidate and corrective review` -> `pass`
- `S02` `by:` `root`

## Notes

- `S02` Sibling write and terminal ownership and native-tool enforcement remain open under the older ACP migration plan.

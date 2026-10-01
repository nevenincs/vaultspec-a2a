---
tags:
  - '#exec'
  - '#provider-binary-policy'
date: '2026-10-01'
modified: '2026-10-01'
body_schema: 'body-v2'
body_hash: 'sha256:2ea03dbdefb403de0427b75261434c6de0126449766cf95142f8dd8bc360c7dc'
related:
  - "[[2026-10-01-provider-binary-policy-plan]]"
---


# `provider-binary-policy` ledger

## Changes


- `S17` `M` `package-lock.json`
- `S17` `M` `package.json`
- `S17` `M` `src/vaultspec_a2a/graph/tests/acp_simulator.py`
- `S17` `M` `src/vaultspec_a2a/providers/_acp_rpc_handlers.py`
- `S17` `M` `src/vaultspec_a2a/providers/_acp_session.py`
- `S17` `M` `src/vaultspec_a2a/providers/_claude_tool_policy.py`
- `S17` `M` `src/vaultspec_a2a/providers/acp_catalog.py`
- `S17` `M` `src/vaultspec_a2a/providers/conditions.py`
- `S17` `M` `src/vaultspec_a2a/providers/factory.py`
- `S17` `M` `src/vaultspec_a2a/providers/tests/_acp_frames.py`
- `S17` `M` `src/vaultspec_a2a/providers/tests/_installed_vocabulary.py`
- `S17` `M` `src/vaultspec_a2a/providers/tests/test_acp_authoring_bridge.py`
- `S17` `M` `src/vaultspec_a2a/providers/tests/test_acp_catalog_live.py`
- `S17` `M` `src/vaultspec_a2a/providers/tests/test_acp_migration_surface.py`
- `S17` `M` `src/vaultspec_a2a/providers/tests/test_claude_permission_posture.py`
- `S17` `M` `src/vaultspec_a2a/providers/tests/test_conditions.py`
- `S17` `M` `src/vaultspec_a2a/providers/tests/test_project_confinement.py`
- `S17` `verify:` `pytest providers graph streaming desktop_tests` -> `pass`
- `S17` `verify:` `live adapter handshake tests -m service` -> `pass`
- `S17` `verify:` `npm audit signatures: 106 verified` -> `pass`
- `S17` `by:` `vaultspec-high-executor`

## Notes

- `S17` Adapter 0.59.0 to 0.84.0, SDK 0.3.207 to 0.3.284, CLI 2.1.207 to 2.1.284. Fixed: session/new died as root with `IS_SANDBOX` set because the adapter armed the skip-permissions flag (declined now); three new error kinds mapped; PowerShell denied to a terminal-less persona. No completed model turn was possible here: the claude lane must re-earn its completed-turn proof on 2.1.284 on a credentialed host.

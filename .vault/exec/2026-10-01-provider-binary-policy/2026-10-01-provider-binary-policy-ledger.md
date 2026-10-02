---
tags:
  - '#exec'
  - '#provider-binary-policy'
date: '2026-10-01'
modified: '2026-10-02'
body_schema: 'body-v2'
body_hash: 'sha256:1c39875ed145e2abf5ae1d3e3bc429c8b0d460ee3cce55a0f2bd437d0b891b93'
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
- `S16` `M` `vault/audit/2026-10-01-provider-binary-policy-audit.md`
- `S16` `M` `.vault/plan/2026-10-01-provider-binary-policy-plan.md`
- `S16` `M` `src/vaultspec_a2a/desktop_tests/test_owned_process_tree.py`
- `S16` `M` `src/vaultspec_a2a/providers/_acp_session.py`
- `S16` `M` `src/vaultspec_a2a/providers/_acp_types.py`
- `S16` `M` `src/vaultspec_a2a/providers/acp_chat_model.py`
- `S16` `M` `src/vaultspec_a2a/providers/tests/test_acp_authoring.py`
- `S16` `M` `src/vaultspec_a2a/providers/tests/test_acp_exceptions.py`
- `S16` `M` `src/vaultspec_a2a/providers/tests/test_acp_handler_failure.py`
- `S16` `M` `src/vaultspec_a2a/providers/tests/test_acp_migration_surface.py`
- `S16` `M` `src/vaultspec_a2a/providers/tests/test_acp_model_selection.py`
- `S16` `M` `src/vaultspec_a2a/providers/tests/test_acp_permission_option_ids.py`
- `S16` `M` `src/vaultspec_a2a/providers/tests/test_acp_security.py`
- `S16` `M` `src/vaultspec_a2a/providers/tests/test_acp_session_ownership.py`
- `S16` `M` `src/vaultspec_a2a/providers/tests/test_acp_token_redaction.py`
- `S16` `M` `src/vaultspec_a2a/providers/tests/test_acp_vault_deny.py`
- `S16` `M` `src/vaultspec_a2a/providers/tests/test_claude_permission_posture.py`
- `S16` `M` `src/vaultspec_a2a/providers/tests/test_harness_mcp_pinning.py`
- `S16` `M` `src/vaultspec_a2a/providers/tests/test_kimi_permission.py`
- `S16` `M` `src/vaultspec_a2a/providers/tests/test_project_confinement.py`
- `S16` `M` `src/vaultspec_a2a/providers/tests/test_terminal_containment.py`
- `S16` `verify:` `pytest provider session ownership/model selection/permission posture` -> `pass`
- `S16` `verify:` `pytest desktop owned process tree` -> `pass`
- `S16` `verify:` `ty changed test callers` -> `pass`
- `S16` `verify:` `ruff changed provider files` -> `pass`
- `S16` `verify:` `relative imports guard` -> `pass`
- `S16` `verify:` `vault check provider-binary-policy` -> `pass`
- `S16` `verify:` `just ci` -> `fail`
- `S01` `M` `src/vaultspec_a2a/providers/_factory_commands.py`
- `S01` `M` `src/vaultspec_a2a/providers/tests/test_capsule_acp_resolution.py`
- `S01` `M` `.vault/audit/2026-10-01-provider-binary-policy-audit.md`
- `S01` `verify:` `pytest capsule_acp_resolution` -> `pass`
- `S01` `verify:` `ruff capsule path files` -> `pass`
- `S01` `verify:` `ty capsule path files` -> `pass`
- `S01` `verify:` `vault check provider-binary-policy` -> `pass`
- `S01` `verify:` `just ci` -> `fail`
- `S02` `M` `src/vaultspec_a2a/desktop/profile.py`
- `S02` `M` `src/vaultspec_a2a/desktop/tests/test_profile.py`
- `S02` `M` `src/vaultspec_a2a/desktop_tests/test_profile_paths.py`
- `S02` `M` `src/vaultspec_a2a/cli/tests/test_desktop_serve.py`
- `S02` `M` `.vault/plan/2026-10-01-provider-binary-policy-plan.md`
- `S02` `M` `.vault/audit/2026-10-01-provider-binary-policy-audit.md`
- `S02` `verify:` `pytest desktop profile and CLI tests` -> `pass`
- `S02` `verify:` `ruff desktop profile files` -> `pass`
- `S02` `verify:` `ty desktop profile files` -> `pass`
- `S02` `verify:` `vault check provider-binary-policy` -> `pass`
- `S02` `verify:` `just ci` -> `fail`
- `S11` `A` `src/vaultspec_a2a/database/migrations/versions/0025_provider_runtime_identity.py`
- `S11` `A` `src/vaultspec_a2a/database/runtime_identity_repository.py`
- `S11` `A` `src/vaultspec_a2a/database/tests/test_runtime_identity_repository.py`
- `S11` `M` `src/vaultspec_a2a/database/models.py`
- `S11` `M` `src/vaultspec_a2a/database/__init__.py`
- `S11` `M` `.vault/audit/2026-10-01-provider-binary-policy-audit.md`
- `S11` `verify:` `dual-backend runtime identity migration/repository pytest` -> `pass`
- `S11` `verify:` `SQLite schema parity pytest 66 passed` -> `pass`
- `S11` `verify:` `Ruff lint and format plus Ty targeted` -> `pass`
- `S03` `M` `src/vaultspec_a2a/control/infra_config.py`
- `S03` `M` `src/vaultspec_a2a/control/config.py`
- `S03` `M` `.env.example`
- `S03` `M` `src/vaultspec_a2a/control/tests/test_settings_sources.py`
- `S03` `M` `.vault/plan/2026-10-01-provider-binary-policy-plan.md`
- `S03` `M` `.vault/audit/2026-10-01-provider-binary-policy-audit.md`
- `S03` `verify:` `pytest settings sources and env example` -> `pass`
- `S03` `verify:` `ruff settings files` -> `pass`
- `S03` `verify:` `ty settings files` -> `pass`
- `S03` `verify:` `vault check provider-binary-policy` -> `pass`
- `S03` `verify:` `just ci` -> `fail`
- `S04` `M` `src/vaultspec_a2a/providers/cli_resolution.py`
- `S04` `M` `src/vaultspec_a2a/providers/acp_chat_model.py`
- `S04` `M` `src/vaultspec_a2a/providers/factory.py`
- `S04` `M` `src/vaultspec_a2a/providers/tests/test_claude_binary_identity.py`
- `S04` `M` `.vault/plan/2026-10-01-provider-binary-policy-plan.md`
- `S04` `M` `.vault/audit/2026-10-01-provider-binary-policy-audit.md`
- `S04` `verify:` `pytest Claude binary identity/capsule/factory` -> `pass`
- `S04` `verify:` `ruff provider resolver files` -> `pass`
- `S04` `verify:` `ty provider resolver files` -> `pass`
- `S04` `verify:` `vault check provider-binary-policy` -> `pass`
- `S04` `verify:` `just ci` -> `fail`
- `S07` `M` `src/vaultspec_a2a/providers/lane_admission.py`
- `S07` `M` `src/vaultspec_a2a/providers/tests/test_lane_admission_current.py`
- `S07` `M` `.vault/plan/2026-10-01-provider-binary-policy-plan.md`
- `S07` `M` `.vault/audit/2026-10-01-provider-binary-policy-audit.md`
- `S07` `verify:` `codex live app-server turn` -> `pass`
- `S07` `verify:` `claude live ACP turn` -> `fail`
- `S07` `verify:` `targeted provider catalog and admission pytest: 54 tests` -> `pass`
- `S07` `verify:` `ruff check and format on S07 files` -> `pass`
- `S07` `verify:` `ty check on S07 files` -> `pass`
- `S07` `verify:` `real ProviderCatalogService admission probe` -> `pass`
- `S07` `by:` `vaultspec-standard-executor`

## Notes

- `S17` Adapter 0.59.0 to 0.84.0, SDK 0.3.207 to 0.3.284, CLI 2.1.207 to 2.1.284. Fixed: session/new died as root with `IS_SANDBOX` set because the adapter armed the skip-permissions flag (declined now); three new error kinds mapped; PowerShell denied to a terminal-less persona. No completed model turn was possible here: the claude lane must re-earn its completed-turn proof on 2.1.284 on a credentialed host.
- `S16` just ci remains red on base 78f3a89f: 44 strict type diagnostics in `dev/ci_contract.py,` 16 in `control/settings_base.py,` and three unconsumed exports in `settings_base.py;` assigned to main integration owner. Changed-file checks and targeted real-behavior tests pass.
- `S01` Full just ci on base 78f3a89f remains red for strict-type and unconsumed-export defects in `dev/ci_contract.py` and `control/settings_base.py,` owned by main integration; this Step changes neither.
- `S02` Full just ci on base 78f3a89f remains red for strict-type and unconsumed-export defects in `dev/ci_contract.py` and `control/settings_base.py,` owned by main integration; changed-file checks pass.
- `S11` PostgreSQL proof used an isolated Compose project and its exact ephemeral volume was removed after the tests.
- `S03` Full just ci on base 78f3a89f remains red for strict-type and unconsumed-export defects in `dev/ci_contract.py` and `control/settings_base.py,` owned by main integration; changed-file checks pass.
- `S04` Full just ci on base 78f3a89f remains red for strict-type and unconsumed-export defects in `dev/ci_contract.py` and `control/settings_base.py,` owned by main integration. Missing-CLI typed refusal is queued to P01.S05.
- `S07` Claude prompt returned Authentication required; Z.ai credential absent, so both lanes are withheld until P02.S21.
- `S07` Integrated just ci is assigned to the root branch after parallel steps land.

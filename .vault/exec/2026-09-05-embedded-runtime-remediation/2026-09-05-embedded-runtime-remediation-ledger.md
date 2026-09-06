---
tags:
  - '#exec'
  - '#embedded-runtime-remediation'
date: '2026-09-05'
modified: '2026-09-07'
body_schema: 'body-v2'
body_hash: 'sha256:9f5776cd0435c61e8a2c00ce7c7bd524f4fbd7eebb6b69d5bf3d4daad58d4594'
related:
  - "[[2026-09-05-embedded-runtime-remediation-plan]]"
---


# `embedded-runtime-remediation` ledger

## Changes

- `S83` `M` `.vault/audit/2026-09-06-embedded-runtime-remediation-w02-p03-s83-recovery-ledger-review-audit.md`
- `S83` `M` `src/vaultspec_a2a/api/app.py`
- `S83` `M` `src/vaultspec_a2a/control/action_lease.py`
- `S83` `M` `src/vaultspec_a2a/control/cancel_service.py`
- `S83` `M` `src/vaultspec_a2a/control/clarification_service.py`
- `S83` `M` `src/vaultspec_a2a/control/direct_control_recovery.py`
- `S83` `M` `src/vaultspec_a2a/control/message_service.py`
- `S83` `M` `src/vaultspec_a2a/control/permission_service.py`
- `S83` `M` `src/vaultspec_a2a/control/recovery.py`
- `S83` `M` `src/vaultspec_a2a/control/tests/test_accepted_input_recovery.py`
- `S83` `M` `src/vaultspec_a2a/control/tests/test_direct_control_leases.py`
- `S83` `M` `src/vaultspec_a2a/control/tests/test_direct_control_recovery_current.py`
- `S83` `M` `src/vaultspec_a2a/control/tests/test_dispatch_receipts.py`
- `S83` `M` `src/vaultspec_a2a/control/tests/test_recovery_attempt_repository.py`
- `S83` `M` `src/vaultspec_a2a/control/thread_service.py`
- `S83` `M` `src/vaultspec_a2a/control/verdict_subscriber.py`
- `S83` `M` `src/vaultspec_a2a/database/migrations/versions/0019_recovery_attempts.py`
- `S83` `A` `src/vaultspec_a2a/database/migrations/versions/0020_control_action_recovery_deadline.py`
- `S83` `M` `src/vaultspec_a2a/database/models.py`
- `S83` `M` `src/vaultspec_a2a/database/permission_repository.py`
- `S83` `M` `src/vaultspec_a2a/team/presets/teams`
- `S83` `M` `src/vaultspec_a2a/team/team_config.py`
- `S83` `M` `src/vaultspec_a2a/team/tests/test_failure_scenario_preset.py`
- `S83` `M` `src/vaultspec_a2a/thread/dispatch_policy.py`
- `S83` `M` `src/vaultspec_a2a/thread/enums.py`
- `S83` `M` `src/vaultspec_a2a/thread/executable_graph.py`
- `S83` `M` `src/vaultspec_a2a/team/presets/teams/deterministic-cancel-window.toml`
- `S83` `M` `src/vaultspec_a2a/team/presets/teams/deterministic-failure.toml`
- `S83` `M` `src/vaultspec_a2a/team/presets/teams/deterministic-permission-pause.toml`
- `S83` `M` `src/vaultspec_a2a/team/presets/teams/deterministic-relay-burst.toml`
- `S83` `M` `src/vaultspec_a2a/team/presets/teams/deterministic-tool-call.toml`
- `S83` `M` `src/vaultspec_a2a/team/presets/teams/mock-autonomous.toml`
- `S83` `M` `src/vaultspec_a2a/team/presets/teams/mock-failure-tool.toml`
- `S83` `M` `src/vaultspec_a2a/team/presets/teams/mock-human-in-loop.toml`
- `S83` `M` `src/vaultspec_a2a/team/presets/teams/mock-invalid.toml`
- `S83` `M` `src/vaultspec_a2a/team/presets/teams/mock-looping.toml`
- `S83` `M` `src/vaultspec_a2a/team/presets/teams/mock-success-multi.toml`
- `S83` `M` `src/vaultspec_a2a/team/presets/teams/mock-success-single.toml`
- `S83` `M` `src/vaultspec_a2a/team/presets/teams/mock-supervisor-human-in-loop.toml`
- `S83` `M` `src/vaultspec_a2a/team/presets/teams/provider-condition-probe.toml`
- `S83` `M` `src/vaultspec_a2a/team/presets/teams/vaultspec-adr-research-clarify.toml`
- `S83` `M` `src/vaultspec_a2a/team/presets/teams/vaultspec-adr-research-deterministic.toml`
- `S83` `M` `src/vaultspec_a2a/team/presets/teams/vaultspec-adr-research-mock.toml`
- `S83` `M` `src/vaultspec_a2a/team/presets/teams/vaultspec-adr-research.toml`
- `S83` `M` `src/vaultspec_a2a/team/presets/teams/vaultspec-doc-editor.toml`
- `S83` `M` `src/vaultspec_a2a/team/presets/teams/vaultspec-solo-coder.toml`

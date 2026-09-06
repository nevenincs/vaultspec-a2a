---
tags:
  - '#exec'
  - '#embedded-runtime-remediation'
date: '2026-09-06'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:a2f7ac1d9097c4218d42e0a44c70acc7e8521e8b88b78c691de88f26b9874812'
step_id: 'S37'
related:
  - "[[2026-09-05-embedded-runtime-remediation-plan]]"
---
# Expose session-scoped command advertisements with explicit supported, blocked and unsupported dispositions

## Scope

- `src/vaultspec_a2a/providers/_acp_protocol.py`

## Changes

- `M` `src/vaultspec_a2a/providers/_acp_protocol.py`
- `M` `src/vaultspec_a2a/providers/_acp_types.py`
- `A` `src/vaultspec_a2a/providers/tests/test_acp_command_advertisements.py`
- `A` `.vault/audit/2026-09-06-embedded-runtime-remediation-native-command-advertisement-review-audit.md`
- `verify:` `uv run python -m vaultspec_a2a.testing.runner --run-timeout 60 --exit-timeout 5 -- -q src/vaultspec_a2a/providers/tests/test_acp_command_advertisements.py src/vaultspec_a2a/providers/tests/test_acp_stop_outcomes.py src/vaultspec_a2a/providers/tests/test_acp_handler_failure.py` -> `pass`
- `verify:` `uv run --no-sync ruff check src/vaultspec_a2a/providers/_acp_types.py src/vaultspec_a2a/providers/_acp_protocol.py src/vaultspec_a2a/providers/tests/test_acp_command_advertisements.py` -> `pass`
- `verify:` `uv run --no-sync ty check src/vaultspec_a2a/providers/_acp_types.py src/vaultspec_a2a/providers/_acp_protocol.py src/vaultspec_a2a/providers/tests/test_acp_command_advertisements.py` -> `pass`

---
tags:
  - '#exec'
  - '#embedded-runtime-remediation'
date: '2026-09-06'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:fae8d0497aae4c69d428c32147f3212b463569247a89ad034b6be4c2c29773e0'
step_id: 'S32'
related:
  - "[[2026-09-05-embedded-runtime-remediation-plan]]"
---
# Settle every supplied ACP stop reason promptly and preserve refusal, cancellation and budget-exhaustion meaning through the stream consumer

## Scope

- `src/vaultspec_a2a/providers/_acp_protocol.py`
- `src/vaultspec_a2a/providers/_acp_types.py`
- `src/vaultspec_a2a/providers/tests/test_acp_handler_failure.py`

## Changes

- `M` `src/vaultspec_a2a/providers/_acp_protocol.py`
- `M` `src/vaultspec_a2a/providers/_acp_types.py`
- `M` `src/vaultspec_a2a/providers/tests/test_acp_handler_failure.py`
- `verify:` `uv run python -m vaultspec_a2a.testing.runner --run-timeout 90 --exit-timeout 5 -- src/vaultspec_a2a/providers/tests/test_acp_handler_failure.py -q` -> `pass`

---
tags:
  - '#exec'
  - '#embedded-runtime-remediation'
date: '2026-09-06'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:eadce8b76578fb91da96a2afdd63c048d9d7f835981c4cd1227f70f88cfc8002'
step_id: 'S34'
related:
  - "[[2026-09-05-embedded-runtime-remediation-plan]]"
---
# Verify bounded provider retries and refuse uncertain external-effect replay

## Scope

- `src/vaultspec_a2a/providers/conditions.py`
- `src/vaultspec_a2a/providers/acp_exceptions.py`
- `src/vaultspec_a2a/providers/_acp_types.py`
- `src/vaultspec_a2a/providers/_acp_protocol.py`
- `src/vaultspec_a2a/providers/acp_chat_model.py`
- `src/vaultspec_a2a/providers/codex_chat_model.py`
- `src/vaultspec_a2a/graph/compiler.py`
- `src/vaultspec_a2a/graph/tests/test_compiler.py`
- `src/vaultspec_a2a/providers/tests/test_acp_stop_outcomes.py`
- `src/vaultspec_a2a/providers/tests/test_codex_chat_model.py`

## Changes

- Froze the complete production retry schedule at three attempts with 0.5-second and 1.0-second waits, a 1.0-second interval cap, and no jitter.
- Retained condition-derived and Codex-declared retry verdicts.
- Added provider-level uncertainty for ACP tool/RPC activity and Codex action activity.
- Refused graph retries after client output or any possible external effect.
- Corrected two S87 test-protocol type gaps found by the full-file review.

## Verification

- `uv run python -m vaultspec_a2a.testing.runner --run-timeout 90 --exit-timeout 5 -- ...` -> `19 passed, 56 deselected in 4.86s`
- Production backoff elapsed: 1.52 seconds for 1.5 seconds configured, inside a 3.0-second hard bound.
- Focused Ruff and Ty checks passed.

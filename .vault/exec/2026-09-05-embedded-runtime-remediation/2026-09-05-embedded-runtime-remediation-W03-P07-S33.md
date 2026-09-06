---
tags:
  - '#exec'
  - '#embedded-runtime-remediation'
date: '2026-09-06'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:dd3a0413a10b6b7f0c8aa325070783926cda80b26424170acbebacfe2ddf0a66'
step_id: 'S33'
related:
  - "[[2026-09-05-embedded-runtime-remediation-plan]]"
---
# Carry known setup, authentication, and model-configuration wire conditions through ACP session failures

## Scope

- `src/vaultspec_a2a/providers/_acp_session.py`
- `src/vaultspec_a2a/providers/_acp_auth.py`
- `src/vaultspec_a2a/providers/tests/test_acp_model_selection.py`
- `src/vaultspec_a2a/providers/tests/test_acp_exceptions.py`

## Changes

- Added one wire-aware `AcpSessionError` construction boundary for initialize, session setup, and configuration RPC failures.
- Preserved structured adapter error data and canonical ACP condition mapping.
- Classified authentication-required and explicit authentication failures as `UNAUTHENTICATED`.
- Classified only proven model/native configuration mismatches as non-retryable `INVALID_REQUEST`; ambiguous malformed provider responses remain `UNKNOWN`.
- Added real pipe and bounded unit proofs for initialization, authentication, and model configuration.

## Verification

- `uv run python -m vaultspec_a2a.testing.runner --run-timeout 120 --exit-timeout 5 -- src/vaultspec_a2a/providers/tests/test_acp_model_selection.py src/vaultspec_a2a/providers/tests/test_acp_exceptions.py -q` -> `42 passed in 3.46s`
- Focused Ruff and Ty checks passed.

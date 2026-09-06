---
tags:
  - '#exec'
  - '#embedded-runtime-remediation'
date: '2026-09-06'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:065760e5ad06123ce5fde743781ec70bfb7478afbf460af79fd11e4e20b9c4cd'
step_id: 'S80'
related:
  - "[[2026-09-05-embedded-runtime-remediation-plan]]"
---
# Propagate retained ACP stop meaning through the chat-model stream consumer and authoritative outcome path

## Scope

- `src/vaultspec_a2a/providers/acp_chat_model.py`
- `src/vaultspec_a2a/providers/acp_exceptions.py`
- `src/vaultspec_a2a/providers/__init__.py`
- `src/vaultspec_a2a/streaming/ingest.py`
- `src/vaultspec_a2a/providers/tests/test_acp_stop_outcomes.py`
- `src/vaultspec_a2a/streaming/tests/test_aggregator.py`

## Changes

- Added typed terminal interpretation at the chat-model stream boundary; only `end_turn` returns successfully.
- Preserved the exact stop reason and mapped budget exhaustion, token exhaustion, and refusal to non-retryable provider conditions.
- Added a distinct provider-cancelled exception and mapped it to authoritative cancelled thread and agent lifecycle states.
- Added discriminating tests that drive the protocol response through the real chunk consumer and ingest outcome boundary.

## Verification

- `uv run python -m vaultspec_a2a.testing.runner --run-timeout 120 --exit-timeout 5 -- src/vaultspec_a2a/providers/tests/test_acp_stop_outcomes.py src/vaultspec_a2a/streaming/tests/test_aggregator.py::test_provider_cancelled_prompt_settles_as_cancelled -q` -> `7 passed`
- `uv run ruff check ...` -> pass
- `uv run ty check ...` -> pass

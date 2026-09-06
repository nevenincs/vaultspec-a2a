---
tags:
  - '#research'
  - '#embedded-runtime-remediation'
date: '2026-09-06'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:4401be5f58dd40c211ff0da600af78496031316d301894449f04748ef773805c'
related:
  - "[[2026-09-05-embedded-runtime-remediation-plan]]"
---
# `embedded-runtime-remediation` research: `ACP stop meaning propagation`

## Result

Protocol settlement alone did not preserve ACP terminal meaning. The chat-model consumer yielded queued partial chunks and then returned normally for every settled prompt, so `max_tokens`, `max_turn_requests`, `refusal`, and `cancelled` could become successful LangChain generations. The authoritative ingest path then had no way to distinguish provider cancellation from failure. The safe boundary is to permit success only for `end_turn`, raise typed non-retryable provider outcomes for the other terminal reasons after draining queued chunks, and map provider cancellation to the existing cancelled lifecycle state.

## Findings

### The stream consumer owns success interpretation

`_yield_chunks` is the first layer that has both the drained partial output and the immutable terminal reason. Returning from it authorizes a successful model result. It must therefore return only for `end_turn`; every other accepted stop reason must raise after queued output has been delivered.

### Terminal meanings map to existing condition authority

`max_turn_requests` means the provider-side turn budget is exhausted and maps to `BUDGET_EXHAUSTED`. `max_tokens` and `refusal` are terminal non-retryable request outcomes and map to `INVALID_REQUEST`. Each exception retains the exact ACP stop reason in structured data, preventing prose matching or blind replay.

### Provider cancellation is an authoritative cancelled outcome

ACP `cancelled` is neither successful completion nor an infrastructure failure. A distinct `AcpPromptCancelledError` preserves that meaning through the graph, and ingest settles the run as `ThreadStatus.CANCELLED` while emitting `AgentLifecycleState.CANCELLED`. Broader task-group cancellation ownership remains separately queued as S21.

## Sources

- `src/vaultspec_a2a/providers/acp_chat_model.py`
- `src/vaultspec_a2a/providers/acp_exceptions.py`
- `src/vaultspec_a2a/streaming/ingest.py`
- `src/vaultspec_a2a/providers/tests/test_acp_stop_outcomes.py`
- `src/vaultspec_a2a/streaming/tests/test_aggregator.py`

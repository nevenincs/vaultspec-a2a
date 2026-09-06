---
tags:
  - '#research'
  - '#embedded-runtime-remediation'
date: '2026-09-06'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:0d984177ca2c42d8a2e073c4b53093d1cbd38957d6047a50a83c4b22c1e912ed'
related:
  - "[[2026-09-05-embedded-runtime-remediation-plan]]"
---
# `embedded-runtime-remediation` research: `provider retry bounds`

## Result

The graph already derived retry eligibility from the shared provider-condition vocabulary, counted real attempts across every condition, attached the policy to every model-backed node, honored Codex `willRetry`, and refused retry after client-visible output. Two architectural gaps remained: the policy inherited timing defaults from LangGraph, and “output relayed” did not prove that a tool or command had not already changed external state. The correction freezes the complete local schedule and carries provider-observed effect uncertainty into the retry decision.

## Findings

### Retry timing must be owned by this runtime

A default-constructed LangGraph `RetryPolicy` delegates attempt count, intervals, jitter, and maximum interval to dependency defaults. The runtime now declares three attempts, delays of 0.5 and 1.0 seconds, a 1.0-second interval cap, and no jitter. A real graph invocation proves the complete 1.5-second wait and enforces a 3.0-second outer bound.

### Supported provider wires expose no retry duration

The ACP adapter consumes upstream retry headers internally and does not forward them. Codex exposes only the boolean `willRetry`. There is therefore no provider-supplied duration the node policy can honestly apply. The fixed local schedule is explicit; future duration support requires a new verified wire field rather than reading prose or inventing a delay.

### Tool and command activity makes replay uncertain

Client-visible text was already a no-retry boundary, but external effects can occur without text. ACP now marks uncertainty when tool notifications or effectful filesystem/terminal RPCs occur. Codex marks it from action-item start or completion. Provider failures retain that flag, and the graph refuses retry before evaluating the otherwise retryable condition.

### Existing condition and attachment proofs remain authoritative

Real compiled-graph tests still prove exactly three attempts for throttled, overloaded, and unreachable conditions, and one attempt for all permanent or unknown conditions. Every model-backed node retains the same production policy. The later full A20 breaker/failover qualification remains owned by S24, S56, and the qualification wave.

## Sources

- `src/vaultspec_a2a/graph/compiler.py`
- `src/vaultspec_a2a/graph/nodes/worker.py`
- `src/vaultspec_a2a/providers/_acp_protocol.py`
- `src/vaultspec_a2a/providers/acp_chat_model.py`
- `src/vaultspec_a2a/providers/codex_chat_model.py`
- `src/vaultspec_a2a/graph/tests/test_compiler.py`
- `src/vaultspec_a2a/providers/tests/test_acp_stop_outcomes.py`
- `src/vaultspec_a2a/providers/tests/test_codex_chat_model.py`

---
tags:
  - '#research'
  - '#embedded-runtime-remediation'
date: '2026-09-06'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:beb1dfc0fa7caaae323052d664962148b27528d3fc7ae5e9b5551747d5735040'
related:
  - "[[2026-09-05-embedded-runtime-remediation-plan]]"
---
# `embedded-runtime-remediation` research: `ACP stop reason settlement`

## Result

The ACP prompt response is terminal for five accepted version-1 stop reasons: `end_turn`, `max_tokens`, `max_turn_requests`, `refusal`, and `cancelled`. The protocol loop previously settled only `end_turn`, so every other valid terminal response left the chunk consumer waiting until an unrelated idle deadline. Prompt settlement must be tied to the active prompt request id, preserve the first validated reason, and fail malformed or unknown terminal results immediately.

## Findings

### Every valid reason ends the protocol wait

A successful prompt response already resolves its response future. Keeping `prompt_done` unset for four valid reasons turns a completed protocol exchange into a local hang. Setting it for every accepted reason makes protocol completion independent of whether downstream code treats the reason as success, refusal, cancellation or exhaustion. See `src/vaultspec_a2a/providers/_acp_protocol.py:140`.

### Settlement belongs to the active prompt identity

The previous code inspected `stopReason` on every client response. A response to another in-flight RPC could therefore end the prompt. The active prompt request id is retained in the session context and provides the exact correlation boundary. See `src/vaultspec_a2a/providers/_acp_types.py:175`.

### First terminal truth must be immutable

Duplicate or late prompt responses can race cleanup. Once a validated terminal reason has settled the prompt, a later response must not replace it. Invalid results also need to wake the consumer with a typed prompt error rather than wait for silence detection. Focused tests exercise all five valid reasons, malformed and unknown results, prompt identity, and conflicting duplicates. See `src/vaultspec_a2a/providers/tests/test_acp_handler_failure.py`.

## Sources

- `src/vaultspec_a2a/providers/_acp_protocol.py:140`
- `src/vaultspec_a2a/providers/_acp_types.py:175`
- `src/vaultspec_a2a/providers/tests/test_acp_handler_failure.py`

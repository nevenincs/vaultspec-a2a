---
tags:
  - '#audit'
  - '#embedded-runtime-remediation'
date: '2026-09-06'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:7d87454f2b37479a0ce1540d177a6673a0d1a14f978a2000c84b1f3008c67da2'
related:
  - "[[2026-09-05-embedded-runtime-remediation-plan]]"
---
# `embedded-runtime-remediation` audit: `ACP stop meaning propagation implementation review`

## Scope

Reviewed the chat-model terminal boundary and authoritative ingest outcome mapping for all five accepted ACP version-1 stop reasons, including partial output, retry classification, provider cancellation, and separation from task-group cancellation.

## Findings

### acp-stop-meaning-propagation | high | Non-success terminal reasons became completed model generations

Resolved. The consumer now returns successfully only for `end_turn`. It raises a typed provider exception after draining queued chunks for `max_tokens`, `max_turn_requests`, `refusal`, and `cancelled`, so transport success and partial output cannot authorize completed work.

### acp-stop-meaning-propagation | high | Provider cancellation became generic failure

Resolved. `AcpPromptCancelledError` reaches ingest as a distinct authoritative outcome, which settles `ThreadStatus.CANCELLED` and emits the cancelled agent lifecycle state.

### acp-stop-meaning-propagation | medium | Exhaustion and refusal could invite blind retry

Resolved. `max_turn_requests` maps to non-retryable `BUDGET_EXHAUSTED`; `max_tokens` and `refusal` map to non-retryable `INVALID_REQUEST`. The exact ACP reason remains in structured exception data.

### acp-stop-meaning-propagation | medium | General task-group cancellation still needs ownership cleanup

Open and already queued as W02.P05.S21. This pass handles a provider-supplied terminal `cancelled` reason; it does not claim to settle cancellation of the ingest task group or release executor ownership.

## Verification

- Focused behavior: seven tests passed through the contained runner.
- Ruff formatting and lint passed for all changed source and tests.
- Ty passed for all changed typed source and tests.
- Review correction restored the existing JSON-RPC prompt-error raise after the new terminal helper was initially inserted at the wrong boundary.
## Recommendations

- Keep successful completion restricted to `end_turn` at the stream-consumer boundary.
- Preserve the exact ACP terminal reason in structured exception data.
- Keep provider cancellation mapped to cancelled lifecycle state and leave task-group ownership cleanup to S21.

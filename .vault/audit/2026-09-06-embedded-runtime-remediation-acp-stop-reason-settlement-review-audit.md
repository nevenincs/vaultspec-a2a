---
tags:
  - '#audit'
  - '#embedded-runtime-remediation'
date: '2026-09-06'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:0bd2928f3584a147f2662e06681d7cc47d299617303b4e1f48d2f84c3c395a08'
related:
  - "[[2026-09-05-embedded-runtime-remediation-plan]]"
---
# `embedded-runtime-remediation` audit: `ACP stop reason settlement implementation review`

## Scope

Reviewed prompt-response settlement in the ACP stdout dispatcher, including all accepted terminal reasons, request correlation, malformed responses, duplicate terminal frames, and the downstream boundary that consumes preserved meaning.

## Findings

### acp-stop-reason-settlement | high | Four valid stop reasons left the prompt consumer waiting

Resolved in this pass. `max_tokens`, `max_turn_requests`, `refusal`, and `cancelled` now settle the same protocol wait as `end_turn` while retaining their distinct reason.

### acp-stop-reason-settlement | high | An unrelated RPC response could end the active prompt

Resolved during review. Stop-reason handling now requires the response id to match the active prompt request id.

### acp-stop-reason-settlement | high | A duplicate response could replace terminal truth

Resolved during review. The first settled prompt result is immutable; later terminal responses are logged and ignored.

### acp-stop-reason-settlement | medium | Malformed terminal results deferred failure to the idle watchdog

Resolved during review. Non-object results, missing reasons, malformed reasons and unknown reasons now settle promptly with `AcpPromptError`.

### acp-stop-reason-settlement | high | Downstream outcome mapping was incomplete

Resolved by W03.P07.S80. The chat-model consumer now returns successfully only for `end_turn`, preserves all other terminal meanings as typed outcomes, and maps provider cancellation to the authoritative cancelled lifecycle path. Evidence is recorded in `2026-09-06-embedded-runtime-remediation-acp-stop-meaning-propagation-review-audit`.

## Recommendations

- Keep the five accepted version-1 reasons as a closed set at the protocol boundary.
- Preserve first-writer terminal identity and the active prompt request correlation.
- Keep provider-supplied cancellation distinct from task-group cancellation ownership queued as S21.

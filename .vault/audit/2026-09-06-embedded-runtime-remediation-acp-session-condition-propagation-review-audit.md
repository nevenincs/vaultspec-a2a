---
tags:
  - '#audit'
  - '#embedded-runtime-remediation'
date: '2026-09-06'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:4b1cedcdb7a7689d3e1d734350cc6a08ec494183332159d73695a79ef3d1f143'
related:
  - "[[2026-09-05-embedded-runtime-remediation-plan]]"
---
# `embedded-runtime-remediation` audit: `ACP session condition propagation implementation review`

## Scope

Reviewed condition preservation for ACP initialization, session creation/loading, authentication, and model/native configuration selection. Checked structured wire data, coarse fallback behavior, local condition assertions, and retry meaning.

## Findings

### acp-session-condition-propagation | high | Known session wire failures were reported as unknown

Resolved. Initialization, session setup, and configuration RPC errors now use one wire-aware `AcpSessionError` constructor that preserves structured data and invokes the canonical total ACP mapper.

### acp-session-condition-propagation | high | Authentication-required setup lost its credential remedy

Resolved. Authentication-required session setup and explicit authentication rejection carry `UNAUTHENTICATED`; watchdog, process-exit, and operator-cancelled authentication outcomes remain `UNKNOWN`.

### acp-session-condition-propagation | medium | Unsupported model/config selection invited unhelpful replay

Resolved. Absence from the negotiated option surface and mismatched selection confirmation carry non-retryable `INVALID_REQUEST`.

### acp-session-condition-propagation | medium | Malformed provider responses could be over-classified as caller faults

Resolved during review. Malformed configuration results, malformed initialization surfaces, and incompatible negotiated protocol responses keep `UNKNOWN` unless a wire discriminator proves a finer condition.

## Verification

- 42 focused ACP model-selection and exception tests passed through the contained runner in 3.46 seconds.
- Ruff and Ty passed for all changed source and tests.
- The first session-setup test shape exposed a pre-result process-lifecycle timeout under host contention; it was removed and replaced with a bounded helper-boundary proof. No passing assertion from that timed-out invocation was counted.

## Recommendations

- Route future ACP session error responses through the shared wire-aware constructor.
- Add only locally proven conditions; retain `UNKNOWN` for malformed or ambiguous provider behavior.
- Keep condition retryability owned by `providers/conditions.py`.

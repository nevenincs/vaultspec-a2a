---
tags:
  - '#research'
  - '#embedded-runtime-remediation'
date: '2026-09-06'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:9c4470857134c5ae5dc89d1dfb926278ce645fe09dbe58735bfd628dbadcf58c'
related:
  - "[[2026-09-05-embedded-runtime-remediation-plan]]"
---
# `embedded-runtime-remediation` research: `ACP session condition propagation`

## Result

ACP session failures carried numeric JSON-RPC codes and, for adapter failures, structured `errorKind` data, but each `AcpSessionError` was constructed with the default `UNKNOWN` condition. The existing total ACP mapper already owns this classification. Session setup should construct errors through that mapper, preserve structured data, and use explicit local conditions only where the client itself proves the request cannot succeed unchanged.

## Findings

### Wire classification was discarded at session boundaries

Initialization, `session/new` or `session/load`, and `session/set_config_option` each read an error response and retained only its numeric code in `AcpSessionError`. A shared constructor now preserves the wire data and resolves the condition through `condition_from_acp_error`.

### Authentication-required setup is a known credential condition

A session response identified by the existing authentication-required predicate has a credential remedy. It is carried as `UNAUTHENTICATED`, including the coarse case where an adapter states the requirement without the canonical numeric code. Unknown setup failures still map to `UNKNOWN`.

### Local model-selection failures are non-retryable request outcomes

A requested model or native configuration absent from the negotiated surface, or an adapter confirmation selecting a different value, cannot succeed when replayed unchanged. Those locally proven failures carry `INVALID_REQUEST`. Malformed confirmations and incompatible protocol responses retain `UNKNOWN` because they do not prove a caller fault.

### Authentication RPC rejection also retains its remedy

An explicit authenticate rejection or failure now carries `UNAUTHENTICATED` through `AcpAuthError`. Operator cancellation, watchdog expiry, and subprocess exit keep the honest `UNKNOWN` floor.

## Sources

- `src/vaultspec_a2a/providers/_acp_session.py`
- `src/vaultspec_a2a/providers/_acp_auth.py`
- `src/vaultspec_a2a/providers/conditions.py`
- `src/vaultspec_a2a/providers/tests/test_acp_model_selection.py`
- `src/vaultspec_a2a/providers/tests/test_acp_exceptions.py`

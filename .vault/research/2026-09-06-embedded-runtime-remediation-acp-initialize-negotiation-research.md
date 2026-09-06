---
tags:
  - '#research'
  - '#embedded-runtime-remediation'
date: '2026-09-06'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:2c59f5893aacaab5cb75e5e025442659532e64844444e5af139d27d5de2fc939'
related:
  - "[[2026-09-05-embedded-runtime-remediation-plan]]"
---
# `embedded-runtime-remediation` research: `ACP initialize negotiation`

## Result

The client sends ACP protocol version 1 but previously ignored the version returned by the agent and coerced malformed initialization fields into empty structures. That allowed session creation on an unverified protocol and silently converted a requested session resume into a new session when `loadSession` was absent. The accepted provider architecture requires exact version negotiation and refusal before session creation.

## Findings

### The response version is execution authority

The request advertises version 1, while the response is the agent's negotiated version. Continuing without checking the returned integer lets later filesystem, terminal, session and prompt messages run against an unproven wire contract. The comparison must reject absent values, strings and booleans as malformed and reject every integer other than the requested version as incompatible. See `src/vaultspec_a2a/providers/_acp_session.py:320` and `src/vaultspec_a2a/providers/_acp_session.py:401`.

### Requested resume makes loadSession mandatory

A configured session id expresses resume intent. The old setup branch used `session/load` only when `loadSession` was exactly true and otherwise fell through to `session/new`, changing the requested operation. Initialization can reject that mismatch before any session RPC because it already has both the configured intent and negotiated agent capabilities. See `src/vaultspec_a2a/providers/_acp_session.py:416`.

### Malformed optional surfaces must not be normalized

Absent optional capabilities or authentication methods can retain their protocol-defined empty meaning. Present values with the wrong container or entry type are malformed peer responses. Filtering or coercing them hides a wire incompatibility and creates an unrecorded compatibility path. Focused real-pipe tests cover exact version acceptance, incompatible and malformed versions, missing required resume support, and malformed response surfaces. See `src/vaultspec_a2a/providers/tests/test_acp_model_selection.py:187`.

## Sources

- `src/vaultspec_a2a/providers/_acp_session.py:320`
- `src/vaultspec_a2a/providers/_acp_session.py:401`
- `src/vaultspec_a2a/providers/_acp_session.py:416`
- `src/vaultspec_a2a/providers/tests/test_acp_model_selection.py:187`

---
tags:
  - '#audit'
  - '#embedded-runtime-remediation'
date: '2026-09-06'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:aaefa8065268272b5fac58f1e06b111165d82ad81ccadefab8dd9a177eda5c3e'
related:
  - "[[2026-09-05-embedded-runtime-remediation-plan]]"
---
# `embedded-runtime-remediation` audit: `ACP initialize negotiation implementation review`

## Scope

Reviewed ACP initialization from request emission through response parsing and the session setup decision, including exact version typing, incompatible versions, malformed negotiated fields, required resume capability, and removal of coercive parsing.

## Findings

### acp-initialize-negotiation | high | Returned protocol version was ignored

Resolved in this pass. Initialization now accepts only an integer version equal to the requested ACP version 1. Missing, string and boolean values fail as malformed; other integers fail as incompatible before session creation.

### acp-initialize-negotiation | high | Unsupported resume silently created a new session

Resolved in this pass. A configured session id now makes negotiated `loadSession: true` mandatory during initialization. The prior fallthrough to `session/new` is unreachable.

### acp-initialize-negotiation | medium | Malformed negotiated fields were coerced or filtered

Resolved during review. A non-object result, malformed capabilities, malformed authentication-method container, or non-object authentication entry now fails explicitly. Absent optional fields retain only their defined empty meaning.

### acp-initialize-negotiation | low | Initial resume test mutated a frozen configuration

Resolved during verification. The failing test exposed that `AcpModelConfig` is immutable; the fixture builder now constructs the requested session identity rather than mutating a built instance. The production path was unaffected.

### acp-initialize-negotiation | low | Error taxonomy has no dedicated protocol mismatch code

Open and queued here. The current domain error set uses `INVALID_PARAMS` for a valid but incompatible returned version and `INTERNAL_ERROR` for malformed peer responses. A dedicated condition should be considered only with the later provider-condition contract work so clients do not receive an uncoordinated new discriminator.

## Recommendations

- Keep the request and accepted response version bound to one constant.
- Preserve exact refusal when resume support is absent; never substitute session creation.
- Revisit the externally served mismatch condition with the provider-condition step rather than adding an isolated error code here.

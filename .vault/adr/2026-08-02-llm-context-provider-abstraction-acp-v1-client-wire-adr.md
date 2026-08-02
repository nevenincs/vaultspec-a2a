---
tags:
  - '#adr'
  - '#llm-context-provider-abstraction'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:d613b9ba7f132f06642751188081091114f5b929cf7aa9c80ff63b965cfe801a'
related:
  - "[[2026-08-02-llm-context-provider-abstraction-acp-v1-client-wire-research]]"
  - "[[2026-08-02-llm-context-provider-abstraction-acp-v1-client-wire-reference]]"
  - "[[2026-02-25-llm-context-provider-abstraction-adr]]"
---
# `llm-context-provider-abstraction` adr: `ACP v1 client wire conformance` | (**status:** `accepted`)

## Problem Statement

The provider harness is a version-1 ACP client, yet its agent-initiated filesystem and terminal paths currently expose local shapes that are not the ACP v1 contract. This creates preventable interoperability risk below, but does not reopen, the accepted subscription-first provider-harness architecture. `2026-08-02-llm-context-provider-abstraction-acp-v1-client-wire-research` establishes the bounded mismatch and `2026-08-02-llm-context-provider-abstraction-acp-v1-client-wire-reference` pins its contract.

## Considerations

- The existing accepted provider-harness ADR remains governing for subscription-first execution, ACP transport, and the future SDK migration; this ADR decides only client wire conformance. `2026-02-25-llm-context-provider-abstraction-adr`.
- Client requests and response lifetimes form one contract: pagination, session ownership, output retention, exit representation, and terminal release must not evolve independently. `2026-08-02-llm-context-provider-abstraction-acp-v1-client-wire-research`.
- No supported client has evidence of relying on the divergent legacy shapes. `2026-08-02-llm-context-provider-abstraction-acp-v1-client-wire-research`.

## Considered options

- **Keep the local shapes.** Rejected: it leaves the known contract mismatch and makes future SDK adoption less credible.
- **Temporarily accept both legacy and v1 shapes.** Rejected: byte and line pagination have incompatible meanings, the additional public contract would need a removal policy, and no supported-client evidence justifies it.
- **Replace the affected surface directly with ACP v1.** Accepted: one explicit contract, an unambiguous ownership and resource model, and real wire-level verification.

## Constraints

- The change remains within protocol version 1 and must not silently broaden client capability authority.
- The direct replacement may not add aliases, fallback parsing, compatibility flags, or undocumented legacy payload acceptance.
- Existing provider behaviour outside the affected client requests remains unchanged unless a separately grounded decision says otherwise.
- Real subprocess tests must prove the supported adapter path; isolated in-process doubles cannot establish wire compatibility.

## Implementation

Implement one validated v1 request boundary for filesystem and terminal RPCs. Enforce session identity on each affected request. Replace byte-offset read handling with one-based line selection and line-count limiting. Track terminal retained output under the requested byte cap, return v1 exit-status objects, and keep a killed terminal addressable until release. Add exact request/response and lifecycle probes through the real adapter path; invalid or cross-session input must fail closed.

A follow-on implementation plan will divide handler migration, real-stdio verification, and the strict typing/quality gates. The plan must include removal proof showing that neither legacy `offset` semantics nor scalar terminal exit status remains accepted.

## Rationale

Direct ACP v1 conformance wins because it resolves the demonstrated mismatch with one public language and avoids manufacturing a second, unproven compatibility contract. The bounded change advances the accepted provider-harness architecture without preempting its planned SDK migration. `2026-08-02-llm-context-provider-abstraction-acp-v1-client-wire-research` and `2026-08-02-llm-context-provider-abstraction-acp-v1-client-wire-reference`.

## Consequences

- Agents using the v1 client contract receive schema-aligned filesystem and terminal behaviour.
- Any unproven consumer sending the prior shapes will fail visibly rather than receive silently divergent semantics.
- Terminal lifecycle state becomes explicit: kill stops execution, release ends addressability.
- The follow-on must demonstrate line semantics, byte-safe retained output, session isolation, and post-kill observability through real protocol traffic.

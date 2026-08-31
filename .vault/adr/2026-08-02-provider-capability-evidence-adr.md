---
tags:
  - '#adr'
  - '#provider-capability-evidence'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:b82bf90a01b5c6b2ddae812bc62f06b98cf8a79ded6d043fec97085a41ce0eb6'
related:
  - "[[2026-08-02-provider-capability-evidence-research]]"
---
# `provider-capability-evidence` adr: `execution-mode capability evidence matrix` | (**status:** `accepted`)

## Problem Statement

Provider catalog health answers whether a model selection is selectable, while separate provider rules answer web activation, MCP permissioning, and completed-turn admission. The product has no single truthful surface for a lane that is upstream-supported but unlicensed, configured but unproven, historically proven but currently blocked, or intentionally denied by local policy. `2026-08-02-provider-capability-evidence-research` grounds the required distinctions.

## Considerations

- `2026-08-02-provider-model-catalog-adr` makes catalog identity execution-mode-specific and keeps admission separate from authentication and enumeration.
- `2026-08-01-tool-cores-web-grounding-adr` requires web support and local proof-gated activation to remain distinct.
- `2026-07-17-kimi-provider-adr` owns Kimi native ACP permission enforcement.
- Vendor documentation establishes upstream support only; it cannot activate a local claim.

## Considered options

- Extend structured catalog health with every capability. Rejected: catalog health and model selectability would acquire unrelated tool and permission semantics.
- Publish a static provider comparison table. Rejected: it would conflate providers with execution modes and rot as credentials and runtime versions change.
- Derive capability truth from adapter type. Rejected: shared ACP transport cannot prove provider configuration, permissions, or completed work.
- Introduce an execution-mode capability-evidence matrix. Proposed: it composes existing facts without replacing their owners.

## Constraints

- Matrix identity is `ProviderCatalogKey` plus capability; evidence never transfers across provider, backend, API/CLI mode, or sibling capability.
- Every external lane carries every matrix capability, and the capability set is immutable and complete.
- Support, local proof, current blockers, and permission mode are independent facts. Missing credentials block a lane; they never establish non-support.
- `PROVEN` requires an exact-lane rerunnable real-behavior test. A support source may not activate a product claim.
- Web search and fetch, native read and write, and subagent and background are independent capabilities.
- Model selectability remains governed by catalog health plus exact-lane admission; capability proof additionally gates only roles and claims that require that capability.

## Implementation

A provider-catalog-owned matrix will expose catalog enumeration, exact selection, completed turn, MCP, native read, native write, web search, web fetch, subagent, and background capability records for every external execution lane. A record carries immutable upstream support, an optional exact-lane proof, typed bounded blockers, and an optional permission mode. Its derived state is unsupported, blocked, supported, or proven.

The matrix reads existing catalog discovery, exact-lane admission, web proof, and permission contracts rather than reimplementing them. KimiÃ¢â‚¬â„¢s native ACP record retains its local read-only policy, while Kimi Claude Code compatibility remains a separate upstream execution mode. API lanes expose unsupported local filesystem and MCP capabilities until a framework binding exists.

## Rationale

The evidence matrix preserves the existing decisionsÃ¢â‚¬â„¢ ownership boundaries while making their combined consequences inspectable. It correctly represents an unlicensed Kimi lane as credential-blocked and a documented but unproven capability as supported, avoiding both false green status and accidental removal of a future remediation path.

## Consequences

- Provider capability disclosure becomes precise enough for the Dashboard and operator workflows without authorizing unproven work.
- A provider can become selectable for ordinary turns while capability-required roles remain blocked until their own proof exists.
- Every new provider or execution mode must receive complete, explicit matrix entries.
- The implementation must maintain evidence citations and invalidation when runtime identity changes.

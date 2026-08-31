---
tags:
  - '#research'
  - '#provider-capability-evidence'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:c097cc52bf5830dc9989c3d9a67cc0a0f0b7a515b401f4da940be84a6fe6d148'
related: []
---
# `provider-capability-evidence` research: `execution-mode capability evidence`

A capability matrix can truthfully represent unlicensed Kimi and configured Z.ai only when support, local proof, current blockers, and permission policy remain separate facts. Existing catalog health and web proof decide part of this already, but they do not provide one execution-mode-scoped capability contract.

## Findings

### Existing health and admission evidence is orthogonal

Catalog health separates configuration, transport, authentication, catalog availability, admission, and derived selectability. Authentication or catalog enumeration cannot admit a lane; only a completed real turn does. `.vault/adr/2026-08-02-provider-model-catalog-adr.md`, `src/vaultspec_a2a/providers/lane_admission.py:169`, and `src/vaultspec_a2a/providers/model_profiles.py:510`.

### Provider identity is too broad for capability proof

Catalog records already require provider plus execution mode, and no API catalog may authorize a CLI or ACP selection. Capability evidence therefore needs the same identity plus capability name; a proof must not transfer across provider, backend, or execution mode. `.vault/reference/2026-08-02-provider-model-catalog-reference.md`; `src/vaultspec_a2a/providers/lane_admission.py:202`.

### Support, proof, and blocking need distinct states

The web gate shows that a supported capability cannot activate or be claimed until local completed-work evidence exists. The matrix must distinguish proven, supported-unproven, blocked with a typed safe reason, and unsupported. `.codex/rules/no-unproven-providers-in-served-profiles.md`; `src/vaultspec_a2a/providers/lane_admission.py:383`.

### Kimi Claude Code compatibility is mode-specific upstream support

Kimi documents an Anthropic-compatible Claude Code configuration, including endpoint, authentication, tier, and subagent variables. It directs operators to verify status and complete a real message. That is upstream support evidence only; it does not prove a local Kimi ACP lane, nor does it transfer to a different execution mode. https://platform.kimi.ai/docs/guide/claude-code-kimi

### Kimi documents conditional and absent web capabilities

For its Claude Code compatibility configuration, K2.7 Code requires thinking enabled for WebSearch, while WebFetch is documented unavailable. These are model and mode conditions, not universal Kimi claims. https://platform.kimi.ai/docs/guide/claude-code-kimi

### Native Kimi ACP has a separate permission contract

The accepted Kimi provider ADR selects native `kimi acp`, session-injected MCP, and exact-name permission enforcement; it does not share the Claude `allowedTools` transport. Permission mode must therefore be an explicit capability fact. `.vault/adr/2026-07-17-kimi-provider-adr.md`.

### Missing license is a credential blocker

An absent Kimi account must leave the lane represented as credential-blocked, unselectable, and unproven; it is neither unsupported nor green. `.vault/reference/2026-08-02-provider-model-catalog-reference.md`.

## Sources

- `.vault/adr/2026-08-02-provider-model-catalog-adr.md`
- `.vault/reference/2026-08-02-provider-model-catalog-reference.md`
- `.vault/adr/2026-07-17-kimi-provider-adr.md`
- `src/vaultspec_a2a/providers/lane_admission.py:169`
- `src/vaultspec_a2a/providers/model_profiles.py:510`
- `.codex/rules/no-unproven-providers-in-served-profiles.md`
- https://platform.kimi.ai/docs/guide/claude-code-kimi

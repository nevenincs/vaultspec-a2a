---
tags:
- '#adr'
- '#llm-context-provider-abstraction'
date: 2026-02-25
modified: '2026-09-06'
body_hash: 'sha256:9dcc7c2d35ea043657e95d9dd2a1ac430c34ab64be07cd1e61777dbe2d3a9a29'
related:
  - '[[2026-03-31-docs-vault-migration-research]]'
  - '[[2026-07-14-orchestration-capabilities-research]]'
  - '[[2026-07-14-orchestration-capabilities-audit]]'
  - '[[2026-09-05-embedded-runtime-remediation-research]]'
  - '[[2026-09-06-embedded-runtime-remediation-acp-initialize-negotiation-research]]'
---

# `llm-context-provider-abstraction` adr: `subscription-first provider harness over ACP` | (**status:** `accepted`)

## Problem Statement

The orchestrator's economic foundation is flat-rate consumer subscriptions: coding agents (Claude, Gemini) run as provider CLIs wrapped over ACP stdio JSON-RPC so agentic loops bill against subscriptions, never pay-as-you-go developer APIs. That core decision stands. What has decayed is the implementation strategy around it: the capability audit (`2026-07-14-orchestration-capabilities-audit`) found hand-rolled ACP protocol plumbing, a deprecated Claude adapter package pin, hardcoded multi-step command-resolution chains, provider-identity leaks inside the generic session layer, and a `Provider` enum that conflates vendor with execution mechanism. Meanwhile the ACP ecosystem matured into exactly the harness this project was hand-building (`2026-07-14-orchestration-capabilities-research`). A decision is needed now on how the provider layer is provisioned going forward, before further agents are added.

This record amends the original ADR-002 (2026-02-25, migrated from the legacy docs tree) in place; the original's context-management decisions (state checkpointing, clean handoffs) are unchanged and remain in force.

## Considerations

- Subscription economics are the knockout driver: CLI wrapping exists to absorb agentic loops into flat-rate plans (original ADR-002 rationale, reaffirmed by the owner 2026-07-14).
- No surveyed project unifies API and CLI execution under one abstraction; Zed runs two subsystems joined at the client (`2026-07-14-orchestration-capabilities-research`).
- An official Python ACP SDK (`agent-client-protocol@0.11.0`, Python 3.13-compatible) and a CDN-served agent registry (~50 agents, pinned binary/npx specs) now exist (research, same stem).
- ACP standardizes auth negotiation (`authMethods`/`authenticate`) and per-session MCP server injection (research).
- The Claude adapter moved to `@agentclientprotocol/claude-agent-acp`; the currently pinned `@zed-industries` path is deprecated (research).
- gemini-cli headless OAuth over ACP is broken upstream; API-key auth is the only reliable headless Gemini path today (research).
- No live end-to-end agent turn has ever been verified (`2026-07-14-orchestration-capabilities-audit`); integration claims must be probe-verified before load-bearing adoption.

## Considered options

- **Status quo (hand-rolled ACP plumbing, hardcoded resolution).** Rejected: four in-house `_acp_*` modules duplicate a maintained SDK, the adapter pin is deprecated, resolution chains break across machines, and auth grows as inline branches - the drift the audit documents.
- **Force-unified single provider abstraction spanning API and CLI.** Rejected: unsolved industry-wide; would invent novel architecture where the mission is to stop inventing. The `BaseChatModel` facade already gives sufficient call-site uniformity.
- **API-first, subscriptions demoted.** Rejected outright: violates the economic driver; developer-API billing for agentic loops is the exact failure mode this architecture exists to prevent.
- **Modernized dual architecture on ACP ecosystem components (chosen).** Subscription CLI execution stays primary, rebuilt on the official SDK, registry-based resolution, and negotiated auth; direct-API providers remain a sanctioned fallback tier behind the same facade.

## Constraints

- `agent-client-protocol@0.11.0` client-side coverage (permission RPCs, terminal RPCs, session fork/list) is README-claimed but unverified; adoption is gated on a probe script proving parity with the current `_acp_*` layer against a real adapter.
- The ACP registry has no PyPI consumer; a small HTTP reader with a local cache is required, and offline operation must fall back to cached or settings-declared launch specs.
- gemini-cli headless OAuth (upstream issues 7549/12042) forces API-key auth for Gemini until fixed; this is an upstream dependency outside our control.
- Consumer OAuth flows remain volatile by nature (original ADR-002 consequence, still true): providers can rotate or deprecate headless token flows at their discretion.
- The Windows subprocess constraints of the original record (no PTY, no `cmd.exe /c` wrapping, `.cmd`-shim-aware spawning) remain binding on whatever the SDK's transport does; if the SDK's spawn path violates them it cannot be adopted for transport, only for schema/framing.

## Implementation

Five layers, replacing the current factory-branch design:

- **Provider descriptors and registry.** Each provider/agent is a declarative descriptor - vendor, execution mode (`cli` or `api`), launch spec or API binding, auth methods, model catalog - registered in a provider registry consulted by the existing `ProviderFactoryProtocol` seam. The flat vendor enum splits into vendor identity plus explicit execution mode, threaded through agent/team TOML config.
- **Agent resolution.** CLI agents resolve from declarative settings entries (command, args, env) and the ACP registry index (pinned platform binaries or npx specs) with a local cache, replacing hardcoded npm paths, the Docker absolute path, and per-vendor fallback chains. The Claude adapter pin migrates to `@agentclientprotocol/claude-agent-acp`.
- **Auth.** CLI-agent auth moves to ACP `authMethods`/`authenticate` negotiation where the adapter supports it; the 1-year headless Claude token (`claude setup-token`, validated in the original record) remains the Claude method of choice; Gemini uses API-key auth headlessly until upstream OAuth is fixed. API-tier credentials follow stored-credential, then environment, then explicit-option resolution. The environment-scrubbing model is retained as sandbox hygiene, no longer as the auth mechanism.
- **Session runtime.** The ACP schema/framing layer is replaced by the official Python SDK (probe-gated per Constraints); the session model, streaming translation to LangChain chunks, and cancellation semantics of the current `AcpChatModel` are preserved on top of it. Per-session MCP server injection uses the protocol's first-class `mcpServers` field.
- **API fallback tier.** Direct-API providers instantiate per-vendor LangChain packages behind the same descriptor registry, replacing the one-`ChatOpenAI`-branch-per-vendor pattern. GLM remains the reference case.

### Complete input, safe prompt views and native controls

Every invocation budgets the assembled provider-visible input immediately before dispatch: persona/rules, workspace mounts, conversation, tool declarations, call arguments/results and reserved output. Units, source and confidence are explicit; approximations and unknown values never masquerade as exact measurements. Input that cannot fit after safe compaction refuses before dispatch.

Compaction creates a replacement prompt view from durable state without overwriting the authoritative transcript. Pinned instructions, workspace identity, pending actions and complete call/result groups survive. Removed conversational meaning has a durable summary with source-range provenance. Commit the view only after budget and structural validation; interruption/failure retains the prior view. New messages remain journalled and follow the committed view in order; cancellation retains priority. Semantic fidelity is proven by continuation tests, not assumed from the existence of a summary. Native compaction claims require independent proof.

Native commands are session-scoped discovered capabilities with supported, blocked or unsupported dispositions. Adapters use the negotiated mechanism, including prompt syntax where appropriate; unknown commands cannot silently become ordinary chat. Identity, arguments, busy disposition, outcome and compaction status are observable through the coordinated control/status contract. No generic shell or arbitrary RPC escape is introduced.

Initialization validates the returned protocol version before sessions or optional operations. Every valid terminal stop outcome settles the stream and preserves refusal, cancellation or budget-exhaustion meaning; partial output and transport success cannot imply completed work. The existing SDK migration remains probe-gated and is not a prerequisite imposed on these corrections.

Grounding for the 2026-09-05 refinement: `2026-09-05-embedded-runtime-remediation-research`. Accepted under the owner's explicit ADR auto-approval; implementation awaits plan approval.

## Rationale

The subscription-first CLI architecture was correct and is reaffirmed; the research shows the surrounding ecosystem caught up and now maintains, as shared infrastructure, everything this repo hand-rolled - protocol framing (official SDK), agent distribution (registry consumed by Zed and JetBrains), and login standardization (`authMethods`). Adopting those components eliminates the audited drift (deprecated pins, resolution chains, inline auth) without touching the economic driver or the `BaseChatModel`/`ProviderFactoryProtocol` facade the graph layer depends on. Mirroring Zed's two-subsystem split rather than force-unifying keeps us on the proven pattern; the explicit vendor-x-mechanism config axis fixes the audited enum conflation with a contained blast radius.

## Consequences

- Gains: four in-house protocol modules deleted in favor of a maintained SDK; new coding agents (Codex, Copilot CLI, Goose, OpenCode) become registry entries plus a descriptor instead of code; login becomes protocol-negotiated instead of env-var archaeology; the audited provider-identity leaks in the generic session layer are removed.
- Difficulties: dependency on the SDK's release cadence and on registry availability (mitigated by local cache and settings-declared fallbacks); migration touches every preset TOML and the team-config schema; the probe gate must pass before the SDK swap lands - if it fails, only the descriptor/registry/auth layers proceed and framing stays in-house.
- Opens: per-session MCP injection gives the orchestrator direct control over each agent's tool surface, the foundation for per-agent security constraints; the descriptor model is the natural home for future per-agent capability policy.
- Unchanged risks: consumer OAuth volatility persists; upstream gemini-cli auth bugs bound Gemini's headless auth options.

## Amendment (2026-09-06): Gemini compatibility support retired

The accepted provider-model-catalog decision now exclusively governs the active
provider and execution-mode inventory. Its 2026-09-06 amendment retires
`gemini/gemini-cli-acp` because the lane existed only to keep old configurations
working and no current nonlegacy mechanism depends on it.

Every Gemini-specific provider, launch, authentication, credential-refresh,
settings, provisioning, and construction promise above is historical and no
longer authorizes implementation. Generic ACP remains an accepted transport
shape, but catalog discovery consumes only negotiated `configOptions`; it does
not accept `models.availableModels` or another old response as a fallback. A
future Gemini lane requires a new current decision, explicit registration, and
exact-mode evidence. Retired identifiers and configurations fail closed and are
never translated into another active provider.

---
tags:
  - '#research'
  - '#orchestration-capabilities'
date: '2026-07-14'
modified: '2026-07-14'
related:
  - "[[2026-07-14-orchestration-capabilities-audit]]"
  - "[[2026-07-14-a2a-edge-conformance-adr]]"
---

# `orchestration-capabilities` research: `provider harness prior art: Zed ACP ecosystem and pi.dev packages`

Question: how should the provider layer be redesigned to support both remote model APIs and local CLI agents without inventing a harness other projects already ship? Stakes: the capability audit (`.vault/audit/2026-07-14-orchestration-capabilities-audit.md`) found the current layer conflates vendor with execution mechanism, hand-rolls ACP JSON-RPC, and hardcodes command resolution and auth. Conclusion of the evidence: a single unified API+CLI provider abstraction is not a solved problem anywhere surveyed - Zed deliberately runs two separate subsystems, and pi.dev's core is API-first with CLI-agent driving only as a community extension. What IS solved and adoptable: the ACP spec's capability-negotiated auth, an official Python ACP SDK that replaces our hand-rolled protocol plumbing, a CDN-served agent registry that replaces hardcoded CLI resolution, and pi-ai's credential-resolution and normalized-streaming patterns. The evidence favors mirroring Zed's two-subsystem split behind our existing `BaseChatModel` facade rather than force-unifying.

## Findings

### The API+CLI unification we want is unsolved industry-wide

No surveyed project unifies remote-API providers and local CLI agents under one abstraction. Zed keeps two disjoint subsystems: `agent_servers` (ACP CLI agents: process spawn + JSON-RPC) and `language_model`/`language_models` (a `LanguageModelProvider` trait + `LanguageModelRegistry` for Anthropic/OpenAI/Google/Ollama/OpenRouter direct APIs) - transport adapter vs SDK client, never variants of one interface (https://deepwiki.com/zed-industries/zed/9-language-model-integration, https://zed.dev/docs/ai/llm-providers, https://zed.dev/docs/ai/external-agents). pi.dev's core (`@earendil-works/pi-ai`) is API-first; driving external CLI agents exists only as the third-party ACP extension `pi-shell-acp` (https://github.com/junghan0611/pi-shell-acp), with core ACP support still an open discussion (https://github.com/earendil-works/pi/discussions/4444). LiteLLM, aisuite, and LangChain `init_chat_model` are API-only. Our engine's existing split (ACP subprocess vs `ChatOpenAI`) matches the industry pattern; the defect is that the split is implicit in the `Provider` enum, not that the split exists.

### ACP spec: auth and MCP config are protocol-negotiated, not env-injected

The ACP v1 spec standardizes what we currently hardcode. Auth: `InitializeResponse.authMethods: AuthMethod[]` advertises each agent's login options (OAuth vs API key vs none) and the client calls `authenticate({methodId})` only if needed (https://agentclientprotocol.com/protocol/schema). MCP servers are a first-class per-session field: `NewSessionRequest.mcpServers` carries stdio/http/sse server specs, so the client owns MCP config and injects it into any spawned agent (same schema page). Session lifecycle is `session/new`/`session/load`/`session/prompt`/`session/update`/`session/cancel` with `session/set_mode` for modes (https://agentclientprotocol.com/protocol/overview). Gaps: model selection is NOT standardized - gemini-cli ships an unstable `unstable_setSessionModel` extension only (https://github.com/google-gemini/gemini-cli/blob/main/docs/cli/acp-mode.md) - and the spec has no agent-discovery method; discovery is the client's job.

### An official Python ACP SDK exists and supersedes our hand-rolled plumbing

`agent-client-protocol@0.11.0` (2026-07-05, Python >=3.10,<3.15 - compatible with our 3.13) ships generated Pydantic schema models tracking ACP releases, an asyncio stdio JSON-RPC transport, and helper builders mirroring the Go/TS SDKs (https://pypi.org/project/agent-client-protocol/, https://github.com/agentclientprotocol/python-sdk, https://agentclientprotocol.com/libraries/python). This directly replaces the in-house `providers/_acp_protocol.py`, `_acp_rpc_handlers.py`, `_acp_session.py`, `_acp_types.py` framing layer. Unverified: whether its models are regenerated automatically per release, and the exact client-vs-agent-side coverage (README-claimed, source not read).

### The ACP registry replaces hardcoded CLI command resolution

A CDN-served index at https://cdn.agentclientprotocol.com/registry/v1/latest/registry.json (backed by https://github.com/agentclientprotocol/registry) lists ~50 agents as of ~June 2026 (Claude Code, Gemini CLI, Codex, Copilot CLI, Goose, OpenCode, Cursor), each resolving to a pinned platform binary or an npx launch spec; Zed and JetBrains both consume it (https://zed.dev/blog/acp-registry, https://blog.jetbrains.com/ai/2026/01/acp-agent-registry/). This is the direct alternative to our hardcoded npm paths, Docker absolute path, and 5-deep Gemini fallback chain (`src/vaultspec_a2a/providers/factory.py:69-171`). No PyPI client for the registry index exists; consumption would be a small custom HTTP reader against the published JSON. Zed's own registration model (settings-declared `{command, args, env}` entries + extension-bundled + registry-sourced, in `AgentServerStore`) is the shape for a declarative agent-server config (https://deepwiki.com/zed-industries/zed/8.3-agent-server-discovery).

### Adapter ecosystem status and a live headless-auth hazard

The Claude adapter moved to `@agentclientprotocol/claude-agent-acp` (old `@zed-industries/claude-code-acp` names still resolve but are deprecated for updates) and wraps the official Claude Agent SDK (https://github.com/zed-industries/claude-agent-acp, https://zed.dev/blog/claude-code-via-acp) - our factory pins the old package path (`factory.py:24-31`). Gemini CLI's ACP flag is now `--acp` (renamed from `--experimental-acp`), and two open bugs matter to us: ACP mode does not reuse cached OAuth credentials (https://github.com/google-gemini/gemini-cli/issues/7549) and OAuth login hangs when spawned from a non-tty parent such as a Python process (https://github.com/google-gemini/gemini-cli/issues/12042). For headless orchestration, API-key auth for gemini-cli is the only reliable path today - an environment constraint, not something fixable client-side.

### pi.dev: portable patterns, no importable code

pi.dev is Mario Zechner's TypeScript monorepo (org `earendil-works/pi`, ex `badlogic/pi-mono`; ~62k stars, v0.73, MIT core, single maintainer; https://pi.dev/news/2026/5/7/pi-has-a-new-home, https://github.com/earendil-works/pi). The `/packages` page lists community plugins for pi, not the core. Nothing is importable from Python; four patterns are portable (https://github.com/earendil-works/pi/blob/main/packages/ai/README.md, https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/models.md):
- One normalized streaming-event vocabulary across 30+ providers (`text_delta`, `toolcall_delta`, `thinking_*`) - the abstraction shape for the API-side surface.
- Credential resolution order as policy: stored credential -> env var -> explicit option, with OAuth subscription login (Claude Pro/Max, ChatGPT Plus, Copilot) and auto-refresh under a store lock (subscription-login list partially unverified against primary source).
- A hot-reloaded local model-catalog file (`~/.pi/agent/models.json`); custom entries need only `baseUrl` + API type (`openai-completions`/`openai-responses`/`anthropic-messages`/`google-generative-ai`), which is also how local models (Ollama/vLLM/LM Studio) register with no code. models.dev integration is NOT core - it is the opt-in extension `pi-models-dev-providers` (https://www.npmjs.com/package/pi-models-dev-providers).
- Provider registration as a pluggable ExtensionAPI rather than hardcoded branches.
Differentiator vs LiteLLM/aisuite/`init_chat_model`: OAuth-native subscription login plus the unified streaming-event model; none of the four bridge to CLI agents in core.

### Option space the ADR must settle

- Architecture: mirror Zed's two-subsystem split (ACP agent-server subsystem + API provider registry, joined only at the `BaseChatModel` facade we already have via `ProviderFactoryProtocol`) vs force-unifying under one provider interface no surveyed project ships. Evidence favors the split; the vendor-vs-mechanism conflation is fixed by making execution surface explicit in config, not by one mega-abstraction.
- ACP plumbing: adopt `agent-client-protocol@0.11.0` and delete the in-house `_acp_*` modules vs keep hand-rolled framing. Adoption requires verifying the SDK covers our client-side needs (permission RPCs, terminal RPCs, session fork/list).
- Agent discovery: consume the ACP registry index (pinned binaries/npx specs) + declarative settings entries vs current hardcoded resolution chains.
- Auth: move CLI-agent auth to ACP `authMethods`/`authenticate` negotiation where adapters support it, with pi-style stored->env->explicit credential resolution for API providers; keep the env-scrub model only as sandbox hygiene. Constraint: gemini-cli headless OAuth is broken upstream (issues 7549/12042).
- API-side instantiation: per-vendor langchain packages (`langchain_anthropic` etc.) or `init_chat_model` behind a small registry, replacing the one-`ChatOpenAI`-branch-per-vendor pattern.
- Model catalog: static `MODEL_MAP` in `graph/enums.py` vs a hot-reloadable catalog file (pi pattern) vs registry/models.dev-sourced.

Not investigated: Zed's keychain credential-storage internals and Copilot device-code flow; ACP raw schema types for `session/set_mode`; pi OAuth token storage formats; whether the ACP Python SDK implements agent-side as well as client-side.

## Sources

- https://agentclientprotocol.com/protocol/overview
- https://agentclientprotocol.com/protocol/schema
- https://agentclientprotocol.com/libraries/python
- https://pypi.org/project/agent-client-protocol/
- https://github.com/agentclientprotocol/python-sdk
- https://github.com/agentclientprotocol/registry
- https://cdn.agentclientprotocol.com/registry/v1/latest/registry.json
- https://zed.dev/blog/acp-registry
- https://zed.dev/blog/claude-code-via-acp
- https://zed.dev/docs/ai/external-agents
- https://zed.dev/docs/ai/llm-providers
- https://deepwiki.com/zed-industries/zed/8.3-agent-server-discovery
- https://deepwiki.com/zed-industries/zed/9-language-model-integration
- https://github.com/zed-industries/claude-agent-acp
- https://www.npmjs.com/package/@zed-industries/claude-code-acp
- https://github.com/google-gemini/gemini-cli/blob/main/docs/cli/acp-mode.md
- https://github.com/google-gemini/gemini-cli/issues/7549
- https://github.com/google-gemini/gemini-cli/issues/12042
- https://github.com/google-gemini/gemini-cli/issues/10855
- https://blog.jetbrains.com/ai/2026/01/acp-agent-registry/
- https://pi.dev/packages
- https://pi.dev/news/2026/5/7/pi-has-a-new-home
- https://github.com/earendil-works/pi
- https://github.com/earendil-works/pi/blob/main/packages/ai/README.md
- https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/models.md
- https://github.com/earendil-works/pi/discussions/4444
- https://github.com/junghan0611/pi-shell-acp
- https://www.npmjs.com/package/pi-models-dev-providers
- https://mariozechner.at/posts/2025-11-30-pi-coding-agent/
- `src/vaultspec_a2a/providers/factory.py:24-31` (deprecated adapter package pin), `factory.py:69-171` (hardcoded resolution chains) - full internal state recorded in the linked audit
- Unverified/general-knowledge flags: pi subscription-login provider list (search-synthesis), ACP Python SDK regeneration cadence and agent-side coverage (README-claimed)

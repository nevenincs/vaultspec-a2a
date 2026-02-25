---
name: "Agents Domain - Distilled"
date: 2026-25-02
type: distilled
summary: "Consolidated provider analysis for Claude, Gemini, Codex, and GLM-5 covering authentication, protocol support, and integration requirements. Refuted hypotheses removed. Contradictions and gaps explicitly identified."
maturity: 45
sources:
  - docs/agents/2026-25-02-claude-agent-support.md
  - docs/agents/2026-25-02-gemini-agent-support.md
  - docs/agents/2026-25-02-codex-agent-support.md
  - docs/agents/2026-25-02-glm5-agent-support.md
---

# Agents Domain — Distilled

**Date**: 2026-02-25
**Status**: Distilled from Phase 1–4 research
**Scope**: Four target providers — Claude, Gemini, Codex, GLM-5

---

## Claude (Anthropic)

### Authentication

The orchestrator authenticates Claude Code CLI via token-based credentials:

- **`CLAUDE_CODE_OAUTH_TOKEN`**: Generated once via `claude setup-token` from a
  Pro/Team/Enterprise subscription. Enables headless execution drawing from the
  subscription's flat-rate quota (5-hour rolling limit).
- **`ANTHROPIC_API_KEY`**: Standard pay-as-you-go API key. Must be **unset** when
  using the OAuth token to avoid routing through the API billing path.
- **Cloud credentials**: AWS (Bedrock) or Google ADC (Vertex AI) for
  cloud-hosted model access.

**Canonical path**: Set `CLAUDE_CODE_OAUTH_TOKEN`, unset `ANTHROPIC_API_KEY`.

### ACP Support

Claude Code CLI does not natively expose an ACP server. Integration requires the
**`claude-code-acp`** adapter package (community/official bridge). This wrapper
handles JSON-RPC communication and enables IDEs and orchestrators to run Claude
as a background agent with streaming and permission flows.

### A2A Support

Claude Code has first-class MCP support. A2A integration uses a **bridge
pattern**:

```
Claude Code (Client) → MCP → A2A Bridge Server → A2A Protocol → Target Agent
```

The A2A-MCP bridge server (e.g., `a2a-mcp`) is configured in
`.claude/settings.json`. It translates MCP tool calls into A2A network requests,
enabling Claude to discover and delegate to A2A-compliant agents.

### Integration Requirements

- Inject `CLAUDE_CODE_OAUTH_TOKEN` into the agent process environment.
- Spawn via the `claude-code-acp` wrapper (not the raw `claude` binary).
- Provide isolated workspaces (Git worktrees) via native tools or MCP filesystem
  server.
- For supervisor mode: inject A2A-MCP bridge into Claude's MCP configuration.

### Pricing

OAuth token enables flat-rate subscription bypass (Pro $20/mo, Premium Seat
$150/mo); API key triggers per-token billing.

---

## Gemini (Google)

### Authentication

The orchestrator authenticates Gemini CLI via API key or cloud credentials:

- **`GEMINI_API_KEY`**: From Google AI Studio. Preferred for headless/automated
  environments.
- **Vertex AI ADC**: Via `gcloud` CLI, service account JSON
  (`GOOGLE_APPLICATION_CREDENTIALS`), or Google Cloud API keys.
- **Auto-auth**: Automatic when running inside Google Cloud Shell or Compute
  Engine.

**Canonical path**: Set `GEMINI_API_KEY` for non-GCP environments; use ADC for
GCP-native deployments.

### ACP Support

Gemini CLI has **native ACP support** (solidified in v0.28.0+). Capabilities
include persistent sessions, agent thought streaming, terminal process
management, and user permission flows. Gemini can act as either an ACP host or a
controlled agent within an ACP-compliant system.

### A2A Support

Gemini CLI has **native A2A support** (experimental). Remote agents are
discovered via Markdown files with YAML frontmatter specifying `agent_card_url`.
Enabled via `settings.json`:

```json
{ "experimental": { "enableAgents": true } }
```

Gemini exposes both local and remote sub-agents as tools to its main agent,
delegating tasks based on Agent Cards per the A2A standard.

### Integration Requirements

- Inject `GEMINI_API_KEY` or Vertex AI credentials.
- Launch in headless/ACP mode (not interactive TUI).
- Consider "YOLO mode" for autonomous operation or ACP permission mechanisms for
  human-in-the-loop.
- Gemini natively supports MCP servers for both consuming and exposing tools.

### Pricing

OAuth login inherits subscription limits (AI Pro ~$20/mo, AI Ultra ~$250/mo);
API key billed separately with free tier available. Subscriptions include
$10–$100/mo in Cloud credits.

---

## Codex (OpenAI)

### Authentication

The orchestrator authenticates the Codex CLI (Rust binary) via session token or
API key:

- **Cached session token**: Generated via initial browser sign-in with a ChatGPT
  subscription (Plus/Pro/Enterprise). Enables flat-rate billing.
- **`OPENAI_API_KEY`**: Standard pay-as-you-go API key for headless environments.

**Canonical path**: Browser sign-in once to generate cached session token; inject
into orchestrator environment for subsequent headless use.

### ACP Support

Codex CLI has **no native ACP support**. Integration requires a custom ACP
wrapper that translates ACP JSON-RPC requests into Codex CLI commands or terminal
streams. No established community package exists at time of research.

### A2A Support

Codex CLI natively supports MCP. A2A integration follows the same **bridge
pattern** as Claude:

```
Codex CLI (Client) → MCP → A2A Bridge Server → A2A Protocol → Target Agent
```

Additionally, Codex has an experimental **multi-agent mode** for task
parallelization and a **local code review** feature using a separate agent
instance.

### Integration Requirements

- Store and inject cached session token for subscription billing.
- Write or source a custom ACP adapter (none exists off-the-shelf).
- Inject A2A-MCP bridge into Codex's MCP configuration.
- **CRITICAL — Windows Compatibility**: Codex CLI is optimized for macOS/Linux.
  Windows support is experimental; OpenAI recommends WSL. Given this project's
  constraint (Windows 11 PWSH, no WSL), the native Windows binary may encounter
  pathing, terminal emulation, or execution bugs. Thorough testing or resilient
  error-handling wrappers are required.

### Pricing

Session token enables flat-rate subscription bypass (Plus $20/mo, Pro $200/mo);
API key triggers per-token billing.

---

## GLM-5 (Zhipu AI)

### Authentication

GLM-5 integration uses **direct API calls only** — no CLI wrapper is needed or
recommended.

- **Coding Plan API Key**: The Zhipu "GLM Coding Plan" subscription issues an
  API key that natively draws from the subscription's monthly quota. This key
  must target the Coding Plan endpoint
  (`https://api.z.ai/api/coding/paas/v4`).
- **OpenAI-compatible REST**: Standard libraries (e.g., the `openai` Python
  package) work by pointing `base_url` to Zhipu's endpoint with the Coding Plan
  key.

**Canonical path**: Subscribe to Coding Plan, use the issued API key directly.
No OAuth bypass or CLI wrapping needed.

### ACP Support

**No native support.** Requires a custom ACP server. Given the OpenAI-compatible
API surface, an ACP wrapper built for OpenAI can be adapted by changing the base
URL and injecting the Coding Plan API key.

### A2A Support

Requires a **custom A2A server** (e.g., using `a2a-python`). The server defines
an `AgentCard`, uses the GLM-5 REST API for its `AgentExecutor`, and translates
A2A SSE streams and task state management into stateless API calls.

### Integration Requirements

- Provide the Zhipu Coding Plan `API_KEY` to the custom A2A server.
- Deploy a lightweight Python A2A server wrapping the GLM-5 API.
- Ensure tool-calling format compatibility between GLM-5 and A2A/MCP
  expectations (translation layer may be needed).
- Target the Coding Plan endpoint specifically (not the standard Open Platform
  endpoint) for correct billing.

### Pricing

Coding Plan subscription (Max ~$65–200/mo) issues an API key with built-in
quota; no CLI wrapping or OAuth bypass needed. Standard API is ~$1/1M input
tokens.

---

## Open Contradictions

These contradictions exist across the provider research and must be resolved
via Architecture Decision Records before implementation.

### C1: ACP Support Heterogeneity

The four providers present four different ACP integration stories:

| Provider | ACP Status |
|----------|-----------|
| Gemini | Native ACP (v0.28.0+) |
| Claude | Adapter required (`claude-code-acp` package) |
| Codex | Custom wrapper required (no package exists) |
| GLM-5 | Custom wrapper required (adaptable from OpenAI) |

**Unresolved**: Is this heterogeneity manageable via a unified adapter
abstraction, or does it warrant choosing a single ACP-native provider (Gemini) as
the reference implementation and adapting the others?

### C2: A2A Integration Uses Three Distinct Patterns

| Pattern | Providers |
|---------|-----------|
| MCP → A2A bridge | Claude, Codex |
| Native A2A (experimental) | Gemini |
| Custom A2A server | GLM-5 |

**Unresolved**: Should the architecture standardize on the MCP→A2A bridge
pattern (broadest compatibility) or build separate integration paths per
provider? The native Gemini A2A support is still experimental and may change.

### C3: Subscription Bypass Mechanisms Vary in Robustness

| Provider | Mechanism | Fragility |
|----------|-----------|-----------|
| Claude | `CLAUDE_CODE_OAUTH_TOKEN` env var | Medium — token generated via CLI command |
| Gemini | OAuth refresh token extraction | High — relies on cached browser token |
| Codex | Cached browser session token | High — generated via interactive login |
| GLM-5 | Native subscription API key | Low — officially issued, no bypass needed |

**Unresolved**: The Claude, Gemini, and Codex bypass mechanisms rely on
undocumented or semi-documented token extraction from consumer-facing auth flows.
What is the failure mode when these tokens expire or the providers change their
auth flow? GLM-5's approach is the only officially supported path.

---

## Knowledge Gaps

These gaps represent missing information that blocks confident
architecture decisions.

### G1: Windows Compatibility for Claude and Gemini CLIs [CRITICAL]

The Codex doc explicitly flags Windows+no-WSL as problematic. The Claude and
Gemini research documents are **silent on Windows compatibility**. Given this
project's hard constraint (Windows 11 PWSH, no WSL), the same risks may apply
to all CLI-based providers. **This gap blocks provider selection decisions.**

### G2: Token Lifecycle and Refresh Mechanisms

All four providers use some form of token/key authentication, but none of the
research documents address:

- Token expiry duration
- Automatic refresh behavior
- Failure modes when tokens expire mid-session
- Whether orchestrator needs to implement token refresh logic

### G3: Concrete Rate Limits Under Subscription Tiers

Only Claude mentions a specific limit ("5-hour rolling limit"). Gemini and Codex
use vague language ("massive limits", "generous quota"). GLM-5 mentions "~1,600
complex coding prompts every 5 hours" for Max Plan. **A head-to-head comparison
of effective throughput under subscription is needed to inform capacity planning.**

### G4: ACP Wrapper Availability for Codex

The Claude doc references an existing `claude-code-acp` package. The Codex doc
states an ACP wrapper "must be written or sourced." **It is unknown whether a
community Codex ACP wrapper exists or if one must be built from scratch.** This
directly impacts implementation effort estimates.

### G5: Tool-Calling Format Compatibility for GLM-5

The GLM-5 doc notes that tool-calling format compatibility with A2A/MCP
expectations must be ensured, but does not specify what the actual differences
are. **The translation layer requirements are undefined.** This gap blocks the
GLM-5 A2A server implementation.

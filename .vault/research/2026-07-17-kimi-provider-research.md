---
tags:
  - '#research'
  - '#kimi-provider'
date: '2026-07-17'
modified: '2026-07-17'
related:
  - "[[2026-07-17-tool-cores-adr]]"
  - "[[2026-07-15-multi-provider-execution-adr]]"
---

# `kimi-provider` research: `kimi moonshot provider lane grounding`

Can Kimi (Moonshot AI) join Claude, Codex, and Z.ai as a provider lane in the
research-to-ADR authoring graph, with full tool-cores conformance? This
research grounds the integration-shape decision. Evidence picture: Moonshot
exposes BOTH an OpenAI-compatible and an Anthropic-compatible API surface (the
latter the structural analogue of the Z.ai lane), and — decisively — the Kimi
Code CLI speaks the Agent Client Protocol natively (`kimi acp` stdio server)
with MCP support via a launch-time config file, satisfied host prerequisites
on this Windows machine, and a uv-tool provisioning lane. Five unknowns
(session-level MCP injection, tool allowlisting, non-interactive auth,
Claude-CLI-against-Moonshot fidelity, handshake `_meta` quirks) need a live
probe before the ADR fixes the shape.

## Findings

### API surfaces

OpenAI-compatible: `https://api.moonshot.ai/v1` (Chat Completions shape).
Anthropic-compatible: `POST https://api.moonshot.ai/anthropic/v1/messages`
(China variant `api.moonshot.cn/anthropic/...`), genuine Anthropic Messages
body incl. `tools`/`tool_choice`/`stream`, auth
`Authorization: Bearer <moonshot_api_key>` — the direct structural analogue of
the Z.ai endpoint our lane injects via `ANTHROPIC_BASE_URL`/
`ANTHROPIC_AUTH_TOKEN` (`src/vaultspec_a2a/providers/factory.py:69`, `:487`).
Quirk: the Anthropic-compat endpoint remaps
`real_temperature = request_temperature * 0.6`
(github.com/MoonshotAI/Kimi-K2 issue 129). Running the Claude Code CLI against
this endpoint is community-blog-attested (the same mechanism as Z.ai), not
vendor-attested — load-bearing precedent exists but is third-party.

### Kimi Code CLI — speaks ACP natively

PyPI `kimi-cli` 1.49.0 (2026-07-16), Python >=3.12 (host has 3.14.6 via
scoop), universal wheel. `kimi acp` starts an ACP agent server over stdio —
the same protocol family as our `AcpChatModel` transport. MCP servers are
declared via `--mcp-config-file <path>` (JSON, standard `mcpServers` root;
stdio `command`+`args` or HTTP `url`+`headers`) at process launch — the same
config-file family as our per-run Codex `CODEX_HOME` `config.toml`
generation. Windows is supported via PowerShell but requires Git for Windows
(bundled Git Bash is the CLI's shell; `KIMI_SHELL_PATH` overrides) — git
2.54.0 already present. Auth as DOCUMENTED is interactive-only: `/login`
(Kimi Code OAuth or Moonshot platform API key) persisted to
`~/.kimi/config.toml`; no `MOONSHOT_API_KEY`-style env auth documented — the
single biggest headless-orchestrator risk, possibly mitigated by a
`KIMI_HOME`-analogue persisted-session override (undocumented, unverified).
No tool-allowlist/approval-mode mechanism and no headless/non-interactive
flag found in any fetched doc.

### Integration shape decision space (for the ADR; not decided here)

- (a) Z.ai-style config variant: same `AcpChatModel` + adapter binary, env
  pointed at Moonshot's Anthropic-compat endpoint. Cheapest; inherits the
  ENTIRE tool-cores mechanism (isolated config home, composition, allowlist)
  unchanged. Runs Kimi's model through Claude Code's agent scaffolding, not
  Kimi's own agent. Fidelity community-attested only.
- (b1) Generic-ACP reuse: point our ACP transport at `kimi acp`. Kimi IS ACP,
  so this is the natural own-agent shape — BUT our ACP client carries
  Claude-CLI-specific `_meta` extensions
  (`clientCapabilities._meta.terminal-auth` handshake,
  `session/new _meta.claudeCode.options.allowedTools` —
  `src/vaultspec_a2a/providers/_acp_session.py:48`, `:138`) that are not
  portable and need per-backend conditioning; Kimi's own allowlist story is
  unknown; MCP delivery would ride `--mcp-config-file` (per-run generated,
  Codex-precedent) unless session-level `mcpServers` proves honored.
- (b2) From-scratch class (codex_chat_model precedent): unjustified — Kimi is
  genuinely ACP, so (b2) reinvents (b1) with more code; only if (b1)'s
  `_meta` portability fails live.
- (c) Hosted OpenAI-compatible BaseChatModel (`Provider.ZHIPU` precedent,
  `factory.py:576`): structurally cannot satisfy the tool-cores mandate (no
  MCP surface); enumerated for completeness only.

### Provisioning (host inventory verified read-only)

Present: scoop git 2.54.0 + python 3.14.6; uv tools vaultspec-rag 0.3.0 +
vaultspec-core 0.1.43; global npm `@zed-industries/claude-agent-acp@0.19.2`
(stale global copy, project-local pin is the migrated
`@agentclientprotocol/claude-agent-acp@0.59.0`), `@openai/codex@0.144.5`,
`@google/gemini-cli@0.46.0`. Absent: kimi-cli (pip/uv/scoop/npm all clean; no
scoop bucket found). Natural provisioning lane: `uv tool install
kimi-cli==<pin>` mirroring the vaultspec-rag/core pattern — a NEW Python
provisioning axis, not an extension of the Node `package.json` pin. Billing/
rate limits: unresearched this pass; the Z.ai lesson (credential-gated lanes
skip loudly — `vaultspec-adr-research.toml:152` profile comment) is the
pattern to replicate.

### Codebase seams

`Provider` enum `src/vaultspec_a2a/graph/enums.py:128` (naming precedent: the
`ZAI`/`ZHIPU` product-vs-parent split suggests `KIMI` for CLI shapes and/or
`MOONSHOT` for hosted); capability map `enums.py:141`; `team_config.py`
provider resolution; `factory.py` branch (Z.ai precedent `:487`, ZHIPU
precedent `:576`); env vars via Pydantic-Settings aliases
(`src/vaultspec_a2a/control/config.py:166` — `zai_*`, `zhipu_api_key`,
`codex_home` precedents; a contingent `kimi_home` if an upstream override
exists); preset profile overlay (`[team.profiles.zai]`,
`vaultspec-adr-research.toml:152`); `probe_provider_readiness`
(`providers/model_profiles.py:379` ZHIPU branch precedent). Tool-cores
contract for ANY new lane (per `2026-07-17-tool-cores-adr`): one-registry
composition, per-run isolated config home, an allowlist/approval answer, and
a live floor + semantic proof with server-side corroboration before the lane
is declared conformant.

### Dedup

Zero repository/vault/knowledge mentions of Kimi or Moonshot — genuinely new
ground; the only prior art is the ZAI/ZHIPU dual-shape precedent and the
tool-cores contract.

### Live probe results (kimi-cli 1.49.0 installed via uv tool, 2026-07-17)

A local install-and-interrogate probe (installed-source reads + a live keyless
ACP handshake) resolved four of the five unknowns:

- **Session-level `mcpServers`: HONORED.** `acp/mcp.py:13`
  (`acp_mcp_servers_to_mcp_config`) converts ACP `session/new` `mcpServers`
  (stdio command/args/env; HTTP url/headers) into Kimi's internal MCP config.
  Live-confirmed: `session/new` with inline `mcpServers` was accepted at the
  param level and advanced to the auth check (`-32000 Authentication
  required` on a dummy key — an auth gate, not a schema rejection). This is
  the decisive contrast with the Claude lane's registration-scope surfacing
  gate: Kimi needs NO isolated-config-home workaround for MCP delivery.
  Full connect-and-surface confirmation still needs a real key.
- **Allowlist/approval: no pre-declared per-tool allowlist** (no
  `allowedTools`/`enabled_tools` analogue). Read-only discipline rides (a)
  the standard ACP `session/request_permission` RPC (`acp/session.py:470`)
  with approve / approve_for_session / reject — client-side gating our
  `AcpChatModel` already implements — and (b) blanket `--yolo`/`default_yolo`
  (`config.py:68`) for headless auto-approval, combined with composing ONLY
  read-only servers.
- **Non-interactive auth EXISTS** (contra the doc-inferred risk):
  `KIMI_API_KEY` (`app.py:722`), `KIMI_BASE_URL` (`:714`, retargets to
  Moonshot endpoints), `KIMI_MODEL_NAME` (`:738`); `MOONSHOT_API_KEY` is NOT
  read. Config-direct auth: `LLMProvider.api_key: SecretStr` in config
  (`config.py:40`), and `resolve_api_key` falls back to the static key
  (`auth/oauth.py:848`). Per-run isolation: no `KIMI_HOME`, but `--config
  <inline TOML/JSON>` loads a complete per-run config with NO file
  (`config.py:63`) and `--config-file <path>` overrides the default
  `~/.kimi/config.toml` — cleaner isolation than the CODEX_HOME redirect.
- **Handshake:** `protocolVersion: 1`; agentInfo Kimi Code CLI 1.49.0;
  `agentCapabilities` incl. `loadSession`, `mcpCapabilities {http: true,
  sse: false}`; `authMethods[0]._meta.terminal-auth` — the SAME `_meta`
  family as the claude-agent-acp >=0.20.2 terminal-auth case our client
  already handles (`_acp_session.py:48`). The auth gate fires at
  `session/new`, not `initialize`, so the handshake is drivable keyless.
- CLI surface: subcommands login/logout/term/acp/info/export/mcp/plugin/vis/
  web; `kimi acp` takes global flags only. Git Bash auto-found;
  `KIMI_SHELL_PATH` honored. Install footprint: uv tool venv +
  `~/.local/bin/kimi`.

### Remaining open unknown

4. Claude-CLI fidelity against Moonshot's Anthropic-compat endpoint (shape
   a) — needs a Moonshot API key; only relevant if the ADR keeps shape (a)
   as anything more than a rejected alternative. Likewise Kimi's full
   MCP connect-and-surface behavior post-auth is key-gated.

## Sources

- https://platform.kimi.ai/docs/api/overview
- https://moonshotai.github.io/kimi-cli/en/configuration/providers.html
- https://github.com/MoonshotAI/kimi-cli
- https://github.com/MoonshotAI/kimi-code
- https://pypi.org/project/kimi-cli/
- https://github.com/MoonshotAI/Kimi-K2/issues/129
- https://docs.litellm.ai/docs/providers/moonshot
- `src/vaultspec_a2a/graph/enums.py:128`
- `src/vaultspec_a2a/control/config.py:166`
- `src/vaultspec_a2a/providers/factory.py:69`
- `src/vaultspec_a2a/providers/factory.py:487`
- `src/vaultspec_a2a/providers/factory.py:576`
- `src/vaultspec_a2a/providers/_acp_session.py:48`
- `src/vaultspec_a2a/providers/_acp_session.py:138`
- `src/vaultspec_a2a/providers/model_profiles.py:379`
- `src/vaultspec_a2a/team/presets/teams/vaultspec-adr-research.toml:152`

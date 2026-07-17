---
tags:
  - '#research'
  - '#tool-cores'
date: '2026-07-17'
modified: '2026-07-17'
related:
  - "[[2026-07-15-graph-agent-framework-harness-plan]]"
  - "[[2026-07-15-agent-harness-provisioning-adr]]"
  - "[[2026-07-14-a2a-edge-conformance-adr]]"
---

# `tool-cores` research: `read-only grounding tools for graph agents`

Can every graph-executed document agent (researcher, synthesist, adr-author,
doc-reviewer — across the Claude, Codex, and Z.ai provider lanes) be given
executable, read-only grounding tools mid-turn: vaultspec-rag semantic search,
vaultspec-core vault reads (ADRs, WAC, references), and file discovery? This
research establishes the current seam, the surfacing constraint, the permission
mechanics, the persona drift, and what already exists versus what is new work,
so the tool-cores ADR can decide the delivery mechanism. The evidence picture:
the composition machinery exists and is protocol-layer proven, but a
registration-scope surfacing gate on the pinned Claude CLI keeps
session-injected tools invisible to the model, and three concrete gaps (no
vaultspec-core MCP entry, no preset opt-in, no allowlist wiring for composed
servers) are unowned by any plan row.

## Findings

### Surfacing gate: registration scope, not transport

The differentiator for whether an injected MCP server's tools surface to the
spawned Claude CLI's model is user-global registration scope — not transport,
not session-versus-config, and not tool search. A full live registration
matrix (session-injected x workspace-config, HTTP x stdio) connected, spawned,
and served tools in every cell, yet none surfaced; only user-global home-config
servers were shown to the model. Evidence:
`.vault/exec/2026-07-14-a2a-edge-conformance/2026-07-14-a2a-edge-conformance-W03-P08-S20.md:31`
(pinned Claude CLI `2.1.210`, adapter `claude-agent-acp@0.23.1`), reconfirmed
for the stdio-shaped vaultspec-rag harness server at
`.vault/exec/2026-07-15-graph-agent-framework-harness/2026-07-15-graph-agent-framework-harness-P04-S15.md:75`
(commit `357d87a`), and unchanged at the 2026-07-16 re-arm check
(`.vault/exec/2026-07-14-a2a-edge-conformance/2026-07-14-a2a-edge-conformance-W05-P14-S31.md:26`).
Upstream trackers: claude-code issues 40314 and 57033.

**Stale-code contradiction to repair:** `src/vaultspec_a2a/graph/nodes/worker.py:135`
and `src/vaultspec_a2a/providers/_acp_authoring.py:104` still assert the
falsified transport-based hypothesis ("stdio surfaces reliably; loopback HTTP
does not") from the 2026-07-14 R4 amendment. The vault record supersedes these
docstrings.

**Inverse risk (central tension):** a user-global WRITABLE vaultspec MCP server
did surface in a live run and let an agent scaffold directly into `.vault/`,
bypassing the ACP fs-deny policy — which is why
`2026-07-15-agent-harness-provisioning-adr` requires the spawned agent's MCP
surface be exactly the injected/declared set with user-global/inherited MCP
suppressed. Session-injected tools are invisible today; user-global tools are
visible but policy-forbidden as a class because a writable one leaked once.
The ADR must resolve this tension for strictly read-only servers.

### Existing composition seam (extend, do not fork)

`src/vaultspec_a2a/providers/_acp_mcp.py` (landed `357d87a`) already implements
the mechanism:

- `_KNOWN_MCP_SERVERS` (`_acp_mcp.py:30`): closed registry with ONE entry —
  `"vaultspec-rag"` -> `uvx --from vaultspec-rag vaultspec-search-mcp` (stdio;
  `uvx` chosen because the ACP subprocess has no uv project cwd). No
  vaultspec-core entry exists anywhere; adding one is new work, including the
  question of whether a vaultspec-core stdio MCP entrypoint exists to launch.
- `resolve_harness_mcp_servers` (`_acp_mcp.py:39`) fails loudly on unknown
  names; `compose_harness_mcp_servers` (`_acp_mcp.py:62`) is ADD-only union by
  server name, coexisting with the authoring binding.
- Invoked at `src/vaultspec_a2a/graph/nodes/worker.py:495` (after
  `_attach_authoring_tools`) and in `graph/compiler.py` for the researcher
  producer.
- **Dead in production:** `TeamConfig.effective_harness()`
  (`src/vaultspec_a2a/team/team_config.py:574`) defaults to no extra MCP
  servers, and zero team presets declare `mcp_servers` in `[team.harness]` —
  including the live `vaultspec-adr-research.toml`. The wiring is
  protocol-layer proven but never opted into.

### Permission/allowlist mechanics and an unlogged gap

Autonomous-mode permissioning is an exact-name allowlist
(`mcp__<server>__<tool>`), never a wildcard:
`authoring_allowed_tool_names` (`src/vaultspec_a2a/providers/_acp_authoring.py:188`),
applied in `worker.py:160`, via `claudeCode.options.allowedTools` at
`_acp_session.py:145`. **Gap (nowhere flagged in the vault before this
research):** `compose_harness_mcp_servers` calls `attach(combined)` with
`allowed_tools=None` (`acp_chat_model.py:213` semantics preserve the prior
allowlist unchanged), so harness-composed servers' tool names (e.g.
`mcp__vaultspec-rag__search`) are never added to the autonomous allowlist.
Whether the CLI's "read tools pass as auto-permitted" behavior generalizes to
arbitrary read-only MCP tools is unverified. Allowlist mechanics are
Claude-Code-specific; no Codex app-server or Z.ai-specific allowlist code was
found (bounded search), so per-provider surfacing/permissioning for Codex is
an open verification item.

### Capability flags and read-only file access

`AgentCapabilitiesConfig` (`team_config.py:190`) gates only the ACP
server-initiated fs/terminal RPCs via `_CAPABILITY_REQUIREMENTS`
(`src/vaultspec_a2a/providers/_acp_protocol.py:29`); the spawned CLI's native
Read/Grep/Glob tools execute agent-side and are NOT gated by these flags.
Whether the pinned CLI issues `fs/read_text_file` RPCs at all when native
tools are available is unproven either way — needs live verification before
the ADR asserts it. All four document personas declare
`filesystem_read=true, filesystem_write=false, terminal=false`
(`vaultspec-researcher.toml:67`, `vaultspec-synthesist.toml:97`,
`vaultspec-adr-author.toml:114`, `vaultspec-doc-reviewer.toml:107`). The
`.vault/**` deny policy is explicitly write-only
(`2026-07-15-agent-harness-provisioning-adr` line 49, "deny at the surface AND
at the sink"); no read-side `.vault` deny exists — read grounding over the
vault is policy-clean today.

### Persona prompt-capability drift

Only `vaultspec-researcher.toml:31-34` instructs CLI invocations
(`vaultspec-core status`, `vaultspec-rag search ... --type vault --doc-type adr`,
`... --type code`) that `terminal=false` cannot execute. This is already owned
by plan row P03.S05 of `2026-07-15-graph-agent-framework-harness-plan`
(open, blocked solely on the upstream surfacing gate; the re-expression must
instruct only tools the model can actually see). Synthesist, adr-author, and
doc-reviewer carry no non-executable instructions (P03.S06/S07/S08 all
checked).

### Dedup sweep — extend versus new

- Extension point: `_acp_mcp.py`'s registry/composition (`357d87a`) is generic
  over server name; a vaultspec-core entry belongs there. Any NEW composition
  mechanism would duplicate the agent-harness-provisioning ADR's Opens item
  ("per-role MCP composition — vaultspec-rag for researchers") and
  P03.S05/P04.S15, which own this goal at the protocol layer.
- Genuinely uncovered gaps: (a) no vaultspec-core MCP registry entry; (b) no
  preset opts into `[team.harness] mcp_servers` (production-dead wiring);
  (c) composed-server tool names absent from the autonomous allowlist;
  (d) P03.S05 blocked on the unmoved upstream gate (`2.1.210`/`0.23.1`).
- Adjacent, already shipped, NOT prior art closing this gap: the engine-owned
  authoring catalog already carries read tools (`read_context`,
  `src/vaultspec_a2a/authoring/catalog.py:178`) with a `risk_tier` field
  admitting `read_only` (`catalog.py:57`). Engine catalog tools are a
  different, engine-owned surface from the rag/core grounding servers.

### Cross-repo edge

No dashboard/engine change appears required: the harness ADR's own framing
(`2026-07-15-agent-harness-provisioning-adr` line 39) anticipates grounding
tools as "further servers by declaration" via the ACP `mcpServers` mechanism,
alongside — not inside — the engine-owned authoring bridge/catalog. This is
argued from the ADR text; the out-of-tree engine repository was not searched.

### Upstream re-arm probe: the pin is deprecated, the gate likely fixed upstream

The adapter pin `@zed-industries/claude-agent-acp@0.23.1` (`package.json:7`) is
DEPRECATED — the package was renamed to `@agentclientprotocol/claude-agent-acp`
(latest `0.59.0`, 36 releases past the frozen pin); all upstream fixes land
under the new name this repo does not depend on. The adapter exact-pins
`@anthropic-ai/claude-agent-sdk@0.2.83` (`package-lock.json:23`), ~129 releases
behind latest (`0.3.212`). The SDK changelog between the pin and latest
carries entries directly on the S20 axis: `0.3.166` "Fixed MCP resource tools
not being injected for servers added at runtime via the mcp_set_servers
control request", `0.2.113` (background MCP connection timing), `0.2.69`
(session-injected vs project/user-level scope distinction). The S20 result has
not moved because the pin cannot move, not because upstream has not.
Provenance note: no standalone claude-code CLI exists in the tree
(`src/vaultspec_a2a/providers/factory.py:206` spawns only the adapter's node
entry); the vault's "CLI 2.1.210" figures do not map to the locked packages
(the vendored SDK self-reports `2.1.83`) — treat 2.1.210 citations as
ambient-package provenance, not this repo's pin. A meaningful re-probe of the
S20 matrix requires migrating to `@agentclientprotocol/claude-agent-acp@0.59.0`
first; re-probing the current pin reproduces the known-stale result.

### Per-provider mechanism matrix (Codex, Z.ai)

Codex has zero MCP wiring today: `CodexChatModel`
(`src/vaultspec_a2a/providers/codex_chat_model.py:222`) is a from-scratch
BaseChatModel speaking codex app-server JSON-RPC, with no `with_mcp_servers`
and no MCP field in `initialize`/`thread/start`/`turn/start` params
(`codex_chat_model.py:340-375`); both `_attach_authoring_tools`
(`worker.py:151`) and `compose_harness_mcp_servers` (`_acp_mcp.py:81`)
feature-detect `with_mcp_servers` and silently no-op for Codex, so Codex
agents get neither the authoring bridge nor grounding tools via the current
mechanism. Codex app-server supports MCP servers through `config.toml` (or
repeated `-c mcp_servers.<name>.command=...` launch flags, plus a
`config/mcpServer/reload` RPC) — a config-file shape, not a session parameter,
so a Codex-lane composition is new work; the per-run `CODEX_HOME` already
threaded at `codex_chat_model.py:304` is the architecturally clean seam for a
per-run `config.toml`. Codex headless permissioning is blanket
(`approval_policy: "never"`, `sandbox: "read-only"`,
`codex_chat_model.py:354`) — the read-only sandbox aligns with the read-only
mandate; whether a per-tool allowlist analogue exists is an open verification
item, not asserted absent. Sources:
https://github.com/openai/codex/blob/main/codex-rs/app-server/README.md,
https://developers.openai.com/codex/mcp.

Z.ai is the Claude ACP path by construction: same `AcpChatModel`, same spawned
command; only env differs (`_build_zai_env`, `factory.py:69`, injecting
`ANTHROPIC_BASE_URL`/`ANTHROPIC_AUTH_TOKEN`; comment `factory.py:488`).
Identical surfacing behavior and pin; it re-arms exactly when Claude does.

### Not investigated

The untracked `.qdrant-initialized`, `scratchpad/`, and
`vaultspec-adr-research-mock.toml`; live verification of native-tool fs
behavior; the engine repository itself; a dedicated source check for a
Codex per-tool allowlist mechanism; live compatibility of our ACP layer
against `@agentclientprotocol/claude-agent-acp@0.59.0` (36-release jump —
session/new shape, permission modes, mcp_servers key, capability flags all
need regression verification before any migration lands).

## Sources

- `src/vaultspec_a2a/providers/_acp_mcp.py:30`
- `src/vaultspec_a2a/providers/_acp_authoring.py:104`
- `src/vaultspec_a2a/providers/_acp_authoring.py:188`
- `src/vaultspec_a2a/providers/acp_chat_model.py:213`
- `src/vaultspec_a2a/providers/_acp_protocol.py:29`
- `src/vaultspec_a2a/graph/nodes/worker.py:135`
- `src/vaultspec_a2a/graph/nodes/worker.py:495`
- `src/vaultspec_a2a/team/team_config.py:190`
- `src/vaultspec_a2a/team/team_config.py:574`
- `src/vaultspec_a2a/authoring/catalog.py:57`
- `src/vaultspec_a2a/authoring/catalog.py:178`
- `src/vaultspec_a2a/team/presets/agents/vaultspec-researcher.toml:31`
- `.vault/exec/2026-07-14-a2a-edge-conformance/2026-07-14-a2a-edge-conformance-W03-P08-S20.md:31`
- `.vault/exec/2026-07-15-graph-agent-framework-harness/2026-07-15-graph-agent-framework-harness-P04-S15.md:75`
- `.vault/exec/2026-07-14-a2a-edge-conformance/2026-07-14-a2a-edge-conformance-W05-P14-S31.md:26`
- `package.json:7`
- `package-lock.json:23`
- `src/vaultspec_a2a/providers/factory.py:69`
- `src/vaultspec_a2a/providers/factory.py:206`
- `src/vaultspec_a2a/providers/factory.py:488`
- `src/vaultspec_a2a/providers/codex_chat_model.py:222`
- `src/vaultspec_a2a/providers/codex_chat_model.py:304`
- `src/vaultspec_a2a/providers/codex_chat_model.py:340`
- `src/vaultspec_a2a/providers/codex_chat_model.py:354`
- `src/vaultspec_a2a/graph/nodes/worker.py:151`
- commit `357d87a`
- https://github.com/anthropics/claude-code/issues/40314
- https://github.com/anthropics/claude-code/issues/57033
- https://github.com/anthropics/claude-agent-sdk-typescript/blob/main/CHANGELOG.md
- https://github.com/openai/codex/blob/main/codex-rs/app-server/README.md
- https://developers.openai.com/codex/mcp

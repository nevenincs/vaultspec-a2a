---
tags:
  - '#adr'
  - '#tool-cores'
date: '2026-07-17'
modified: '2026-07-17'
related:
  - "[[2026-07-17-tool-cores-research]]"
  - "[[2026-07-15-agent-harness-provisioning-adr]]"
  - "[[2026-07-14-a2a-edge-conformance-adr]]"
  - "[[2026-07-15-graph-agent-framework-harness-adr]]"
  - "[[2026-07-15-graph-agent-framework-harness-plan]]"
---
# `tool-cores` adr: `read-only grounding tools for graph document agents` | (**status:** `accepted`)

## Problem Statement

Graph-executed document agents (researcher, synthesist, adr-author, doc-reviewer,
across the Claude, Codex, and Z.ai lanes) author on prompt context alone. They cannot,
mid-turn, semantically search the codebase, semantically recall the vault's governing
ADRs and references, or deterministically read a named `.vault` document: the grounding
the harness contract promises. `2026-07-17-tool-cores-research` establishes that the
composition machinery to inject grounding servers already exists and is protocol-proven,
but the servers stay invisible to the model on the pinned Claude stack, and three wiring
gaps (no preset opt-in, no allowlist entry for composed servers, personas naming tools the
runtime cannot run) leave the wiring production-dead. A decision is needed on the delivery
mechanism for strictly read-only grounding across all three provider lanes, on the current
stack rather than only after an upstream fix: the owner directive is sequence, not defer.

## Considerations

- The observed surfacing gate (session-injected and workspace-config MCP servers connect and
  serve but never surface to the model; only user-global home config surfaces) is grounded in
  the S20 registration-scope matrix (`2026-07-14-a2a-edge-conformance-W03-P08-S20`, all cells
  stdio and HTTP) and `2026-07-17-tool-cores-research`.
- The gate is very likely an artifact of a stale, DEPRECATED adapter. Our pin
  `@zed-industries/claude-agent-acp@0.23.1` (`package.json:7`) is deprecated and renamed to
  `@agentclientprotocol/claude-agent-acp` (now 0.59.0, 36 releases ahead); its vendored SDK
  `@anthropic-ai/claude-agent-sdk@0.2.83` is ~129 releases behind 0.3.212. SDK changelog 0.3.166
  ("Fixed MCP resource tools not being injected for servers added at runtime via the
  mcp_set_servers control request") and 0.2.69 (session vs project/user scope fix) target the
  exact registration-scope axis S20 found dispositive (changelog
  https://github.com/anthropics/claude-agent-sdk-typescript/blob/main/CHANGELOG.md). All upstream
  fixes land under the new package name we do not depend on.
- Version provenance is ambiguous: there is no standalone claude-code CLI in-tree; `factory.py:206-246`
  spawns only the adapter's node entry, and the vendored SDK self-reports 2.1.83 while the vault
  records "CLI 2.1.210". The pinned-version figures do not map cleanly to the locked packages;
  "2.1.210" is not our literal pin and should not be treated as one.
- The stdio authoring bridge is NOT a surfacing counterexample: the same S20 record shows its
  seven catalog tools served under both session-injected and workspace-config channels yet none
  surfaced. The "stdio surfaces reliably" claim in `src/vaultspec_a2a/graph/nodes/worker.py:135`
  and `src/vaultspec_a2a/providers/_acp_authoring.py:104,113` is falsified by its own record.
- The suppression invariant forbidding inherited user-global MCP was a response to a WRITE leak:
  a user-global writable vaultspec MCP once scaffolded directly into `.vault/`, bypassing the
  fs-deny (`2026-07-15-agent-harness-provisioning-adr`). The `.vault` deny is write-only; read
  grounding over the vault is policy-clean. That suppression is declared but UNBUILT today (no
  strict-mcp-config or config-home isolation in `src/vaultspec_a2a/providers/`, S15 note at
  `2026-07-15-graph-agent-framework-harness-P04-S15`), and its need is INDEPENDENT of the surfacing
  gate: the write-leak vector exists whether or not read-only servers surface, so the isolation
  must be built regardless of the re-probe outcome.
- The spawned CLI's built-in Read/Grep/Glob execute agent-side over the workspace fs, always
  surface (no MCP, no gate), and `.vault` reads are permitted; all four personas already declare
  `filesystem_read=true` (`2026-07-17-tool-cores-research`).
- vaultspec-rag (`vaultspec-search-mcp`) is read-only by construction and already searches both
  code and vault; it is the sole `_KNOWN_MCP_SERVERS` entry (`src/vaultspec_a2a/providers/_acp_mcp.py:30`).
  A vaultspec-core MCP server also exists (`vaultspec-mcp`) but exposes all nine verbs including
  create/edit/plan with no read-only launch mode (`vaultspec-mcp --help`).
- Claude autonomous permissioning is a flat exact-name allowlist (`mcp__<server>__<tool>`);
  `compose_harness_mcp_servers` calls `attach(combined)` with no allowlist, so composed tool
  names are never auto-permitted (`src/vaultspec_a2a/providers/_acp_mcp.py:81-87`).
- Codex has ZERO MCP wiring today: `CodexChatModel` is a from-scratch app-server JSON-RPC model
  with no `with_mcp_servers` and no `mcpServers` in its initialize/thread/turn params
  (`src/vaultspec_a2a/providers/codex_chat_model.py:340-375`), so both `_attach_authoring_tools`
  (`worker.py:151-153`) and `compose_harness_mcp_servers` (`_acp_mcp.py:81-83`) feature-detect
  `with_mcp_servers` and silently no-op for Codex. Codex takes MCP via per-run `CODEX_HOME`
  config.toml (already threaded, `codex_chat_model.py:304`) or `-c mcp_servers.<name>.*` flags, with
  `[mcp_servers.<name>]` supporting `enabled_tools` (allow), `disabled_tools` (deny-after), and
  `default_tools_approval_mode` / per-tool `approval_mode` (auto|prompt|writes|approve) - more
  expressive than Claude's flat allowlist (config-reference
  https://learn.chatgpt.com/docs/config-file/config-reference). Codex headless runs are
  `approval_policy:"never"` + `sandbox:"read-only"` (`codex_chat_model.py:354`).
- Z.ai is identical to Claude by construction: same `AcpChatModel`, same adapter, only env differs
  (`factory.py:69-87`); same gate, re-arms exactly when Claude does. No separate mechanism.

## Considered options

- **Keep the deprecated adapter and session-injection, wait for a fix (pure defer).** Rejected:
  the fix lands only under the renamed package we do not depend on; delivers zero grounding and
  violates sequence-not-defer.
- **Migrate the adapter to `@agentclientprotocol/claude-agent-acp@0.59.0`, then re-run the S20
  matrix (chosen primary).** The rename is mandatory to receive ANY upstream fix, and the SDK
  changelog names the exact surfacing fix. If session-injected MCP now surfaces, the existing
  `_acp_mcp.py` composition is fully viable with NO user-global surfacing carve-out and NO
  harness-ADR amendment: the cleanest outcome. Cost: a 36-release compatibility jump to
  regression-verify.
- **Worker-owned isolated CLI config home (chosen for suppression always; for surfacing only as
  contingency).** The isolated home is built regardless to deliver the harness ADR's unbuilt
  ambient-MCP suppression. If the re-probe shows session-injected servers surface, that is all it
  does - a small isolation step. If the re-probe still fails, the SAME home additionally carries the
  declared read-only servers so they surface as user-global config. Populating with only read-only
  servers keeps the write leak closed either way.
- **Compose the full write-capable vaultspec-core MCP, constrained only by the allowlist.**
  Rejected: write verbs remain in the surfaced set (handed to the model, merely not
  auto-permitted), violating the harness ADR's deny-at-the-surface rule; no read-only launch mode
  exists to trim it.
- **Bridge read tools through the engine authoring catalog.** Rejected: the catalog is
  engine-owned (R4, `2026-07-14-a2a-edge-conformance-adr`) and its bridge tools do not surface
  today either (same S20 gate); it forks ownership for no live gain.

Native Read/Grep/Glob deterministic grounding is composed with whichever semantic-tier option
wins; it is not an alternative to them but the floor that ships regardless.

## Constraints

- Deprecated pin, mandatory migration: `@zed-industries/claude-agent-acp@0.23.1` (`package.json:7`)
  is deprecated/renamed; the migration to `@agentclientprotocol/claude-agent-acp@0.59.0` is a
  prerequisite for every semantic-tier outcome and is itself a 36-release jump with likely
  breaking changes. The plan must regression-verify the ACP surface our layer targets: `session/new`
  shape, permission modes / `allowedTools`, the `mcpServers` config key, capability flags, and the
  server-initiated fs-RPC behavior (fs/read_text_file and the write-deny chokepoint).
- Frontier/upstream risk: whether the migrated adapter actually surfaces session-injected servers
  is UNPROVEN until re-probed; this is the plan's primary live-verify item and the decision point
  for whether the isolated home must also carry the surfacing role. If the contingency triggers,
  whether a redirected, populated config home surfaces its servers is a second unproven inference
  (S20 proved only that the operator's REAL user-global servers surface).
- Read-only is a hard boundary across both transports: no write verb is ever composed. A
  vaultspec-core read MCP requires an upstream read-only launch mode; an a2a-side wrapper is
  forbidden (workspace-over-bundled, dedup). rag + native tools cover recall without it.
- Codex undocumented-axis risk: `sandbox_mode` is documented as an exec-path jail; its interaction
  with MCP tool invocation is inferred, not documented. The plan's Codex live proof must verify MCP
  tool calls actually surface and invoke under `approval_policy:"never"` + `sandbox:"read-only"` +
  per-tool `approval_mode` composition (config-reference
  https://learn.chatgpt.com/docs/config-file/config-reference).
- One registry, single source of truth: `_KNOWN_MCP_SERVERS` (`_acp_mcp.py`) is the sole server
  catalog; the two delivery shapes (ACP session params for Claude/Z.ai, `CODEX_HOME` config.toml for
  Codex) both consume it. A second catalog is forbidden (dedup mandate).
- Parent-feature stability: the ambient-MCP suppression this ADR builds is the harness-provisioning
  invariant, declared but unbuilt; this ADR builds it, and does not assume it.

## Implementation

Grounding is delivered on three legs over one server registry, with native deterministic tools as
the always-on floor.

**Floor - deterministic grounding, live today, no MCP, no gate.** `.vault` reads, file discovery,
and code grep are served by the spawned CLI's native Read/Grep/Glob (Claude/Z.ai) and by Codex's
read-only sandbox file access, all agent-side over the workspace fs. The only work is permission
(permit the read built-ins in autonomous mode; the `.vault` deny is write-only) and persona
reconciliation. This ships on every lane independent of the surfacing gate.

**Leg 1 - Claude + Z.ai semantic grounding.** Sequenced FIRST and actionable now: migrate the
adapter dependency to `@agentclientprotocol/claude-agent-acp@0.59.0`, regression-verify the ACP
surface, then re-run the S20 registration-scope matrix. Two things follow from the outcome. The
ambient-MCP suppression (a worker-owned isolated CLI config home that excludes the operator's
writable user-global servers) is built EITHER WAY - it is the harness ADR's unbuilt invariant and
the write-leak vector is independent of surfacing. If the re-probe shows session-injected MCP
surfaces, that isolation is a small standalone step and the existing `_acp_mcp.py` composition
delivers vaultspec-rag with the allowlist gap closed (`compose_harness_mcp_servers` joins
`mcp__vaultspec-rag__*` into the autonomous `allowedTools`, parallel to
`authoring_allowed_tool_names`) - no surfacing carve-out, no harness amendment. If it still fails,
the SAME isolated home additionally carries the declared read-only servers so they surface as
user-global config, and the harness invariant is amended to name that dual role. Z.ai inherits this
unchanged (same `AcpChatModel`, env-only difference at `factory.py:69-87`).

**Leg 2 - Codex semantic grounding (new delivery shape, same registry).** Codex gains MCP via a
per-run `CODEX_HOME` config.toml (already threaded at `codex_chat_model.py:304`) whose
`[mcp_servers.<name>]` entries are built from the SAME `_KNOWN_MCP_SERVERS` catalog. This is the
same structural mechanism as Claude's per-run isolated config home - a per-run, worker-owned config
directory carrying exactly the declared servers - expressed in each provider's native config shape;
the registry is shared, the serialization differs. Read-only discipline uses Codex's more expressive
axis: `enabled_tools` names only the read verbs, `approval_mode` auto for reads; the existing
`sandbox:"read-only"` is defense-in-depth. The plan must live-prove MCP tool invocation surfaces and
works under `approval_policy:"never"` + `sandbox:"read-only"` + per-tool `approval_mode` before
asserting parity. No `with_mcp_servers` no-op path is added; Codex composition is its own config.toml
seam, not the ACP one.

**Shared leg - registry, presets, personas.** `_KNOWN_MCP_SERVERS` stays the single source of truth;
a vaultspec-core read entry is added only if an upstream read-only launch mode appears (else omitted,
rag + native cover recall). Document-authoring presets (the live `vaultspec-adr-research.toml`) declare
a `[team.harness]` block naming `vaultspec-rag`; the flat team-level schema delivers it to all document
roles, with per-role composition left as the harness ADR's deferred schema extension. The researcher
persona (plan row P03.S05 of `2026-07-15-graph-agent-framework-harness-plan`) is re-expressed to name
only tools the model can see - the rag search MCP tool and native Read/Grep/Glob - dropping the
`terminal=false`-unexecutable CLI invocations. The falsified "stdio surfaces reliably" docstrings are
corrected to the S20 truth.

## Rationale

The knockout reframing is that the surfacing gate is almost certainly a stale-adapter artifact,
not a fixed property of the design. Our adapter is deprecated and 36 releases behind, and the SDK
changelog names the exact runtime-injection surfacing fix (0.3.166) and the exact session-vs-scope
fix (0.2.69) on the axis S20 found dispositive. Migrating is mandatory regardless (a deprecated pin
receives no updates ever, which by itself violates the frontier posture), so the cheapest path to
the cleanest outcome is migrate-then-reprobe: if it surfaces, the composition seam already built
works as-is, with no surfacing carve-out and no weakening of the harness suppression invariant.
Separating suppression from surfacing is what makes this clean: the ambient-MCP isolation is built
either way because the write-leak vector is real independent of surfacing, but it only has to double
as the surfacing path in the contingency - so a successful re-probe closes the harness ADR's Opens
item with no invariant change, and a failed one refines the invariant honestly (the original leak
was a WRITE path; a read-only carve-out over a read-clean vault refines rather than weakens it). The
native-tool floor makes the whole sequence safe: real deterministic grounding ships on every lane
immediately, so the semantic tier's dependence on an external re-probe gates no value. One registry
over two delivery shapes keeps Claude/Z.ai and Codex honest to the dedup mandate while honoring each
provider's native config, and the per-run isolated config home is the same structural mechanism on
both lanes; the Codex read-only sandbox plus `enabled_tools` allowlist gives a stricter read-only
posture than Claude's flat allowlist. Composing the write-capable vaultspec-core MCP or bridging
engine catalog tools both fail the deny-at-the-surface rule or the engine-ownership boundary.

## Consequences

- Gains: deterministic grounding ships on all three lanes the day the floor lands; the mandatory
  adapter migration is claimed as an owned, sequenced step rather than latent deprecated-dependency
  debt; a single registry serves both delivery shapes; the harness ADR's unbuilt ambient-MCP
  suppression becomes real code regardless of the re-probe outcome.
- Conditional harness-provisioning ADR amendment: the ambient-MCP suppression is built either way,
  but the invariant TEXT is amended ONLY if the re-probe fails and the isolated home must also carry
  surfacing - refined from "inject only via session `mcpServers`; suppress all user-global MCP" to
  "the worker owns an isolated CLI config home containing EXACTLY the declared read-only harness
  servers; ambient and operator user-global MCP are suppressed by that isolation; no write-capable
  server is ever composed or written into the home." If the re-probe succeeds, no amendment is needed
  and the harness ADR's per-role MCP-composition Opens item closes at the delivery layer.
- Difficulties and honest risk: the adapter jump (0.23.1 to 0.59.0) may break the ACP surface our
  layer targets (`session/new`, permission modes/`allowedTools`, `mcpServers` key, capability flags,
  fs-RPC behavior) - regression-verified in the plan. The re-probe outcome is unproven and is the
  decision point. The Codex MCP-under-read-only-sandbox composition is an undocumented axis the plan
  must prove live. Version provenance ("2.1.210" vs vendored 2.1.83) remains ambiguous and is not
  relied on.
- Dead/stale code the decision supersedes, named for removal: the "stdio surfaces reliably" transport
  framing in `src/vaultspec_a2a/graph/nodes/worker.py:135` and
  `src/vaultspec_a2a/providers/_acp_authoring.py:104,113`; the allowlist-less `attach(combined)` call
  in `src/vaultspec_a2a/providers/_acp_mcp.py:81-87`; and the already-slated dead `has_workspace_rules`
  consumption (S15).
- Opens: a read-only vaultspec-core MCP for structured vault queries, gated on an upstream read-only
  launch mode; true per-role harness composition when a real need arises.

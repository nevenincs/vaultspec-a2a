---
generated: true
tags:
  - '#index'
  - '#tool-cores'
date: '2026-07-17'
modified: '2026-07-17'
related:
  - '[[2026-07-17-tool-cores-P01-S01]]'
  - '[[2026-07-17-tool-cores-P01-S02]]'
  - '[[2026-07-17-tool-cores-P01-S03]]'
  - '[[2026-07-17-tool-cores-P01-S04]]'
  - '[[2026-07-17-tool-cores-P01-S05]]'
  - '[[2026-07-17-tool-cores-P02-S06]]'
  - '[[2026-07-17-tool-cores-P02-S07]]'
  - '[[2026-07-17-tool-cores-P02-S08]]'
  - '[[2026-07-17-tool-cores-P02-S09]]'
  - '[[2026-07-17-tool-cores-P03-S10]]'
  - '[[2026-07-17-tool-cores-P03-S11]]'
  - '[[2026-07-17-tool-cores-P03-S12]]'
  - '[[2026-07-17-tool-cores-P03-S13]]'
  - '[[2026-07-17-tool-cores-P03-S14]]'
  - '[[2026-07-17-tool-cores-P03-S15]]'
  - '[[2026-07-17-tool-cores-P03-S16]]'
  - '[[2026-07-17-tool-cores-P03-S17]]'
  - '[[2026-07-17-tool-cores-P04-S18]]'
  - '[[2026-07-17-tool-cores-P04-S19]]'
  - '[[2026-07-17-tool-cores-P04-S20]]'
  - '[[2026-07-17-tool-cores-P04-S21]]'
  - '[[2026-07-17-tool-cores-P05-S22]]'
  - '[[2026-07-17-tool-cores-adr]]'
  - '[[2026-07-17-tool-cores-audit]]'
  - '[[2026-07-17-tool-cores-dedup-audit]]'
  - '[[2026-07-17-tool-cores-plan]]'
  - '[[2026-07-17-tool-cores-research]]'
---

# `tool-cores` feature index

Auto-generated index of all documents tagged with `#tool-cores`.

## Documents

### adr

- `2026-07-17-tool-cores-adr` - `tool-cores` adr: `read-only grounding tools for graph document agents` | (**status:** `accepted`)

### audit

- `2026-07-17-tool-cores-audit` - `tool-cores` audit: `S24 holistic safety and intent gate`
- `2026-07-17-tool-cores-dedup-audit` - `tool-cores` audit: `P05.S23 vault dedup sweep — decision-vs-decision, decision-vs-code, and cross-plan reconciliation`

### exec

- `2026-07-17-tool-cores-P01-S01` - Permit the native read built-ins Read, Grep, and Glob in autonomous mode for document-authoring roles so deterministic grounding is invocable without a local prompt (executor-core)
- `2026-07-17-tool-cores-P01-S02` - Re-express the researcher persona to name the native Read, Grep, and Glob grounding tools and remove the terminal-false-unexecutable vaultspec-core and rag CLI invocations, claiming P03.S05 of the graph-agent-framework-harness plan, with the rag MCP tool names added later once surfacing is confirmed (executor-service)
- `2026-07-17-tool-cores-P01-S03` - Correct the falsified stdio-surfaces-reliably docstring to the S20 registration-scope truth (executor-core)
- `2026-07-17-tool-cores-P01-S04` - Correct the falsified stdio-surfaces-reliably docstring to the S20 registration-scope truth (executor-core)
- `2026-07-17-tool-cores-P01-S05` - Prove live on the Claude lane that a document agent reads a named .vault ADR mid-turn and cites it, real run against the live engine with no mocks and zero .vault writes (executor-service)
- `2026-07-17-tool-cores-P02-S06` - Migrate the adapter dependency from the deprecated at-zed-industries claude-agent-acp to at-agentclientprotocol claude-agent-acp version 0.59.0 (executor-core)
- `2026-07-17-tool-cores-P02-S07` - Update the adapter entry-point resolution and npm install hint from the zed-industries path to the renamed agentclientprotocol package layout (executor-core)
- `2026-07-17-tool-cores-P02-S08` - Regression-verify the ACP surface the provider layer targets against the migrated adapter: session-new shape, permission modes and allowedTools, mcpServers config key, capability flags, and server-initiated fs-RPC behavior (executor-core)
- `2026-07-17-tool-cores-P02-S09` - Re-run the S20 registration-scope matrix on the migrated stack and record the decision-point outcome as an exec record: surfaced routes P03 to the existing composition path, not-surfaced routes P03 to the isolated-config-home surfacing fallback (executor-service)
- `2026-07-17-tool-cores-P03-S10` - Extend compose_harness_mcp_servers to accept and apply an allowlist so the composed servers exact tool names join the autonomous allowedTools, closing the attach-combined gap (executor-core)
- `2026-07-17-tool-cores-P03-S11` - Thread the composed rag tool names into the autonomous allowlist at the worker composition site alongside the authoring tool names (executor-core)
- `2026-07-17-tool-cores-P03-S12` - Declare the team.harness mcp_servers opt-in naming vaultspec-rag on the live document-authoring preset (executor-service)
- `2026-07-17-tool-cores-P03-S13` - Build the worker-owned isolated CLI config home that excludes the operator writable user-global MCP, delivering the harness ambient-MCP suppression required regardless of the re-probe outcome (executor-core)
- `2026-07-17-tool-cores-P03-S14` - If the P02 exec record shows session-injected servers do not surface, additionally populate the isolated config home with the declared read-only servers so they surface as user-global config (executor-core)
- `2026-07-17-tool-cores-P03-S15` - Add the rag search MCP tool name to the researcher persona grounding instructions once surfacing is confirmed by the P02 outcome (executor-service)
- `2026-07-17-tool-cores-P03-S16` - Prove live that a Claude document agent invokes vaultspec-rag search mid-turn, capturing the tool-call trace and confirming citations resolve to real locations, real run with no mocks and zero .vault writes (executor-service)
- `2026-07-17-tool-cores-P03-S17` - Prove live that a Z.ai document agent invokes vaultspec-rag search mid-turn, capturing the tool-call trace and confirming citations resolve to real locations, real run with no mocks and zero .vault writes (executor-service)
- `2026-07-17-tool-cores-P04-S18` - Emit a per-run CODEX_HOME config.toml carrying the shared _KNOWN_MCP_SERVERS entries as mcp_servers blocks in the Codex config shape, one registry across two transports (executor-core)
- `2026-07-17-tool-cores-P04-S19` - Constrain the Codex MCP surface to read verbs via enabled_tools with approval_mode auto for reads, keeping the read-only sandbox as defense-in-depth (executor-core)
- `2026-07-17-tool-cores-P04-S20` - Prove live on the Codex lane that a document agent reads a named .vault ADR via read-only sandbox filesystem access mid-turn and cites it, real run with no mocks and zero .vault writes (executor-service)
- `2026-07-17-tool-cores-P04-S21` - Prove live that a Codex document agent invokes vaultspec-rag search mid-turn under approval-policy never and sandbox read-only, capturing the tool-call trace and confirming citations resolve, real run with no mocks (executor-service)
- `2026-07-17-tool-cores-P05-S22` - Remove the superseded allowlist-less attach-combined path and any other code the landed composition mechanism supersedes (executor-core)

### plan

- `2026-07-17-tool-cores-plan` - `tool-cores` plan

### research

- `2026-07-17-tool-cores-research` - `tool-cores` research: `read-only grounding tools for graph agents`

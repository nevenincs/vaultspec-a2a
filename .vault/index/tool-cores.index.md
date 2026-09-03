---
generated: true
tags:
  - '#index'
  - '#tool-cores'
date: '2026-08-05'
modified: '2026-09-03'
body_schema: 'body-v2'
body_hash: 'sha256:4131c5fbe019c1c284b182ca963df2d76be3450bfe5db9b00f03de6948f8fe59'
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
  - '[[2026-07-17-tool-cores-P05-S23]]'
  - '[[2026-07-17-tool-cores-P05-S24]]'
  - '[[2026-07-17-tool-cores-P05-S25]]'
  - '[[2026-07-17-tool-cores-adr]]'
  - '[[2026-07-17-tool-cores-audit]]'
  - '[[2026-07-17-tool-cores-dedup-audit]]'
  - '[[2026-07-17-tool-cores-plan]]'
  - '[[2026-07-17-tool-cores-research]]'
  - '[[2026-08-01-tool-cores-P01-S01]]'
  - '[[2026-08-01-tool-cores-P01-S02]]'
  - '[[2026-08-01-tool-cores-P01-S03]]'
  - '[[2026-08-01-tool-cores-P01-summary]]'
  - '[[2026-08-01-tool-cores-P02-S04]]'
  - '[[2026-08-01-tool-cores-P02-S05]]'
  - '[[2026-08-01-tool-cores-P02-S06]]'
  - '[[2026-08-01-tool-cores-P02-S07]]'
  - '[[2026-08-01-tool-cores-P02-S13]]'
  - '[[2026-08-01-tool-cores-P02-S14]]'
  - '[[2026-08-01-tool-cores-P02-S22]]'
  - '[[2026-08-01-tool-cores-P03-S11]]'
  - '[[2026-08-01-tool-cores-plan]]'
  - '[[2026-08-01-tool-cores-web-grounding-adr]]'
  - '[[2026-08-01-tool-cores-web-grounding-research]]'
  - '[[2026-08-02-tool-cores-codex-isolation-p02s22-audit]]'
---

# `tool-cores` feature index

Auto-generated index of all documents tagged with `#tool-cores`.

## Documents

### adr

- `2026-07-17-tool-cores-adr` - `tool-cores` adr: `read-only grounding tools for graph document agents` | (**status:** `accepted`)
- `2026-08-01-tool-cores-web-grounding-adr` - `tool-cores` adr: `web grounding` | (**status:** `accepted`)

### audit

- `2026-07-17-tool-cores-audit` - `tool-cores` audit: `S24 holistic safety and intent gate`
- `2026-07-17-tool-cores-dedup-audit` - `tool-cores` audit: `P05.S23 vault dedup sweep — decision-vs-decision, decision-vs-code, and cross-plan reconciliation`
- `2026-08-02-tool-cores-codex-isolation-p02s22-audit` - `tool-cores` audit: `Codex isolation P02.S22 review`

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
- `2026-07-17-tool-cores-P05-S23` - Sweep the vault via rag semantic search for duplicate or overlapping tool-cores records and reconcile any found, keeping one record per decision (executor-service)
- `2026-07-17-tool-cores-P05-S24` - Run the mandatory code-review gate over all landed tool-cores changes for safety and intent, which must return PASS before close-out (vaultspec-code-reviewer)
- `2026-07-17-tool-cores-P05-S25` - Reconcile the plan and exec records against what actually landed, ensuring every Step has its exec record and the Verification criteria are honestly closed (executor-service)
- `2026-08-01-tool-cores-P01-S01` - Split the registry trust-root marker so network egress is its own declared axis: an entry or native tool set with no egress declaration is REFUSED fail-loud at the real composition seam, never defaulted, migrating the sole existing registry entry to declare no-egress in the same change so the tree stays green. Closes on a test that drives the production config-home and spawn composition path and proves the refusal fires for an undeclared entry (executor-core)
- `2026-08-01-tool-cores-P01-S02` - Admit the typed web locator into the research-finding contract - kind web, url, retrieved-at ISO-8601, optional title and capped excerpt - enforced in the branch-side finding validation with caps. Closes on a graph-level test through the real dispatch, reducer, and checkpoint seam proving the locator survives into checkpointed state and reaches synthesis, never a direct field-set (executor-core)
- `2026-08-01-tool-cores-P01-S03` - Extend the submit refusal structurally: when accumulated findings carry web locators, every distinct locator URL must appear in the proposed document body, else the document-conformance error routes the run into the existing revision loop. Closes on a test through the real submit path proving the refusal FIRES on an undisclosed URL, plus a mutation run demonstrating the test fails when the check is absent (executor-core)
- `2026-08-01-tool-cores-P01-summary` - `tool-cores` P01 summary
- `2026-08-01-tool-cores-P02-S04` - Introduce the proven-web-lanes activation gate consumed by both tool composition and persona-text composition, empty at landing, by EXTENDING the existing lane-admission module rather than declaring a second mechanism
- `2026-08-01-tool-cores-P02-S05` - Compose the Claude and Z.ai web built-ins WebSearch and WebFetch into the autonomous allowlist by exact name for every document-authoring role, using the same role predicate that governs the native read floor, gated on the proven set, carrying the decided bounds through the first-party controls
- `2026-08-01-tool-cores-P02-S06` - Enable Codex web search through the per-run config home in live mode as the served posture, gated on the proven set, with cached mode reachable by configuration for a deployment that prefers zero egress
- `2026-08-01-tool-cores-P02-S07` - Compose the persona web-capability text lane-conditionally: the web-grounding paragraph with its citation obligations is injected for every document-authoring role only on lanes in the proven set, the existing no-online-access disclaimer stays the default, and preset descriptions remain unchanged in this Phase
- `2026-08-01-tool-cores-P02-S13` - Land the web-locator extractor in the research producer so a real retrieval becomes a typed locator, and decide in the same change whether the producer normalises a malformed locator or the branch refuses it
- `2026-08-01-tool-cores-P02-S14` - Close the two trust-structure findings the P01 review raised, as one change because they share a root
- `2026-08-01-tool-cores-P03-S11` - Prove the Codex live-mode lane live to the completed-retrieval standard, additionally verifying the undocumented axis the decision record constrains - live web search actually surfacing and invoking under the read-only sandbox and never approval policy
- `2026-08-01-tool-cores-P02-S22` - Always isolate Codex homes and surface redacted startup diagnostics

### plan

- `2026-07-17-tool-cores-plan` - `tool-cores` plan
- `2026-08-01-tool-cores-plan` - `tool-cores` plan

### research

- `2026-07-17-tool-cores-research` - `tool-cores` research: `read-only grounding tools for graph agents`
- `2026-08-01-tool-cores-web-grounding-research` - `tool-cores` research: `provider-native web grounding`

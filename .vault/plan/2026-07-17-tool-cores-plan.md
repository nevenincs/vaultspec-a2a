---
tags:
  - '#plan'
  - '#tool-cores'
date: '2026-07-17'
modified: '2026-07-17'
tier: L2
related:
  - '[[2026-07-17-tool-cores-adr]]'
  - '[[2026-07-17-tool-cores-research]]'
  - '[[2026-07-15-agent-harness-provisioning-adr]]'
  - '[[2026-07-15-graph-agent-framework-harness-plan]]'
---

# `tool-cores` plan

### Phase `P01` - Deterministic floor and persona truth

Land native read-tool grounding on every lane, the persona and docstring truth, and a live floor proof on the Claude lane; depends on nothing and ships regardless of the surfacing gate.

Deliver read-only grounding to graph document agents across the Claude, Codex, and Z.ai
lanes, executing the accepted `2026-07-17-tool-cores-adr`.

- [ ] `P01.S01` - Permit the native read built-ins Read, Grep, and Glob in autonomous mode for document-authoring roles so deterministic grounding is invocable without a local prompt (executor-core); `src/vaultspec_a2a/graph/nodes/worker.py`.
- [ ] `P01.S02` - Re-express the researcher persona to name the native Read, Grep, and Glob grounding tools and remove the terminal-false-unexecutable vaultspec-core and rag CLI invocations, claiming P03.S05 of the graph-agent-framework-harness plan, with the rag MCP tool names added later once surfacing is confirmed (executor-service); `src/vaultspec_a2a/team/presets/agents/vaultspec-researcher.toml`.
- [ ] `P01.S03` - Correct the falsified stdio-surfaces-reliably docstring to the S20 registration-scope truth (executor-core); `src/vaultspec_a2a/graph/nodes/worker.py`.
- [ ] `P01.S04` - Correct the falsified stdio-surfaces-reliably docstring to the S20 registration-scope truth (executor-core); `src/vaultspec_a2a/providers/_acp_authoring.py`.
- [ ] `P01.S05` - Prove live on the Claude lane that a document agent reads a named .vault ADR mid-turn and cites it, real run against the live engine with no mocks and zero .vault writes (executor-service); `src/vaultspec_a2a/service_tests/`.

### Phase `P02` - Adapter migration and surfacing re-probe

Migrate the deprecated adapter to the renamed package, regression-verify the ACP surface, re-run the S20 registration-scope matrix, and record the decision-point outcome that routes the semantic tier.

- [ ] `P02.S06` - Migrate the adapter dependency from the deprecated at-zed-industries claude-agent-acp to at-agentclientprotocol claude-agent-acp version 0.59.0 (executor-core); `package.json`.
- [ ] `P02.S07` - Update the adapter entry-point resolution and npm install hint from the zed-industries path to the renamed agentclientprotocol package layout (executor-core); `src/vaultspec_a2a/providers/factory.py`.
- [ ] `P02.S08` - Regression-verify the ACP surface the provider layer targets against the migrated adapter: session-new shape, permission modes and allowedTools, mcpServers config key, capability flags, and server-initiated fs-RPC behavior (executor-core); `src/vaultspec_a2a/providers/`.
- [ ] `P02.S09` - Re-run the S20 registration-scope matrix on the migrated stack and record the decision-point outcome as an exec record: surfaced routes P03 to the existing composition path, not-surfaced routes P03 to the isolated-config-home surfacing fallback (executor-service); `src/vaultspec_a2a/service_tests/`.

### Phase `P03` - Claude and Z.ai semantic grounding

Deliver vaultspec-rag to Claude and Z.ai document roles with read-only discipline. Ambient-MCP suppression is built regardless of the re-probe outcome; the allowlist and preset are needed either way; the isolated-home surfacing population fires only if P02 recorded not-surfaced.

- [ ] `P03.S10` - Extend compose_harness_mcp_servers to accept and apply an allowlist so the composed servers exact tool names join the autonomous allowedTools, closing the attach-combined gap (executor-core); `src/vaultspec_a2a/providers/_acp_mcp.py`.
- [ ] `P03.S11` - Thread the composed rag tool names into the autonomous allowlist at the worker composition site alongside the authoring tool names (executor-core); `src/vaultspec_a2a/graph/nodes/worker.py`.
- [ ] `P03.S12` - Declare the team.harness mcp_servers opt-in naming vaultspec-rag on the live document-authoring preset (executor-service); `src/vaultspec_a2a/team/presets/teams/vaultspec-adr-research.toml`.
- [ ] `P03.S13` - Build the worker-owned isolated CLI config home that excludes the operator writable user-global MCP, delivering the harness ambient-MCP suppression required regardless of the re-probe outcome (executor-core); `src/vaultspec_a2a/providers/acp_chat_model.py`.
- [ ] `P03.S14` - If the P02 exec record shows session-injected servers do not surface, additionally populate the isolated config home with the declared read-only servers so they surface as user-global config (executor-core); `src/vaultspec_a2a/providers/acp_chat_model.py`.
- [ ] `P03.S15` - Add the rag search MCP tool name to the researcher persona grounding instructions once surfacing is confirmed by the P02 outcome (executor-service); `src/vaultspec_a2a/team/presets/agents/vaultspec-researcher.toml`.
- [ ] `P03.S16` - Prove live that a Claude document agent invokes vaultspec-rag search mid-turn, capturing the tool-call trace and confirming citations resolve to real locations, real run with no mocks and zero .vault writes (executor-service); `src/vaultspec_a2a/service_tests/`.
- [ ] `P03.S17` - Prove live that a Z.ai document agent invokes vaultspec-rag search mid-turn, capturing the tool-call trace and confirming citations resolve to real locations, real run with no mocks and zero .vault writes (executor-service); `src/vaultspec_a2a/service_tests/`.

### Phase `P04` - Codex semantic grounding

Deliver vaultspec-rag to Codex through a per-run CODEX_HOME config.toml built from the same registry, read-only, and prove both floor and semantic grounding under the read-only sandbox.

- [ ] `P04.S18` - Emit a per-run CODEX_HOME config.toml carrying the shared _KNOWN_MCP_SERVERS entries as mcp_servers blocks in the Codex config shape, one registry across two transports (executor-core); `src/vaultspec_a2a/providers/codex_chat_model.py`.
- [ ] `P04.S19` - Constrain the Codex MCP surface to read verbs via enabled_tools with approval_mode auto for reads, keeping the read-only sandbox as defense-in-depth (executor-core); `src/vaultspec_a2a/providers/codex_chat_model.py`.
- [ ] `P04.S20` - Prove live on the Codex lane that a document agent reads a named .vault ADR via read-only sandbox filesystem access mid-turn and cites it, real run with no mocks and zero .vault writes (executor-service); `src/vaultspec_a2a/service_tests/`.
- [ ] `P04.S21` - Prove live that a Codex document agent invokes vaultspec-rag search mid-turn under approval-policy never and sandbox read-only, capturing the tool-call trace and confirming citations resolve, real run with no mocks (executor-service); `src/vaultspec_a2a/service_tests/`.

### Phase `P05` - Close-out

Remove superseded code, sweep the vault for duplication via rag, pass the mandatory review gate, and reconcile the plan and exec records.

- [ ] `P05.S22` - Remove the superseded allowlist-less attach-combined path and any other code the landed composition mechanism supersedes (executor-core); `src/vaultspec_a2a/providers/_acp_mcp.py`.
- [ ] `P05.S23` - Sweep the vault via rag semantic search for duplicate or overlapping tool-cores records and reconcile any found, keeping one record per decision (executor-service); `.vault/`.
- [ ] `P05.S24` - Run the mandatory code-review gate over all landed tool-cores changes for safety and intent, which must return PASS before close-out (vaultspec-code-reviewer); `.vault/audit/`.
- [ ] `P05.S25` - Reconcile the plan and exec records against what actually landed, ensuring every Step has its exec record and the Verification criteria are honestly closed (executor-service); `.vault/exec/`.

## Description

This plan executes `2026-07-17-tool-cores-adr` (read-only grounding tools for graph document
agents), grounded in `2026-07-17-tool-cores-research` and the harness contract of
`2026-07-15-agent-harness-provisioning-adr`. The ADR decides a two-tier design over one server
registry (`_KNOWN_MCP_SERVERS` in `src/vaultspec_a2a/providers/_acp_mcp.py`): a native-tool floor
that ships regardless of the surfacing gate, and a semantic tier (vaultspec-rag) delivered per
provider. It is strictly read-only: no write verb is ever composed, and the write-capable
`vaultspec-mcp` server is omitted.

Phase P01 lands the deterministic floor, the persona and docstring truth, and a live floor proof on
the Claude lane; it depends on nothing and ships immediately. Phase P02 is the decision gate:
migrate the deprecated adapter (`@zed-industries/claude-agent-acp@0.23.1`, renamed upstream to
`@agentclientprotocol/claude-agent-acp@0.59.0`), regression-verify the ACP surface, re-run the S20
registration-scope matrix, and record the outcome as an exec record. That record routes Phase P03:
if session-injected servers surface, the existing composition path suffices (P03 steps S10 to S12);
if they do not, the isolated config home additionally carries the surfacing role (step S14). The
ambient-MCP suppression (step S13) is built regardless of the outcome, because the write-leak vector
is independent of surfacing, per the ADR. Phase P04 delivers Codex semantic grounding through a
per-run `CODEX_HOME` config.toml built from the same registry, read-only via `enabled_tools`, and
proves both floor and semantic grounding under the read-only sandbox. Phase P05 closes out: dead-code
removal, a vault dedup sweep via rag, the mandatory review gate, and plan/exec reconciliation.

The ADR's mention of dead `has_workspace_rules` is already resolved: no such symbol exists in the
current tree, so no removal step is carried for it. The executing persona is named in each Step's
action text (executor-core for provider and graph code, executor-service for presets, tests, and
live proofs, vaultspec-code-reviewer for the review gate), since the plan row grammar carries no
dedicated persona field.

## Steps

## Parallelization

Phase P01 is independent of every other phase and can run in parallel with P02 from the start.
Phase P02 is a hard ordering gate for the semantic tier: its recorded outcome decides step S14 in
P03, so S14 must not begin until P02 records its result; the P03 allowlist, preset, and suppression
steps (S10 to S13) share no interdependency with the re-probe and may proceed alongside P02. Phase
P04 (Codex) shares only the registry with P03 and can run in parallel with P03 once P01 lands. Phase
P05 is sequenced last: each live-proof step depends on its provider lane being complete, the
dead-code removal depends on the P03 allowlist step having superseded the old path, and the review
gate depends on all implementation and proof steps having landed.

## Verification

The plan is complete when every Step is closed and the following observable live evidence holds;
tests alone are not accepted as proof. The floor is verified per lane by a real run in which a
document agent reads a named `.vault` ADR mid-turn and cites it (Claude in P01, Codex in P04), with
zero `.vault` writes observed by a before-and-after watcher. The adapter migration is verified when
the regression surface (`session/new` shape, permission modes and `allowedTools`, the `mcpServers`
config key, capability flags, and server-initiated fs-RPC behavior) is confirmed intact on the
migrated stack and the S20 matrix outcome is recorded as a durable exec record. The semantic tier is
verified per provider by a real run in which a document agent invokes vaultspec-rag search mid-turn,
the tool-call trace is captured, and the returned citations resolve to real vault and code
locations, against the live engine with no mocks, stubs, or skips. Read-only discipline is verified
by confirming no write verb is present in any composed surface on either transport and that zero
agent-origin `.vault` writes occur across every proof run. The Codex semantic proof additionally
verifies the undocumented axis composition (`approval_policy:"never"` plus `sandbox:"read-only"` plus
per-tool `approval_mode`) actually admits the MCP tool call. Honesty limit: if the P02 re-probe
records that session-injected servers still do not surface, the Claude and Z.ai semantic proofs are
gated on the isolated-home surfacing step S14, and any residual gap is recorded as an explicit
re-arm criterion rather than reported as passing. Close-out requires a reviewer PASS on the review
gate and a reconciled exec record for every Step.

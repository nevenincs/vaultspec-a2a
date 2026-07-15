---
tags:
  - '#research'
  - '#agent-harness-provisioning'
date: '2026-07-15'
modified: '2026-07-15'
related:
  - "[[2026-07-14-adr-authoring-orchestration-adr]]"
---

# `agent-harness-provisioning` research: `the agent harness as a contract: what authoring agents can currently see and where it silently degrades`

Question: the owner's directive (2026-07-15) states the agent harness is composed of skills, agent personas, rules, and tools (CLI, MCP) - all of which must be available to executing and authoring agents, plus internet access. What does the runtime actually give an agent today, and where does the harness silently degrade? Conclusion: four of five harness surfaces have partial machinery and one (skills) has none; the failure mode is uniformly SILENT degradation - an unprovisioned workspace produces agents that author blind with no error anywhere - proven live by the first S10 run's non-conformant output and its reversal after manual full provisioning (ws5).

## Findings

### Rules: injected when present, silently absent when not

`context/rules.py` RuleManager discovers and compiles `.vaultspec/rules/rules/*.md` into a system-prompt block, wired into both supervisor and worker message assembly (`rules.py:22-76`; `graph/nodes/worker.py` `_build_worker_messages`). But `compile()` returns None on an empty/absent rules dir and the callers skip the block - no warning, no eligibility signal. A minimal workspace yields rule-less agents invisibly.

### Templates and personas: readable only if the workspace carries them

Claude ACP agents have filesystem_read within workspace_root, so `.vaultspec/templates/*.md` and the persona depth are reachable - IF provisioned. Nothing verifies presence; the first S10 run's workspace had neither, and its ADR shipped with the raw `{proposed|accepted|...}` enum and annotation residue. The provisioned ws5 rerun (manual vaultspec-core install + strengthened directives) is the live counterfactual.

### Skills: no runtime concept at all

`.vaultspec/skills/` exists in provisioned workspaces but the runtime never references skills anywhere (zero hits in team_config, context, graph). The vaultspec framework treats skills as first-class procedure documents; the agent runtime is blind to them.

### Tools: MCP injection exists; CLI availability is unmanaged; web is provider-dependent

Per-session MCP surfacing is solved (ACP `mcpServers` injection - the authoring bridge, S19). The vaultspec-core CLI is NOT guaranteed in the spawned agent's environment (ws5 verified uv/uvx resolvability by hand); read-only self-validation (`vault check` on drafts staged outside `.vault/`) was an owner-directive addition with no runtime support. Web tooling exists natively on the ACP path and not at all on ChatOpenAI - now an eligibility concern (orchestration ADR refinement, 2026-07-15) with no enforcement.

### The enforcement point exists: eligibility

The model-profiles resolver already serves per-role eligibility with safe reasons, consumed by discovery and run-start (`providers/model_profiles.py`). A `harness_ready` term slots into the same service - making harness completeness a served truth instead of a driver courtesy.

Not investigated: harness needs of non-authoring (future) run kinds; MCP servers beyond the authoring bridge (vaultspec-rag injection is plausible but unassessed for token cost).

## Sources

- `src/vaultspec_a2a/context/rules.py:22-76`
- `src/vaultspec_a2a/graph/nodes/worker.py` (_build_worker_messages), `graph/nodes/supervisor.py` (_build_supervisor_messages)
- `src/vaultspec_a2a/providers/_acp_authoring.py` + `protocols/mcp/tools/authoring_bridge.py` (MCP injection precedent)
- `src/vaultspec_a2a/providers/model_profiles.py` (eligibility service)
- S10 live evidence: first-run non-conformant output vs provisioned ws5 rerun (S10 step record, 2026-07-15); owner directive pinned in `2026-07-14-adr-authoring-orchestration-adr` Implementation refinement

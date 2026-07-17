---
tags:
  - '#exec'
  - '#graph-agent-framework-harness'
date: '2026-07-17'
modified: '2026-07-17'
step_id: 'S05'
related:
  - "[[2026-07-15-graph-agent-framework-harness-plan]]"
---

# Rewrite the researcher persona's discovery-rag prompt instructions to name only model-visible tools - DONE by the tool-cores feature: P01.S02 landed the native Read, Grep, and Glob re-expression and P03.S15 added the surfaced mcp__vaultspec-rag__ read tools after the isolated-config-home surfacing proof (tool-cores P03.S14)

## Scope

- `src/vaultspec_a2a/team/presets/agents/vaultspec-researcher.toml`

## Description

Retroactive reconciliation record, authored at plan close-out (P05.S12). The
researcher discovery-prompt rewrite this step called for was carried out under
the parallel tool-cores feature, not by a commit owned by this plan; this record
attributes that work honestly.

- The researcher persona's discovery instructions were re-expressed to name only
  model-visible tools: `ab8d482` (tool-cores P01.S02) dropped the unrunnable
  `vaultspec-core` / `vaultspec-rag` / `rg` CLI calls and grounded discovery on
  the native `Read`, `Grep`, and `Glob` built-ins.
- `951a113` (tool-cores P03.S15) then named the surfaced `mcp__vaultspec-rag__`
  read tools in the researcher grounding, after the isolated-config-home
  surfacing proof (tool-cores P03.S14) established that the composed rag MCP tools
  reach the model boundary.
- Net effect resolves the one genuinely-open rag-axis item the `P01` probe
  identified: the researcher prompt no longer instructs an invocation the runtime
  cannot execute.

## Outcome

Closed by `ab8d482` and `951a113` on `src/vaultspec_a2a/team/presets/agents/vaultspec-researcher.toml`.
The `P01`-flagged blocker (rag-search gated on `agent-harness-provisioning-adr`'s
per-role MCP composition) was cleared upstream once the surfacing proof landed, so
this step's target is satisfied rather than deferred.

## Notes

The substantive edit belongs to tool-cores commits, not to a commit under this
plan's own feature - honest attribution, not a claim of authorship here. This
record exists to close the exec-missing gap and cross-reference the real landing
SHAs.

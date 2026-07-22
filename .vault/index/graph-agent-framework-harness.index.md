---
generated: true
tags:
  - '#index'
  - '#graph-agent-framework-harness'
date: '2026-07-22'
modified: '2026-07-22'
related:
  - '[[2026-07-15-graph-agent-framework-harness-P01-S01]]'
  - '[[2026-07-15-graph-agent-framework-harness-P01-S02]]'
  - '[[2026-07-15-graph-agent-framework-harness-P01-summary]]'
  - '[[2026-07-15-graph-agent-framework-harness-P02-S03]]'
  - '[[2026-07-15-graph-agent-framework-harness-P02-S04]]'
  - '[[2026-07-15-graph-agent-framework-harness-P02-S13]]'
  - '[[2026-07-15-graph-agent-framework-harness-P03-S05]]'
  - '[[2026-07-15-graph-agent-framework-harness-P03-S06]]'
  - '[[2026-07-15-graph-agent-framework-harness-P03-S07]]'
  - '[[2026-07-15-graph-agent-framework-harness-P03-S08]]'
  - '[[2026-07-15-graph-agent-framework-harness-P04-S09]]'
  - '[[2026-07-15-graph-agent-framework-harness-P04-S10]]'
  - '[[2026-07-15-graph-agent-framework-harness-P04-S14]]'
  - '[[2026-07-15-graph-agent-framework-harness-P04-S15]]'
  - '[[2026-07-15-graph-agent-framework-harness-P05-S11]]'
  - '[[2026-07-15-graph-agent-framework-harness-P05-S12]]'
  - '[[2026-07-15-graph-agent-framework-harness-P05-summary]]'
  - '[[2026-07-15-graph-agent-framework-harness-adr]]'
  - '[[2026-07-15-graph-agent-framework-harness-plan]]'
  - '[[2026-07-15-graph-agent-framework-harness-research]]'
  - '[[2026-07-16-graph-agent-framework-harness-batch2-3-review-audit]]'
  - '[[2026-07-16-graph-agent-framework-harness-batch4-5-review-audit]]'
  - '[[2026-07-16-graph-agent-framework-harness-exec]]'
---

# `graph-agent-framework-harness` feature index

Auto-generated index of all documents tagged with `#graph-agent-framework-harness`.

## Documents

### adr

- `2026-07-15-graph-agent-framework-harness-adr` - `graph-agent-framework-harness` adr: `closing the framework-harness gap for graph-executed document-authoring agents` | (**status:** `accepted`)

### audit

- `2026-07-16-graph-agent-framework-harness-batch2-3-review-audit` - `graph-agent-framework-harness` audit: `batch-2 and batch-3 reviewer verdict: bundled rule wiring, role-leak fix, and context-graph cycle break`
- `2026-07-16-graph-agent-framework-harness-batch4-5-review-audit` - `graph-agent-framework-harness` audit: `batch-4 and batch-5 reviewer verdict: P05.S11 receipt proof, verify_harness rules-leg fix, and MCP composition`

### exec

- `2026-07-15-graph-agent-framework-harness-P01-summary` - `graph-agent-framework-harness` `P01` summary
- `2026-07-15-graph-agent-framework-harness-P02-S03` - Extract the taxonomy/frontmatter/wiki-link/template conventions a document-authoring agent needs into a role-scoped rule source, separate from the full builtin corpus
- `2026-07-15-graph-agent-framework-harness-P02-S04` - Add role-targeting to rule discovery so a worker's compiled rule set can be scoped by persona role instead of concatenating every non-builtin file into every turn
- `2026-07-15-graph-agent-framework-harness-P02-S13` - Fix the RuleManager path-misalignment defect: align _RULES_SUBDIR to the current flat vaultspec-core 0.1.42 schema (rules live directly under .vaultspec/rules/*.md, confirmed by spec rules status) rather than the nonexistent nested rules/rules/ directory, with no dual-read legacy fallback per the owner's no-compat-shims directive
- `2026-07-15-graph-agent-framework-harness-P04-S09` - Wire the P02 role-scoped rule selection into the worker node's rule-compilation call, replacing the unconditional whole-corpus compile
- `2026-07-15-graph-agent-framework-harness-P04-S10` - Wire the equivalent role-scoped rule selection into the supervisor node's rule-compilation call
- `2026-07-15-graph-agent-framework-harness-P04-S14` - Wire the role-scoped rule compilation into the researcher producer path - create_researcher_node's injected producer never routed through the worker node's rule-compilation call, leaving the fourth document persona conventions-blind (P04.S09 follow-on flag, landed in 96bd13e as _make_research_producer compiling the researcher role with the bundled dir and the same workspace_root state fallback as the worker path)
- `2026-07-15-graph-agent-framework-harness-P04-S15` - Consume the declared team.harness mcp_servers into the ACP session composition - resolve each declared server name to a launch spec and thread it per-role through AcpChatModel.with_mcp_servers into session/new, claiming the agent-harness-provisioning ADR's unowned per-role MCP-composition Opens item with a protocol-layer assertion (advertised servers present in session/new params), model-visible surfacing remaining upstream-gated per the S20 constraint
- `2026-07-15-graph-agent-framework-harness-P05-S11` - Add a live service-level assertion that a research_adr worker turn's compiled system messages actually contain the P02 role-scoped rule content, run against a real provisioned workspace rather than a static-repo RuleManager.compile() call
- `2026-07-16-graph-agent-framework-harness-exec` - context-graph import cycle fix + LOW-1 invariant
- `2026-07-15-graph-agent-framework-harness-P01-S01` - Verify the persona-prompt CLI-invocation finding against the parallel session's landed 9c2e9dc/b1d9892 fixes: confirm the scaffold-propose half is closed (personas emit body, DocumentProposalSubmitter submits), and confirm the rag-search half (amend-vs-supersede check, discovery calls) remains genuinely open pending MCP composition
- `2026-07-15-graph-agent-framework-harness-P01-S02` - Record the verified finding as a probe note: scaffold-propose CLI instructions resolved upstream, rag-search CLI instructions tracked as an open dependency on agent-harness-provisioning-adr's MCP-composition work, not re-litigated here
- `2026-07-15-graph-agent-framework-harness-P03-S05` - Rewrite the researcher persona's discovery-rag prompt instructions to name only model-visible tools - DONE by the tool-cores feature: P01.S02 landed the native Read, Grep, and Glob re-expression and P03.S15 added the surfaced mcp__vaultspec-rag__ read tools after the isolated-config-home surfacing proof (tool-cores P03.S14)
- `2026-07-15-graph-agent-framework-harness-P03-S06` - Confirm the synthesist persona carries no residual document-scaffold CLI instructions - the scaffold-propose path was excised upstream by 9c2e9dc and the current prompt only PROHIBITS vault-add/propose while describing the graph-submitter flow, verified per the P01 probe and re-verified against HEAD, reducing this step from a rewrite to a doc-consistency confirmation per architect ruling
- `2026-07-15-graph-agent-framework-harness-P03-S07` - Confirm the adr-author persona carries no residual scaffold or amend-vs-supersede rag-search instructions - both were excised upstream by 9c2e9dc and verified by the P01 probe (416b7f0), reducing this step from a rewrite to a doc-consistency confirmation per architect ruling
- `2026-07-15-graph-agent-framework-harness-P03-S08` - Confirm the doc-reviewer persona prompt is consistent with the graph-submitter mechanism - aligned upstream by b1d9892 to review the writer's message body with the scaffold-echo auto-revision rule, verified per the P01 probe and re-verified against HEAD, reducing this step from a rewrite to a doc-consistency confirmation per architect ruling
- `2026-07-15-graph-agent-framework-harness-P05-S12` - Record the verification evidence and close out the plan's Verification criteria, reconciling this feature's exec summary against what actually landed
- `2026-07-15-graph-agent-framework-harness-P05-summary` - `graph-agent-framework-harness` `P05` summary

### plan

- `2026-07-15-graph-agent-framework-harness-plan` - `graph-agent-framework-harness` plan

### research

- `2026-07-15-graph-agent-framework-harness-research` - `graph-agent-framework-harness` research: `what graph-executed research_adr agents actually receive vs. the vaultspec framework harness they need`

---
tags:
  - '#plan'
  - '#graph-agent-framework-harness'
date: '2026-07-15'
modified: '2026-07-15'
tier: L2
related:
  - '[[2026-07-15-graph-agent-framework-harness-adr]]'
  - '[[2026-07-15-graph-agent-framework-harness-research]]'
  - '[[2026-03-31-universal-rule-propagation-adr]]'
  - '[[2026-07-14-adr-authoring-orchestration-adr]]'
  - '[[2026-07-14-adr-authoring-orchestration-plan]]'
  - '[[2026-07-15-multi-provider-execution-adr]]'
  - '[[2026-07-15-multi-provider-execution-plan]]'
---

# `graph-agent-framework-harness` plan

### Phase `P01` - resolve the persona-prompt CLI-invocation question

Determine, with evidence rather than assumption, whether the four research_adr personas' TOML prompt instructions to invoke vaultspec-core/vaultspec-rag CLI commands are vestigial leftovers from an earlier design or an unbuilt invocation path, so later phases fix the right thing.

- [ ] `P01.S01` - Verify the persona-prompt CLI-invocation finding against the parallel session's landed 9c2e9dc/b1d9892 fixes: confirm the scaffold-propose half is closed (personas emit body, DocumentProposalSubmitter submits), and confirm the rag-search half (amend-vs-supersede check, discovery calls) remains genuinely open pending MCP composition; `src/vaultspec_a2a/authoring/submitter.py`, `src/vaultspec_a2a/graph/nodes/phase_gate.py`, `src/vaultspec_a2a/team/presets/agents/vaultspec-researcher.toml`, `vaultspec-synthesist.toml`, `vaultspec-adr-author.toml`, `vaultspec-doc-reviewer.toml`.
- [ ] `P01.S02` - Record the verified finding as a probe note: scaffold-propose CLI instructions resolved upstream, rag-search CLI instructions tracked as an open dependency on agent-harness-provisioning-adr's MCP-composition work, not re-litigated here; `.vault/exec/2026-07-15-graph-agent-framework-harness/2026-07-15-graph-agent-framework-harness-P01-summary.md`.

### Phase `P02` - design a role-scoped rule-propagation shape

Shape which mechanical conventions (tag taxonomy, wiki-link/frontmatter rules, template-read guidance) each of the four document personas needs, scoped per role rather than a blanket include_builtin=True, to avoid ADR-028's flagged token-inflation and cross-role-noise risk.

- [ ] `P02.S13` - Fix the RuleManager path-misalignment defect: align _RULES_SUBDIR to the current flat vaultspec-core 0.1.42 schema (rules live directly under .vaultspec/rules/*.md, confirmed by spec rules status) rather than the nonexistent nested rules/rules/ directory, with no dual-read legacy fallback per the owner's no-compat-shims directive; `src/vaultspec_a2a/context/rules.py`.
- [ ] `P02.S03` - Extract the taxonomy/frontmatter/wiki-link/template conventions a document-authoring agent needs into a role-scoped rule source, separate from the full builtin corpus; `.vaultspec/rules/ (new non-builtin rule file(s), flat per the current schema), .vaultspec/templates/adr.md, research.md, plan.md, audit.md, ref-audit.md`.
- [ ] `P02.S04` - Add role-targeting to rule discovery so a worker's compiled rule set can be scoped by persona role instead of concatenating every non-builtin file into every turn; `src/vaultspec_a2a/context/rules.py`.

### Phase `P03` - reconcile the four persona prompts

Rewrite each of the four research_adr document personas' TOML system prompts against the resolved reading from P01 - either pointing them at a newly built invocation path, or replacing the impossible CLI instructions with an accurate description of the real graph-driven propose/submit flow.

- [ ] `P03.S05` - Rewrite the researcher persona's discovery-rag prompt instructions per the P01 finding; `src/vaultspec_a2a/team/presets/agents/vaultspec-researcher.toml`.
- [ ] `P03.S06` - Rewrite the synthesist persona's document-scaffold CLI prompt instructions per the P01 finding; `src/vaultspec_a2a/team/presets/agents/vaultspec-synthesist.toml`.
- [ ] `P03.S07` - Rewrite the adr-author persona's scaffold and mandatory amend-vs-supersede rag-search prompt instructions per the P01 finding; `src/vaultspec_a2a/team/presets/agents/vaultspec-adr-author.toml`.
- [ ] `P03.S08` - Reconcile the doc-reviewer persona's prompt instructions per the P01 finding for consistency across all four personas; `src/vaultspec_a2a/team/presets/agents/vaultspec-doc-reviewer.toml`.

### Phase `P04` - wire role-scoped propagation at the graph entry points

Wire the P02-designed role-scoped rule selection into the two RuleManager call sites so each persona's worker/supervisor turn actually receives its scoped rule set.

- [ ] `P04.S09` - Wire the P02 role-scoped rule selection into the worker node's rule-compilation call, replacing the unconditional whole-corpus compile; `src/vaultspec_a2a/graph/nodes/worker.py`.
- [ ] `P04.S10` - Wire the equivalent role-scoped rule selection into the supervisor node's rule-compilation call; `src/vaultspec_a2a/graph/nodes/supervisor.py`.

### Phase `P05` - prove live receipt against a real provisioned run

Assert end-to-end, against a real provisioned run workspace rather than RuleManager.compile() in isolation, that a graph-executed persona actually receives its scoped rules and reconciled prompt, per the ADR's live-proof constraint.

- [ ] `P05.S11` - Add a live service-level assertion that a research_adr worker turn's compiled system messages actually contain the P02 role-scoped rule content, run against a real provisioned workspace rather than a static-repo RuleManager.compile() call; `src/vaultspec_a2a/service_tests/test_pw7_acceptance.py or a new sibling service test module`.
- [ ] `P05.S12` - Record the verification evidence and close out the plan's Verification criteria, reconciling this feature's exec summary against what actually landed; `.vault/exec/2026-07-15-graph-agent-framework-harness/2026-07-15-graph-agent-framework-harness-P05-summary.md`.

## Description

Executes the accepted `graph-agent-framework-harness-adr` (closing the framework-harness gap for graph-executed document-authoring agents), grounded in `graph-agent-framework-harness-research`. This plan is the live continuation of `universal-rule-propagation-adr` (ADR-028, now reconciled to accepted): ADR-028's `RuleManager` mechanism was built and wired, but concrete gaps remain open - a `_RULES_SUBDIR` path-misalignment defect (`RuleManager` reads a nested `rules/rules/` directory that does not exist under the current flat vaultspec-core 0.1.42 schema, so it silently finds nothing even though 112 real rule files sit flat under `.vaultspec/rules/`), `include_builtin=False` excluding the mechanical builtin rule files at both call sites once the path is fixed, and - for the four research_adr document personas' TOML prompts - a rag-search CLI-invocation gap that remains open after the scaffold-propose half was independently resolved upstream (`9c2e9dc`/`b1d9892`).

Phase `P01` verifies the persona-prompt finding against the already-landed upstream fixes rather than re-deriving it from scratch, confirming what is closed (scaffold-propose) and what remains open (rag-search) before later phases proceed. `P02` first fixes the `_RULES_SUBDIR` path defect (a mechanical code bug, not a design choice), then designs a role-scoped rule-propagation shape that avoids ADR-028's own flagged token-inflation and cross-role-noise risk rather than reaching for a blanket `include_builtin=True`. `P03` reconciles any remaining persona-prompt gaps against the `P01` finding. `P04` wires the `P02` shape into the two `RuleManager` call sites. `P05` proves the fix live against a real provisioned run workspace, per the ADR's explicit constraint that a static-repo check is insufficient.

Related to `adr-authoring-orchestration-adr`/`-plan` (the research_adr topology this harness gap lives inside) and `multi-provider-execution-adr`/`-plan` (the broader Program 3 mission this feature belongs to). Cross-referenced, not folded into, the parallel session's `agent-harness-provisioning-adr`/`-plan`: that plan covers the system-wide harness contract across all agent types and its own open `Opens` item (per-role rag MCP composition) is the dependency this plan's rag-search half tracks, not resolves; this plan is the narrower, code-verified fix for the research_adr topology's specific `RuleManager` and persona-prompt gaps.

## Steps

## Parallelization

Sequential by design: `P01` gates `P02` and `P03` (the propagation shape and the persona-prompt reconciliation both depend on the resolved vestigial-vs-aspirational reading), `P02` gates `P04` (wiring needs the designed shape), and `P04` gates `P05` (nothing to prove live until the wiring lands). `P03` and `P04` may run in parallel once `P01` and `P02` close, since persona-prompt text and the two call-site wiring touch disjoint files.

Explicit sequencing constraint from team-lead: this plan is NOT prioritized ahead of the PW7 acceptance-harness build (executor-opus-7's critical path). Steps here begin only once PW7 lands or executor-opus-5 is otherwise free; do not contend for the same reviewer/gate attention PW7 needs. Steps are sized for executor-opus-5 (idle, fresh) as primary assignee; `P01.S01` and `P02.S04` (role-targeting logic change) are higher-reasoning steps suited to `vaultspec-high-executor`, the remainder to `vaultspec-standard-executor`.

## Verification

The plan is complete when every Step is closed. Beyond checkbox completion, mission success requires:

- The `P01` probe note confirms, by content not summary, which persona-prompt instructions the upstream `9c2e9dc`/`b1d9892` fixes already resolved and which (rag-search) remain open and tracked, not re-litigated.
- The `_RULES_SUBDIR` path defect is fixed to the current flat vaultspec-core schema with no dual-read legacy fallback, and `RuleManager.discover()` demonstrably finds the real rule corpus under `.vaultspec/rules/` post-fix.
- The role-scoped rule source lands as real files under `.vaultspec/rules/` (flat, per the current schema), readable and distinct from the full builtin corpus, with `RuleManager` discovery able to select a persona-scoped subset (not all-or-nothing).
- Any persona TOML prompt edits in `P03` leave no instruction the runtime cannot execute; each prompt accurately reflects either the already-landed graph-driven propose/submit flow or an explicitly tracked open dependency (rag-search).
- Both `worker.py` and `supervisor.py` call sites inject the role-scoped rule set, verified by reading the actual code change, not a summary.
- `P05`'s live assertion demonstrates end-to-end that a graph-executed persona's compiled system messages actually contain its scoped rule content in a real provisioned run workspace - `RuleManager.compile()` returning non-None in isolation is explicitly insufficient per the ADR's Constraints.
- Token-inflation cost of the new propagation is measured (approximate token count added per turn), not assumed away, honoring ADR-028's and this ADR's shared caution.

Be honest in the closing `P05` summary about any criterion not fully met; a plan claiming completion from a stub or an isolated unit check would repeat the exact failure mode this ADR was written to close.

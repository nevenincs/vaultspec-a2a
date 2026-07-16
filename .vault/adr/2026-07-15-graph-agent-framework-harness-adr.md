---
tags:
  - '#adr'
  - '#graph-agent-framework-harness'
date: '2026-07-15'
modified: '2026-07-16'
related:
  - "[[2026-07-15-graph-agent-framework-harness-research]]"
  - "[[2026-03-31-universal-rule-propagation-adr]]"
  - "[[2026-07-14-adr-authoring-orchestration-adr]]"
  - "[[2026-07-15-multi-provider-execution-adr]]"
---

# `graph-agent-framework-harness` adr: `closing the framework-harness gap for graph-executed document-authoring agents` | (**status:** `accepted`)

## Problem Statement

Graph-executed research_adr agents (researcher, synthesist, adr-author, doc-reviewer) do not reliably receive the vaultspec framework harness - the builtin mandate/discovery/CLI rules, and working invocation paths for the tools their own prompts instruct them to use - that a human session gets for free. The engine's server-side validation covers wire-shape and frontmatter mechanics but not body-prose taxonomy conventions, so the gap manifests as non-conformant document CONTENT even when proposals are accepted. Grounding: `2026-07-15-graph-agent-framework-harness-research`, verified against vaultspec-core 0.1.42 (MCP tool-schema 0.1.43).

## Considerations

- `RuleManager` (ADR-028's mechanism) is fully implemented and wired into both `worker.py:60` and `supervisor.py:310` - the propagation MECHANISM exists and works (research).
- **Corrected finding (2026-07-15, owner correction):** `RuleManager`'s `_RULES_SUBDIR` constant (`context/rules.py:19`) targets a nested `.vaultspec/rules/rules/` directory that does not exist under the current flat vaultspec-core 0.1.42 schema. The rule corpus is fully present - `vaultspec-core spec rules status` reports 112 up-to-date files sitting flat under `.vaultspec/rules/*.md` - `RuleManager` is simply pointed at the wrong path. This is a straightforward path-misalignment defect, not a workspace-emptiness non-issue as this ADR originally framed it (research).
- `include_builtin=True` is never passed at either call site, and survives the schema correction as a distinct, still-live finding: once the path is fixed and `discover()` finds the real flat corpus, the four `.builtin.md` files (core mandates, discovery sequence, CLI reference, rag syntax) remain excluded by design, while every OTHER role's persona-guidance file is included indiscriminately (research).
- `RuleManager.discover()` has no role-targeting - any populated non-builtin rule file is concatenated into EVERY worker's context regardless of role, a token-inflation and cross-role-noise risk ADR-028 itself already flagged (research, considerations).
- Templates (`.vaultspec/templates/*.md`, carrying the LINK RULES/FRONTMATTER RULES conventions this session itself has been bitten by) are a separate mechanism `RuleManager` never touches, regardless of the path fix; an agent gets this guidance only if its own prompt tells it to read the template file AND it has `filesystem_read` (research).
- Persona-prompt CLI-invocation gap is now PARTIALLY resolved, verified by content: the parallel session's `9c2e9dc`/`b1d9892` reframed the synthesist and adr-author personas away from the scaffold-then-propose CLI path (vestigial, per ADR PW3's graph-submitter architecture) to emitting the document as message body - the scaffold/propose half of the original finding is closed. The RAG-SEARCH half is smaller than this ADR originally stated (correction follows the `P01` probe, `416b7f0`): `9c2e9dc` ALSO excised the adr-author's entire `Amend-or-supersede check (mandatory before authoring)` section, including its `vaultspec-rag search` invocation, so the adr-author amend-check is closed too. The researcher's discovery sequence (`vaultspec-researcher.toml` lines 29-36, with `terminal = false`) is the SOLE remaining open rag-search item. It stays gated on the accepted `agent-harness-provisioning-adr`'s `Opens` item - per-role MCP composition of rag for researchers (that ADR lines 62, 71) - a tracked dependency, not a committed decision (research).
- The engine already scaffolds and validates frontmatter/filenames/templates server-side at propose/apply time (`a2a-edge-conformance-reference`, pre-existing decision, not revisited here) - the gap this ADR addresses is concentrated in body-prose conventions the engine's shallow in-process validation does not reach (research, citing the already-committed `document-authoring-orchestration-audit`).
- **Companion-ADR scope (2026-07-15):** this ADR is the narrower companion to the parallel session's accepted `agent-harness-provisioning-adr` (the system-wide harness contract across all agent types). This ADR owns exactly two findings that one does not: the `_RULES_SUBDIR` path-misalignment defect and the `include_builtin=False` exclusion at `worker.py:60`/`supervisor.py:310`, both specific to the research_adr topology's `RuleManager` call sites. An amendment carrying these two findings, cited by file:line, is authored against the accepted `agent-harness-provisioning-adr` so the system-wide contract inherits them; this ADR is not folded into that one.

## Constraints

- Per the owner's standing no-legacy-compat directive: the `_RULES_SUBDIR` fix aligns to the CURRENT flat vaultspec-core schema; it must not add a fallback or dual-read path that also checks the old nested location for backward compatibility. No evidence was found that the nested layout was ever the shipped structure - this is corrected forward, not deprecated gracefully.
- Any propagation-scope change (e.g. `include_builtin=True`, role-targeted rule sets) must weigh the token-inflation and cross-role-noise risk ADR-028 already named - this is not a cost-free toggle.
- This ADR does not revisit the engine-side scaffolding/validation boundary (frontmatter, filenames, templates) - that is settled prior architecture (`a2a-edge-conformance-reference`) and out of scope here.
- Per team-lead's directive, this ADR must NOT block `executor-opus-7`'s PW7 acceptance-harness build: the harness's deterministic (Option A) lane uses fixed, pre-written document content unaffected by this gap, and the harness's own assertions are wire-level (materialization, gate mechanics), not content-quality.
- The rag-search invocation gap is NOT decided by this ADR or by `agent-harness-provisioning-adr` (an acknowledged `Opens` item there) - this ADR's plan tracks it as an open dependency, not a resolved design.

## Considered options

- **Assume the gap doesn't exist because RuleManager is wired.** Rejected: contradicted directly by the `_RULES_SUBDIR` path-misalignment defect and the `include_builtin=False` default - the wiring being correct does not mean the read path or the payload scope is correct.
- **Fix by populating a rule corpus with `include_builtin=True` everywhere, unconditionally.** Rejected as the sole fix: would dump the full builtin corpus (CLI reference, rag syntax, discovery sequence, EVERY persona's guidance) into every single graph turn with no role-targeting, reproducing ADR-028's own flagged token-inflation risk at maximum severity.
- **Fix only the persona prompts (strip the impossible CLI instructions).** Partially already done by the parallel session for the scaffold/propose half; rejected as the SOLE fix for the rag-search half, since removing the instruction without replacing rag-search capability trades one gap for another.
- **Combined, scoped fix (chosen, elaborated at plan time): correct the path-misalignment defect, then design a role-scoped rule-propagation shape, then reconcile any remaining persona-prompt gaps.** Fix `_RULES_SUBDIR` to the current flat schema first (a real code bug, not a design choice); then scope which conventions each of the four personas needs without the full builtin corpus or cross-role noise; then verify the persona-prompt reconciliation already landed for the scaffold half and track the rag-search half as an open dependency on `agent-harness-provisioning-adr`'s MCP composition work.

## Implementation

High-level, elaborated by a future plan once this ADR is ratified:

- Fix the `_RULES_SUBDIR` path-misalignment defect first - a small, mechanical code change, not a design decision.
- Design a role-scoped rule-propagation shape (not blanket `include_builtin=True`) that gets each of the four personas the taxonomy/frontmatter/wiki-link/template conventions they need without the full builtin corpus or cross-role noise.
- Verify the persona-prompt reconciliation already landed (scaffold/propose half) and reconcile any remaining instruction text against the corrected path/scope.
- Prove the fix live against a real provisioned run workspace, not just the static repo.

## Rationale

The grounding research found a genuinely more precise and more actionable gap than either the symptom's original framing or this ADR's own first pass suggested: the rule-PROPAGATION plumbing already exists and works, but reads from a path that was never the current schema's shipped location - a mechanical defect, not an empty-corpus non-issue. Separately, `include_builtin=False` scopes out exactly the mechanical guidance the symptom points at, and the persona-prompt CLI-invocation gap is now half-closed by independent, verified work from the parallel session. Treating this as "nothing to propagate" (this ADR's own original misreading) would have exported that misreading into the broader `agent-harness-provisioning-adr` via a premature amendment - caught and corrected before that happened.

## Consequences

- Positive: closing this gap raises document CONTENT conformance (taxonomy, linking, structure) independent of the engine's wire-level acceptance; the existing `RuleManager` plumbing is reused via a targeted path fix, not replaced.
- Negative / open: the rag-search invocation gap is unresolved here and depends on `agent-harness-provisioning-adr`'s own open MCP-composition item; any propagation-scope expansion carries a real token-inflation cost that must be measured, not assumed away.
- Future: this ADR's role-scoped propagation shape is the natural extension point if a fifth document-authoring persona is added later; the amendment to `agent-harness-provisioning-adr` keeps the system-wide contract current with these two findings without duplicating tracking.

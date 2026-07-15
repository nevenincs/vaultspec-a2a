---
tags:
  - '#adr'
  - '#graph-agent-framework-harness'
date: '2026-07-15'
modified: '2026-07-15'
related:
  - "[[2026-07-15-graph-agent-framework-harness-research]]"
  - "[[2026-03-31-universal-rule-propagation-adr]]"
  - "[[2026-07-14-adr-authoring-orchestration-adr]]"
  - "[[2026-07-15-multi-provider-execution-adr]]"
---

# `graph-agent-framework-harness` adr: `closing the framework-harness gap for graph-executed document-authoring agents` | (**status:** `accepted`)

## Problem Statement

Graph-executed research_adr agents (researcher, synthesist, adr-author, doc-reviewer) do not reliably receive the vaultspec framework harness — the builtin mandate/discovery/CLI rules, and working invocation paths for the tools their own prompts instruct them to use — that a human session gets for free. The engine's server-side validation covers wire-shape and frontmatter mechanics but not body-prose taxonomy conventions, so the gap manifests as non-conformant document CONTENT even when proposals are accepted. Grounding: `2026-07-15-graph-agent-framework-harness-research`.

## Considerations

- `RuleManager` (ADR-028's mechanism) is fully implemented and wired into both `worker.py:60` and `supervisor.py:310` — the propagation MECHANISM exists and works (research).
- Today, `.vaultspec/rules/rules/*.md` is empty in this repo, so `RuleManager.compile()` returns `None` regardless of wiring — a workspace-state fact, not a code defect, and unverified against the engine's actual per-run workspace (research).
- `include_builtin=True` is never passed at either call site, so even a populated `.vaultspec/rules/rules/` would exclude exactly the files (`vaultspec-system.builtin.md`, `vaultspec-discovery.builtin.md`, `vaultspec-cli.builtin.md`, `vaultspec-rag.builtin.md`) carrying the mechanical "how to work this system" guidance the symptom points at (research).
- `RuleManager.discover()` has no role-targeting — any populated non-builtin rule file is concatenated into EVERY worker's context regardless of role, a token-inflation and cross-role-noise risk ADR-028 itself already flagged (research, considerations).
- Templates (`.vaultspec/templates/*.md`, carrying the LINK RULES/FRONTMATTER RULES conventions this session itself has been bitten by) are a separate mechanism `RuleManager` never touches; an agent gets this guidance only if its own prompt tells it to read the template file AND it has `filesystem_read` (research).
- All four research_adr document personas declare `terminal=false`, yet at least three of their own prompts instruct `vaultspec-core`/`vaultspec-rag` CLI invocations (`adr-author`'s mandatory amend-vs-supersede rag search; `synthesist`'s and `adr-author`'s document-scaffold CLI calls; `researcher`'s discovery rag calls) — structurally impossible given `terminal=false` and the already-documented S20 MCP non-surfacing limitation (research). This is the sharpest, most concrete finding: prompts instruct actions the runtime cannot perform.
- The engine already scaffolds and validates frontmatter/filenames/templates server-side at propose/apply time (`a2a-edge-conformance-reference`, pre-existing decision, not revisited here) — the gap this ADR addresses is concentrated in body-prose conventions the engine's shallow in-process validation does not reach (research, citing the already-committed `document-authoring-orchestration-audit`).
- No dedicated vault artifact from the parallel session documenting this exact finding was found; this ADR and its grounding research are net-new, built from direct code verification, not a retrieved prior analysis (research, discovery-provenance note).
- **Ratification note (2026-07-15):** the parallel session's `agent-harness-provisioning` ADR (accepted, broader system-wide harness contract across all agent types) was found complementary, not competing, to this ADR: it does not name the `include_builtin=False` exclusion or the persona-prompt CLI-invocation impossibility this ADR surfaces. The owner ratified this ADR as its own accepted decision, not folded into the other; the two remain related, cross-linked companions. This ADR's implementation plan proceeds after the PW7 harness build (not prioritized ahead of it, per owner/team-lead sequencing).

## Constraints

- Whether `.vaultspec/rules/rules/` is populated in the engine's actual provisioned run workspace (as opposed to this static repo) is unverified — any fix must be proven against a live run, not assumed from the repo's current empty state.
- The two candidate readings of the persona-prompt CLI instructions (vestigial vs. aspirationally-correct-but-unimplemented) are NOT distinguished by the grounding research; this ADR's decision must not assume one reading without owner/prior-session input, since the correct fix differs (strip the instructions vs. build the missing invocation path). **The implementation plan must resolve this with evidence (a small probe), not assumption.**
- Any propagation-scope change (e.g. `include_builtin=True`, role-targeted rule sets) must weigh the token-inflation and cross-role-noise risk ADR-028 already named — this is not a cost-free toggle.
- This ADR does not revisit the engine-side scaffolding/validation boundary (frontmatter, filenames, templates) — that is settled prior architecture (`a2a-edge-conformance-reference`) and out of scope here.
- Per team-lead's directive, this ADR must NOT block `executor-opus-7`'s PW7 acceptance-harness build: the harness's deterministic (Option A) lane uses fixed, pre-written document content unaffected by this gap, and the harness's own assertions are wire-level (materialization, gate mechanics), not content-quality. The harness's Option C (real-provider) content-quality claims are QUALIFIED by this ADR until the framework harness actually reaches graph-executed agents — a live Option C run proves the WIRE contract, not document conformance to vaultspec conventions, until this gap closes.

## Considered options

- **Assume the gap doesn't exist because RuleManager is wired.** Rejected: contradicted directly by the empty `.vaultspec/rules/rules/` directory and the `include_builtin=False` default — the wiring being correct does not mean the payload is complete.
- **Fix by populating `.vaultspec/rules/rules/` with `include_builtin=True` everywhere, unconditionally.** Rejected as the sole fix: would dump the full builtin corpus (CLI reference, rag syntax, discovery sequence, EVERY persona's guidance) into every single graph turn with no role-targeting, reproducing ADR-028's own flagged token-inflation risk at maximum severity, and does nothing about the persona-prompt CLI-invocation gap (a rules-text fix cannot make `terminal=false` execute a command).
- **Fix only the persona prompts (strip the impossible CLI instructions).** Rejected as the sole fix: removes the confusing instruction but does not replace it with the taxonomy/conformance guidance the agent still needs — trades one gap for another.
- **Combined, scoped fix (chosen, elaborated at plan time): role-targeted builtin propagation plus persona-prompt reconciliation.** Populate `.vaultspec/rules/rules/` (or an equivalent per-role subset) with the mechanical conventions a document-authoring agent needs (tag taxonomy, wiki-link/frontmatter rules, the template-read instruction already partially present), scoped by role rather than blanket `include_builtin=True`; and reconcile each of the four personas' prompts against what they can ACTUALLY invoke — either building the missing tool-invocation path (if reading (b) from Considerations is confirmed correct) or rewriting the prompt to describe the real graph-driven propose/submit flow (if reading (a) is confirmed). This ADR does not resolve which reading is correct; the plan's first step must.

## Implementation

High-level, elaborated by a future plan once this ADR is ratified:

- Resolve the vestigial-vs-aspirational question first (Constraints) — likely requires reading the actual `DocumentProposalSubmitter`/phase-gate call sequence against each persona's instructed actions, and/or owner input on original intent.
- Design a role-scoped rule-propagation shape (not blanket `include_builtin=True`) that gets each of the four personas the taxonomy/frontmatter/wiki-link/template conventions they need without the full builtin corpus or cross-role noise.
- Reconcile the four persona TOMLs' system prompts against the resolved reading above.
- Prove the fix live against a real provisioned run workspace, not just the static repo, per the Constraints caveat.

## Rationale

The grounding research found a genuinely more precise and more actionable gap than the symptom's framing suggested: the rule-PROPAGATION plumbing already exists and works, but (a) has nothing to propagate today, (b) is scoped to exclude exactly the mechanical guidance the symptom points at, and (c) coexists with persona prompts that instruct actions the runtime cannot perform at all. Treating this as "agents get nothing" would miss that real infrastructure already exists to build on; treating it as "just turn on include_builtin" would miss the token-inflation risk and the deeper prompt/capability mismatch. The combined, scoped fix targets the actual verified gaps rather than the symptom's surface framing.

## Consequences

- Positive: closing this gap raises document CONTENT conformance (taxonomy, linking, structure) independent of the engine's wire-level acceptance, closing the actual quality gap the owner named; the existing `RuleManager` plumbing is reused, not replaced.
- Negative / open: the vestigial-vs-aspirational persona-prompt question is unresolved here and gates the plan's first step; any propagation-scope expansion carries a real token-inflation cost that must be measured, not assumed away.
- Future: this ADR's role-scoped propagation shape is the natural extension point if a fifth document-authoring persona (e.g. plan-authoring, curation, per the adr-authoring-orchestration ADR's own reuse framing) is added later.

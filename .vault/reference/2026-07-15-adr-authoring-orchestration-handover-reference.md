---
tags:
  - '#reference'
  - '#adr-authoring-orchestration'
date: '2026-07-15'
modified: '2026-07-15'
related:
  - "[[2026-07-14-adr-authoring-orchestration-adr]]"
  - "[[2026-07-14-adr-authoring-orchestration-plan]]"
---

# `adr-authoring-orchestration` reference: `dashboard handover requirements and verified reality for production wiring`

The dashboard team's handover prompt
(`Y:/code/vaultspec-dashboard-worktrees/main/tmp/tmp.md`, read in full
2026-07-15) is the requirements source for completing the production
`research_adr` runtime. This reference carries (a) the requirements
condensed, (b) the claims-vs-reality survey result - the prompt's "current
reality" section is substantially stale, and its distrust of the S06 record
is unfounded on current state - and (c) the verified gap list that scopes
the production-wiring plan extension. Discovery for this survey was rag-led
with grep used only for exact-symbol confirmation, per the owner's standing
directive; executors must work the same way.

## Summary

### Handover requirements, condensed

The 13-step workflow: ground feature/workspace context; dispatch configured
research branches via LangGraph Send; accumulate structured findings;
synthesize the research document; internal document-review revision loop;
create, populate, validate, and submit the research proposal through the
Rust authoring API; park at the research human-governance gate; resume from
the authoritative Rust-backend verdict; on approval author the ADR from the
approved research; ADR review loop; ADR proposal through the API; park at
the ADR gate; resume and finish only when approved.

Implementation requirements: production `DocumentProposalSubmitter` backed
by `AuthoringSession`; submitter and any `AuthoringToolBinding` constructed
and injected through the production worker lifecycle; LangGraph state
carries ONLY Rust-backend identifiers (authoring session id, changeset ids,
proposal ids); everything before `interrupt()` deterministic and
idempotent; verdicts resolved from the Rust backend only - no second
approval authority in A2A; rejected/request-changes verdicts route as
revision with reviewer notes; fail closed with typed actionable errors when
the engine endpoint, actor identity, proposal submitter, role configuration,
or credentials are unavailable; never log, checkpoint, or expose tokens;
never write generated content to `.vault/**`; never expose internal
LangGraph node names as product status contracts.

Verification requirements (adopted verbatim as the plan's Verification): no
completion claims from a stub submitter or graph-shape-only test;
real-behavior evidence that the bundled preset loads, the production graph
compiles with all roles, research content becomes a real engine proposal,
the run parks durably at the research gate, a real engine approval verdict
resumes it, ADR content becomes a second real proposal, restart/recovery
preserves proposal correlation and resumes correctly, replaying a gate
creates no duplicate sessions/changesets/proposals, no `.vault/**` mutation
occurs outside the engine, and missing engine/identity/credentials/wiring
produces a truthful unavailable state. Repository testing rules apply: no
fakes, mocks, stubs, monkeypatching, or skipped tests; live loopback engine.

Documentation integrity: reconcile the S06 record with landed source;
checkboxes only on executable evidence; the five-verb gateway,
model-profile selection, and product discovery are separate issue domains.

### Verified reality (scout survey, 2026-07-15): the prompt is stale, the corpus is honest

DONE AND REAL - do not re-scope:

- The `vaultspec-adr-research` preset: `type = research_adr`, four roles
  (researcher, synthesist, adr-author, doc-reviewer), structural not
  order-driven.
- `phase_gate.py` committed with the `DocumentProposalSubmitter` Protocol
  (`graph/nodes/phase_gate.py:53-65`; async call taking state and phase,
  returning the proposal id).
- `TopologyType.RESEARCH_ADR` and typed `ResearchThreadSpec`
  (`team/team_config.py:76,231,262`).
- The full compiler branch `_compile_research_adr`
  (`graph/compiler.py:396-409,1007-1161`): diverge -> synthesis ->
  doc-review loop -> research gate -> adr-author -> review loop -> adr
  gate -> END, fail-closed when the submitter or a role is missing.
- The verdict subscriber is real AND RUNNING in the production gateway
  lifespan (`api/app.py:257-287`): consumes `/v1/events` from a persisted
  cursor, correlates via `authoring_proposal_ids` in TeamState, resumes
  parked threads via Command resume, gap-frame fallback - live-tested.
- The S06 execution record is HONEST: it scopes itself to the structural
  spine proven with stub models and explicitly defers the live proof to
  P04.S10. The handover prompt's distrust of it is unfounded on current
  state; the earlier fork-point confusion (preset committed before the
  enum) explains the stale impression.

REAL GAPS - the entire production-wiring scope:

- No production `DocumentProposalSubmitter`: the Protocol has no concrete
  implementation; the production class wraps `AuthoringSession` and
  conforms to the Protocol signature.
- `worker/graph_lifecycle.py:251-263` never passes `proposal_submitter=`,
  so the topology is fail-closed dead code in production (the correct
  posture - it needs the construction site: worker-lifecycle-scoped,
  fed from `RunTokenStore`).
- No `AuthoringToolBinding` production construction site found; context:
  W03 explicitly deferred binding assembly to production wiring - the
  S19 checkbox covers the mechanism, the S20 record covers the deferral;
  reconcile honestly rather than re-claiming.
- The live end-to-end proof is the existing plan's single unchecked box,
  P04.S10.

### Strategic insight: the submitter path is not blocked upstream

Gate proposal submission is GRAPH-CODE-driven - a direct in-process
`AuthoringSession` call with no LLM tool invocation - so the upstream CLI
MCP-surfacing limitation (the S20 deferral) does NOT block it. Completing
the gaps delivers real agent-authored proposals into the dashboard review
lane from a production run through the contract-blessed mechanism
(whole-document proposals under per-role tokens through the authoring
API). The relationship between the two mechanisms and the effect on the
conformance program's S20 gate are decided in the ADR amendment, not here.

### Ledger fences

The graph-domain import cycle and the provider execution-mode axis remain
successor items and do not intersect this scope: production wiring adds
worker-layer construction without graph-package restructuring, and the
preset pins its provider.

Sources: handover prompt (path above); scout claims-vs-reality survey
2026-07-15 (locators inline); `2026-07-14-adr-authoring-orchestration-adr`
(topology decisions); conformance W01-W05 review audits (seam inventory
and evidence standards).

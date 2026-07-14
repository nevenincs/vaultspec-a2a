---
tags:
  - '#research'
  - '#adr-authoring-orchestration'
date: '2026-07-14'
modified: '2026-07-14'
related:
  - "[[2026-07-14-document-authoring-orchestration-audit]]"
  - "[[2026-07-14-orchestration-capabilities-research]]"
  - "[[2026-07-14-a2a-edge-conformance-adr]]"
---

# `adr-authoring-orchestration` research: `the shape of research-to-ADR document authoring as a LangGraph orchestration`

Question: what graph topology, persona set, and gating machinery does "research a problem and produce an ADR" require, given the owner's 2026-07-14 scope directive (agents author vault documents only - audits, research, ADRs, plans; coding and code management out of scope)? Conclusion of the evidence: the workflow is a five-stage phase machine (ground -> diverge -> synthesize -> gate -> decide) with two loop kinds - an inner quality loop (document reviewer + engine validation findings) and an outer human loop (dashboard review-lane verdicts re-entering a parked run). None of the three existing topologies expresses the diverge stage's fan-out; the replay-safe interrupt-node pattern just landed in the codebase generalizes into the per-phase gate; the engine side of the outer loop is already built and only the a2a-side subscriber is missing. Full grounding for the current-state claims lives in `2026-07-14-document-authoring-orchestration-audit` (personas, topologies, mandate enforcement, engine verification) and is not restated here.

## Findings

### The workflow decomposes into five stages with distinct tool profiles

Derived from the vaultspec research/ADR skill mandates (`.claude/skills/vaultspec-research/SKILL.md`, `.claude/skills/vaultspec-adr/SKILL.md`): Ground (recall prior decisions, read whole, decide amend-vs-supersede posture - deterministic and cheap), Diverge (parallel research threads with heterogeneous toolsets: codebase read/search vs web prior-art), Synthesize (writer produces the Research document against the skill's quality bar: answer-first, locator-anchored, comparative, bounded), Gate (proposal submit + human verdict), Decide (ADR author consumes approved research, cite-by-stem, same review loop and gate). Tool policy falls out per stage: researchers read+search+web only; writers add propose/validate; no persona ever gets request_apply - the human applies via the review lane.

### Fan-out is the one shape the current topologies cannot express

star routes one worker per superstep, pipeline is a fixed chain, pipeline_loop has a single compile-time loop target (`src/vaultspec_a2a/graph/compiler.py:402-813`). The Diverge stage needs N parallel researcher invocations converging on a synthesis node. LangGraph's Send API (https://docs.langchain.com/oss/python/langgraph/graph-api, map-reduce/Send section) is the framework-native primitive; zero uses exist in `src/` today. Accumulation needs a findings state field with an append reducer, matching the existing reducer idiom in `src/vaultspec_a2a/thread/state.py:82-103`.

### The replay-safe gate node is the generalizable human-checkpoint primitive

LangGraph re-runs a resumed node from its start (https://docs.langchain.com/oss/python/langgraph/interrupts, "the node restarts from the beginning... any code before the interrupt runs again"), so gate nodes must be deterministic before their `interrupt()`. Commit `f5f650d` established the pattern (`create_plan_approval_node`, `src/vaultspec_a2a/graph/nodes/supervisor.py`). For document phases the pre-interrupt side effect is propose+submit through the authoring client, which is replay-safe by construction: the client derives idempotency keys from stable run-local material (`src/vaultspec_a2a/authoring/`, W03.P06), so a replayed submit is a no-op replay per the engine's idempotency reservation.

### The outer human loop exists engine-side; only the a2a subscriber is missing

Verified against engine source (recorded in the linked audit's verification subsection): review verdicts land at `POST /v1/reviews/{approval_id}/decisions` over a 15-state changeset lifecycle, and externally observable, authoritative lifecycle events stream from `GET /authoring/v1/events` (durable-outbox SSE with cursor replay and gap signaling) with `GET /authoring/v1/recovery` as the polling fallback. The missing piece is an a2a-side subscriber mapping Approved/Rejected/RequestChanges lifecycle events for a parked run's proposal ids to `Command(resume=verdict)` on the checkpointed thread. `TeamState` already carries `authoring_proposal_ids`/`authoring_changeset_ids` (`src/vaultspec_a2a/thread/state.py:166-168`) as the correlation keys.

### The inner quality loop has existing state machinery

`validation_errors` with an append/clear reducer already exists (`src/vaultspec_a2a/thread/state.py:147`) and the supervisor FINISH-block consumes it. The engine returns structured, code-addressable `ValidationFinding`s (typed codes incl. MissingFrontmatter/InvalidFrontmatter/StaleBaseRevision) at the proposal snapshot endpoint (audit verification subsection). Wiring findings into `validation_errors` gives the writer persona a concrete revise signal; a document-reviewer persona enforces the prose quality bar the engine cannot (locators re-fetchable, claims flagged, options compared).

### Persona set: two of the needed five exist; the coding personas are retired by scope

Per the linked audit: analyst (research) and planner exist as document-oriented runtime personas; coder and code-reviewer are coding-scoped and out of mission per the owner's 2026-07-14 directive. Needed set: researcher (multi-instance, read+web), synthesist (research-doc writer), adr-author, doc-reviewer (quality gate). The planner sentinel pattern (machine-checkable completion marker, `team/presets/agents/vaultspec-planner.toml:99`) generalizes to all writer personas.

### Curation is the map-reduce sibling on the same machinery

The second intent family (reconcile vault documents against drift, tighten language) is: enumerate corpus -> parallel per-document/per-cluster checks -> propose amendments -> same review lane. It reuses the fan-out primitive, the gate node, and the subscriber wholesale, with no divergent synthesis - the natural burn-in workload after the research->ADR shape lands. Not designed further here.

### Residual code defects independent of the new shape

Carried from the graph audit (this session, partially fixed in `f5f650d`): the ADR-021-rejected drain side-channel still live in `src/vaultspec_a2a/graph/nodes/worker.py:318-327` (post-f5f650d offsets: `worker.py:353-404`), and `vault_index` populated once at compile time (`compiler.py:218-234`) and never refreshed, which starves phase gating and mounting of newly produced documents mid-run. Both must be fixed for the phase machine to see its own outputs.

Not investigated: multi-run concurrency on one feature's documents (engine conflict/rebase surfaces exist but the graph-side handling is undesigned); plan-Step canonical-ID allocation across the edge (open gap RS-1(a) in the linked audit); curation-specific personas.

## Sources

- https://docs.langchain.com/oss/python/langgraph/interrupts
- https://docs.langchain.com/oss/python/langgraph/graph-api
- https://docs.langchain.com/oss/python/langgraph/fault-tolerance
- `src/vaultspec_a2a/graph/compiler.py:218-234, 402-813`
- `src/vaultspec_a2a/graph/nodes/supervisor.py` (commit `f5f650d`)
- `src/vaultspec_a2a/graph/nodes/worker.py:353-404`
- `src/vaultspec_a2a/thread/state.py:82-103, 147, 166-168`
- `src/vaultspec_a2a/team/presets/agents/vaultspec-planner.toml:99`
- `.claude/skills/vaultspec-research/SKILL.md`, `.claude/skills/vaultspec-adr/SKILL.md`
- Engine-side verification locators recorded in `2026-07-14-document-authoring-orchestration-audit` (verification subsection)

---
tags:
  - '#exec'
  - '#adr-authoring-orchestration'
date: '2026-07-14'
modified: '2026-07-14'
step_id: 'S04'
related:
  - "[[2026-07-14-adr-authoring-orchestration-plan]]"
---

# Build the Send-based diverge stage: dispatch node emitting one Send per research thread, researcher workers appending findings, join into synthesis

## Scope

- `src/vaultspec_a2a/graph/nodes/`
- `src/vaultspec_a2a/graph/compiler.py`

## Description

- Added a diverge node module holding the reusable fan-out primitives:
  `create_research_dispatch_node`, `create_researcher_node`, the
  `researcher_node_name` deterministic namer, and a `ResearchFindingProducer`
  Protocol seam.
- Implemented the dispatch node with LangGraph `Send`: it returns
  `Command(goto=[Send(researcher, state), ...])`, launching one parallel branch
  per research thread and carrying no static outgoing edges.
- Implemented the researcher branch node to close over its thread spec, run the
  injected producer, and append the single resulting finding through the
  `research_findings` reducer, so branches never touch the message channel and
  the fan-out does not duplicate messages.
- Added the `_wire_diverge_stage` compiler helper: it adds the dispatch node,
  one researcher node per spec, and a static edge from every researcher into the
  synthesis node to form the join, returning the dispatch name for the caller to
  edge into.
- Exported the diverge factories from the nodes package facade.
- Added real-graph tests over a StateGraph with an InMemorySaver: dispatch emits
  one Send per researcher, a researcher appends exactly one finding, the full
  stage accumulates every branch's finding and the synthesis join observes the
  complete set, empty specs are rejected, and the namer is deterministic.

## Outcome

- The diverge stage the research_adr topology needs is in place as reusable,
  tested primitives: N parallel researcher branches converging on a synthesis
  join, with findings accumulated through the append reducer added in the prior
  Step.
- Full graph suite passes (95 tests, five new); `ruff check`, `ruff format`, and
  `ty check` are clean on the changed modules.

## Notes

- Model wiring is intentionally deferred: the branch node takes a
  `ResearchFindingProducer` rather than a model, so this Step lands the fan-out
  and join structure while the research_adr topology supplies the model-backed
  producers and the synthesis node with its inner review loop.
- The dispatch node passes the full current state as each `Send` payload so every
  branch sees the shared conversation and feature context; branches return only
  their finding, so the message channel is not duplicated across the fan-out.

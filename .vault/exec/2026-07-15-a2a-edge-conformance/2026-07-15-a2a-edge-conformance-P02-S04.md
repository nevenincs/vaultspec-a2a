---
tags:
  - '#exec'
  - '#a2a-edge-conformance'
date: '2026-07-15'
modified: '2026-07-15'
step_id: 'S04'
related:
  - "[[2026-07-15-a2a-edge-conformance-plan]]"
---

# Project semantic authoring phases (starting, researching, synthesizing_research, reviewing_research, awaiting_research_decision, writing_adr, reviewing_adr, awaiting_adr_decision, completed, failed, cancelled, recovery_required) from research_adr topology position and gate state into run-status, plus target feature and authoring session id fields

## Scope

- `src/vaultspec_a2a/control/thread_state_service.py`
- `src/vaultspec_a2a/api/routes/gateway.py`
- `src/vaultspec_a2a/api/schemas/gateway.py`

## Description

- Added a pure project_semantic_phase to the thread-state service that maps a
  run's terminal and recovery states first, then its research_adr checkpoint
  node position, into the product-safe authoring-phase vocabulary, so the Rust
  backend never interprets LangGraph node names.
- Mapped the research_adr structural nodes to phases: the dispatch and
  researcher fan-out nodes to researching, synthesis to synthesizing_research,
  research_review to reviewing_research, research_gate to
  awaiting_research_decision, adr_author to writing_adr, adr_review to
  reviewing_adr, and adr_gate to awaiting_adr_decision, stripping the mount
  prefix and skipping end/empty nodes.
- Gave non-research_adr runs an honest generic running phase (or starting before
  dispatch) rather than fabricated authoring precision, and mapped terminal
  statuses to completed/failed/cancelled and deliberate recovery states to
  recovery_required.
- Excluded a transient checkpoint-unavailable posture from recovery_required: a
  freshly dispatched run with no checkpoint yet is normal startup, not recovery;
  genuine checkpoint loss transitions the thread to a recovery status.
- Added a non-raising SemanticContext reader that pulls the run's target feature
  and produced authoring session id from the checkpoint channel values, mirroring
  the existing authoring-ids reader.
- Added semantic_phase, feature_tag, and authoring_session_id to the run-status
  response and wired the projection and reader into the run-status endpoint.
- Added parametrized unit tests covering every phase in the vocabulary plus the
  transient-checkpoint and generic-running cases, and extended the live
  five-verbs run-status assertion to the projected phase and new fields.

## Outcome

- run-status now serves a product-safe semantic authoring phase plus the target
  feature and authoring session id, so the Rust backend reads authoring progress
  without decoding node names.
- Scoped suites green: api and control (278); `ruff check`, `ruff format`, and
  `ty check` clean on the changed modules.

## Notes

- The projection is node-position driven from the checkpoint's next nodes, which
  captures the awaiting-decision phases naturally (a run parked at a gate node is
  positioned there); the gate_phase/gate_verdict state added in the orchestration
  plan is available for later refinement but is not required for the phase.
- A full research_adr phase-transition sweep with live models is the evidence
  battery's job (P03.S06); this Step proves the projection logic exhaustively by
  unit test and the wiring end to end on a real run.

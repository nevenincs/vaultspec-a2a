---
tags:
  - '#exec'
  - '#adr-authoring-orchestration'
date: '2026-07-14'
modified: '2026-07-14'
step_id: 'S05'
related:
  - "[[2026-07-14-adr-authoring-orchestration-plan]]"
---

# Generalize the plan_approval pattern into a phase-gate node factory with deterministic idempotent propose-and-submit before interrupt

## Scope

- `src/vaultspec_a2a/graph/nodes/`
- `src/vaultspec_a2a/authoring/`

## Description

- Added a phase-gate node module generalizing the plan-approval pattern into
  `create_phase_gate_node`, a factory parameterized by document phase, an
  injected proposal submitter, and the approved/revision routing targets.
- Defined the `DocumentProposalSubmitter` Protocol as the seam for the
  deterministic, idempotent propose-and-submit run before the interrupt; the
  concrete authoring-client wiring is left to the control layer.
- Ran the submit before `interrupt()` on every pass so the pre-interrupt side
  effect is replay-safe: a resumed node re-runs from its start, and the
  submitter is idempotent by contract (same proposal id), so the replayed submit
  is a no-op.
- Emitted the distinct document-gate wire contract - interrupt payload
  `{"type": "document_approval_request", "phase", "proposal_id", "feature"}` and
  resume `{"verdict", "notes"}` - without touching the existing plan-approval
  payload or resume shapes.
- Routed via `Command.goto`: `approved` advances to the approved target and
  records `gate_phase` / `gate_verdict` plus the proposal id; `rejected` and
  `request_changes` route to the phase writer with the reviewer note appended to
  `validation_errors`, and any unrecognised verdict fails closed to revision
  rather than silently advancing.
- Exported the gate factory and the submitter Protocol from the nodes facade.
- Added real-graph tests over an InMemorySaver covering the interrupt payload,
  approved advance, rejected and request_changes routing with notes, the
  fail-closed unknown verdict, and idempotent resubmission on resume.

## Outcome

- The reusable per-phase human gate the research_adr topology needs is in place:
  it proposes and submits deterministically, parks on the human verdict, and
  routes on resume, all replay-safe.
- Full graph suite passes (101 tests, six new); `ruff check`, `ruff format`, and
  `ty check` are clean on the changed modules.

## Notes

- The submitter seam is defined in the gate module rather than the authoring
  package: the gate declares the interface it needs, the control layer injects
  the concrete client, and this keeps the gate decoupled from the
  concurrently-edited authoring package. The Step therefore touches
  `graph/nodes/` only, not `authoring/`; no authoring source was modified.
- Model-backed submitter wiring and the topology edges (writer loop control,
  phase sequencing) land in P02.S06, which composes this gate into the
  research_adr topology.

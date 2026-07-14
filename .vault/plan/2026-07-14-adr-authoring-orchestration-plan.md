---
tags:
  - '#plan'
  - '#adr-authoring-orchestration'
date: '2026-07-14'
modified: '2026-07-14'
tier: L2
related:
  - '[[2026-07-14-a2a-edge-conformance-plan]]'
  - '[[2026-07-14-adr-authoring-orchestration-adr]]'
  - '[[2026-07-14-adr-authoring-orchestration-research]]'
---

# `adr-authoring-orchestration` plan

### Phase `P01` - Graph prerequisites

Fix the two audited defects the phase machine depends on: mid-run vault_index refresh and the ADR-021 drain-pattern regression.

- [x] `P01.S01` - Refresh vault_index for the active feature on every mount pass so gates and mounts observe newly produced documents mid-run; `src/vaultspec_a2a/graph/nodes/vault_reader.py, src/vaultspec_a2a/graph/compiler.py`.
- [x] `P01.S02` - Replace the ADR-021-rejected drain side-channel in the worker node with Command-returning tool wiring per the ADR's accepted revision; `src/vaultspec_a2a/graph/nodes/worker.py, src/vaultspec_a2a/graph/tools/task_queue.py`.

### Phase `P02` - Phase-machine primitives

Build the reusable orchestration primitives: findings state, Send-based diverge stage, generalized phase-gate node, and the research_adr topology.

- [x] `P02.S03` - Add the research_findings append-reducer field and gate/verdict state fields to TeamState; `src/vaultspec_a2a/thread/state.py`.
- [ ] `P02.S04` - Build the Send-based diverge stage: dispatch node emitting one Send per research thread, researcher workers appending findings, join into synthesis; `src/vaultspec_a2a/graph/nodes/, src/vaultspec_a2a/graph/compiler.py`.
- [ ] `P02.S05` - Generalize the plan_approval pattern into a phase-gate node factory with deterministic idempotent propose-and-submit before interrupt; `src/vaultspec_a2a/graph/nodes/, src/vaultspec_a2a/authoring/`.
- [ ] `P02.S06` - Wire the research_adr topology type through team config and the compiler with structural phase sequencing; `src/vaultspec_a2a/graph/compiler.py, src/vaultspec_a2a/team/team_config.py`.

### Phase `P03` - Verdict subscriber

Consume the engine's authoring lifecycle events and resume parked runs with reviewer verdicts.

- [x] `P03.S07` - Build the engine lifecycle-event subscriber: SSE consumer with persisted cursor, recovery-snapshot fallback, proposal-id correlation, and Command resume dispatch to parked threads; `src/vaultspec_a2a/control/, src/vaultspec_a2a/authoring/, src/vaultspec_a2a/database/`.
- [ ] `P03.S08` - Prove the subscriber live against the loopback engine: approve and reject verdicts resume a parked run correctly across a gateway restart; `src/vaultspec_a2a/service_tests/, src/vaultspec_a2a/control/tests/`.

### Phase `P04` - Document personas and end-to-end proof

Author the document-authoring persona set and team preset, and prove the research-to-ADR shape end to end.

- [x] `P04.S09` - Author the researcher, synthesist, adr-author, and doc-reviewer persona TOMLs and the vaultspec-adr-research team preset on the new topology; `src/vaultspec_a2a/team/presets/agents/, src/vaultspec_a2a/team/presets/teams/`.
- [ ] `P04.S10` - Drive a research-to-ADR run end to end producing research and ADR proposals visible in the dashboard review lane with zero vault writes; `src/vaultspec_a2a/service_tests/`.

## Description

## Steps

## Parallelization

## Verification

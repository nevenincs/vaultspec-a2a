---
generated: true
tags:
  - '#index'
  - '#adr-authoring-orchestration'
date: '2026-07-15'
modified: '2026-07-15'
related:
  - '[[2026-07-14-adr-authoring-orchestration-P01-S01]]'
  - '[[2026-07-14-adr-authoring-orchestration-P01-S02]]'
  - '[[2026-07-14-adr-authoring-orchestration-P01-summary]]'
  - '[[2026-07-14-adr-authoring-orchestration-P02-S03]]'
  - '[[2026-07-14-adr-authoring-orchestration-P02-S04]]'
  - '[[2026-07-14-adr-authoring-orchestration-P02-S05]]'
  - '[[2026-07-14-adr-authoring-orchestration-P02-S06]]'
  - '[[2026-07-14-adr-authoring-orchestration-P02-summary]]'
  - '[[2026-07-14-adr-authoring-orchestration-P03-S07]]'
  - '[[2026-07-14-adr-authoring-orchestration-P03-S08]]'
  - '[[2026-07-14-adr-authoring-orchestration-P03-summary]]'
  - '[[2026-07-14-adr-authoring-orchestration-P04-S09]]'
  - '[[2026-07-14-adr-authoring-orchestration-adr]]'
  - '[[2026-07-14-adr-authoring-orchestration-audit]]'
  - '[[2026-07-14-adr-authoring-orchestration-plan]]'
  - '[[2026-07-14-adr-authoring-orchestration-research]]'
  - '[[2026-07-15-adr-authoring-orchestration-handover-reference]]'
---

# `adr-authoring-orchestration` feature index

Auto-generated index of all documents tagged with `#adr-authoring-orchestration`.

## Documents

### adr

- `2026-07-14-adr-authoring-orchestration-adr` - `adr-authoring-orchestration` adr: `phase-machine topology, document personas, and external-verdict gates for research-to-ADR authoring` | (**status:** `accepted`)

### audit

- `2026-07-14-adr-authoring-orchestration-audit` - `adr-authoring-orchestration` audit: `P01-P04 partial code review`

### exec

- `2026-07-14-adr-authoring-orchestration-P01-S01` - Refresh vault_index for the active feature on every mount pass so gates and mounts observe newly produced documents mid-run
- `2026-07-14-adr-authoring-orchestration-P01-S02` - Replace the ADR-021-rejected drain side-channel in the worker node with Command-returning tool wiring per the ADR's accepted revision
- `2026-07-14-adr-authoring-orchestration-P01-summary` - `adr-authoring-orchestration` `P01` summary
- `2026-07-14-adr-authoring-orchestration-P02-S03` - Add the research_findings append-reducer field and gate/verdict state fields to TeamState
- `2026-07-14-adr-authoring-orchestration-P02-S04` - Build the Send-based diverge stage: dispatch node emitting one Send per research thread, researcher workers appending findings, join into synthesis
- `2026-07-14-adr-authoring-orchestration-P02-S05` - Generalize the plan_approval pattern into a phase-gate node factory with deterministic idempotent propose-and-submit before interrupt
- `2026-07-14-adr-authoring-orchestration-P02-S06` - Wire the research_adr topology type through team config and the compiler with structural phase sequencing
- `2026-07-14-adr-authoring-orchestration-P03-S07` - Build the engine lifecycle-event subscriber: SSE consumer with persisted cursor, recovery-snapshot fallback, proposal-id correlation, and Command resume dispatch to parked threads
- `2026-07-14-adr-authoring-orchestration-P03-S08` - Prove the subscriber live against the loopback engine: approve and reject verdicts resume a parked run correctly across a gateway restart
- `2026-07-14-adr-authoring-orchestration-P03-summary` - `adr-authoring-orchestration` `P03` summary
- `2026-07-14-adr-authoring-orchestration-P04-S09` - Author the researcher, synthesist, adr-author, and doc-reviewer persona TOMLs and the vaultspec-adr-research team preset on the new topology
- `2026-07-14-adr-authoring-orchestration-P02-summary` - `adr-authoring-orchestration` `P02` summary

### plan

- `2026-07-14-adr-authoring-orchestration-plan` - `adr-authoring-orchestration` plan

### reference

- `2026-07-15-adr-authoring-orchestration-handover-reference` - `adr-authoring-orchestration` reference: `dashboard handover requirements and verified reality for production wiring`

### research

- `2026-07-14-adr-authoring-orchestration-research` - `adr-authoring-orchestration` research: `the shape of research-to-ADR document authoring as a LangGraph orchestration`

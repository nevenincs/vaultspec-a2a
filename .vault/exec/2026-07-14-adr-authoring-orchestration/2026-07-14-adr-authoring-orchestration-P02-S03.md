---
tags:
  - '#exec'
  - '#adr-authoring-orchestration'
date: '2026-07-14'
modified: '2026-07-14'
step_id: 'S03'
related:
  - "[[2026-07-14-adr-authoring-orchestration-plan]]"
---

# Add the research_findings append-reducer field and gate/verdict state fields to TeamState

## Scope

- `src/vaultspec_a2a/thread/state.py`

## Description

- Added the `_append_research_findings` append-only reducer: it accumulates the
  per-thread findings the Send-based diverge stage will contribute across
  parallel branches, in arrival order, with no removal and no dedup.
- Added the `research_findings` field to `TeamState`, annotated with that
  reducer. Each item is a `{"claim", "locators", "source_thread"}` dict; the
  field is `NotRequired` because only the research_adr topology populates it.
- Added the `gate_phase` and `gate_verdict` scalar fields to record the most
  recent document phase-gate outcome (the gated phase and the reviewer verdict:
  approved, rejected, or request_changes), mirroring the approval_status /
  approval_request_id pair the plan-approval gate uses; last-write-wins.
- Extended the state schema test to assert the three new annotation keys and
  added reducer unit tests covering ordered append, parallel-branch
  accumulation without dedup, empty-update passthrough, and non-mutation of the
  existing list.

## Outcome

- `TeamState` now carries the findings-accumulation and gate-verdict schema the
  diverge stage (P02.S04) and the phase-gate node (P02.S05) consume.
- All fields are JSON-serializable primitives, preserving the SQLite
  checkpointer constraint the state schema documents.
- `graph/tests`... rather, `thread/tests/test_state.py` passes (22 tests);
  `ruff check`, `ruff format`, and `ty check` are clean on the changed module.

## Notes

- No behavioural wiring lands in this Step: the fields are schema only. The
  reducers and consumers arrive in P02.S04 (diverge) and P02.S05 (phase gate).
- The gate fields are deliberately scalar last-write-wins rather than a
  per-phase map: the research_adr machine gates one phase at a time and the
  topology sequences phases structurally, so a single most-recent-verdict pair
  is sufficient and matches the existing approval-gate shape.

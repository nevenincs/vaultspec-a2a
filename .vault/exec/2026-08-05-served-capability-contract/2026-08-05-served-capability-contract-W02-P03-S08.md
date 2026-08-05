---
tags:
  - '#exec'
  - '#served-capability-contract'
date: '2026-08-05'
modified: '2026-08-05'
body_schema: 'body-v1'
body_hash: 'sha256:2164da092db5c184391184af517aa043f823925acbb0854efdfbe6360f8d1595'
step_id: 'S08'
related:
  - "[[2026-08-05-served-capability-contract-plan]]"
---

# F14 IN FLIGHT with agent contract-audit - correct the module docstring that claims three topology types where four are dispatched

## Scope

- `src/vaultspec_a2a/graph/compiler.py`

## Description

- Correct the graph compiler's module docstring, which claimed three topology
  types where four are dispatched.

## Outcome

Closes in full. The module docstring now states four topology types and names
the research-to-decision chain among them.

INDEPENDENTLY VERIFIED FROM THE TREE by the vault writer rather than taken on
report: the line reads as claimed. This is one of the few Steps in this feature
whose completion is directly checkable from source without a behavioural
narrative, which is why it needed no verification detail from its author.

## Notes

The docstring was the sole stale copy - the function docstring and the dispatch
itself were already correct. That is what made it a documentation defect rather
than a behavioural one, and also what made it invisible: nothing failed, so
nothing pointed at it.

Landed in the same commit as the legacy-route retirement, which is why the
commit subject names only that half.

This record was authored by the vault writer from the implementing agent's
report relayed by the routing lead, not from direct observation of the work.

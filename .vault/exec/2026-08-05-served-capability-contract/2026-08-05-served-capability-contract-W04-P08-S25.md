---
tags:
  - '#exec'
  - '#served-capability-contract'
date: '2026-08-05'
modified: '2026-08-05'
body_schema: 'body-v1'
body_hash: 'sha256:87b6ec50297fd1e02f4fb7eef8aea452954cfcc6b1faaeb5629271ff1eca8351'
step_id: 'S25'
related:
  - "[[2026-08-05-served-capability-contract-plan]]"
---

# F20 - define what reconciling means, how long it may persist and how a run leaves it, then provide the recovery path a stranded run currently lacks

## Scope

- `src/vaultspec_a2a/control/run_discovery_service.py`

## Description

- Give a run abandoned in the reconciling state a defined exit, so it is
  reconciled rather than left occupying the active view indefinitely.

## Outcome

Closes in full. THE LIFECYCLE WAS TRACED BEFORE ANY CODE WAS WRITTEN: the state
is entered by the reconciliation computation, its obliged writer is a ONE-SHOT
STARTUP SWEEP, and three swallowed-continue paths were identified as the gap.
The transition to failed was ALREADY VALID in the state machine, so the state
machine was not touched - the missing piece was a writer obliged to use it, not
a missing transition.

T3 COMPLIANCE IS EXACT. The abandonment bound is derived from the preset's OWN
step timeout plus a margin, with a floor - the same shape as the ingest-stall
fix, generalising it exactly as the governing clause instructs rather than
inventing a second flat global.

It is wired into BOTH read seams and fires opportunistically on whichever read
reaches the thread next. No background task and no new process, which is what
"independent of the dead writer's liveness" means concretely rather than
aspirationally.

Proven a FIX by stashing the two source files: the active-run listing still
contained the abandoned run, and its status still read reconciling rather than
failed. Both failed pre-fix.

TWO GUARDS, AND ONE IS THE IMPORTANT ONE: a larger preset budget surviving a
silence that a flat floor would have killed. That is the literal
T3-generalisation proof - it demonstrates the bound is genuinely derived rather
than merely larger, which a single higher constant would also have satisfied.
113 tests across consumers pass unchanged.

## Notes

Two honest limitations are recorded as findings in this feature's audit rather
than left in a report. The bound is a BORROWED PROXY: no preset declares a
reconciliation budget, so a per-step quantity stands in for a per-run one, and a
bound borrowed from a different question is correct only by coincidence.

And the reconciler is CHECKPOINT-OBLIVIOUS, resolving on elapsed time and status
alone without checking whether the graph already reached its end. That makes it
the audit's ONLY potential false RED - every other truthfulness defect recorded
in this feature is a false green. The direction is the safer one and the
reasoning is sound, but it is still a field that can assert something untrue.

This record was authored by the vault writer from the implementing agent's
report relayed by the routing lead, not from direct observation of the work.

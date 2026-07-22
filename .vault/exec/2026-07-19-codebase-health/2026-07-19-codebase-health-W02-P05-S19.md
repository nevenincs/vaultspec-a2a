---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S19'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Unify launch discovery and acceptance on one profile eligibility decision

## Scope

- `src/vaultspec_a2a/providers/model_profiles.py, src/vaultspec_a2a/api/routes/gateway.py, src/vaultspec_a2a/authoring/discovery.py`

## Description

- Enumerate every caller of the profile eligibility decision.
- Compare the arguments each passes, and establish whether the differences are
  divergence or deliberate.
- Read the defaults to determine what an omitted argument means.
- Change nothing if one decision already governs both paths.

## Outcome

Already satisfied; no change was made. One function composes profile eligibility and both
the launch path and the discovery listing call it. There is no second implementation and no
inlined variant.

The two call sites pass different arguments, and reading the defaults shows that is design
rather than drift. An omitted readiness mapping means probe internally rather than skip, so
launch does evaluate provider readiness - it simply does not reuse discovery's per-preset
cache. An omitted harness verdict means the harness term is not composed, which is correct
for a non-authoring caller.

The remaining asymmetry is deliberate and documented at the launch site: the acceptance gate
and engine reachability are discovery-certification signals rather than launch blockers, and
enforcing them at launch would refuse every run. Launch therefore passes both as satisfied
on purpose.

Harness provisioning is enforced at launch, through the separate run-start eligibility
decision rather than through profile eligibility. Those two decisions answer different
questions - whether this request can start a run, and whether this profile is runnable - and
neither duplicates the other.

## Notes

Closing without a diff needs the evidence rather than the assertion, so the verification is
recorded: two call sites, one function, no third implementation, and the argument
differences explained by the defaults rather than by divergence.

The plan was authored against an earlier tree and this consolidation appears to have landed
between authoring and execution. That is the ordinary case for a plan of this size, and
reporting a Step already satisfied is more useful than restructuring working code to justify
the row - which would have been the outcome of trusting the Step's wording over the code.

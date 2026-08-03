---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-03'
modified: '2026-08-03'
body_schema: 'body-v1'
body_hash: 'sha256:89203623629164adaacd24af4d4386538adf4b8886d0f9f39c0d2789114c16ed'
step_id: 'S49'
related:
  - "[[2026-08-02-provider-error-taxonomy-plan]]"
---
# Forward the condition on the a2a ops route

## Scope

- `engine/crates/vaultspec-api/src/routes/ops/a2a.rs`

## Description

- Establish whether the pass-through already carries the field, and prove it
  rather than assume it.
- Hold the edge to forwarding a failed run's classification unaltered.

## Outcome

Landed with NO production behaviour change, and the absence of a change is the
result rather than a shortfall. The run-status verb is a byte-verbatim
pass-through, so the field already reached the client the moment the emitting
side served it.

A membership gate was deliberately NOT added at this edge, and the reasoning is
now recorded at the verb. The vocabulary is additive, so gating here would blank
a whole run's status the day a member is added - costing the client the run
rather than one field. The strict boundary belongs at the write path, where a bad
value would otherwise be persisted; a read-through has nothing to protect.

The proof is a real loopback handler test that serves both a known member and one
the store itself would refuse, asserting the whole envelope arrives unaltered. It
fails if anyone reshapes or gates the pass-through later, which is the only thing
that could quietly break a route that currently works by doing nothing.

## Notes

Independently exercised beyond the test: a dashboard engine was pointed at a live
emitting gateway through the documented home variable and attached, with the
pass-through returning that gateway's real envelope. That established the
cross-repository path is drivable on this machine, which the consuming
repository's own live harness header had recorded as not spawnable.

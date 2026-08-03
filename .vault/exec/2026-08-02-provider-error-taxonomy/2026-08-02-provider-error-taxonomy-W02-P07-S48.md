---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-03'
modified: '2026-08-03'
body_schema: 'body-v1'
body_hash: 'sha256:ee771599abacc1ad6d3f89b1f16d84046e99d9445a906ed6cfa4968672232374'
step_id: 'S48'
related:
  - "[[2026-08-02-provider-error-taxonomy-plan]]"
---
# Persist and read back the condition on a failed run

## Scope

- `engine/crates/vaultspec-api/src/authoring/session/mod.rs`

## Description

- Record the settled condition on the run when a run reaches its failed
  terminal, through the same settlement path that records the reason.
- Enforce that only a failed run carries one, rather than trusting the caller.

## Outcome

Landed. The invariant is enforced at the store rather than assumed of callers,
which matches how the emitting side enforces it: a completed or non-terminal run
carrying a condition is a contradiction, and the emitting repository proved in a
live run that a completed run correctly carries none.

The two fields stay independent. Nothing derives the condition from the reason
prose, which is the property the whole campaign turns on - and which the live
runs vindicated, since the reason text was misleading on two of three refusals
while the typed condition was right on all three.

## Notes

The janitor's abandoned-run reap deliberately records NO condition. A runtime
that stopped reporting says nothing about whether a provider refused anything,
and stamping the floor member there would present an inference as an observation.
Left as a separate decision rather than folded in silently.

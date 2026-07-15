---
tags:
  - '#exec'
  - '#a2a-edge-conformance'
date: '2026-07-15'
modified: '2026-07-15'
step_id: 'S32'
related:
  - "[[2026-07-14-a2a-edge-conformance-plan]]"
---

# Raise the dashboard multiagent-composition re-arm as a cross-repo contract event with the first composing two-agent run as evidence

## Scope

- `.vault/exec/`

## Description

Raise the dashboard multiagent-composition re-arm as a cross-repo contract event,
with the first composing two-agent run as evidence. This record IS the vault
event; the wave report carries the ask to the dashboard owners (the user relays
it, since the two repositories hold halves of one contract).

### The cross-repo event

A2A now emits multi-role (composing) runs across the frozen five-verb edge: a
single run drives more than one role, and run-status reports per-role topology
position and per-role state. The dashboard side must re-arm its
multiagent-composition handling to render and attribute a composing run — the
review lane and progress view need to show more than one actor per run and key
each produced proposal to its per-role actor.

### Evidence: the first composing two-agent run

The S31 acceptance test `test_multirole_run_status_recovery_and_zero_vault_writes`
drives a real two-role run (coder then reviewer) through the five-verb surface:
run-start accepts the per-role token bundle, both roles execute and checkpoint,
and run-status returns the composing topology plus per-role state, recovering
identically after a simulated restart. This is the first composing run over the
edge and the concrete artifact the dashboard can re-arm against.

### The ask (for the dashboard owners)

- Re-arm multiagent-composition rendering: a run may carry multiple roles; show
  each role's topology position and lifecycle state from run-status.
- Key each proposal in the review lane to its per-role actor (the engine already
  provisions per-role actor tokens at run-start; A2A threads them per worker).
- Treat this as a cross-repo contract event: the mirrored edge reference must
  stay in sync, and any composition-shape change is a coordinated change.

## Outcome

Complete. The cross-repo event is recorded here with the first composing
two-agent run (S31) as evidence, and the ask is raised to the dashboard owners
through the wave report for the user to relay.

## Notes

This is a visibility/contract note, not a code change in this repository; the
A2A side of composition (multi-role runs, per-role tokens, per-role run-status)
is already implemented and tested (W04 P09/P10, S31). The dashboard-observed
proposal proof remains the standing S20 deferral and is tracked separately;
this re-arm is about composition rendering, which is independent of that
upstream CLI limitation.

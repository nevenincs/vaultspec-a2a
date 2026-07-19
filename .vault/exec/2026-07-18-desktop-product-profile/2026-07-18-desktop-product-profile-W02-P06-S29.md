---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S29'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

# Prove interrupted snapshot or restore never exposes a partially committed group

## Scope

- `src/vaultspec_a2a/desktop_tests/test_snapshot_recovery.py`

## Description

- Add a certification that an interrupted snapshot or restore never exposes a
  partially committed group, constructing on real files the exact intermediate
  on-disk states each defined stage boundary leaves, using the module's own
  descriptor and marker layout.
- Prove a capture interrupted after the captured stores are written but before the
  group descriptor commits is invisible: it is absent from the snapshot listing
  and fails inspection.
- Prove a restore interrupted after the quiesced marker is written but before the
  first store is restored is detected via the marker, refuses a fresh restore, and
  rolls forward on resume to return both stores to the captured content.
- Prove a restore interrupted between the two stores -- a genuine half-restored
  pair on disk (primary restored, checkpoint still mutated) -- is never reported
  healthy: the durable marker flags it and a fresh restore is refused, and resume
  converges the checkpoint too, clearing the marker.
- Prove a restore interrupted after the last store but before the marker clears is
  still detected and resumes idempotently to a consistent group.
- Prove an uninterrupted snapshot and restore leaves no pending marker and a
  digest-consistent authoritative group.

## Outcome

Interrupted snapshot and restore are certified never to expose a partially
committed or half-restored group: every stage-boundary crash state is detectable
and recovers to a consistent group. `ruff` and `ty` pass; all five certification
cases pass.

## Notes

- Recovery is roll-forward: because the committed snapshot is the immutable source
  of truth, resuming an interrupted restore re-restores every member idempotently
  and always converges to the captured content; there is no marker-clearing path
  that could leave a half pair looking healthy.

---
tags:
  - '#exec'
  - '#control-action-leases'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:2c2f600a081bb7aa5e753407208ae40948c93b30169d935549d564d85131b773'
step_id: 'S11'
related:
  - "[[2026-08-02-control-action-leases-plan]]"
---

# Settle permission leases from authoritative progress events

## Scope

- `src/vaultspec_a2a/control/event_handlers.py`

## Description

Settled permission actions from permission-resolved and correlated post-resume progress events.

## Outcome

Permission application clears the exact lease while terminal cancellation uses the common applied transition.

## Notes

Generic progress cannot safely identify message actions; an explicit dispatch application receipt was added instead.

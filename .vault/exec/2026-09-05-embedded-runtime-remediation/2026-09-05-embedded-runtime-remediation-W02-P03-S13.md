---
tags:
  - '#exec'
  - '#embedded-runtime-remediation'
date: '2026-09-06'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:22a053bb6d3aeebdf5583526ba8e392298388f661007ba7d315f2cb0fb7e4ca3'
step_id: 'S13'
related:
  - "[[2026-09-05-embedded-runtime-remediation-plan]]"
---
# Settle application only from the durable receipt and reconcile completion arriving before running has committed

## Scope

- `src/vaultspec_a2a/control/event_handlers.py`

## Changes

- `M` `src/vaultspec_a2a/control/event_handlers.py`
- `M` `src/vaultspec_a2a/control/tests/test_event_handlers.py`
- `verify:` `.venv/Scripts/python.exe -m vaultspec_a2a.testing.runner --run-timeout 60 --exit-timeout 5 -- src/vaultspec_a2a/control/tests/test_event_handlers.py -q -k cancellation -o addopts=` -> `pass`
- `verify:` `.venv/Scripts/python.exe -m vaultspec_a2a.testing.runner --run-timeout 60 --exit-timeout 5 -- src/vaultspec_a2a/control/tests/test_event_handlers.py src/vaultspec_a2a/worker/tests/test_state_projection.py -q -o addopts=` -> `pass`
- `verify:` `focused Ruff and Ty for event handler, its tests, and executor source` -> `pass`

## Notes

This partial S13 increment moves exact cancellation settlement behind the durable writer election. Valid `cancellation-evidence-v1` must name the current cancellation receipt while the thread remains under that exact cancelling authority. The election, terminal projection, permission cleanup, exact action disposition and repair projection commit in one transaction. Stale or mismatched evidence changes nothing and does not release the drain gate.

Formal review findings:

- HIGH / stale terminal overwrite: cancellation evidence previously validated action identity but still reached an unconditional lifecycle write, allowing an obsolete worker terminal to overwrite newer authority -> resolved for evidence-bearing cancellation terminals.
- HIGH / non-atomic settlement: lifecycle state and exact cancellation action effects were not elected and committed as one winner -> resolved for evidence-bearing cancellation terminals.
- HIGH / unauthorised generic terminal: cancelled events without cancellation evidence, and completed or failed events, still use the unconditional terminal writer -> open in S13.
- HIGH / incomplete receipt validation: progress-event application settlement still trusts dispatch identity without validating the complete durable receipt -> open in S13.
- MEDIUM / duplicate evidence observation: replay after the first cancellation commit is refused as stale rather than acknowledged as an idempotent duplicate -> open for S13 review with the durable delivery owner.

Evidence exited naturally: four focused cancellation cases passed in 5.85 seconds, then the complete event-handler and state-projection modules passed 24 cases in 3.22 seconds. The Step remains open.
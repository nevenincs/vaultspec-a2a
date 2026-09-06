---
tags:
  - '#exec'
  - '#embedded-runtime-remediation'
date: '2026-09-06'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:0edfd52d7f35d029675c932060c64b8ce54c53746c874bd80c3588d17b6ba18b'
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
## Durable application receipt checkpoint

- `M` `src/vaultspec_a2a/api/internal.py`
- `M` `src/vaultspec_a2a/control/event_handlers.py`
- `M` `src/vaultspec_a2a/thread/checkpoint_evidence.py`
- `M` `src/vaultspec_a2a/control/tests/test_event_handlers.py`
- `M` `src/vaultspec_a2a/control/tests/test_direct_control_leases.py`
- `M` `src/vaultspec_a2a/control/tests/test_verdict_subscriber_live.py`
- `verify:` `focused Ruff and Ty across all six changed files` -> `pass`
- `verify:` `event-handler module before final lock refinement, 16 cases in 39.01 seconds` -> `pass`
- `verify:` `direct receipt plus recovery authority, seven cases in 14.96 seconds` -> `pass`
- `verify:` `exact application and missing-checkpoint discriminators, first run in 8.72 seconds` -> `pass`
- `verify:` `API internal module, 60-second bounded run` -> `fail`
- `verify:` `isolated API private-receipt case, 30-second bounded run` -> `fail`
- `verify:` `combined event/direct/recovery gate, 60-second bounded run` -> `fail`
- `verify:` `final repeat of two application discriminators, 30-second bounded run` -> `fail`

## Notes

The gateway now parses the closed `DispatchApplicationReceiptPayload`, validates its complete graph receipt against the current stored accepted action, verifies the transport verb, and reads the exact named checkpoint. The checkpoint must contain matching incorporated graph authority from a loop commit. After that external read, the consumer locks and revalidates the current thread and action rows before committing journal, permission, repair or lifecycle effects. Internal HTTP, batch and WebSocket relay paths pass the application-owned checkpointer explicitly. Missing checkpointer, partial payload, cross-thread identity, wrong checkpoint and stale current authority all refuse settlement.

Formal review findings:

- HIGH / bare identity settlement: a dispatch id alone previously applied a journal action -> resolved.
- HIGH / invented incorporation: the gateway previously ignored the supplied graph receipt and checkpoint id -> resolved through exact durable checkpoint validation.
- HIGH / concurrent authority overwrite: application effects could commit after a newer writer won -> resolved by post-checkpoint row locks and exact current-receipt revalidation.
- MEDIUM / unavailable checkpoint recovery: an unavailable or timed-out checkpoint leaves the action visibly leased but this consumer does not itself schedule durable retry -> open under S14/S83.
- MEDIUM / verification instability: bounded API and combined runs repeatedly hang before producing a result on this host, while isolated receipt and recovery gates naturally pass -> open as a harness/resource condition; all reaped runs remain FAIL evidence.
- HIGH / generic terminal authority: completed, failed and evidence-free cancelled terminals still use the unconditional lifecycle writer -> open in S13.

No compatibility parser, partial-payload fallback, alias, backfill or inferred receipt was added. S13 remains open.
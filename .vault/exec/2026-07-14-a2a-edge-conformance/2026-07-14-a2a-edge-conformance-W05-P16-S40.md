---
tags:
  - '#exec'
  - '#a2a-edge-conformance'
date: '2026-07-17'
modified: '2026-07-17'
step_id: 'S40'
related:
  - "[[2026-07-14-a2a-edge-conformance-plan]]"
---

# Fix the startup-reconciliation recovery-epoch bug: the paused_resumable repair outcome path never increments threads.recovery_epoch (unlike checkpoint_unavailable), so any subsequent boot re-derives the same startup-repair idempotency key and crashes the whole app with an IntegrityError on the control_actions insert. Increment the epoch on every applied repair outcome and make the idempotency-key insert conflict-tolerant (an already-applied repair replays as a no-op, honoring idempotency semantics instead of crashing). Prove with a live boot-reboot cycle over a thread in paused_resumable state

## Scope

- `src/vaultspec_a2a/database/reconciliation.py`
- `src/vaultspec_a2a/database/tests/`

## Description

Confirmed root cause by reading the pure decision logic against the I/O executor.
Every applied reconciliation outcome seeds a `startup-repair:{tid}:{epoch+1}`
control-action idempotency key from the thread's `recovery_epoch`, and every branch
except one advances the epoch afterward. The `paused_resumable` branch - taken when
a thread has a surviving unanswered permission and its checkpoint is still present -
was the lone outcome that left `increment_recovery_epoch` unset. So the epoch stayed
at its prior value while a `repair_started` action at that epoch's key was already
journaled; the next boot re-derived the identical key and the `control_actions`
INSERT hit the `thread_id + idempotency_key` UNIQUE constraint, raising
`IntegrityError` and crashing startup for the whole app.

Two-layer fix:

- Pure logic: set `increment_recovery_epoch=True` on the `paused_resumable` outcome
  so the epoch advances like every other applied outcome. Generation is deliberately
  left unbumped - a paused_resumable thread must resume its pending permission from
  the existing checkpoint, and `recovery_epoch` only seeds the idempotency-key
  namespace, it is not the worker-generation fence.
- Executor: route the two startup control-action inserts (`repair_started`,
  `repair_finished`) through a new conflict-tolerant `get_or_create_control_action`
  helper that looks the key up first and replays an already-present action as a
  no-op instead of inserting a duplicate. A duplicate idempotency key is the success
  signal of an already-applied action; crashing on it contradicts the key's purpose.
  This layer self-heals rows written before the epoch fix (epoch stuck at 0 with a
  `:1` action already present) and tolerates the scoped two-row DB repair applied
  during the resident promotion.

## Outcome

Live boot-reboot proof (real SQLite database, real langgraph checkpointer, no
mocks): reconciled a thread held in `paused_resumable` (surviving unanswered
permission plus a present checkpoint) across two consecutive boots. Boot one applied
the repair and advanced `recovery_epoch` 0 -> 1; boot two - the reboot that
previously crashed - completed without an `IntegrityError`, advanced the epoch 1 ->
2, and journaled a fresh `startup-repair:{tid}:2` action. A second test seeds the
pre-fix stuck state (epoch 0 with `startup-repair:{tid}:1` already present) and
confirms the boot replays the duplicate key as a no-op and advances the epoch rather
than crashing.

Separately confirmed the crash mechanism empirically: a raw second insert of the
same `(thread_id, idempotency_key)` raises `UNIQUE constraint failed:
control_actions.thread_id, control_actions.idempotency_key`.

Validation: `ruff` and `ty` clean on touched modules; the reconciliation,
control-action, and permission suites pass (`29 passed` on the database slice, `18
passed` on the pure-logic slice, `2 passed` on the new boot-reboot tests).

## Notes

The regression guard requires both fix layers: the epoch assertion fails without the
pure-logic change, and the no-crash requires the conflict-tolerant insert - neither
half alone makes the test green, so it cannot silently rot into a tautology.

`get_or_create_control_action` is scoped to startup reconciliation's legitimate
replay; the broadly-used `create_control_action` keeps its insert-or-raise contract
so a genuine duplicate elsewhere still surfaces rather than being masked.

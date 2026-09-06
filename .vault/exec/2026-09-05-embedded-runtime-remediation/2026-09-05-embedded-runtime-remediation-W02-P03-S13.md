---
tags:
  - '#exec'
  - '#embedded-runtime-remediation'
date: '2026-09-06'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:96cb79a4117d25fc995a76235da275ca3c4056e85125ad40542a3d96263e5a73'
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
## Checkpoint-proven terminal checkpoint

- `M` `src/vaultspec_a2a/control/event_handlers.py`
- `M` `src/vaultspec_a2a/control/recovery_authority.py`
- `M` `src/vaultspec_a2a/control/tests/test_event_handlers.py`
- `verify:` `checkpoint completion plus missing/mismatched cancellation evidence, three cases in 3.29 seconds` -> `pass`
- `verify:` `focused Ruff and Ty` -> `pass`

## Notes

A completed worker notification now triggers the shared checkpoint recovery coordinator. The coordinator validates the current accepted receipt and immutable graph-completion receipt, elects the exact writer, and commits action, permission, approval, repair and captured stream-sequence effects together. Completion may therefore arrive before a RUNNING projection without being lost or overriding newer authority. The notification itself proves nothing.

A cancelled notification without `cancellation-evidence-v1` is refused without lifecycle mutation, drain release or aggregator cleanup. The former test requiring cleanup after an unproven terminal/database failure was deleted because it encoded the unsafe contract that observation alone ends admitted work.

Formal review findings:

- HIGH / notification-as-completion: raw completed events previously wrote terminal state unconditionally -> resolved through checkpoint-first reconciliation.
- HIGH / evidence-free cancellation: raw cancelled events previously changed lifecycle state despite lacking cessation/no-active proof -> resolved by refusal.
- HIGH / contradictory evidence: cancellation evidence on a non-cancelled event could have entered completion reconciliation -> resolved by validating evidence/status before any terminal branch.
- HIGH / failed-terminal authority: failed events still use the unconditional lifecycle writer and can overwrite newer authority -> open in S13.
- MEDIUM / terminal delivery: checkpoint-unavailable completion remains active and visible but still needs S14/S83 durable retry scheduling.

S13 remains open for exact failed-task settlement and removal of the final generic terminal writer.
## Exact failure terminal checkpoint

- `A` `src/vaultspec_a2a/thread/failure_evidence.py`
- `M` `src/vaultspec_a2a/control/event_handlers.py`
- `M` `src/vaultspec_a2a/worker/executor.py`
- `M` `src/vaultspec_a2a/worker/state_projection.py`
- `M` `src/vaultspec_a2a/control/tests/test_event_handlers.py`
- `M` `src/vaultspec_a2a/worker/tests/test_state_projection.py`
- `verify:` `exact failure consumer and terminal producer selection, six cases in 7.87 seconds` -> `pass`
- `verify:` `complete event-handler and state-projection modules, 25 cases in 3.56 seconds` -> `pass`
- `verify:` `focused Ruff and Ty across all changed files` -> `pass`
- `verify:` `three historical executor failure cases` -> `fail`

## Notes

`graph-failure-v1` binds a worker-observed failure to the complete accepted graph receipt, exact error-detail fingerprint and provider condition. The executor constructs it at compile refusal, runtime settle and unhandled-dispatch boundaries. State projection refuses missing or contradictory failed-terminal evidence. The gateway requires the same closed evidence, verifies its detail and condition, validates it against the current durable graph receipt, and elects FAILED before committing the action result, failure account, stream sequence, permission/approval cleanup and repair projection.

The last unconditional lifecycle write and its unconditional drain/aggregation cleanup are deleted. Completed, cancelled and failed notifications now each have a distinct evidence authority.

Formal review findings:

- HIGH / stale failed terminal overwrite: raw failed notifications could overwrite newer lifecycle authority -> resolved by exact accepted-action evidence and election.
- HIGH / unbound failure classification: provider condition and detail were accepted independently of action identity -> resolved by the evidence fingerprint and condition binding.
- HIGH / unconditional terminal writer: one generic status setter remained reachable for failed events -> resolved; the branch is deleted.
- HIGH / producer qualification: three historical executor tests use pre-current partial dispatches; one now correctly fails for missing failure evidence and another also carries the already-queued four-member cache key -> open under S84 for current accepted-input and frozen-graph replacement, without adapters or defaults.
- MEDIUM / delivery durability: failure evidence becomes durable only when the gateway commits it; relay exhaustion still belongs to S14/S83.

The three failing historical cases exited naturally in 0.89 seconds. They are not qualification evidence and must not be restored through partial request support. S13 implementation is complete, but its plan checkbox remains open until the current executor producer proof is added.
## Current executor failure producer proof

- `M` `src/vaultspec_a2a/worker/tests/test_executor.py`
- `verify:` `current runtime failure and empty-stash backstop, two cases in 0.37 seconds` -> `pass`
- `verify:` `current dispatch-dies-before-settle backstop, one case in 0.32 seconds` -> `pass`
- `verify:` `focused Ruff` -> `pass`
- `verify:` `full executor-test Ty` -> `fail`

## Notes

The migrated executor cases construct accepted-action-input-v2 from a frozen `mock-success-single` graph, derive the receipt fingerprint from that exact accepted payload, and pass the complete receipt to the worker. Runtime failure and both unhandled-settlement paths emit `graph-failure-v1` with the same dispatch identity. No test-only partial dispatch or inferred graph authority remains in these three cases.

Formal review resolves the HIGH executor-wiring proof gap for ordinary runtime failure and the unhandled-settlement backstop. The failed-checkpoint replay case remains HIGH S84 work because it still registers an arbitrary graph under a retired four-member cache identity. Full executor-test Ty reports that case and five other existing four-member cache fixtures; this increment does not claim them or add a placeholder digest.
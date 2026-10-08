---
tags:
  - '#audit'
  - '#run-continuation'
date: '2026-10-01'
modified: '2026-10-08'
body_schema: 'body-v2'
body_hash: 'sha256:68886640d5600c1c736de8ea0cdfccfb82c0c14cfe7a64e6c9af1c63a4229dc0'
related:
  - "[[2026-10-01-run-continuation-plan]]"
---

# `run-continuation` audit: `execution of the continuation prerequisites`

## Scope

Findings raised while executing Phase P01 of `2026-10-01-run-continuation-plan` (P01.S01-S03) under `2026-10-01-run-continuation-adr`. Rolling: later Phases append here.

## Findings

### drain-refusal-counts-as-transport-failure | medium | a draining worker's 503 opens the shared breaker

Open. A worker answering `CAPACITY_DRAINING` replies 503 (`src/vaultspec_a2a/worker/app.py`, `_capacity_refusal`), and the gateway's server-error branch records a transport failure for it (`src/vaultspec_a2a/control/dispatch.py`). The worker did answer, so by the breaker's own rule this is an admission outcome, not transport health; whether a departing worker should open the shared breaker is a ruling under `2026-08-02-control-action-leases-adr`, which already says capacity does not affect transport health.

### capacity-refusal-lacks-retry-after | medium | a 503 for capacity carries no Retry-After although the delay is known

Open. The worker sends `Retry-After` and `DispatchOutcome.retry_after_seconds` captures it, but neither the message result nor the permission result carries it to the route, so the gateway's 503 omits a header RFC 9110 section 15.6.4 says it should carry when the delay is known.

### permission-pre-dispatch-refusals-untyped | medium | the permission verb's pre-dispatch 409s are untyped strings

Open. Only the dispatch-outcome 409 is typed; the verb's own guards (no longer active, no longer pending, no valid options, unknown option, previously rejected, different response, no active project, incompatible state) still answer a bare string, so a client can tell them apart only by matching text. The served schema documents the union honestly.

### idempotency-key-status-diverges-from-the-draft | info | a missing Idempotency-Key is a 422 where the IETF draft suggests 400

Recorded from P01.S03. The httpapi Idempotency-Key draft says a server SHOULD answer a missing required key with 400 and key reuse with a different payload with 422; this surface answers 422 for a missing key, as FastAPI validates and as the plan Step states, and a typed 409 `conflict` for reuse. Both are deliberate divergences from a SHOULD in a draft.

### dispatch-result-circuit-flags-unused | low | the result objects' circuit-open flags have no consumer

Fixed for the message verb in P04.S10 (8eedbfa), which removed `MessageResult.circuit_open` with the dispatch path it described; the permission result's flag remains. Original finding: the route now maps a refusal from its failure type, so `MessageResult.circuit_open` and `PermissionResult.circuit_open` are read by nothing.

### undocumented-403-and-404 | low | the follow-up and permission routes serve undocumented 403 and 404

Open. Both routes can answer 403 and 404 that `openapi.json` does not list.

### terminal-frame-still-relayed-on-a-promoted-turn | high | a promoted run still shows viewers a terminal frame at the first turn's end

Fixed in P03.S19 (d379515): the relay hands the terminal to the settlement as a publisher; a promoting settlement drops it, so it takes no sequence and leaves no replay row, and every other outcome publishes it at the old point. Real-gateway tests on the HTTP and websocket relays prove one terminal at the second turn's end with contiguous numbering. Original finding: the control plane promoted instead of settling, but the client-visible `thread_terminal` frame is broadcast by `_relay_single_event` in `src/vaultspec_a2a/api/internal.py` through the aggregator before `relay_event` reaches any control-plane decision, so the ADR's "no terminal event is published" does not yet hold and P06.S17 cannot pass. The replay log records that frame too, so a resumed stream would also replay it.

### queued-continuation-survives-a-failed-or-cancelled-run | high | a continuation queued on a run that fails or is cancelled waits forever

Fixed in P03.S18 (687bb66): the proven-failure, proven-cancellation and both reconciling-sweep refusals call `refuse_queued_continuations` in their own transaction, bound to the won election; proven on both backends. Original finding (owned by P03.S18; the ADR amendment of 2026-10-01 rules the outcome): Promotion runs only on the COMPLETED path, so a run settling FAILED or CANCELLED leaves its queued row at `queued` on a terminal run, promoted by nothing and reported to no one. `refuse_queued_continuations` (P03.S09) is the needed verb and is not called from the failed or cancelled confirmation. Reachable once P04 admits continuations.

### promotion-refusal-stalls-rather-than-settles | medium | a refused promotion leaves the run unsettled until its predecessor's deadline

Open; raised by the P02-P03 executor. `_refuse_promotion` (unreadable envelope, lost election, refused receipt) settles nothing, so the run holds a proven but unsettled turn until the predecessor action's recovery deadline expires and it is quarantined to RECONCILING with operator intervention required. Bounded and visible, but the stall can last a whole run timeout, and a durably corrupt queued envelope hits it on every pass.

### queued-rows-excluded-from-recovery-only-structurally | low | the dispatcher skips a queued row only because it joins on the writer

Recorded from P03.S07. A queued continuation is invisible to `_expire_overdue_actions` and `seed_recovery_attempts` because both join on the thread's writer identity, which a queued row never holds; there is no explicit `result_status <> 'queued'` predicate. Nothing fails without one, so it is an invariant to keep if those queries are rewritten.

### promotion-proofs-run-on-sqlite-only | low | the promotion suites prove the row locking on SQLite, where it is a no-op

Addressed in P06.S17. Type: verification coverage. S04 and S05 proved both backends, while the original promotion and recovery suites ran on SQLite only. S17 now drives queued promotion, replay, completion and gateway restart through real PostgreSQL gateway and worker processes; the PostgreSQL admission-versus-settlement race suite also proves the shared run lock.

### real-worker-app-harness-needs-a-settings-mutation | low | the real worker app cannot be given its IPC credential without mutating settings

Recorded from P03.S07. `create_worker_app()` answers a misconfigured 500 in an undeclared development environment with no internal token, and the established harness sets the token through a settings mutation the test rules forbid, so S07's dispatch receiver is a real FastAPI app rather than the production worker app. The worker needs an official way to take its IPC credential at construction.

### settlement-transaction-read-first-lock-upgrade | info | a read-first SQLite settlement transaction could not upgrade to a write

Fixed in P03.S07. Reading the queue made a SELECT the first statement of the settlement transaction, and a deferred SQLite transaction that reads first cannot upgrade once another connection has committed; the real-gateway restart suite failed with `database is locked`. The settlement transaction now opens as a write transaction.

### terminal-shown-when-a-continuation-cannot-be-promoted | medium | a refused promotion publishes a terminal on a run that has not ended

Fixed in P06.S17. `_promote_queued_continuation` can refuse (unreadable envelope, lost election, refused receipt) and `_confirm_completed_terminal` folds that into `_TerminalDisposition.REFUSED`. Previously the relay published that refusal even though the run remained RUNNING with an accepted continuation. The terminal gate now publishes only settled dispositions. The separate promotion-stall issue remains tracked as `promotion-refusal-stalls-rather-than-settles`.

### settled-cursor-and-stream-ids-are-different-number-spaces | medium | a run's recorded cursor and its stream ids come from different counters

Open; raised by the P03.S19 executor. `thread.last_sequence` is written from the emitters' per-thread counter, while every client-visible id comes from the run sequence allocator; the replay store reads `last_sequence` as a reseed floor and the snapshot publishes it for gap detection against ids the other counter issued. It is safe today only because the retained high-water mark is preferred when present, and each promotion now advances the emitters' counter for a frame nobody saw, over-counting by one per promotion (the safe direction). The two should be one number.

### a-settled-run-s-terminal-could-reach-the-wire-without-an-id | medium | a settled run's terminal could lose its resumable id

Fixed in P03.S19 (d379515). The purge that forgets a run's counter runs in the same step as the terminal's release, and the stream asked `is_numbered` whether to stamp an id, so the settled terminal could reach the wire with none; it was scheduling-dependent before and deterministic after the release moved. `is_numbered` now answers for a forgotten run whose floor is remembered and stays false for a run known unseedable.

### a-failed-terminal-fan-out-loses-the-frame | low | a fan-out that throws costs the live terminal rather than the relay

Accepted in P03.S19. `_publish_terminal` logs instead of raising, because the settlement is already durable and raising would strand the run's admission slot; reachable only if `enqueue_payload` itself throws, which its bounded delivery is written not to do.

### followup-admission-was-unserialized-on-postgresql | high | admission and settlement could both commit on PostgreSQL

Fixed in P04.S11 (e3d2c21). Admission read the run with a plain SELECT and settlement locked the thread row only at its election update, so on PostgreSQL a settlement could read an empty queue while an uncommitted admission read a live run, and both committed - the queued row on a settled run that the decision forbids. Two concurrent admissions could likewise take the one free place. SQLite's `BEGIN IMMEDIATE` hid it. Admission and all three settlement paths now take `lock_run_for_continuation_decision`, proven by `control/tests/test_continuation_admission_race.py` on real PostgreSQL.

### replay-after-settlement-reported-the-run-not-the-turn | medium | a retried admission on a settled run read as a turn that never ran

Fixed in P04.S11. A repeat of an accepted key answered `terminal` once the run settled, so a caller retrying after a lost 202 could not learn its turn was accepted and ran, and would send the work twice; replay is now decided before eligibility and serves the journal row's own status.

### followup-contract-narrowed | info | the follow-up route no longer documents 502 or the worker-saturation 503

Recorded from P04.S10 for the P06.S16 contract event. Both answers are unreachable now that the verb never dispatches; the narrowing of a published contract belongs in R6 beside the reachable 202, `queue_full` and `queued_messages`.

### promotion-is-the-only-dispatcher-for-a-follow-up | info | a follow-up reaches a worker only through promotion

Recorded from P04.S10. A gateway that never runs its recovery pass accepts turns and never runs them; P06.S17's live proof is where that becomes observable, and the contract event should say it.

### queue-full-is-not-in-the-dispatch-failure-policy-table | low | the admission refusal has no row in the dispatch failure policy

Recorded from P04.S10. `FailureType.QUEUE_FULL` is not keyed in `thread/dispatch_policy.py`; it is an admission refusal and unreachable from a dispatch outcome, an invariant to keep if the two vocabularies merge.

### windows-postgres-fixture-uses-proactor | low | direct pooled PostgreSQL fixture cannot connect on Windows

Open. Type: test portability. `pooled_postgres_saver` opens psycopg's async pool on the default Windows Proactor event loop, which psycopg rejects; the S15 PostgreSQL attempt timed out in fixture setup. The successor checkpoint proof passed through the production `open_checkpointer` selector-thread bridge instead. The direct pooled fixture should use the same supported event-loop path or declare a selector loop.

### successor-seed-omits-non-dialogue-messages | low | a successor carries textual user and assistant turns only

Open. Type: transcript fidelity. `surviving_transcript` projects the retained checkpoint to nonempty textual `HumanMessage` and `AIMessage` values. System, tool, and rich-content messages do not cross into the successor's first graph input. This avoids invalid truncated tool-call pairs, but a continuation that needs a prior tool result may need to retrieve it again. Revisit if the settled-run consumer requires tool context to survive the lineage boundary.

### queued-position-missing-from-r6-event | low | the recorded edge event omitted the served queue position

Fixed in P06.S16. Type: contract drift. The live `202` response includes a one-based `queue_position` so a client can distinguish queue admission from execution; R6's draft event named `action_status` but omitted that field. The amendment now states the served shape and the narrowed `502`/`503` answers.

### refused-terminal-published-after-promotion | high | a stale first-turn terminal closed a live PostgreSQL run

Fixed in P06.S17. Type: behavioral defect. The real PostgreSQL gateway/worker test queued and completed two turns but retained two `thread_terminal` frames. Recovery had already promoted the queued successor when the delayed first-turn terminal arrived, so completion reconciliation returned `lost`; `_handle_terminal_event` treated that refusal as publishable. The terminal gate now publishes only a durable `SETTLED` disposition, and both backends prove a refused terminal emits no frame while a valid final settlement emits one. The real PostgreSQL service test now sees one terminal in the replay log.

### restart-proof-could-miss-the-crash-window | low | an observed second turn alone did not prove restart promoted it

Fixed in P06.S17. Type: test coverage. The first live restart test killed the gateway after a fast mock turn had already been promoted. It still observed two user turns after restart, so it passed without proving recovery owned the queued action. The harness now pauses VidaiMock while the worker retains the first turn, kills the gateway, releases the mock reply, waits for the worker checkpoint, and asserts the continuation journal row is still `queued` with no graph receipt before restart. SQLite and PostgreSQL pass this exact window.

### postgres-scratch-url-preserves-unsupported-sslmode | low | a psycopg test URL fails when converted to asyncpg

Open. Type: test configuration. `database/tests/_backends.py` converts `VAULTSPEC_A2A_TEST_POSTGRES_URL` to an asyncpg SQLAlchemy URL for scratch databases but retains a `sslmode=disable` query argument, which asyncpg rejects as an unexpected `connect()` keyword. The S17 PostgreSQL service lane used the psycopg URL directly and passed; its focused scratch-backend regression passed after the same URL omitted that optional query. Normalize or translate driver-specific query arguments in the scratch backend fixture.

### run-busy-proof-spans-two-real-seams | info | the public continuation verb does not dispatch a second active turn

Accepted in P06.S17. Type: verification boundary. The live service test holds a real worker turn and sends a distinct valid dispatch over loopback HTTP; the worker returns `409 run_busy`, its original action receipt remains exact, the gateway health breaker stays closed, and the accepted run completes after the model is released. This probe goes directly to the worker, so it does not itself exercise gateway dispatch classification. `test_a_busy_worker_keeps_the_action_claim_for_the_run_it_is_running` supplies that half by driving `redrive_direct_control_actions` against the real worker FastAPI app and asserting the breaker stays closed and the recovery claim remains owned. A public continuation queues without dispatch, and ordinary redelivery uses the same dispatch ID, so a gateway-originated second dispatch to this active run would require synthetic journal or writer mutation. An `applied` journal row can still name an active worker turn; application is not graph completion.

### checkpoint-transcript-added-two-type-diagnostics | medium | S15 transcript guards missed the basedpyright baseline

Fixed in P06.S17. Type: CI regression. Integrated `just ci` found new `reportUnnecessaryIsInstance` and `reportUnknownVariableType` diagnostics in `surviving_transcript`. The first guard tested a checkpoint channel map already declared as `dict[str, Any]`; the list comprehension then iterated values with unknown element type. The runtime guards remain, but the channel map and message list are explicitly narrowed to `object` and checked before typed casts. `just audit-types` now reports 60 advisory diagnostics with none in `database/checkpoints.py`, down from 62; the lineage test and Ruff/Ty checks pass.

### absent-lineage-changed-persisted-run-digest | high | a new null field refused identical older requests

Fixed in P06.S20. Type: backward-compatibility defect. `RunStartRequest.continues_run_id` was added with a `None` default, and the shared digest function serialized that default into every plain-start and staged request. The pinned current-rule fingerprint moved from `74449631...` to `48dc128b...`, so an otherwise identical retry of a previously accepted run would conflict after upgrade. The digest now omits only an absent predecessor, preserving older request bytes; a non-null predecessor remains in both staged and replay fingerprints and is explicitly classified as work identity. The pinned digest, independent rule calculations, and cross-process and predecessor-variation tests pass.

### stream-resume-tests-relayed-unproven-completion | medium | terminal gate withheld synthetic test events

Fixed in P06.S20. Type: test-fixture drift. Two live SSE resume tests created only a RUNNING row, then relayed a fabricated COMPLETED terminal. The S17 settlement gate correctly refused the frame because no accepted graph action or completed checkpoint proved it, leaving the viewer waiting for a terminal. The tests now seed a real accepted action receipt and completed checkpoint through existing test helpers before relaying; the previously timing-out cursor test and neighboring reconnect test both pass without weakening the terminal gate.

### stream-test-sqlite-connections-reach-garbage-collector | low | neighboring suites emitted pooled connection warnings

Open. Type: test resource hygiene. The focused eight-module API run passed 64 tests but emitted four SQLAlchemy warnings that an `aiosqlite` adapted connection reached garbage collection while not checked into its pool. The warnings came from neighboring stream and promoted-terminal tests, not the two repaired terminal tests. Trace fixture and app/session shutdown ownership if this persists in integrated CI.

### clarification-park-never-input-required | high | a run parked on a clarification stayed running and queued follow-ups

Fixed in 8a6fbe62; residue open. Type: contract drift against the Constraints of `2026-10-01-run-continuation-adr` (a run parked on input_required refuses, whether the pause is a clarification or a permission request). Only permission, plan-approval and document-approval events elected `INPUT_REQUIRED` (`control/event_handlers.py`), so a clarification park stayed `RUNNING`: `POST /messages` was admitted as a queued continuation, and gateway restart drove the park to `RECONCILING`. P04.S12 closed on `api/tests/test_run_continuation_admission.py:191-264`, which seeds an `INPUT_REQUIRED` row with no permission request, a state production never produced for a clarification. The fix `control/clarification_service.reconcile_clarification_pause` re-projects the pause from checkpoint truth on the relayed clarification nudge, on a resume application receipt and on startup redrive. It elects under the current writer identity, with the witness read before the checkpoint. `test_a_worker_reported_park_reads_input_required_and_refuses_followups` drives a park from a real worker through the real gateway and fails on the prior code. Still open, owned by the codebase-remediation plan (FX.1): a restart proof, and replacing the hand-seeded premise with a real park.

### clarification-park-restart | medium | A clarification park now survives a gateway restart under test

R4-F1 residue. Status: fixed on refactor/centralize (PV01, the PVG branch commit e644995a, integrated as 33c79748). Type: coverage. `api/tests/test_clarification_loop_live.py` `test_a_clarification_park_survives_a_gateway_restart` parks a run on a real clarification through a real worker, discards the gateway, client and worker, runs `control/reconciliation.reconcile_threads_on_startup` over the same stores, and proves a second gateway reads `input_required` with the same request id and resumes the real graph. The hand-seeded `INPUT_REQUIRED` premise in `api/tests/test_run_continuation_admission.py` is replaced by real interrupts.

## Recommendations

- Rule under `2026-08-02-control-action-leases-adr` whether a draining worker's refusal is admission or transport, then classify it (`drain-refusal-counts-as-transport-failure`).
- Carry the worker's retry delay through to the 503 (`capacity-refusal-lacks-retry-after`).
- Type the permission verb's guard refusals with the shared refusal vocabulary (`permission-pre-dispatch-refusals-untyped`).
- Refuse queued continuations on every failed or cancelled settlement and gate the client terminal frame on the promotion disposition before P04 admits anything (`queued-continuation-survives-a-failed-or-cancelled-run`, `terminal-frame-still-relayed-on-a-promoted-turn`).
- Repair the direct PostgreSQL test fixture on Windows (`windows-postgres-fixture-uses-proactor`).
- Assess whether tool results must survive a settled-run lineage boundary (`successor-seed-omits-non-dialogue-messages`).

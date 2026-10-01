---
tags:
  - '#audit'
  - '#run-continuation'
date: '2026-10-01'
modified: '2026-10-01'
body_schema: 'body-v2'
body_hash: 'sha256:831bb25e1588bb71d1b9688235f3ee531671e8b036fa8edfcb92582baf70f062'
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

Recorded from architecture-review P06.S47. The route now maps a refusal from its failure type, so `MessageResult.circuit_open` and `PermissionResult.circuit_open` are read by nothing.

### undocumented-403-and-404 | low | the follow-up and permission routes serve undocumented 403 and 404

Open. Both routes can answer 403 and 404 that `openapi.json` does not list.

### terminal-frame-still-relayed-on-a-promoted-turn | high | a promoted run still shows viewers a terminal frame at the first turn's end

Open; raised by the P02-P03 executor, owned by P03.S19. The control plane now promotes instead of settling, but the client-visible `thread_terminal` frame is broadcast by `_relay_single_event` in `src/vaultspec_a2a/api/internal.py` through the aggregator before `relay_event` reaches any control-plane decision, so the ADR's "no terminal event is published" does not yet hold and P06.S17 cannot pass. The replay log records that frame too, so a resumed stream would also replay it.

### queued-continuation-survives-a-failed-or-cancelled-run | high | a continuation queued on a run that fails or is cancelled waits forever

Open; raised by the P02-P03 executor, owned by P03.S18; the ADR amendment of 2026-10-01 rules the outcome. Promotion runs only on the COMPLETED path, so a run settling FAILED or CANCELLED leaves its queued row at `queued` on a terminal run, promoted by nothing and reported to no one. `refuse_queued_continuations` (P03.S09) is the needed verb and is not called from the failed or cancelled confirmation. Reachable once P04 admits continuations.

### promotion-refusal-stalls-rather-than-settles | medium | a refused promotion leaves the run unsettled until its predecessor's deadline

Open; raised by the P02-P03 executor. `_refuse_promotion` (unreadable envelope, lost election, refused receipt) settles nothing, so the run holds a proven but unsettled turn until the predecessor action's recovery deadline expires and it is quarantined to RECONCILING with operator intervention required. Bounded and visible, but the stall can last a whole run timeout, and a durably corrupt queued envelope hits it on every pass.

### queued-rows-excluded-from-recovery-only-structurally | low | the dispatcher skips a queued row only because it joins on the writer

Recorded from P03.S07. A queued continuation is invisible to `_expire_overdue_actions` and `seed_recovery_attempts` because both join on the thread's writer identity, which a queued row never holds; there is no explicit `result_status <> 'queued'` predicate. Nothing fails without one, so it is an invariant to keep if those queries are rewritten.

### promotion-proofs-run-on-sqlite-only | low | the promotion suites prove the row locking on SQLite, where it is a no-op

Recorded from P03.S06-S09. S04 and S05 prove both backends; the promotion, recovery, ownership and lifetime suites run on SQLite only, like their sibling recovery suites, so the `FOR UPDATE` locking they rely on is exercised only on PostgreSQL. P06.S17 is the natural home for the PostgreSQL lane.

### real-worker-app-harness-needs-a-settings-mutation | low | the real worker app cannot be given its IPC credential without mutating settings

Recorded from P03.S07. `create_worker_app()` answers a misconfigured 500 in an undeclared development environment with no internal token, and the established harness sets the token through a settings mutation the test rules forbid, so S07's dispatch receiver is a real FastAPI app rather than the production worker app. The worker needs an official way to take its IPC credential at construction.

### settlement-transaction-read-first-lock-upgrade | info | a read-first SQLite settlement transaction could not upgrade to a write

Fixed in P03.S07. Reading the queue made a SELECT the first statement of the settlement transaction, and a deferred SQLite transaction that reads first cannot upgrade once another connection has committed; the real-gateway restart suite failed with `database is locked`. The settlement transaction now opens as a write transaction.

## Recommendations

- Rule under `2026-08-02-control-action-leases-adr` whether a draining worker's refusal is admission or transport, then classify it (`drain-refusal-counts-as-transport-failure`).
- Carry the worker's retry delay through to the 503 (`capacity-refusal-lacks-retry-after`).
- Type the permission verb's guard refusals with the shared refusal vocabulary (`permission-pre-dispatch-refusals-untyped`).
- Refuse queued continuations on every failed or cancelled settlement and gate the client terminal frame on the promotion disposition before P04 admits anything (`queued-continuation-survives-a-failed-or-cancelled-run`, `terminal-frame-still-relayed-on-a-promoted-turn`).

---
tags:
  - '#exec'
  - '#run-continuation'
date: '2026-10-01'
modified: '2026-10-01'
body_schema: 'body-v2'
body_hash: 'sha256:498908ba083886832b7aa01b451a73debc8b9a4a461b1d92e7f88c40dfb83525'
related:
  - "[[2026-10-01-run-continuation-plan]]"
---

# `run-continuation` ledger

## Changes

- `S02` `M` `src/vaultspec_a2a/control/action_lease.py`
- `S02` `M` `src/vaultspec_a2a/control/direct_control_recovery.py`
- `S02` `M` `src/vaultspec_a2a/control/tests/test_direct_control_recovery_current.py`
- `S02` `verify:` `pytest src/vaultspec_a2a/control src/vaultspec_a2a/thread` -> `pass`
- `S01` `M` `src/vaultspec_a2a/control/tests/test_dispatch_refusal_classification.py`
- `S01` `verify:` `pytest control api thread` -> `pass`
- `S01` `by:` `vaultspec-high-executor`
- `S03` `M` `src/vaultspec_a2a/api/routes/_gateway_action_endpoints.py`
- `S03` `M` `src/vaultspec_a2a/api/schemas/gateway.py`
- `S03` `M` `src/vaultspec_a2a/control/message_service.py`
- `S03` `M` `src/vaultspec_a2a/thread/idempotency.py`
- `S03` `A` `src/vaultspec_a2a/api/tests/test_followup_idempotency_key.py`
- `S03` `M` `src/vaultspec_a2a/api/tests/test_endpoints.py`
- `S03` `M` `src/vaultspec_a2a/api/tests/test_gateway_drain.py`
- `S03` `M` `src/vaultspec_a2a/api/tests/test_gateway_live.py`
- `S03` `M` `src/vaultspec_a2a/service_tests/harness.py`
- `S03` `M` `src/vaultspec_a2a/service_tests/test_stream_followup.py`
- `S03` `M` `openapi.json`
- `S03` `verify:` `pytest control api thread database --require-prerequisite=postgres` -> `pass`
- `S03` `by:` `vaultspec-high-executor`
- `S04` `M` `src/vaultspec_a2a/thread/enums.py`
- `S04` `M` `src/vaultspec_a2a/database/control_action_schema.py`
- `S04` `M` `src/vaultspec_a2a/database/models.py`
- `S04` `A` `src/vaultspec_a2a/database/migrations/versions/0024_control_action_continuation_queue.py`
- `S04` `A` `src/vaultspec_a2a/database/tests/test_continuation_queue_schema.py`
- `S04` `verify:` `pytest-control-database-thread-api-worker-postgres` -> `pass`
- `S04` `by:` `vaultspec-high-executor`
- `S05` `M` `src/vaultspec_a2a/domain_config.py`
- `S05` `M` `.env.example`
- `S05` `A` `src/vaultspec_a2a/control/repositories/continuation_queue.py`
- `S05` `M` `src/vaultspec_a2a/control/repositories/__init__.py`
- `S05` `A` `src/vaultspec_a2a/control/repositories/tests/test_continuation_queue.py`
- `S05` `verify:` `pytest-control-database-thread-api-worker-postgres` -> `pass`
- `S05` `by:` `vaultspec-high-executor`
- `S06` `M` `src/vaultspec_a2a/control/recovery_authority.py`
- `S06` `M` `src/vaultspec_a2a/control/event_handlers.py`
- `S06` `M` `src/vaultspec_a2a/control/repositories/continuation_queue.py`
- `S06` `A` `src/vaultspec_a2a/control/tests/test_continuation_promotion.py`
- `S06` `verify:` `pytest-control-database-thread-api-worker-postgres` -> `pass`
- `S06` `by:` `vaultspec-high-executor`
- `S07` `M` `src/vaultspec_a2a/control/recovery_authority.py`
- `S07` `M` `src/vaultspec_a2a/control/repositories/continuation_queue.py`
- `S07` `A` `src/vaultspec_a2a/control/tests/_continuation.py`
- `S07` `A` `src/vaultspec_a2a/control/tests/test_continuation_promotion_recovery.py`
- `S07` `M` `src/vaultspec_a2a/control/tests/test_continuation_promotion.py`
- `S07` `verify:` `pytest-control-database-thread-api-worker-postgres` -> `pass`
- `S07` `by:` `vaultspec-high-executor`
- `S08` `M` `src/vaultspec_a2a/control/recovery_authority.py`
- `S08` `M` `src/vaultspec_a2a/control/repositories/continuation_queue.py`
- `S08` `M` `src/vaultspec_a2a/database/reconciliation.py`
- `S08` `A` `src/vaultspec_a2a/control/tests/test_continuation_queue_ownership.py`
- `S08` `verify:` `pytest-control-database-thread-api-worker-postgres` -> `pass`
- `S08` `by:` `vaultspec-high-executor`
- `S09` `M` `src/vaultspec_a2a/control/recovery_authority.py`
- `S09` `M` `src/vaultspec_a2a/control/repositories/continuation_queue.py`
- `S09` `A` `src/vaultspec_a2a/control/tests/test_continuation_lifetime.py`
- `S09` `verify:` `pytest-control-database-thread-api-worker-postgres` -> `pass`
- `S09` `by:` `vaultspec-high-executor`
- `S19` `M` `src/vaultspec_a2a/api/internal.py`
- `S19` `A` `src/vaultspec_a2a/api/tests/test_promoted_turn_terminal.py`
- `S19` `M` `src/vaultspec_a2a/control/event_handlers.py`
- `S19` `M` `src/vaultspec_a2a/control/tests/_continuation.py`
- `S19` `M` `src/vaultspec_a2a/streaming/subscribers.py`
- `S19` `M` `src/vaultspec_a2a/streaming/tests/test_run_sequence_allocation.py`
- `S19` `verify:` `pytest control database api streaming worker -n 4 --require-prerequisite=postgres` -> `pass`
- `S19` `verify:` `python -m dev lint all` -> `pass`
- `S19` `by:` `vaultspec-high-executor`

## Notes

- `S02` Satisfied by architecture-review P06.S38 (commit e76fd43): the busy-worker retention rule is stated once as `DEFINITE_NON_DELIVERY` and `test_a_busy_worker_keeps_the_action_claim_for_the_run_it_is_running` drives the worker's real `run_busy.`
- `S01` Already satisfied in production: dispatch records a refusal, not a failure, for a 429 and every non-5xx answer; a guard test now fails if either opens the breaker.
- `S03` Dashboard contract event: POST `/v1/runs/{run_id}/messages` requires Idempotency-Key (1-255 chars), 422 when absent; `RunMessageResponse.idempotency_key` is always the caller key.
- `S04` Migration 0024 follows 0023 (stream replay log); its downgrade refuses while any continuation is still queued, because the earlier schema cannot express one.
- `S05` Served service-wide cap is 64, matched to the recovery page size so one recovery pass examines every admitted continuation.
- `S06` Scope correction: COMPLETED settlement lives in `control/recovery_authority.py,` not `event_handlers.py;` dispatch the ingest is realised as hand the promoted turn to the durable recovery dispatcher, a revisable hypothesis the ADR names. The client-visible terminal frame is still relayed before the control plane decides; owned by a new P03 Step.
- `S07` Scope correction: `direct_control_recovery.py` needed no change. The settlement transaction now opens with a write transaction, because a SQLite read-first transaction cannot upgrade once another connection commits; this surfaced as database is locked in the real-gateway restart suite.
- `S09` Scope correction: the bound is enforced in `recovery_authority.py` at promotion; `event_handlers.py` and `domain_config.py` were changed in S06 and S05.
- `S19` The terminal is handed to the settlement as a publisher and dropped on promotion, never deferred; releasing it after settlement exposed a settled run whose terminal reached the wire without an id, fixed by `is_numbered` answering for a forgotten run whose floor is remembered. `recovery_authority.py` needed no change.

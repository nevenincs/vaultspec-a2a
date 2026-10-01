---
tags:
  - '#exec'
  - '#run-continuation'
date: '2026-10-01'
modified: '2026-10-01'
body_schema: 'body-v2'
body_hash: 'sha256:e2eeb00e0aa46a716975f5342762d975424eee3eeed21334e2cf63a845c9e829'
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

## Notes

- `S02` Satisfied by architecture-review P06.S38 (commit e76fd43): the busy-worker retention rule is stated once as `DEFINITE_NON_DELIVERY` and `test_a_busy_worker_keeps_the_action_claim_for_the_run_it_is_running` drives the worker's real `run_busy.`
- `S01` Already satisfied in production: dispatch records a refusal, not a failure, for a 429 and every non-5xx answer; a guard test now fails if either opens the breaker.
- `S03` Dashboard contract event: POST `/v1/runs/{run_id}/messages` requires Idempotency-Key (1-255 chars), 422 when absent; `RunMessageResponse.idempotency_key` is always the caller key.

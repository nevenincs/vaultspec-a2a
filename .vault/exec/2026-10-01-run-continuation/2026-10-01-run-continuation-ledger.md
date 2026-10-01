---
tags:
  - '#exec'
  - '#run-continuation'
date: '2026-10-01'
modified: '2026-10-01'
body_schema: 'body-v2'
body_hash: 'sha256:0a280271f5f3467b52f3434997919273917767769b06be8551173bf6d9a152e7'
related:
  - "[[2026-10-01-run-continuation-plan]]"
---


# `run-continuation` ledger

## Changes


- `S02` `M` `src/vaultspec_a2a/control/action_lease.py`
- `S02` `M` `src/vaultspec_a2a/control/direct_control_recovery.py`
- `S02` `M` `src/vaultspec_a2a/control/tests/test_direct_control_recovery_current.py`
- `S02` `verify:` `pytest src/vaultspec_a2a/control src/vaultspec_a2a/thread` -> `pass`

## Notes

- `S02` Satisfied by architecture-review P06.S38 (commit e76fd43): the busy-worker retention rule is stated once as `DEFINITE_NON_DELIVERY` and `test_a_busy_worker_keeps_the_action_claim_for_the_run_it_is_running` drives the worker's real `run_busy.`

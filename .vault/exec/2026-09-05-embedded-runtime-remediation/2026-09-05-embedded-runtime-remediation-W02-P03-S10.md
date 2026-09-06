---
tags:
  - '#exec'
  - '#embedded-runtime-remediation'
date: '2026-09-06'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:6244b7c6c918ee6d02dcc7300dfa996b644eca37315352ee306dfe63a31023b1'
step_id: 'S10'
related:
  - "[[2026-09-05-embedded-runtime-remediation-plan]]"
---
# Adopt the atomic election for lifecycle writers that already carry a durable applicable receipt, including initial dispatch, cancellation, direct-control recovery, permission-request projection, archive and atomic deletion-saga entry, with side effects only after the winner

## Scope

- `src/vaultspec_a2a/control`
- `src/vaultspec_a2a/database`

## Changes

- `M` `src/vaultspec_a2a/control/cancel_service.py`
- `M` `src/vaultspec_a2a/control/direct_control_recovery.py`
- `M` `src/vaultspec_a2a/control/event_handlers.py`
- `M` `src/vaultspec_a2a/control/repositories/deletion_saga.py`
- `M` `src/vaultspec_a2a/control/repositories/tests/test_deletion_saga.py`
- `M` `src/vaultspec_a2a/control/tests/test_direct_control_leases.py`
- `M` `src/vaultspec_a2a/control/tests/test_direct_control_recovery.py`
- `M` `src/vaultspec_a2a/control/tests/test_event_handlers.py`
- `M` `src/vaultspec_a2a/control/tests/test_thread_service_tokens.py`
- `M` `src/vaultspec_a2a/control/thread_service.py`
- `M` `src/vaultspec_a2a/database/__init__.py`
- `M` `src/vaultspec_a2a/database/thread_repository.py`
- `verify:` `uv run --no-sync python -m pytest <focused S10 nodes> -q --timeout=30` -> `pass`
- `verify:` `uv run --no-sync ruff check <S10 paths>` -> `pass`
- `verify:` `uv run --no-sync ty check <S10 paths>` -> `pass`
- `verify:` `uv run --no-sync python -m pytest <three S10 formal-review correction nodes> -q --timeout=30` -> `pass`
- `verify:` `uv run --no-sync python -m pytest <valid-newer and stale-older recovery nodes> -q --timeout=30` -> `pass`
- `verify:` `uv run --no-sync python -m pytest <deletion refusal and archive contention nodes> -q --timeout=30` -> `pass`

## Notes

The full deletion module reached its bound without process exit during formal review. The reviewer terminated only its exact owned process tree and verified no survivor; no full-module pass is claimed. A paired cancel test command also reached 100 percent before hanging after suite completion; its exact session was interrupted, and both nodes later passed as separate normal-exit runs.

---
tags:
  - '#exec'
  - '#embedded-runtime-remediation'
date: '2026-09-06'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:555cfb5b0023e6de5b977fd9aab914f56e270d24eb85eedf3fc4c8e3f09891eb'
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

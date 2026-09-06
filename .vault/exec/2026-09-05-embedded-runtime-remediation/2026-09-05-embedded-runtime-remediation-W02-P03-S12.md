---
tags:
  - '#exec'
  - '#embedded-runtime-remediation'
date: '2026-09-06'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:30587881097d5f180b4715adda506d44f3fa8c751721a88945a7ed19a135368b'
step_id: 'S12'
related:
  - "[[2026-09-05-embedded-runtime-remediation-plan]]"
---
# Persist request-scoped checkpoint incorporation evidence for graph actions before reporting application, retaining dispatch identity and winning payload fingerprint; use durable cessation or no-op evidence for cancellation without graph incorporation

## Scope

- `src/vaultspec_a2a/{control`
- `database`
- `thread`
- `ipc`
- `worker} graph-action receipt admission`
- `persistence and incorporation`

## Changes

- `M` `src/vaultspec_a2a/control/clarification_service.py`
- `M` `src/vaultspec_a2a/control/direct_control_recovery.py`
- `M` `src/vaultspec_a2a/control/dispatch.py`
- `M` `src/vaultspec_a2a/control/dispatch_receipts.py`
- `M` `src/vaultspec_a2a/control/message_service.py`
- `M` `src/vaultspec_a2a/control/permission_service.py`
- `M` `src/vaultspec_a2a/control/thread_service.py`
- `M` `src/vaultspec_a2a/control/verdict_subscriber.py`
- `M` `src/vaultspec_a2a/control/tests/test_dispatch_receipts.py`
- `M` `src/vaultspec_a2a/control/tests/test_thread_service_tokens.py`
- `M` `src/vaultspec_a2a/database/models.py`
- `M` `src/vaultspec_a2a/database/graph_receipt_repository.py`
- `M` `src/vaultspec_a2a/database/migrations/versions/0018_graph_action_receipts.py`
- `M` `src/vaultspec_a2a/ipc/schemas.py`
- `M` `src/vaultspec_a2a/thread/action_receipts.py`
- `M` `src/vaultspec_a2a/thread/tests/test_action_receipts.py`
- `M` `src/vaultspec_a2a/worker/app.py`
- `M` `src/vaultspec_a2a/worker/executor.py`
- `M` `src/vaultspec_a2a/worker/tests/test_executor.py`

- `verify:` `bounded runner: initial admission, receipt ownership and real worker incorporation` -> `pass`

## Notes

Partial S12 implementation. Cancellation cessation/no-op evidence, atomic follow-up admission and complete receipt consumption remain open in the recovery architecture audit. S12 remains unchecked; these focused passes do not establish complete recovery or a green worker suite.
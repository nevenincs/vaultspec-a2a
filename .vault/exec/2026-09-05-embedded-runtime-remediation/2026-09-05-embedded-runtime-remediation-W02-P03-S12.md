---
tags:
  - '#exec'
  - '#embedded-runtime-remediation'
date: '2026-09-06'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:388da82519dfe6ee928cf4acd33982c380c6f578535dc74ee324e16465054f88'
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

- `M` `src/vaultspec_a2a/control/action_lease.py`
- `M` `src/vaultspec_a2a/database/session.py`

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

Partial S12 implementation. Continuing verification: atomic acceptance and database bootstrap passed four tests in 39.19 seconds with bounded runner exit 0. Cancellation cessation/no-op evidence, atomic follow-up admission and complete receipt consumption remain open in the recovery architecture audit. S12 remains unchecked; these focused passes do not establish complete recovery or a green worker suite.

## Acceptance projection transaction correction

- `M` `src/vaultspec_a2a/control/action_lease.py`
- `M` `src/vaultspec_a2a/control/cancel_service.py`
- `M` `src/vaultspec_a2a/control/clarification_service.py`
- `M` `src/vaultspec_a2a/control/direct_control_recovery.py`
- `M` `src/vaultspec_a2a/control/message_service.py`
- `M` `src/vaultspec_a2a/control/permission_service.py`
- `M` `src/vaultspec_a2a/control/verdict_subscriber.py`
- `M` `src/vaultspec_a2a/database/permission_repository.py`
- `M` `src/vaultspec_a2a/control/tests/test_dispatch_receipts.py`
- `verify:` `bounded real SQLite aborted/finalized acceptance discriminator` -> `pass`
- `verify:` `focused production Ty` -> `pass`

S12 remains open for complete accepted effective inputs, initial receipt atomicity, pure delivery binding and cancellation evidence. The removed implicit-commit API has no compatibility alias.

## Initial receipt and delivery boundary correction

- `M` `src/vaultspec_a2a/control/dispatch_receipts.py`
- `M` `src/vaultspec_a2a/control/recovery_authority.py`
- `M` `src/vaultspec_a2a/control/thread_service.py`
- `verify:` `real HTTP committed initial receipt before delivery` -> `pass`
- `verify:` `missing-receipt refusal initial fixture` -> `fail`
- `verify:` `missing-receipt refusal with required active project` -> `pass`
- `verify:` `receipt revision preservation and stale writer refusal` -> `pass`

Initial receipt atomicity and pure delivery binding are corrected. S12 remains open for complete noninitial effective inputs, project validation before acceptance and cancellation evidence.

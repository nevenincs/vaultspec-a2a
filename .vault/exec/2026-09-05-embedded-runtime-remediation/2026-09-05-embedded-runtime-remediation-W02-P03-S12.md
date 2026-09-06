---
tags:
  - '#exec'
  - '#embedded-runtime-remediation'
date: '2026-09-06'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:6ce6f3e010a0fa7ed04726fc1375dc042a31e0deebe34dd490652e4e673f2f9f'
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

## Current-input checkpoint and handoff

- `A` `src/vaultspec_a2a/control/accepted_input.py`
- `A` `src/vaultspec_a2a/control/tests/test_accepted_input_recovery.py`
- `M` `src/vaultspec_a2a/control/action_lease.py`
- `M` `src/vaultspec_a2a/control/dispatch_receipts.py`
- `M` `src/vaultspec_a2a/control/thread_service.py`
- `M` `src/vaultspec_a2a/control/message_service.py`
- `M` `src/vaultspec_a2a/control/permission_service.py`
- `M` `src/vaultspec_a2a/control/clarification_service.py`
- `M` `src/vaultspec_a2a/control/verdict_subscriber.py`
- `M` `src/vaultspec_a2a/control/cancel_service.py`
- `M` `src/vaultspec_a2a/control/direct_control_recovery.py`
- `M` `src/vaultspec_a2a/control/_thread_metadata.py`
- `M` `src/vaultspec_a2a/thread/dispatch_policy.py`
- `M` `src/vaultspec_a2a/api/app.py`
- `M` `src/vaultspec_a2a/control/tests/test_dispatch_receipts.py`
- `M` `src/vaultspec_a2a/control/tests/test_recovery_authority.py`
- `M` `src/vaultspec_a2a/control/tests/test_thread_service_tokens.py`
- `verify:` `bounded test_dispatch_receipts -k share_acceptance-or-retry_preserves, three cases` -> `pass`
- `verify:` `bounded test_thread_service_tokens -k tokens_to_worker, one case` -> `pass`
- `verify:` `bounded test_accepted_input_recovery, two cases` -> `pass`
- `verify:` `bounded test_recovery_authority -k direct, session 45164` -> `fail`
- `verify:` `focused production/test Ty and Ruff` -> `pass`

S12 remains OPEN. Complete non-secret dispatch fields and preclaim follow-up/resume project checks are implemented. Still required: freeze executable graph/runtime step limits for the execution deadline; durable cancellation cessation/no-op evidence; finish worker/event/checkpoint consolidation and durable retry/refusal ownership through S11/S13/S83; replace retired contract tests in S84. Do not restore compatibility aliases or partial-payload interpretation.

Next command: `.venv/Scripts/python.exe -m vaultspec_a2a.testing.runner --run-timeout 60 --exit-timeout 5 -- src/vaultspec_a2a/control/tests/test_recovery_authority.py -q -k direct`. This is an unresolved discriminator, not permission to repeat until green. If it fails or hangs, retain FAIL and inspect only the exact owned process tree. Read the recovery architecture audit before extending the implementation. The next source focus is frozen graph/runtime deadline authority, followed by durable scheduler storage and checkpoint-first worker/event consumers.

The failed owned run reported no pytest session result within 60 seconds and tree_reaped=true. Its exact process census ended with zero survivors (45060, 7524, 38412, 67312, 2504, 50768, 64392). The guarded cleanup found that tree already gone. There are no active owned verification sessions to resume at handoff. Parent-owned provider files are outside this checkpoint.
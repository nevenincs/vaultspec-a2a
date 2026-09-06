---
tags:
  - '#exec'
  - '#embedded-runtime-remediation'
date: '2026-09-06'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:ecdcd0c3e03a04494c6e466872494697bc1502935da94dc432a65a3ba044424b'
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

## Frozen executable-program checkpoint

- `A` `src/vaultspec_a2a/thread/executable_graph.py`
- `A` `src/vaultspec_a2a/control/graph_definition.py`
- `A` `src/vaultspec_a2a/worker/tests/test_frozen_graph_authority.py`
- `M` `src/vaultspec_a2a/control/accepted_input.py`
- `M` `src/vaultspec_a2a/graph/compiler.py`
- `M` `src/vaultspec_a2a/worker/graph_lifecycle.py`
- `M` `src/vaultspec_a2a/worker/executor.py`
- `M` `src/vaultspec_a2a/ipc/schemas.py`
- `M` `src/vaultspec_a2a/thread/state.py`
- `verify:` `bounded frozen graph battery, first attempt` -> `fail`
- `verify:` `bounded frozen graph, accepted redrive and receipt battery, 11 cases in 7.45 seconds` -> `pass`
- `verify:` `bounded recovery authority and initial HTTP battery, 11 cases in 4.53 seconds` -> `pass`
- `verify:` `focused changed source Ty` -> `pass`

Accepted-action-input-v2 now carries the complete executable-graph-v1 team/agent/supervisor definition and a declared positive step timeout. Worker graph compilation and resume consume accepted authority without reloading team files or deriving recursion defaults. Cache/checkpoint identity includes the definition digest. Later actions read the initial receipt-bound graph definition; delivery validates full request equality before attaching its stored receipt. The failed first attempt was an exact fixture identity mismatch (coder versus mock-coder-success), not a production fallback; the fixture now freezes the declared worker through the real catalog.

S12 remains OPEN. Next architecture work: durable cancellation cessation/no-op proof; review later-action provider/project metadata against the initial accepted authority; then S11/S13 checkpoint-first worker/event consumers and S83 durable retry owner/deadline derivation. S84 must migrate explicit compiler timeout, current accepted-input and checkpoint/cache fixtures. Do not infer a run deadline from this step limit alone. Do not restore aliases or defaults to make historical tests pass.

Final review discriminator: bounded recovery-authority and dispatch-receipt battery passed 11 cases in 6.97 seconds after adding the receipt-bound initial definition read and changed outgoing recursion refusal. All three passing batteries exited with code zero. Exact census found zero survivors for observed PIDs 62052, 68868, 39532, 52724, 66928, 20648, 66876 and 42156; no test session remains active.

Commands: `.venv/Scripts/python.exe -m vaultspec_a2a.testing.runner --run-timeout 60 --exit-timeout 5 -- src/vaultspec_a2a/worker/tests/test_frozen_graph_authority.py src/vaultspec_a2a/control/tests/test_accepted_input_recovery.py src/vaultspec_a2a/control/tests/test_dispatch_receipts.py -q -o addopts=`; the second substituted `test_recovery_authority.py` and `test_thread_service_tokens.py`; the final substituted `test_recovery_authority.py` and `test_dispatch_receipts.py`.

Next command: inspect `src/vaultspec_a2a/control/cancel_service.py` and `src/vaultspec_a2a/worker/executor.py` cancellation handling against the durable cessation/no-op contract before extending S12. The earlier direct-recovery owned-run failure remains preserved above; these later completed runs do not erase it.
## Durable cancellation disposition checkpoint

- `A` `src/vaultspec_a2a/thread/cancellation_evidence.py`.
- `M` worker executor/state projection, gateway event settlement, terminal effects and result vocabulary.
- A worker cancellation terminal can now carry one closed `cancellation-evidence-v1` object binding the accepted cancel dispatch identity to either `ceased` or `no_active_work`.
- The no-active worker path emits `no_active_work`; an active run retains the exact cancel identity until its cancelled settle consumes it as `ceased`. Evidence is one-shot and cannot attach to a non-cancelled terminal.
- Gateway settlement validates the schema, exact latest cancel dispatch id and current thread writer authority before applying the cancel action. It persists the disposition as `cancelled_ceased` or `cancelled_no_active_work`.
- An absent, malformed or mismatched cancellation proof may still report a terminal observation, but it leaves the cancel action leased/unapplied and does not claim `last_applied_action=cancel`.

Formal review findings:

- HIGH / false application: any cancelled terminal previously applied the latest cancel row without action identity -> resolved for cancellation settlement.
- HIGH / missing semantic outcome: worker terminals could not distinguish active cessation from a no-start/no-active no-op -> resolved with the closed two-member evidence vocabulary.
- HIGH / false projection: terminal effects claimed cancel as the last applied action even when no cancel action existed -> resolved; the claim now requires validated cancellation evidence.
- HIGH / consumer election: `_handle_terminal_event` still writes terminal lifecycle status through the older unconditional terminal consumer before cancellation evidence validation. S13 remains responsible for exact terminal writer election; this checkpoint only prevents unproven cancel-action settlement.
- HIGH / delivery durability: evidence becomes durable when the gateway commits it to the control action. Worker crash or exhausted event delivery before that commit leaves an unresolved cancellation lease; S14/S83 still own durable delivery/retry.
- HIGH / completion race: active work can still complete concurrently with cancellation before the ingest loop observes its cancel event. S20-S22/S54 remain required for wakeup, cleanup and terminal-winner proof.
- MEDIUM / verification: full-file Ty for `worker/tests/test_executor.py` remains blocked by its already queued four-member graph cache fixtures. Changed production files and the other changed tests pass Ty; Ruff passes all changed files.

Verification evidence:

- Four exact/missing/mismatched gateway settlement cases passed in 16.77 seconds.
- Producer, transport and consumer selection passed eight cases in 6.99 seconds.
- Full event-handler plus state-projection modules passed 24 cases in 8.77 seconds.
- No-active and active retained-identity executor producer cases plus projector discriminators passed in the focused gates; the latest three-case producer gate passed in 0.33 seconds before the active retained-identity case was added, and the final eight-case combined gate includes it.
- Focused production/test Ruff and production plus event/projector Ty passed.

S12 remains open for the named S13/S14/S20-S22 authority consumers and later-action provider/project qualification. This checkpoint closes cancellation evidence shape and exact cancel-action settlement only.

---
tags:
  - '#exec'
  - '#embedded-runtime-remediation'
date: '2026-09-06'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:3305fef5bcc7747f89c220d3388105faee811ba68324d96f2bd010307995ba6c'
step_id: 'S83'
related:
  - "[[2026-09-05-embedded-runtime-remediation-plan]]"
---
# Persist one leased recovery attempt per run revision and action receipt with classified condition, attempt count, next eligible attempt and run-derived deadline; drain it during startup and ordinary operation so circuit-open, capacity, typed rejection and transport loss cannot strand accepted work or depend on client polling

## Scope

- `src/vaultspec_a2a/database/models.py`
- `src/vaultspec_a2a/database/migrations`
- `src/vaultspec_a2a/control/recovery.py`

## Changes

- `M` `src/vaultspec_a2a/control/direct_control_recovery.py`
- `M` `src/vaultspec_a2a/control/tests/test_direct_control_recovery_current.py`
- `A` `src/vaultspec_a2a/control/recovery.py`
- `A` `src/vaultspec_a2a/control/tests/test_recovery_attempt_repository.py`
- `A` `src/vaultspec_a2a/database/migrations/versions/0019_recovery_attempts.py`
- `M` `src/vaultspec_a2a/database/models.py`
- `M` `src/vaultspec_a2a/database/__init__.py`
- `M` `src/vaultspec_a2a/database/_helpers.py`
- `M` `src/vaultspec_a2a/database/admin.py`
- `M` `src/vaultspec_a2a/thread/enums.py`
- `verify:` `complete current direct-control recovery module, three cases in 21.63 seconds` -> `pass`
- `verify:` `strengthened permanent project-refusal discriminator, one case in 5.27 seconds` -> `pass`
- `verify:` `durable recovery repository, three real SQLite cases in 3.17 seconds` -> `pass`
- `verify:` `model-to-migration parity, 56 cases in 8.77 seconds` -> `pass`
- `verify:` `focused Ruff and Ty` -> `pass`
- `verify:` `combined repository, parity and migration-authority lane` -> `fail: owner reaped at 60 seconds after 65 emitted cases without a session result; no emitted case counted`

## Notes

The first S83 increment removed the permanent-refusal retry loop. An impossible exact current accepted action is locked, revalidated, moved to RECONCILING when needed, settled as `rejected_invalid_state`, and marked `operator_intervention_required` with its typed refusal reason.

The second increment installs the durable schedule authority. `recovery_attempts` carries an exact current writer identity, closed condition, positive attempt count, next eligibility, mandatory immutable deadline, renewable claim and settlement timestamp. Database constraints reject incomplete claims, invalid ordering, unknown conditions, unsupported action kinds and malformed receipt identities. The producer locks and revalidates the current thread and accepted action before creating or advancing the one row allowed for that writer. Due work is claimed with a bounded compare-and-set page; reschedule and settlement require the exact claim token. Migration 0019 refuses a populated store because missing retry history and deadlines cannot be reconstructed.

Formal review findings:

- HIGH / infinite permanent-refusal loop: recovery made an impossible accepted action immediately eligible forever -> resolved in `955ede7b`.
- HIGH / missing durable schedule authority: no row could name classification, attempt, eligibility, deadline or lease ownership -> resolved in the current schema increment.
- HIGH / fabricated or stale retry identity: an unvalidated caller could otherwise create retry work for a writer that did not own the thread -> resolved by locked exact thread and action revalidation.
- HIGH / runtime producer adoption: dispatch failures do not yet create or advance the durable schedule -> open in S83.
- HIGH / missing ordinary-operation owner: the gateway still runs startup recovery plus at most one lease-delay retry -> open in S83/S14.
- HIGH / permanent classification queryability: the refusal type is still durable only in repair prose until permanent outcomes write a settled attempt -> open in S83.
- MEDIUM / settled-ledger retention: settled attempts are retained with the permanent run record and currently have no independent bound -> queued for the storage-retention work after scheduler adoption establishes required history.
- MEDIUM / recovery precedence: checkpoint-proven completion may supersede a project refusal -> intentional durable truth precedence; the scheduler matrix still needs the explicit proof in S84.

S83 remains open.
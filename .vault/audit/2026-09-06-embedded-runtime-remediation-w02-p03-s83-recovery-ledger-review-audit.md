---
tags:
  - '#audit'
  - '#embedded-runtime-remediation'
date: '2026-09-06'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:051361be3caa1109ecacf973ba009623c8812406e9c95c035dd35bb042610fa5'
related:
  - "[[2026-09-05-embedded-runtime-remediation-plan]]"
  - "[[2026-09-05-embedded-runtime-remediation-adr]]"
  - "[[2026-09-06-embedded-runtime-remediation-recovery-architecture-audit]]"
  - "[[2026-09-05-embedded-runtime-remediation-W02-P03-S83]]"
---
# S83 durable recovery ledger review

## Scope

Formal review of the S83 schema and repository increment against the binding recovery ADR amendments and the current-only product boundary.

## Findings

### s83-runtime-producer-adoption | high | open

Dispatch failures still return through `direct_control_recovery.py` without creating or advancing the new durable recovery schedule. Until producer adoption lands, the schema is present but cannot prevent stranded accepted work.

### s83-ordinary-operation-owner | high | open

The gateway still owns startup recovery plus a single lease-delay retry. A periodic, cancellation-safe owner must drain due records during ordinary operation, independent of client reads and new execution demand.

### s83-permanent-classification-row | high | open

Permanent reconstruction refusals are quarantined and typed in repair prose, but their classification is not yet independently queryable. They must write an immediately settled recovery record under the same exact authority.

### s83-fabricated-retry-authority | high | resolved

The first repository draft accepted a structurally valid tuple without proving it owned the current thread and unapplied accepted action. The final implementation locks and checks the exact thread authority and matching action receipt before any insert or increment.

### s83-schema-invariant-locality | high | resolved

The first draft enforced schedule ordering and complete claim pairs only in Python. The final model and migration enforce positive attempts, ordered eligibility/deadline timestamps, complete claim pairs, unclaimed settlement, closed conditions, current recoverable actions and bounded receipts in the database.

### s83-settled-ledger-retention | medium | queued

Settled attempts remain with the permanent run history and have no separate count or age bound. Preserve them through scheduler adoption because they are the only independent classification and attempt history; measure growth and decide retention in the storage-retention pass.

### s83-broad-combined-test-timeout | medium | queued

A combined repository, schema-parity and migration-authority run emitted 65 passing cases but produced no final session result within 60 seconds and was reaped. Isolated repository and schema-parity lanes exited naturally and passed. Continue using narrow bounded lanes while host contention remains active.

## Verification

- Durable repository: 3 passed in 3.17 seconds against real file-backed SQLite.
- Model/migration parity: 56 passed in 8.77 seconds through the real Alembic chain.
- Ruff and Ty: passed for the changed production and test modules.
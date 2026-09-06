---
tags:
  - '#exec'
  - '#embedded-runtime-remediation'
date: '2026-09-06'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:23bfe0f771ec98cc5d5c6938e693422c294be6705a76f261c7c7a1d9e474b480'
step_id: 'S11'
related:
  - "[[2026-09-05-embedded-runtime-remediation-plan]]"
---
# Replace fragmented startup redispatch, read-time abandonment and pre-election projection with one durable recovery coordinator covering conditions 1-16

## Scope

- `src/vaultspec_a2a/control/recovery.py`
- `src/vaultspec_a2a/control/dispatch.py`
- `src/vaultspec_a2a/control/run_discovery_service.py`
- `src/vaultspec_a2a/control/thread_state_service.py`

## Changes

- `M` `src/vaultspec_a2a/control/dispatch.py`
- `M` `src/vaultspec_a2a/control/run_discovery_service.py`
- `M` `src/vaultspec_a2a/control/tests/test_reconciling_abandonment.py`
- `M` `src/vaultspec_a2a/control/tests/test_redispatch_failure_ladder.py`
- `A` `.vault/audit/2026-09-06-embedded-runtime-remediation-w02-p03-s11-abandoned-election-audit.md`
- `A` `.vault/research/2026-09-06-embedded-runtime-remediation-w02-p03-s11-abandoned-election-research.md`
- `verify:` `focused 14-case S11 pytest gate` -> `pass`
- `verify:` `two exact post-adjustment nodes` -> `pass`
- `verify:` `uv run ruff check <S11 paths>` -> `pass`
- `verify:` `uv run ty check <S11 paths>` -> `pass`

## Notes

Commit `4001cc77` is a partial implementation and received formal **FAIL**. Active discovery can serve one pre-election `reconciling` projection after a newer terminal writer wins, and the test checks only durable state. The plan and binding ADRs now replace split recovery ownership with one durable coordinator covering conditions 1-16. The Step remains open.

The focused pytest command emitted `14 passed in 25.05s` but did not exit naturally by 30 seconds. Exact session `74355` was interrupted and no matching pytest process survived. Condition 17 is now explicit plan Step S85 under the verification lifecycle owner.

## Partial coordinator correction

- `A` `src/vaultspec_a2a/control/recovery_authority.py`
- `A` `src/vaultspec_a2a/thread/checkpoint_evidence.py`
- `A` `src/vaultspec_a2a/control/tests/test_recovery_authority.py`
- `M` `src/vaultspec_a2a/control/run_discovery_service.py`
- `M` `src/vaultspec_a2a/control/thread_state_service.py`
- `M` `src/vaultspec_a2a/database/reconciliation.py`
- `M` `src/vaultspec_a2a/api/app.py`
- `M` `src/vaultspec_a2a/api/routes/gateway.py`
- `M` `src/vaultspec_a2a/control/config.py`
- `M` `src/vaultspec_a2a/lifecycle/__init__.py`
- `D` `src/vaultspec_a2a/lifecycle/reconciliation.py`
- `verify:` `two combined four-case bounded runner invocations` -> `fail`
- `verify:` `isolated startup discriminator and split current five-case evidence` -> `pass`

S11 remains open. Worker/event consumers, invalid-receipt quarantine, frozen execution deadlines and durable leased retries remain required. This pass does not replace the failed historical evidence above with a whole-step success claim.
## Fresh active-projection checkpoint

- `A` `src/vaultspec_a2a/control/tests/test_run_discovery_fresh_projection.py`
- `review:` HIGH stale served projection from `4001cc77` -> resolved by the unconditional post-recovery query in `99dbf79d`.
- `review:` MEDIUM missing public response race coverage -> resolved by the real-SQLite discovery discriminator.
- `verify:` canonical bounded focused test -> one passed in 4.51 seconds, natural exit 0.
- `verify:` focused Ruff and Ty -> pass.

S11 remains open for its recorded worker/event, quarantine, frozen-deadline and durable retry/refusal scope. This checkpoint closes only the stale served-projection review failure and its missing measurement.

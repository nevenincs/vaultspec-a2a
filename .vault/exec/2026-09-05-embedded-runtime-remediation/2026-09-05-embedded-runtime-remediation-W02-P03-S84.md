---
tags:
  - '#exec'
  - '#embedded-runtime-remediation'
date: '2026-09-06'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:117734ee66453563b06132683d0d08519f4234a234ae5605224d93b9b1092f8e'
step_id: 'S84'
related:
  - "[[2026-09-05-embedded-runtime-remediation-plan]]"
---
# Verify the recovery architecture against the complete conditions 1-16 matrix using real durable receipts and fresh projections

## Changes

- `D` `src/vaultspec_a2a/control/tests/test_reconciling_abandonment.py`
- Removed assertions for the retired read-time abandonment helper, mutable preset reload, and invented 300-second recovery floor.
- Current checkpoint-first recovery, startup demotion, and fresh served projection tests retain the valid behavioral coverage.
- No production compatibility alias or test-only legacy implementation was introduced.

## Review findings

- HIGH retired abandonment contract blocked collection and asserted invalid authority -> resolved.
- HIGH six control test modules still import removed `claim_control_action` -> open and queued for the next S84 migration increment.
- S84 remains unchecked; the complete conditions 1-16 matrix is not yet qualified.

## Verification

- Canonical control-test collection after deletion -> fail, 439 tests collected and six exact import errors.
- The failure exited naturally with code 1 under the bounded owner.
- Remaining failing modules: `test_direct_control_leases.py`, `test_direct_control_recovery.py`, `test_event_handlers.py`, `test_verdict_loop_live.py`, `test_verdict_subscriber.py`, and `test_verdict_subscriber_live.py`.

## Next action

Migrate each retained scenario to explicit prepare/finalize acceptance with a real current receipt. Delete scenarios whose only purpose is the removed implicit-commit contract. Do not add `claim_control_action` back under any name or provide partial-payload interpretation.
## Populated pre-current action test removal

- `D` retired `test_pre_0012_action_is_backfilled_and_claimable` from `src/vaultspec_a2a/database/tests/test_migrations.py`.
- Removed its import of the deleted implicit-commit claim API.
- HIGH legacy backfill/claimability expectation -> resolved by deletion.
- `verify:` canonical database-test collection -> 385 tests collected, natural exit 0.
- `verify:` focused Ty -> pass.
- `verify:` focused Ruff initially reported import grouping after deletion; corrected before commit.

S84 remains open for the six recorded control-test modules and the complete conditions matrix.

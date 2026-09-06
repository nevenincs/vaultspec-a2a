---
tags:
  - '#exec'
  - '#embedded-runtime-remediation'
date: '2026-09-06'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:ac2df0860b75131dd9dd396da3d8add1b9575285241e75e1809bbc85774c8ef0'
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
## Event settlement fixture migration

- `M` `src/vaultspec_a2a/control/tests/test_event_handlers.py`.
- Replaced the removed implicit claim helper with explicit current journal creation and lease acquisition for the exact state consumed by event settlement.
- Did not create accepted-action payloads: the event consumer does not validate them, which preserves the existing S13 high-severity receipt-consumer finding instead of manufacturing false authority.
- `verify:` focused event-handler suite -> 12 passed in 15.44 seconds, natural exit 0.
- `verify:` focused Ruff and Ty -> pass.
- `verify:` canonical control collection -> 452 collected with five import errors, natural exit 1.
- Remaining collection failures: `test_direct_control_leases.py`, `test_direct_control_recovery.py`, `test_verdict_loop_live.py` through its live-subscriber import, `test_verdict_subscriber.py`, and `test_verdict_subscriber_live.py`.

S84 remains open. The collection blocker count fell from six modules to five; S13 still owns durable receipt validation by terminal event consumers.

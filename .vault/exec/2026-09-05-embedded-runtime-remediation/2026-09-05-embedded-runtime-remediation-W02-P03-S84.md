---
tags:
  - '#exec'
  - '#embedded-runtime-remediation'
date: '2026-09-06'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:f35b81af318e67a804650aa2fce282b95824ddedf275208661c73d35f910775f'
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
## Retired verdict-lease test removal

- `M` `src/vaultspec_a2a/control/tests/test_verdict_subscriber.py`.
- `M` `src/vaultspec_a2a/control/tests/test_verdict_subscriber_live.py`.
- Deleted the expired and fresh verdict-lease scenarios because they constructed the removed partial verdict payload through the retired implicit claim API.
- No skipped test, alias, compatibility fixture, partial accepted input, or default reconstruction remains.
- `verify:` canonical control collection -> 474 of 480 tests collected, six deselected, with two remaining import errors; natural exit 1.
- `verify:` verdict subscriber unit suite -> 20 passed and two failed in 24.39 seconds; natural exit 1.
- `verify:` focused Ruff -> pass.
- `verify:` focused Ty -> fail on three four-member graph cache fixtures that lack the required executable-graph digest.

Open review queue:

- HIGH: current accepted-input tests must replace proof of expired verdict redrive and fresh-lease duplicate suppression; deletion does not qualify those behaviors.
- HIGH: `test_verdict_subscriber.py`, `test_verdict_subscriber_live.py`, and `test_verdict_loop_live.py` retain pre-current four-member graph cache keys and must bind the exact frozen graph digest.
- HIGH: `test_direct_control_leases.py` and `test_direct_control_recovery.py` are the last two collection blockers importing the retired claim API.

S84 remains open.
## Direct-control lease contract retirement

- `M` `src/vaultspec_a2a/control/tests/test_direct_control_leases.py`.
- Deleted the visible fresh-cancel-lease-without-authority scenario: current acceptance commits lease and thread authority atomically, so another session cannot observe that intermediate state.
- Deleted the restart test that persisted three partial legacy payloads; complete accepted-input recovery remains covered by `test_accepted_input_recovery.py`, while action-specific recovery coverage remains open in `test_direct_control_recovery.py`.
- Removed the retired implicit claim and direct-recovery imports.
- `verify:` isolated direct-control lease collection -> eight tests collected in 20.16 seconds, natural exit 0.
- `verify:` focused Ruff initially found one now-removed unused import.
- `verify:` focused Ty -> fail on the file's existing four-member graph cache key, which lacks the frozen graph-definition digest.
- `verify:` one parallel focused suite and one parallel full collection each reached the 90-second owner deadline without a pytest session result; both reported `tree_reaped=true` and are classified FAIL.

Open review queue:

- HIGH: migrate the direct-control graph fixture to an exact accepted five-member cache identity before counting runtime results.
- HIGH: migrate `test_direct_control_recovery.py` from partial action payloads to accepted-action-input-v2; it is now the final retired-import collection blocker.
- MEDIUM: do not run two cold control suites concurrently on this host; the bounded owners prevented hangs but resource contention consumed both deadlines.

S84 remains open.

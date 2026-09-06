---
tags:
  - '#exec'
  - '#embedded-runtime-remediation'
date: '2026-09-06'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:4b533f92428dc6ce706d31a88a56fcb8ea66664d3ebcd1c691914fd6a7277b8f'
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
## Final retired-import removal

- `D` `src/vaultspec_a2a/control/tests/test_direct_control_recovery.py`.
- Deleted the fixture because every recovery row carried a partial pre-current payload and installed thread authority in a later manual election, contradicting accepted-action-input-v2 and atomic acceptance.
- `verify:` canonical control collection -> 482 of 488 tests collected, six service deselections, no collection errors, 1.94 seconds, natural exit 0.

Open review queue:

- HIGH: replace active-project refusal, complete three-action stable-ID redrive, and stale-action refusal with accepted-action-input-v2 plus exact receipts and frozen graph definitions.
- HIGH: collection surfaced `test_ensure_worker_adopts_legacy_missing_or_blank_target`; the no-legacy audit must remove both that expectation and any corresponding production adoption path.
- Existing HIGH graph-cache identity, receipt-consumer, cancellation-proof and recovery scheduler findings remain open.

All retired `claim_control_action` imports are gone from control tests. S84 remains open because collection health is only a prerequisite to the complete conditions 1-16 matrix, not qualification.
## Verdict subscriber frozen-graph migration

- `M` `src/vaultspec_a2a/control/tests/test_verdict_subscriber.py`.
- Parked resume fixtures now persist an accepted initial action with accepted-action-input-v2, its immutable receipt, the exact frozen graph definition, and current model assignment.
- Checkpoint state and the injected compiled-graph cache key now carry the matching model-assignment and graph-definition digests.
- Replaced the invented `verdict-receipt-preset` identity with the real `mock-success-single` definition.
- `verify:` focused Ruff and Ty -> pass.
- `verify:` subscriber suite -> 20 passed and two failed in 14.28 seconds, natural exit 1.
- `verify:` the two migrated dispatch cases -> two failed in 9.69 seconds, natural exit 1.

Open review queue:

- HIGH: both current-authority dispatches now reach the ASGI worker but receive HTTP 500 before dispatch admission; align the worker fixture with the current dispatch-auth contract and preserve exact credential behavior.
- HIGH: apply the same accepted initial authority and exact cache-key migration to the live subscriber and verdict-loop fixtures.
- The prior graph-cache identity finding is resolved only for `test_verdict_subscriber.py`.

S84 remains open.
## Verdict subscriber dispatch lifecycle correction

- `M` `src/vaultspec_a2a/control/tests/test_verdict_subscriber.py`.
- The real ASGI worker dispatch now presents an explicit current bearer credential, while the worker verifier receives the same test-only configured token. No unauthenticated fallback or compatibility branch was introduced.
- The executor's event bridge now targets a real in-process ASGI event receiver instead of a dead TCP port, so verdict race verification measures journal election and dispatch rather than IPC retry exhaustion.
- Parked checkpoints retain the valid identifier generated by `empty_checkpoint()`; the fixture no longer replaces it with a non-hex synthetic identifier that LangGraph cannot resume.
- The competing-verdict assertion now validates `accepted-action-input-v2` and its frozen semantic `intent` instead of expecting the retired flat verdict payload.

Formal review findings:

- HIGH / contract: missing explicit current IPC authentication caused both dispatch cases to receive HTTP 500 before admission -> resolved.
- MEDIUM / verification liveness: the dead event receiver made executor settlement retry unrelated network failure and contributed to bounded-run hangs -> resolved with a real ASGI sink.
- MEDIUM / test construction: a hand-written non-UUID checkpoint id caused LangGraph startup cancellation (`binascii.Error`) -> resolved by retaining the library-generated id.
- MEDIUM / contract drift: a flat-payload assertion contradicted the required v2 accepted envelope -> resolved.
- LOW / test construction: an intermediate attempt tried to monkeypatch the read-only `environment_declared` property and produced two setup errors -> corrected by configuring the mutable current `internal_token` setting directly.

Verification evidence:

- Before lifecycle correction, the paired race run reached one marker but produced no session result within 90 seconds; the runner reported `tree_reaped=true` and the run remains classified FAIL.
- Isolated concurrent-resume verification produced no session result within 60 seconds and was reaped; classified FAIL.
- Isolated competing-payload verification exited naturally with one failure in 14.84 seconds, exposing the stale flat-payload assertion and invalid checkpoint teardown.
- After correction, both race cases passed in 38.12 seconds with natural exit 0.
- The complete subscriber module passed 22 tests in 56.19 seconds with natural exit 0.
- Focused Ruff and Ty passed.

The unit subscriber fixture's dispatch-auth and graph-cache findings are resolved. S84 remains open: live subscriber and verdict-loop fixtures still require complete accepted graph authority, and the complete conditions 1-16 qualification matrix is unfinished.
## Live verdict subscriber frozen-authority migration

- `M` `src/vaultspec_a2a/control/tests/test_verdict_subscriber_live.py`.
- Receipt-bearing parked-gate fixtures now persist the complete accepted initial action, immutable graph receipt, current model assignment, exact frozen `mock-success-single` graph, and matching checkpoint/cache digests.
- Removed the invented `verdict-receipt-preset`, four-member cache identity, synthetic non-hex checkpoint ids, and unauthenticated worker requests. No compatibility interpretation was introduced.
- Formal review found no new production defect. HIGH graph-authority and dispatch-auth fixture drift -> resolved statically; MEDIUM invalid checkpoint construction -> resolved. The event bridge still buffers the receipt for explicit event-consumer exercise and its live lifecycle remains runtime-qualified only when the declared service stack exists.
- `verify:` focused Ruff and Ty -> pass.
- `verify:` default profile -> five service cases deselected, natural exit 1 because no tests ran; not pass evidence.
- `verify:` explicit service profile -> five skips in 2.47 seconds, natural exit 0, because no healthy engine discovery record resolved. Runtime behavior is unqualified rather than blocked or inferred.

S84 remains open. The live subscriber's static current-contract migration is complete; verdict-loop migration and live service execution remain queued.
## Verdict-loop acceptance-order migration

- `M` `src/vaultspec_a2a/control/tests/test_verdict_loop_live.py`.
- Initial ingest is now accepted durably before worker delivery: the thread, complete accepted-action-input-v2, stable dispatch id, immutable graph receipt, current provider assignment, frozen graph definition and metadata commit before the exact request crosses `/dispatch`.
- Worker dispatch uses explicit current bearer authentication. The cache identity has all five current members and binds the frozen graph digest; the invented `verdict-loop-live` preset and constant four-member key are removed.
- The permission row and INPUT_REQUIRED projection remain after the real graph parks, preserving their actual temporal role.
- `verify:` focused Ruff and Ty -> pass.
- `verify:` explicit service profile -> one skip in 1.76 seconds, natural exit 0, because no healthy engine discovery record resolved. Runtime behavior remains unqualified.

Formal review queue:

- HIGH / proof integrity: this service test deliberately injects a purpose-built phase-gate compiled graph, while the frozen executable definition names the catalog `mock-success-single` program. The five-member identity and accepted-delivery ordering are current, but the test does not prove that the cached compiled object was produced from the receipt-bound definition. Resolve by compiling the test graph from durable declarative authority or by running the actual receipt-bound compiler topology; do not bless arbitrary injected graphs through a digest-only fixture.
- HIGH / scope: the same injected-graph limitation applies to the unit and live subscriber receipt fixtures migrated earlier. Their identity plumbing is current, but semantic compiler provenance remains unqualified.

S84 remains open for semantic compiled-graph provenance, live service execution, current action-recovery replacements and the complete conditions matrix.
## Direct-control lease current-authority migration

- `M` `src/vaultspec_a2a/control/tests/test_direct_control_leases.py`.
- `M` `src/vaultspec_a2a/control/message_service.py`.
- Every nonterminal direct-control fixture now begins with a complete accepted initial graph action, immutable receipt, active project, frozen `mock-success-single` definition and current provider assignment. The receipt graph uses the matching five-member identity and exact authenticated worker dispatch.
- The worker event bridge now uses a real in-process receiver, and receipt settlement observes either buffered or already-relayed events. Dead-port retry time is removed from the lease behaviors.
- An authority-mismatch response now preserves the durable `claim.action_id` instead of erasing an already-known stable identity.

Formal review findings:

- HIGH / contract: message and permission fixtures without initial accepted graph authority failed before their intended behavior -> resolved by one current thread-authority builder.
- HIGH / identity: the losing authority-mismatch arm returned an empty action id despite a durable reservation -> resolved by returning the claim's stable action id.
- MEDIUM / verification liveness: the real executor relayed events to a dead port during teardown -> resolved with a real ASGI receiver.
- HIGH / concurrency: one identical-message run elected one dispatch but the losing caller transiently reported `INCOMPATIBLE_STATE` after failing receipt authority. The final stable identity is now retained, but the transaction/receipt election can still misclassify an identical concurrent retry and remains queued.
- HIGH / proof integrity: the one-node injected receipt graph is still not proven to have been compiled from its frozen definition; this joins the existing semantic compiler-provenance finding.

Verification evidence:

- Focused receipt race passed once in 6.05 seconds.
- The first full run naturally failed three cases and passed five in 13.77 seconds, exposing missing initial graph authority in retained setups.
- After current setup migration, the next full run naturally failed one case and passed seven in 49.49 seconds, exposing erased stable identity on the intermittent authority-mismatch arm.
- Final full run passed all eight cases in 22.48 seconds with natural exit 0.
- Focused Ruff and Ty passed.

S84 remains open for the identical-retry authority classification, semantic compiled-graph provenance, current recovery replacements, live service proof and the complete conditions matrix.

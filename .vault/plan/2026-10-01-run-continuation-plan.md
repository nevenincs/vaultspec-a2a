---
tags:
  - '#plan'
  - '#run-continuation'
date: '2026-10-01'
tier: L2
related:
  - '[[2026-10-01-run-continuation-adr]]'
  - '[[2026-08-02-control-action-leases-adr]]'
  - '[[2026-07-14-a2a-edge-conformance-adr]]'
  - '[[2026-08-05-served-capability-contract-state-truthfulness-adr]]'
  - '[[2026-08-02-clarification-continuation-adr]]'
modified: '2026-10-01'
body_schema: body-v2
body_hash: 'sha256:6654ca118a0affbd484c21457b5e59c7f35936c5b2d5c6cd50c67067ea977ea8'
---

# `run-continuation` plan

Make the published follow-up verb reachable: queue one continuation behind a busy run's in-flight turn, keep the typed respond verb the only answer for a parked run, and continue a settled run as a new run that names its predecessor.

## Description

Approved 2026-10-01. Basis: the user's blanket approval of this work given in session on 2026-10-01, together with the acceptance of `2026-10-01-run-continuation-adr` in that same session. That record's Implementation, Constraints and verification list are binding on every Step below; its implementation hypotheses are revisable within those constraints.

`POST /v1/runs/{run_id}/messages` is published and refuses in every lifecycle state, so the versioned surface can start a run and watch it but can never say anything further to it (`src/vaultspec_a2a/api/routes/_gateway_action_endpoints.py`, `run_message_endpoint`). This plan builds the three lifecycle answers the decision settles. A busy run (SUBMITTED, RUNNING) admits at most one queued continuation, reserved as a journal action with a lease and no receipt, promoted only once the predecessor turn's terminal checkpoint evidence commits. A parked run keeps refusing and names the typed respond verb for the pause it holds. A settled run keeps refusing, and continuation becomes a new run carrying an optional `continues_run_id`. No transition out of a terminal state is added anywhere.

Decision coverage. Every Step executes an accepted decision; no new ADR is needed and none is proposed here.

- `2026-10-01-run-continuation-adr` governs the whole plan and is the sole authority for P02 through P05.
- `2026-08-02-control-action-leases-adr` governs P01.S01, P01.S02 and P03. Its journal-owned pending delivery, one renewable dispatcher per run, per-run and service queue limits, and never-discard-accepted-work rules are the machinery promotion reuses. The run-continuation record refines the same decision by stating what makes a follow-up eligible and that a worker `run_busy` refusal is a semantic conflict, not transport failure.
- `2026-08-05-served-capability-contract-state-truthfulness-adr` governs P03.S08: T2 requires every transitional state to name the writer obliged to leave it, and T3 requires an abandoned transition to be reconciled. A run holding a queued continuation is RUNNING with no live worker for the width of the promotion window, so the promotion dispatcher is named its obliged writer and T3 treats it as owned until that action's lease expires.
- `2026-08-02-clarification-continuation-adr` governs P04.S12. The messages route is never an answer path; the refusal is narrowed to name the respond verb, and the prohibition in `.vaultspec/rules/clarifications-are-typed-interrupts.md` is unchanged and strengthened.
- `2026-07-14-a2a-edge-conformance-adr` R6 governs P06.S16, the additive cross-repository contract event.

Sequencing. P01 lands three prerequisites the decision names before anything may queue: a promotion path that retries delivery must not open the shared failure breaker first (`breaker-fed-by-backpressure`), the `run_busy` lease-retention rule must be stated and tested rather than left as an unstated change (`run-busy-not-in-the-recovery-lease-release-set`), and this verb must require a client-supplied idempotency key because two deliberate identical continuations are two turns (`content-derived-idempotency`). P02 adds the durable and configured foundation. P03 lands promotion before P04 lands admission, deliberately: with no queued rows the promotion path behaves exactly as settlement does today, whereas admission without promotion would strand an accepted continuation behind a settled run. P05 is independent of the queue and touches only the settled answer. P06 records the contract event and proves the lifecycle end to end.

Migrations. This plan adds exactly one, in P02.S04: the queue position and the queued result status on the control-action journal (`control_actions`, latest committed revision `0022`). Name it for its purpose, not for a reserved number. Three plans drafted concurrently also add migrations - stream resumption adds `run_events`, the tool permission model adds `permission_rules` and permission-log attribution, and the provider binary policy adds a runtime identity row - so revision ids and `down_revision` chains are assigned at execution in merge order, by whichever plan merges first. An executor reads `src/vaultspec_a2a/database/migrations/versions/` at the moment of writing and takes the next free id then.

Relationship to `2026-09-05-embedded-runtime-remediation-plan`. That plan is not edited by this one. Its Steps `W02.P04.S16` (atomic per-run and service queue limits, stable retry positions, conflicting-payload refusal) and `W02.P04.S17` (drain accepted messages in journal order with one renewable dispatcher per run, reconciling receipt evidence before redelivery) are superseded in substance here: `W02.P04.S16` by P02.S05, P04.S10 and P04.S11, and `W02.P04.S17` by P03.S06 and P03.S07, which give them the queue policy they were missing. `W02.P04.S18` is superseded only in its control-plane half, by P01.S01 and P01.S02; its worker-side disposition in `src/vaultspec_a2a/worker/executor.py` stays with that plan. The orchestrator closes or re-scopes those rows there once the covering Steps here land.

Expected creations. `src/vaultspec_a2a/control/repositories/continuation_queue.py` in P02.S05, one migration file in P02.S04, and `src/vaultspec_a2a/service_tests/test_run_continuation_live.py` in P06.S17. Every other path named in a Step exists today.

Open points an executor must raise rather than settle alone. The decision enumerates four schema changes and one migration; it does not say where the single-parent lineage link is persisted, so P05.S14 puts `continues_run_id` on the run's stored metadata rather than opening a second migration for a `threads` column. It also does not enumerate a served queue position on `RunMessageResponse`, which its replay rule implies; P04.S10 adds one, and that widens the contract event P06.S16 records. The service-wide cap has no served initial value in the decision, only the per-run depth of 1. The clarifying sentence the decision proposes for `2026-02-26-protocol-ecosystem-bridge-adr` is not a Step here: that record flags it as possibly belonging in the edge-conformance corpus instead.

## Steps

### Phase `P01` - Prerequisites that must hold before anything queues

A semantic refusal about one run stops opening the shared breaker, the run_busy lease rule is stated and tested, and this verb requires a client-supplied idempotency key.

- [x] `P01.S01` - Count only transport failure against the shared breaker so a worker run_busy 409 and a capacity 429 leave it closed while still refusing the dispatch; `src/vaultspec_a2a/control/dispatch.py, src/vaultspec_a2a/control/circuit_breaker.py, src/vaultspec_a2a/control/tests/test_dispatch_refusal_classification.py`.
- [x] `P01.S02` - State and test that a worker run_busy 409 retains the action lease and discards no accepted work, keeping it out of the recovery release set; `src/vaultspec_a2a/control/direct_control_recovery.py, src/vaultspec_a2a/control/tests/test_direct_control_leases.py`.
- [x] `P01.S03` - Require a client-supplied Idempotency-Key on the follow-up verb, answer 422 when it is absent, and retire the content-derived default key for this verb only; `src/vaultspec_a2a/api/routes/_gateway_action_endpoints.py, src/vaultspec_a2a/control/message_service.py, src/vaultspec_a2a/thread/idempotency.py, openapi.json`.

### Phase `P02` - Journal and configuration foundation for a queued continuation

The control-action journal can hold a queued continuation with a position, and the per-run depth, service-wide cap and maximum run lifetime are served configuration.

- [ ] `P02.S04` - Migrate the control-action journal to carry a queued continuation position and a queued result status, naming the revision for its purpose and taking the next free id at execution; `src/vaultspec_a2a/database/migrations/versions/, src/vaultspec_a2a/database/models.py, src/vaultspec_a2a/thread/enums.py`.
- [ ] `P02.S05` - Serve the per-run continuation depth, the service-wide queue cap and the maximum run lifetime as configuration, and add the journal queries that reserve, count, position and read the next queued continuation; new file src/vaultspec_a2a/control/repositories/continuation_queue.py; `src/vaultspec_a2a/domain_config.py, src/vaultspec_a2a/control/repositories/continuation_queue.py, src/vaultspec_a2a/control/repositories/__init__.py`.

### Phase `P03` - Promotion: defer terminal settlement while a continuation is queued

A proven terminal checkpoint promotes a queued continuation inside the same run write transaction instead of settling, recovers once after a crash, and the abandoned-transition reconciler treats such a run as owned.

- [ ] `P03.S06` - Check the queue inside the terminal write transaction and promote instead of settling: bind the graph action receipt, install the writer, re-derive the deadline, dispatch the ingest, leave the run RUNNING, and publish no terminal frame or settled-history prune; `src/vaultspec_a2a/control/event_handlers.py, src/vaultspec_a2a/control/dispatch_receipts.py, src/vaultspec_a2a/control/repositories/continuation_queue.py`.
- [ ] `P03.S07` - Make promotion a durable recovery attempt under the existing lease machinery so a gateway killed between settlement and dispatch promotes the same queued action exactly once on restart; `src/vaultspec_a2a/control/direct_control_recovery.py, src/vaultspec_a2a/control/recovery_authority.py`.
- [ ] `P03.S08` - Treat a run holding a queued continuation as owned by the promotion dispatcher until that action lease expires, so the abandoned-transition reconciler never settles it or drops the queued turn; `src/vaultspec_a2a/control/recovery_authority.py, src/vaultspec_a2a/database/reconciliation.py`.
- [ ] `P03.S09` - Bound the total lifetime of a run across promotions, refusing to promote past the configured maximum and settling the run with its own terminal instead; `src/vaultspec_a2a/control/event_handlers.py, src/vaultspec_a2a/control/repositories/continuation_queue.py, src/vaultspec_a2a/domain_config.py`.

### Phase `P04` - Admission: queue one continuation on a busy run

A busy run admits at most one continuation as a reserved journal action answered 202 queued, a parked run refuses by naming its own respond verb, and run-status discloses the queue depth.

- [ ] `P04.S10` - Admit SUBMITTED and RUNNING for a follow-up and reserve it as a queued journal action with no receipt, no writer and no dispatch, answering 202 with action_status queued, its position and the queue_full refusal when the per-run depth or the service-wide cap is spent; CANCELLING stays run_busy; `src/vaultspec_a2a/thread/message_policy.py, src/vaultspec_a2a/control/message_service.py, src/vaultspec_a2a/api/routes/_gateway_action_endpoints.py, src/vaultspec_a2a/api/schemas/gateway.py, src/vaultspec_a2a/thread/tests/test_message_policy.py, openapi.json`.
- [ ] `P04.S11` - Replay the queued action and its position for a repeat idempotency key and refuse a changed payload under that key with conflict; `src/vaultspec_a2a/control/message_service.py, src/vaultspec_a2a/control/action_lease.py, src/vaultspec_a2a/control/repositories/continuation_queue.py`.
- [ ] `P04.S12` - Narrow the parked refusal to name the typed respond verb for the pause the run actually holds, reading the pending request rather than guessing from status alone; `src/vaultspec_a2a/thread/message_policy.py, src/vaultspec_a2a/control/message_service.py, src/vaultspec_a2a/database/permission_repository.py, src/vaultspec_a2a/thread/tests/test_message_policy.py`.
- [ ] `P04.S13` - Disclose a bounded queued_messages count on run-status so a client reloading without a stream reads the queue depth from authoritative state; `src/vaultspec_a2a/api/routes/_gateway_read_endpoints.py, src/vaultspec_a2a/api/schemas/gateway.py, src/vaultspec_a2a/control/snapshot.py, openapi.json`.

### Phase `P05` - Settled runs continue as a new run that names its predecessor

run-start accepts an optional continues_run_id, the successor seeds its graph input from the predecessor's surviving final checkpoint, and both runs disclose the link.

- [ ] `P05.S14` - Accept an optional continues_run_id on run-start, refuse a predecessor that is not a settled run of the same workspace, record the single-parent link on the successor, and disclose it on run-status; `src/vaultspec_a2a/api/schemas/gateway.py, src/vaultspec_a2a/api/routes/_gateway_run_start.py, src/vaultspec_a2a/api/routes/_gateway_read_endpoints.py, src/vaultspec_a2a/context/metadata.py, openapi.json`.
- [ ] `P05.S15` - Seed the successor run's graph input from the predecessor's surviving final checkpoint at a configured bounded transcript depth, refusing rather than starting empty when that checkpoint is gone; `src/vaultspec_a2a/control/thread_service.py, src/vaultspec_a2a/database/checkpoints.py, src/vaultspec_a2a/domain_config.py`.

### Phase `P06` - Contract event and end-to-end proof

The R6 contract event is recorded for the dashboard, and the ADR's full verification list runs against a real gateway and worker on both database backends.

- [ ] `P06.S16` - Record the R6 contract event for the dashboard: the reachable 202 queued answer, the sixth refusal code queue_full, the queued_messages and continues_run_id disclosures, and the behavioural change that a quiet turn boundary is not completion; `.vault/adr/2026-07-14-a2a-edge-conformance-adr.md`.
- [ ] `P06.S17` - Certify the whole continuation lifecycle against a real gateway and worker: a continuation queued during a live in-flight turn runs after it with no RECONCILING and no refused terminal, one terminal frame at the second turn's end, the admission-versus-settlement race resolving to exactly one outcome, and a gateway kill between settlement and promotion promoting once on restart; new file src/vaultspec_a2a/service_tests/test_run_continuation_live.py; `src/vaultspec_a2a/service_tests/test_run_continuation_live.py, src/vaultspec_a2a/service_tests/harness.py, src/vaultspec_a2a/service_tests/_state.py`.

## Parallelization

Three executors may run at once in the first group, each in its own git worktree with disjoint write ownership. Owner A takes `P01.S01` and `P01.S02`, writing only `src/vaultspec_a2a/control/dispatch.py`, `src/vaultspec_a2a/control/circuit_breaker.py`, `src/vaultspec_a2a/control/direct_control_recovery.py` and their sibling test modules. Owner B takes `P01.S03`, writing only `src/vaultspec_a2a/api/routes/_gateway_action_endpoints.py`, `src/vaultspec_a2a/control/message_service.py` and `src/vaultspec_a2a/thread/idempotency.py`. Owner C takes `P05.S14` and `P05.S15`, writing only `src/vaultspec_a2a/api/routes/_gateway_run_start.py`, `src/vaultspec_a2a/api/routes/_gateway_read_endpoints.py`, `src/vaultspec_a2a/context/metadata.py`, `src/vaultspec_a2a/control/thread_service.py` and `src/vaultspec_a2a/database/checkpoints.py`.

Two files cross those boundaries and are serialized rather than owned. `src/vaultspec_a2a/api/schemas/gateway.py` is appended to by owners B and C and later by P04; each adds only its own fields and the orchestrator merges. `openapi.json` is generated, never hand-edited: each executor regenerates it inside its own Step with `uv run --no-sync python -m vaultspec_a2a.api.tests.test_openapi_artifact`, and the orchestrator re-runs that one command after every merge so the artifact matches the merged application. `src/vaultspec_a2a/domain_config.py` is appended to by P02.S05, P03.S09 and P05.S15; the same merge rule applies.

Everything after that group is strictly ordered and single-owner. P02 runs after the first group merges, and its two Steps are sequential because `P02.S05` queries the columns `P02.S04` adds. P03 runs after P02, one owner, Steps in order: `P03.S07` and `P03.S08` both write `src/vaultspec_a2a/control/recovery_authority.py`, and `P03.S09` writes the handler `P03.S06` changes. P04 runs after P03 and never before it, because an admitted continuation with no promotion path would be accepted work behind a settled run; its four Steps are one owner, in order, since `P04.S10`, `P04.S11` and `P04.S12` all write `src/vaultspec_a2a/control/message_service.py`. `P06.S16` may be drafted while P04 runs but is committed only once P04 and P05 are merged, so no record advertises a capability the service does not yet serve. `P06.S17` is last and single-owner.

Executors commit one Step per commit, and do not write `.vault/`. The orchestrator logs rows, closes Steps and merges. `P06.S16` is the one Step whose scope is a vault record; it belongs to the orchestrator, not to a code executor.

## Verification

- Every Step carries at least one test that fails against the code before the Step and passes after it. No mocks, no monkeypatching, no `unittest` import, no skip or expected-failure marker. Test doubles appear only where a Step isolates pure logic, which here is `src/vaultspec_a2a/thread/message_policy.py` alone.
- `just ci` is green on the merged result.
- The ADR's verification list is proven against a real gateway process and a real worker process over real loopback HTTP, with a real checkpointer and a real thread store: a continuation queued during a live in-flight turn runs after it with no RECONCILING and no refused terminal; a run with a queued continuation emits no terminal frame at its first turn's end and exactly one at its second's; a second continuation refuses `queue_full` while the first is queued; a repeat idempotency key replays the queued action and its position, and a changed payload under that key refuses `conflict`; a continuation racing terminal settlement either queues or meets `terminal`, never both and never neither; a worker `run_busy` 409 leaves the breaker closed and the accepted work intact; and a gateway killed between settlement and promotion promotes exactly once on restart.
- `test_every_lifecycle_status_resolves_to_a_typed_answer` in `src/vaultspec_a2a/thread/tests/test_message_policy.py` asserts the queued answer for SUBMITTED and RUNNING, `run_busy` for CANCELLING, and the narrowed parked refusal naming the respond verb.
- Every persistence Step runs on both backends. SQLite is the default; the PostgreSQL proofs run with `VAULTSPEC_A2A_TEST_POSTGRES_URL` exported to a writable database and `--require-prerequisite=postgres` on the command line, so an absent server is a failure rather than a silent skip.
- `P02.S04` proves its migration upgrades and downgrades cleanly on both backends, and that the live model and the migrated schema agree.
- Every Step that changes a served schema regenerates `openapi.json` in the same commit with `uv run --no-sync python -m vaultspec_a2a.api.tests.test_openapi_artifact`, and `src/vaultspec_a2a/api/tests/test_openapi_artifact.py` passes against the merged application.
- `P06.S16` is verified by reading the recorded paragraph against the served surface: the 202 with `action_status` `queued`, the sixth refusal code `queue_full`, the `queued_messages` and `continues_run_id` disclosures, and the statement that a quiet turn boundary is not completion.
- Findings from each Step's review are classified and appended to the feature's rolling audit, including anything deferred beyond this plan.
- The plan is complete when every Step is closed and the final integrated review passes against the merged behaviour, not against the files in isolation.

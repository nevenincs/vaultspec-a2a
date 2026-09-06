---
tags:
  - '#audit'
  - '#embedded-runtime-remediation'
date: '2026-09-06'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:c8c80d894d590d9bb7564da983f6dd260cb62a6e8cfd54d67838dfef580a44dc'
related:
  - "[[2026-09-05-embedded-runtime-remediation-plan]]"
  - "[[2026-09-06-embedded-runtime-remediation-w02-p03-s11-abandoned-election-research]]"
---
# Recovery authority and evidence architecture review

## Scope

Review of the amended recovery ADRs and the production owners for conditions 1-16 before implementation. Condition 17 is separately owned by the verification lifecycle correction.

## Findings

### startup-unconditional-writer | high | open; lifecycle ownership

`src/vaultspec_a2a/database/reconciliation.py:execute_reconciliation` still calls the unconditional lifecycle setter and changes repair state after deciding from a stale batch snapshot. The shared recovery coordinator must own startup entry as well as exits from reconciling; moving only redispatch and API abandonment leaves this stale writer authoritative.

### checkpoint-completion-heuristic | high | open; evidence integrity

`src/vaultspec_a2a/worker/state_projection.py:pre_flight_checkpoint` equates empty pending writes with completion and permits dispatch after checkpoint-read failure using an in-memory heuristic. Empty pending writes do not establish the absence of scheduled graph tasks or identify the current accepted action. Completion must come from durable action-bound evidence. Unreadable evidence cannot authorize replay.

### missing-action-incorporation | high | open; architectural dependency

`src/vaultspec_a2a/thread/state.py` has clarification-specific fingerprints but no general journal-action, payload-fingerprint and dispatch receipt. The generic worker notification in `executor.py:_emit_dispatch_application_receipt` proves only entry into graph execution. The coordinator cannot distinguish a previous turn's completed checkpoint from the current action until the general receipt declaration and real incorporation producer exist. S78 and S12 are prerequisites of S11/S83, despite their later displayed positions.

### incomplete-durable-dispatch | high | open; recovery authority

`src/vaultspec_a2a/control/thread_service.py:create_thread_service` journals only title, preset and autonomous input before dispatch. Initial content and the effective dispatch inputs are not recoverable from that payload. `dispatch.py:redispatch_reconciling_threads` constructs a fresh INGEST with a newly generated dispatch id. Recovery must retain the accepted dispatch identity and complete recoverable non-secret inputs before network delivery; missing inputs require typed refusal, never reconstruction using defaults. Ephemeral actor tokens require a separately authorized fresh credential path or explicit refusal, never durable secret storage.

### impossible-integrity-election | high | open; decision contradiction

The amended state-truthfulness ADR requires a terminal receipt-mismatch refusal through an election whose SQL predicate requires that missing receipt. `thread_repository.py:elect_thread_status` therefore returns RECEIPT_MISMATCH without changing the indefinitely reconciling row. The decision must distinguish ordinary receipt-authorized advancement from a constrained integrity quarantine: compare the exact observed current row and the absence of its matching receipt, refuse execution, and never invent replacement authority.

### demand-gated-recovery | high | open; lifecycle progress

`src/vaultspec_a2a/api/app.py:_deferred_reconcile` waits for a worker-demand event emitted by a new dispatch. Polling an interrupted run cannot release that gate. Durable checkpoint settlement and recovery disclosure must operate before worker demand; network redelivery must respect the desktop worker ownership contract and disclose a waiting-for-demand obligation when applicable.

### mutable-deadline-authority | high | open; execution contract

`run_discovery_service.py:_derive_reconciling_abandonment_bound` loads the current preset from disk, silently substitutes a global floor when configuration cannot be loaded, and measures from mutable updated_at. These are not frozen run execution authority. Admission must retain the effective execution deadline inputs; recovery attempts and API reads must not extend the deadline.

## Recommendations

Implement the general checkpoint receipt and its producer before the coordinator. Persist complete non-secret dispatch authority at admission before delivery. Centralize startup, periodic and read-triggered recovery after resolving the quarantine and desktop-demand rules. Keep all conditions open until the production consumers use these owners; declaration tests alone do not close a recovery defect.

## Review disposition

FAIL for the amended architecture as an immediately implementable S11-only change. No production code changed during this review. The single-agent executor proceeds through the prerequisite corrections and updates the audit on each implementation pass.

### checkpoint-receipt-declaration | low | resolved within S78; producer remains open

Formal self-review of `thread/action_receipts.py`, its `TeamState` reducer and the real checkpoint test passes the declaration boundary. The version, journal action, fingerprint, dispatch and ownership fields are required, bounded and immutable. Cancellation cannot masquerade as graph incorporation. Receipt reuse with different evidence raises instead of replacing the prior fact. Existing clarification and permission state are unchanged. This is an incorporation declaration, explicitly not proof of terminal completion. S12 still owns production receipt creation and validation; S11/S83 and every runtime recovery finding remain open.

Verification: the two focused tests passed in 0.31 seconds. The exact subprocess exited naturally with code 0 and an empty descendant census under a 60-second owner deadline. Ruff and Ty passed on the three changed source/test paths. No legacy interpretation, translation or inferred receipt is present.

### initial-dispatch-authority | high | resolved at admission by S86; recovery consumption open

Formal self-review of `control/thread_service.py` and `control/tests/test_thread_service_tokens.py` passes the initial admission boundary. The effective dispatch is built before the run INSERT; the run, stable action identity and versioned non-secret input record commit in one transaction before HTTP. An independent database session inside the receiving HTTP handler reads the same non-secret input and dispatch id. An invalid project fails before any durable reservation; even an explicit caller commit leaves no run or action. Actor-token values are absent from the journal while their required-presence flag is retained. Concurrent completion, deletion and a different cancellation writer preserve their existing election behavior.

The initial admission part of incomplete-durable-dispatch is corrected. Recovery decoding and refusal, other action admission, frozen deadline authority and production incorporation remain open under S11/S12/S83; none is inferred from this result.

Verification: the first five-case battery exited naturally with five passes in 19.12 seconds and zero survivors. After adding the invalid-input discriminator, one six-case command printed six dots but exceeded its 60-second owner deadline before producing a summary; it was terminated with zero survivors and is classified FAIL. The same six-case battery then completed through the resource-aware runner with run timeout 60 seconds and exit timeout 5 seconds: six passed in 3.54 seconds, process exit 0. Ruff and Ty passed on both changed paths. The earlier timeout is retained as verification-lifecycle evidence for S85, not relabelled as a pass.

### graph-action-producer | high | partially corrected in S12; recovery remains open

Formal self-review confirms immutable journal receipts are persisted before graph dispatch, under the exact durable thread writer. A status-only revision preserves the original receipt; recovery cannot install an older action. New message, permission, clarification and verdict actions install ownership only from the witness observed before acquiring their lease. Initial accepted input excludes the derived receipt as well as transport secrets, avoiding a circular payload fingerprint. Worker admission refuses missing or mismatched current evidence before compilation. Graph input carries the receipt, and application notification reads the matching committed loop checkpoint instead of treating entry into execution as incorporation.

Verification: the initial admission and checkpoint declaration battery passed eight tests in 8.85 seconds; two real-SQLite ownership tests passed in 8.90 seconds; the real worker and StateGraph incorporation test passed in 0.67 seconds. All commands used the bounded runner and exited 0. The ownership test first failed at setup because its fixture belonged to another package, then failed validation because its request omitted required recursion_limit; both test construction defects were corrected before the reported passing run. Ruff passed changed production paths and receipt tests; focused Ty passed. Whole-project Ty reported eight diagnostics outside the receipt implementation, including concurrent provider work, so no whole-project type-check pass is claimed.

### cancellation-proof | high | open; S12 remaining work

Cancellation still emits terminal state from in-memory absence of an active ingest and has no durable cessation or no-op receipt. Graph incorporation deliberately excludes cancellation. S12 remains unchecked until the separate cessation evidence exists and is consumed.

### receipt-consumer-boundary | high | open; S13 dependency

The worker now emits checkpoint identity and its exact journal receipt, but generic progress-event settlement still trusts dispatch_id without validating those durable fields. S13 must precede recovery completion claims. Existing worker tests that construct pre-current graph requests require current authority; they have not been mass-adapted or counted as evidence of runtime completion.

### admission-transaction-gap | high | open; accepted-action atomicity

Follow-up and resume producers still commit their lease and requested projection before installing thread ownership. The binder fences network dispatch and prevents stale installation, but a crash between those transactions leaves an accepted action that recovery cannot promote. The single durable admission/recovery authority must commit accepted payload, writer and receipt together. Complete effective input storage currently covers initial admission only; other actions still require equivalent recoverable inputs.

### schema-refusal-verification | medium | open; migration evidence

Migration 0018 refuses populated pre-current stores instead of inventing historical graph receipts. Fresh-schema admission was exercised through the production migration-backed test fixture. A dedicated populated-store refusal and cancellation/no-op migration discriminator remains required. This partial S12 pass does not close the recovery conditions.

### physical-transaction-escape | high | corrected in continuing S12; broader contention review open

Formal review and a real SQLite test found reservation SAVEPOINT release committed a new accepted action before the intended outer transaction existed. Rolling back a failed writer election left that action present. This was reproduced as one failing test in the first two-case atomicity run (10.76 seconds, exit 1). The application engine now owns physical BEGIN before SAVEPOINT through SQLAlchemy events. Graph-action claim installs the writer and persists the receipt before committing its lease; delivery cannot promote a writer. The corrected two-case discriminator passed in 8.97 seconds with bounded runner exit 0. An independent session verifies accepted action, writer and receipt are visible together; stale refusal leaves no action row.

The graph writer/receipt portion of admission-transaction-gap is corrected. Permission/requested projections and full non-initial effective dispatch input still need integration into the durable authority. Explicit SQLite read transactions also expose lock or snapshot-upgrade contention that must be classified and scheduled through S83; this pass does not claim that retry owner is complete. Cancellation-proof and receipt-consumer-boundary remain open. Focused Ty passed; the continuing S12 row remains unchecked.

### durable-graph-completion-producer | high | corrected in S87; consumers open

Formal self-review confirms all four served compiler topology terminal routes converge on one finalizer before END. The worker supplies the explicitly active accepted action on ingest and resume. The finalizer requires its matching incorporation receipt and writes immutable, versioned completion evidence into graph state. Only the resulting committed channel value proves completion; neither pending writes nor prior action receipts substitute for it. Interrupted work has no completion receipt for its active action. Reopening the real SQLite checkpoint and resuming under a distinct accepted action records completion only for that resume.

Verification through the bounded runner: two interruption/reopen and missing-incorporation tests passed in 2.17 seconds; two production pipeline/pipeline-loop topology tests passed in 2.53 seconds; the real worker active-action input test passed in 1.06 seconds. All exited 0. Focused Ruff and Ty passed after correcting test RunnableConfig annotations. The finalizer obeys the existing graph recursion budget; no extra execution budget is invented.

S87 provides successful completion evidence only. S11 must consume it before any deadline or replay decision and replace the old empty-pending-writes heuristic. S13 must reject unverified terminal notifications. Durable cancellation/cessation evidence, failed-task classification, atomic requested projections and current-schema refusal remain queued; runtime recovery is not closed by this producer.

### administrative-process-timeout | low | resolved; verification lifecycle

The S87 Core exec-record set-body process exceeded a 30-second parent subprocess bound, then emitted its successful mutation result after the parent timed out. The administrative invocation is recorded as a timeout, not a clean process pass. The exact command-body-file process census subsequently found zero matching survivors and the stored exec body was verified. The graph tests above completed naturally through the bounded verification runner.

### shared-checkpoint-settlement | high | corrected partial S11 architecture

Formal self-review of the actual implementation finds startup, active discovery and served state capture now call one exact accepted-action checkpoint authority. Durable completion is elected before abandonment or replay. Empty pending writes never imply completion. The coordinator releases its database read snapshot before the checkpoint await, then compares the saved complete writer witness. Only the winner applies terminal action/permission/repair effects in the same database transaction. Discovery re-queries all projected fields after recovery. Startup runs before worker demand and demotes unfinished execution through the same election; a read trigger does not demote live work.

### remaining-recovery-authorities | high | S11 and S13 remain open

Architecture/contract: the worker still has the older empty-pending-writes and unreadable-checkpoint behavior, event consumers still trust terminal notifications, and deferred network recovery is not yet owned by this coordinator. Missing or invalid durable action receipts return an incompatible observation but lack the constrained exact-row quarantine election required for retired state. No legacy state is synthesized or dispatched by the new authority. These existing gaps remain required follow-up work, not completion claims.

### recovery-scheduling-and-retired-tests | high | S83 and S84 remain open

Architecture/liveness: removal of mutable-preset, updated-at and global-floor abandonment removes false deadline authority, but frozen accepted execution deadlines and durable leased retries are still absent. Startup's bounded pass may leave unvisited rows for the future scheduler. Atomic complete noninitial inputs, cancellation evidence and database contention classification remain open. Verification/contract: tests importing the retired pure startup helpers or abandonment helper must be replaced against current architecture in S84; this pass does not claim whole-suite compatibility or success.

### recovery-verification-lifecycle | high | combined battery failure retained

Two combined four-case invocations reached four dots but produced no pytest session result within 60 seconds. Both bounded runners reported tree_reaped=true and are FAIL. After explicit trigger integration, isolated startup demotion passed one case in 1.50 seconds, direct completion plus empty-pending evidence passed two cases in 4.29 seconds, and startup/discovery/demotion passed three cases in 4.91 seconds; these runs exited naturally with code zero and whole-containment quiescence. This does not erase the combined invocation failures. Parent owns condition 17 investigation.

### s87-test-protocol-typing | medium | correction owned by S34

Verification/type: parent full-file Ty found two S87 topology tests calling get_graph through a protocol that does not declare it. Parent corrected those test inspections with explicit Any casts while owning the same file for S34. Earlier S87 focused Ty evidence did not cover those full-file diagnostics; retain this correction in the audit trail.

### atomic-acceptance-finalizer | high | corrected further S12 transaction ownership

Architecture/atomicity: the former shared claim committed before the caller could add its permission/message/cancellation projection. The repository also explicitly refused composition with unflushed accepted state. Preparation now leaves the winning transaction open, and every production caller explicitly finalizes its verified lease before dispatch after adding the accepted effects. Cancellation and recovery losing paths roll back; clarification early refusal constructs its response before rolling back expired ORM state. The lease-only pending-state guard is removed under the amended binding transaction owner.

Formal self-review found and corrected two clarification early-return paths that could otherwise leave a prepared transaction for an outer caller to commit. The real production-configured SQLite discriminator verifies closing before finalization persists none of the new action/writer/requested projection, while finalization publishes all of them including immutable graph receipt and lease token. Both cases passed in 12.93 seconds through the bounded runner with natural exit zero and whole-containment quiescence. Focused source Ty passed.

### complete-accepted-input-still-open | high | S12 remains open

Architecture/input authority: complete noninitial effective dispatch controls are still not journaled, and message project validation remains after durable acceptance. Initial graph receipt creation still needs to join the initial input transaction. The delivery binder still owns a commit and must become a pure reader of accepted evidence. These are required remaining corrections before the durable retry scheduler can reconstruct every action. Cancellation cessation evidence remains separate and open.

### retired-claim-test-contract | medium | S84 current-contract tests required

Verification/contract: the old auto-committing claim API is removed without an alias. Historical direct-control, recovery, event and verdict tests importing that API must adopt explicit prepare/finalize acceptance and real current receipts. Only the receipt/acceptance discriminator is migrated in this pass; no broad suite pass is claimed. The existing combined-run lifecycle failures remain failed evidence.

### delivery-cannot-create-authority | high | initial atomicity and pure binding corrected in S12

The initial input transaction now prepares its immutable graph receipt before commit. The delivery binder only reads and validates existing evidence; it no longer creates receipts or commits. Recovery and delivery call one current-receipt validator so payload fingerprint, writer generation and action identity have one interpretation. This closes the initial-receipt and binder items from complete-accepted-input-still-open; complete noninitial inputs, preacceptance project validation and cancellation evidence remain open.

Verification: real HTTP receiver independently observed the committed initial input and receipt before acknowledgement, one case passed in 16.94 seconds. A missing-receipt delivery discriminator initially failed because its ingest fixture omitted the required active project (one failed, two passed in 7.42 seconds); after supplying the real temporary project it passed one case in 4.06 seconds. It proves that even committing after binding cannot fabricate missing receipt authority. Receipt-revision preservation and stale-writer refusal passed two cases in 2.86 seconds. All these runner invocations exited naturally; the fixture failure remains failed evidence. Focused Ruff and source Ty passed.
### delivery-read-transaction-owner | medium | corrected in S12 review

The pure delivery binder now owns a separate short read session. It cannot see uncommitted caller acceptance, publish or discard caller writes, or hold its read transaction across network delivery. The finalized/aborted acceptance discriminator now also attempts binding before finalization and proves that no receipt is exposed; both cases passed in 11.02 seconds. Missing-receipt refusal and committed receipt preservation passed two cases in 3.86 seconds. Shared recovery completion passed one case in 15.46 seconds. All exited naturally with code zero and whole-containment quiescence. Final focused Ruff/Ty and Core error checks passed.

### complete-current-dispatch-input | high | further S12 checkpoint correction

Architecture/input: initial, message, permission, clarification, verdict and cancel producers now retain every effective non-secret DispatchRequest field in accepted-action-input-v1 with semantic intention and credential requirement. The stable action dispatch ID is excluded from payload comparison and is supplied explicitly to reservation. Permission/clarification replay readers consume the strict envelope. Receipt validation rejects retired partial payloads. Direct redrive consumes the frozen input rather than current preset, permission rows, agent defaults or a supplied recursion limit. Actor credential absence has a distinct credentials_required refusal. Delivery never substitutes ambient credentials.

Project validation for follow-up and resume paths now precedes claim preparation: the shared metadata reader requires an explicitly named existing canonical directory; unavailable projects return refusal before the new action is reserved. Initial input serialization occurs before run creation. The initial gateway already owns project admission, but direct low-level initial service validation of every unusable-project case is not fully discriminated in this pass.

### accepted-input-verification | medium | bounded evidence and failure retained

Real SQLite current-input acceptance/revision cases passed three in 5.29 seconds. The real HTTP initial input/receipt visibility case passed one in 6.36 seconds. The redrive discriminator passed two in 9.05 seconds: changed thread preset and empty current metadata did not replace accepted preset, recursion limit, decision or frozen provider assignment, and retired partial input produced no dispatch. All exited naturally with code zero and whole-containment quiescence. A final test annotation Ty diagnostic and Ruff line-length diagnostic were corrected; final focused source/test Ty and Ruff passed.

The subsequent current-input recovery-direct invocation (session 45164) emitted no output during observation, later one dot, and the runner reported no pytest session result within 60 seconds with tree_reaped=true. It is FAIL. The exact observed owned process tree was shell 45060, uv 7524/38412, runner 67312/2504, child 50768/64392. A guarded cleanup command found that tree already gone and the census verified zero survivors. No hung run is counted as passed.

### remaining-recovery-root-work | high | S12 S11 S13 S83 S84 remain open

Architecture: DispatchRequest still names a team preset rather than freezing the executable graph/topology and sanctioned step timeout. Persist those accepted runtime controls before deriving an execution deadline; do not infer them from current configuration. Cancellation still lacks durable cessation/no-op proof. S11 still needs worker preflight, event settlement and deferred startup/network dispatch to use the shared checkpoint-first authority; old worker empty-pending-writes and unreadable-checkpoint fallback behavior remains. S13 still trusts raw application/terminal events. S83 still lacks the durable classified retry record, bounded leased scheduler, permanent-refusal election and frozen execution deadline. These are required root corrections, not optional polish.

Verification: S84 must replace historical tests importing the removed auto-committing claim API, old initial input schema and retired startup/abandonment helpers. The current redrive, receipt, recovery and initial-input fixtures are migrated; no whole-suite pass is claimed. Filesystem project existence currently uses a synchronous directory probe; its bounded ownership under slow filesystem failure remains an open liveness discriminator.
### retired-abandonment-contract | high | resolved in partial S84

The deleted `test_reconciling_abandonment.py` imported the removed read-time abandonment helper and asserted the retired mutable-preset timeout plus global 300-second floor. Recreating that helper would restore invalid recovery authority. Its current requirements are covered by checkpoint-first recovery, startup-only unfinished-execution demotion, and the public fresh-projection terminal-winner discriminator.

A canonical collection-only run after deletion collected 439 current control tests and exited 1 with six remaining collection errors. Every error is a historical test importing the removed auto-committing `claim_control_action` API: direct-control leases, direct recovery, event handlers, verdict loop, verdict subscriber, and live verdict subscriber. This failed collection is the exact S84 queue for the next migration pass. No alias or compatibility helper will be added.
### retired-precurrent-backfill-contract | high | resolved in partial S84

The migration test required a pre-0012 populated action to receive a synthetic dispatch identity and remain claimable through the removed implicit-commit API. That is legacy backfill behavior and conflicts with the current rule that populated pre-current stores are refused rather than interpreted. The test and its obsolete control-action imports are removed. The migration chain remains usable to construct a fresh schema; no populated historical action is accepted by this change.

After removal, canonical collection of the database test directory completed naturally with 385 tests and no collection error. The broader S84 control-test queue remains open.

### mutable-executable-program | high | corrected in partial S12

Architecture/input: worker compilation previously reread current TOML and could omit a missing worker or substitute supervisor configuration. Resume also reconstructed recursion from current team/global defaults. S12 now accepts a complete executable-graph-v1 snapshot with an explicit positive step timeout, upgrades the closed envelope to accepted-action-input-v2 without a v1 adapter, reads the receipt-bound initial definition for later graph actions, and binds cache/checkpoint reuse to its digest. Worker compilation consumes the snapshot and accepted recursion directly.

### delivery-payload-divergence | high | corrected in S12 review

Integrity: binding a valid stored receipt without comparing the actual outgoing effective input could authorize a changed graph or control value. Binding now requires exact equality of all non-secret accepted request fields and the credential requirement. Initial graph-definition reads also validate action type, identities and payload fingerprint against the immutable receipt.

### graph-authority-qualification | medium | S84 migration and S12 consumers remain open

Verification/contract: compiler callers must now provide an explicit positive step timeout; worker checkpoints require graph and provider digests; accepted graph actions require the complete v2 snapshot. Historical compiler, worker and service fixtures using omitted timeout, four-element cache keys or partial dispatch envelopes must migrate to the current contract in S84. No compatibility shim is supplied. The initial 4-case graph battery failed one case because its fixture selected the coder key instead of the declared mock-coder-success worker; the real catalog fixture now accepts explicit required identities. This failure is retained. Subsequent 11-case graph/acceptance/delivery and 11-case recovery/HTTP batteries exited normally, passing in 7.45 and 4.53 seconds respectively.

Architecture follow-up: S12 remains open for durable cancellation cessation/no-op evidence and complete authority-consumer qualification. Later-action provider/project metadata must be audited against initial accepted authority. S11/S13 worker preflight and raw terminal/application event handling remain open; S83 durable retry storage, leased drain, deadline/elapsed-time derivation and quarantine election remain open. A step timeout alone is never completion or cancellation proof.
### event-settlement-fixture-current-state | medium | resolved for S84 collection; S13 authority finding remains open

The event-handler tests no longer import or reproduce the retired implicit claim API. Their setup now creates the journal row and acquires the durable lease through the current database primitives, which are the only state the event consumer presently reads. All twelve focused cases pass. The complete control collection now reaches 452 cases and stops on five remaining retired imports instead of six.

The setup deliberately carries no accepted-action-v2 payload or graph receipt. This is evidence for the existing high-severity `receipt-consumer-boundary` finding: the current event handler settles a leased action from dispatch identity alone. S13 remains responsible for requiring and validating durable receipt evidence. S84 must not invent valid acceptance evidence merely to keep that older consumer test green.
### verdict-lease-retirement | high | obsolete fixtures removed; current recovery proof open

The two verdict tests that manually created expired or fresh leases used the removed implicit claim operation and a partial verdict-only payload. They are deleted rather than skipped or translated. Control collection now passes the verdict modules and stops only on the two direct-control modules.

Their behavioral obligations remain open: an expired accepted verdict must redrive the exact stable dispatch, and a fresh accepted verdict lease must suppress duplicate dispatch. Replacement proofs must begin from accepted-action-input-v2 plus the exact frozen executable graph and receipt. They may not restore the partial payload through a fixture.

### verdict-graph-cache-identity | high | three current test fixtures omit frozen graph identity

The verdict subscriber unit run produced 20 passes, then two failures before dispatch because its injected compiled graph uses the retired four-member cache key. Focused Ty identifies the same omission in the unit, live subscriber and verdict-loop fixtures. The current cache authority is five members and includes the frozen graph-definition digest. S84 must migrate all three fixtures from actual accepted graph authority; a constant placeholder digest would not prove the worker consumes the same graph.
### direct-control-legacy-state-tests | high | impossible and partial states removed; current action recovery open

The direct-control lease suite no longer asserts that another session can observe a committed cancellation lease before its thread authority. Current cancellation acceptance performs reservation, election and final commit in one transaction, so that intermediate state is not part of the supported architecture. Its old three-action restart test also persisted partial message, cancellation and permission payloads that accepted-action-input-v2 rejects. Both scenarios are deleted rather than rebuilt as compatibility fixtures.

The retained eight lease tests collect through the current schema. Runtime qualification remains blocked by that file's four-member compiled-graph key, which omits the required frozen graph digest. Action-specific restart behavior remains assigned to migration of `test_direct_control_recovery.py`; the existing complete-input recovery discriminator proves shape refusal but does not replace the three behavioral cases.

### parallel-cold-control-verification | medium | bounded resource contention classified

Running the direct-lease suite and full control collection concurrently produced no pytest session result within either 90-second deadline. Both owners reaped their trees and are failures. A subsequent isolated collection naturally exited with eight cases in 20.16 seconds. Continue these cold database and graph checks serially on this host.
### direct-control-recovery-retired-fixture | high | collection blocker resolved; behavioral replacements open

The final control-test import blocker was a recovery file whose message, cancellation and permission rows all used partial payloads and whose fixture committed action authority separately from lease acceptance. That state cannot be interpreted by accepted-action-input-v2 and cannot be made current by adding missing defaults. The file is deleted. Canonical control collection now completes naturally with 482 of 488 cases collected and six service deselections.

Three obligations remain open for current-schema replacement: unavailable active-project refusal must prevent graph dispatch while permitting cancellation; complete accepted message, cancellation and permission inputs must redrive their stable identities; and an older accepted action must lose after newer exact authority wins. These require real frozen graph definitions, receipts and atomic writer state.

### legacy-worker-adoption-surface | high | open no-legacy violation discovered during collection

The clean collection enumerated `test_ensure_worker_adopts_legacy_missing_or_blank_target`. A supported worker attachment path must not accept missing provenance as an older implied shape. Review the production worker-provenance branch and delete both the adoption behavior and its approving test under the existing no-legacy campaign before qualification.

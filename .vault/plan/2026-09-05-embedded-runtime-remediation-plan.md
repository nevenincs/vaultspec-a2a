---
tags:
  - '#plan'
  - '#embedded-runtime-remediation'
date: '2026-09-05'
tier: L3
related:
  - '[[2026-09-05-embedded-runtime-remediation-adr]]'
  - '[[2026-09-05-embedded-runtime-remediation-research]]'
  - '[[2026-09-05-embedded-runtime-robustness-audit]]'
  - '[[2026-09-05-embedded-runtime-robustness-research]]'
  - '[[2026-08-02-control-action-leases-adr]]'
  - '[[2026-08-05-served-capability-contract-state-truthfulness-adr]]'
  - '[[2026-08-01-dashboard-bundled-runtime-subordination-adr]]'
  - '[[2026-07-14-a2a-edge-conformance-adr]]'
  - '[[2026-02-25-llm-context-provider-abstraction-adr]]'
  - '[[2026-08-02-provider-error-taxonomy-adr]]'
  - '[[2026-08-02-provider-capability-evidence-adr]]'
  - '[[2026-08-02-provider-capability-evidence-plan]]'
  - '[[2026-08-02-provider-model-catalog-adr]]'
  - '[[2026-08-02-provider-model-catalog-plan]]'
  - '[[2026-08-05-served-capability-contract-plan]]'
  - '[[2026-08-02-llm-context-provider-abstraction-plan]]'
  - '[[2026-09-05-embedded-runtime-remediation-no-legacy-curation-audit]]'
modified: '2026-09-06'
body_schema: body-v2
body_hash: 'sha256:4e304efa04859553ffc7b5c1224b77dd2327aeb4125379d1e54a1c9906b2a6ab'
---

# `embedded-runtime-remediation` plan

## Description

Remediate ER01-ER28 as the Dashboard-embedded binary, using the related remediation research for grounding and ownership. The accepted embedded-runtime-remediation ADR governs qualification and closure throughout. Wave 'Freeze execution prerequisites' establishes evidence and existing-owner gates. The amended control-action-leases and state-truthfulness ADRs govern 'Repair durable control and lifecycle'. The base provider/context, provider-error-taxonomy and capability-evidence ADRs govern 'Preserve provider and context semantics'. The amended edge and Dashboard-subordination ADRs govern 'Conform the consumer and binary lifecycle'. The remediation ADR governs 'Measure the complete qualification matrix' and 'Review and close the campaign'. The historical base provider modernization plan is context, not an imposed SDK migration dependency.

For every Step, re-ground its named source and decision through rag-first semantic discovery before exact-symbol inspection; if the recorded RAG prerequisite is unavailable, use Core discovery plus narrow source inspection and record the limitation. The audit owns observed failures; the research owns the ownership map; these rows own execution. Existing active-plan rows are dependency-verification gates, not duplicate implementation assignments. Preserve their canonical identifiers and historical completed records. Coordinate shared-file work with repository-tooling-hardening. Dashboard paths are relative to the separate vaultspec-dashboard checkout; all other source paths are relative to this checkout.

Each implementation Step includes discriminating tests at its real production boundary, formal code review, severity/type/status classification of every finding, an audit-queue update and an execution record before closure. Provider/model remediation follows the no-legacy amendment in `2026-08-02-provider-model-catalog-adr`: retired profile, preset-policy, static-map, compatibility, restart, redispatch and product-wire behavior must be removed and typed-refused, never retained or migrated. A Wave cannot land until these obligations are met. All rows begin unchecked. ADR acceptance authorizes these design decisions only; execution waits for separate plan approval.

The first Wave inventories external prerequisites; their absence does not block independent local correction. Final provider/consumer verification gates stay in the qualification Wave. No release, merge or implementation action is authorized by this saved plan.

## Steps

## Wave `W01` - Freeze execution prerequisites

Establish a reproducible execution baseline and coordinated consumer contract before behavior changes, under the remediation and Dashboard-subordination ADRs. The durable-control and consumer Waves depend on this recorded identity and ownership boundary.

### Phase `W01.P01` - Record qualification inputs

Freeze intended revisions, supported operations, limits and evidence prerequisites.

- [x] `W01.P01.S01` - Record the intended A2A commit/binary identity, Dashboard generation, A01-A34 applicability, supported-mode inventory and pre-test queue/deadline/host limits without changing the frozen acceptance thresholds; `qualification evidence`.
- [x] `W01.P01.S02` - Resolve the intended consumer's lifecycle, discovery, broker and schema contract and record the coordinated change boundary before either repository changes wire behavior; `Dashboard engine/crates/vaultspec-product/src`.
- [x] `W01.P01.S03` - Record prerequisite status and exact evidence needed from catalog plan P03.S19 and P03.S20; allow independent local remediation while missing provider or Dashboard qualification blocks only its dependent proof; `provider selection dependency`.

### Phase `W01.P02` - Repair test prerequisites

Restore meaningful prerequisite-dependent checks without weakening runtime claims.

- [x] `W01.P02.S04` - Run PostgreSQL URL checks under the locked server dependency profile and make that profile explicit while preserving the SQLite binary profile; `pyproject.toml`.
- [x] `W01.P02.S05` - Verify catalog availability-test correction under owner P01.S11 in 2026-08-02-provider-model-catalog-plan, preserving exact-mode admission assertions; `src/vaultspec_a2a/api/tests/test_provider_catalog_route.py`.
- [x] `W01.P02.S06` - Align an isolated RAG client/service test environment and rerun the real project-pinning discriminator without altering an unrelated shared daemon; `src/vaultspec_a2a/providers/tests/test_harness_mcp_pinning.py`.
- [x] `W01.P02.S07` - Diagnose the intermittent compilation loop-gap measurement on the named representative host/load and correct the owning warmup path if required without relaxing its existing budget; `src/vaultspec_a2a/providers/warmup.py`.
- [x] `W01.P02.S08` - Apply a reviewed locked dependency correction for the Starlette BlockingPortal deprecation and verify the warning disappears without suppression; `uv.lock`.

## Wave `W02` - Repair durable control and lifecycle

Implement uncovered persistence, queue, cancellation and worker-capacity corrections under the amended leases/state-truthfulness ADRs. Provider and consumer work depend on truthful durable outcomes and bounded control admission.

### Phase `W02.P03` - Elect durable outcomes

Remove stale-write and early-completion races while retaining existing state obligation owners.

- [ ] `W02.P03.S76` - Declare durable run revision and writer generation plus action-specific receipt identity without storing credentials or duplicating transcript authority; `src/vaultspec_a2a/database/models.py`.
- [ ] `W02.P03.S77` - Add the current ownership and receipt schema with upgrade validation; refuse pre-current or unknown-ownership rows as incompatible without backfill, translation, migration-time substitution or execution; `src/vaultspec_a2a/database/migrations`.
- [ ] `W02.P03.S09` - Add atomic expected-state/revision election with durable writer/action identity and test completed-versus-cancelled stale sessions; `src/vaultspec_a2a/database/thread_repository.py`.
- [ ] `W02.P03.S10` - Verify transitional-writer and projection obligations under 2026-08-05-served-capability-contract-plan W04.P07.S22 and W04.P08.S26 against the new election primitive; `state obligation dependency`.
- [ ] `W02.P03.S11` - Verify abandoned-run reconciliation under owner W04.P08.S56 and integrate the new atomic election without duplicating its existing generic reconciliation assignment; `abandoned transition dependency`.
- [ ] `W02.P03.S78` - Declare checkpointed graph-action receipts binding action, payload fingerprint and dispatch identity while retaining existing typed clarification and permission state; `src/vaultspec_a2a/thread/state.py`.
- [ ] `W02.P03.S12` - Persist request-scoped checkpoint incorporation evidence for graph actions before reporting application, retaining dispatch identity and winning payload fingerprint; use durable cessation or no-op evidence for cancellation without graph incorporation; `src/vaultspec_a2a/worker/executor.py`.
- [ ] `W02.P03.S13` - Settle application only from the durable receipt and reconcile completion arriving before running has committed; `src/vaultspec_a2a/control/event_handlers.py`.
- [ ] `W02.P03.S14` - Give durable terminal delivery an independent bounded retry/reconciliation owner so a failed relay cannot strand an otherwise completed run; `src/vaultspec_a2a/control/direct_control_recovery.py`.

### Phase `W02.P04` - Drain ordered accepted work

Keep one durable acceptance and delivery authority through contention, busy execution and restart.

- [ ] `W02.P04.S15` - Diagnose SQLite contention using effective connection settings and extended errors, then bound run-creation transactions and return typed retryable refusal without claiming uncommitted acceptance; `src/vaultspec_a2a/control/thread_service.py`.
- [ ] `W02.P04.S79` - Project exhausted SQLite admission contention into a bounded typed retryable HTTP refusal with stable request identity and no false durable acceptance; `src/vaultspec_a2a/api/routes/gateway.py`.
- [ ] `W02.P04.S16` - Enforce atomic per-run and service queue limits, stable retry positions and conflicting-payload refusal before message acknowledgement; `src/vaultspec_a2a/control/message_service.py`.
- [ ] `W02.P04.S17` - Drain accepted messages in journal order with one renewable dispatcher per run during normal operation and startup, reconciling receipt evidence before redelivery; `src/vaultspec_a2a/control/direct_control_recovery.py`.
- [ ] `W02.P04.S18` - Return a recoverable busy disposition without suppressing or discarding accepted work when a run already owns its active slot; `src/vaultspec_a2a/worker/executor.py`.

### Phase `W02.P05` - Keep cancellation and recovery available

Separate control admission from execution capacity and make cancellation cleanup total.

- [ ] `W02.P05.S19` - Admit authenticated idempotent cancellation through a separately bounded path at execution capacity and overload; `src/vaultspec_a2a/worker/app.py`.
- [ ] `W02.P05.S20` - Wake blocked graph/provider event awaits from cancellation and distinguish acknowledgement from cessation or unresolved effects; `src/vaultspec_a2a/streaming/ingest.py`.
- [ ] `W02.P05.S21` - Make ingest task-group cancellation release active ownership and settle or explicitly reconcile without using an uninitialized outcome; `src/vaultspec_a2a/worker/executor.py`.
- [ ] `W02.P05.S22` - Make resume task-group cancellation release active ownership and settle or explicitly reconcile without using an uninitialized outcome; `src/vaultspec_a2a/worker/executor.py`.
- [ ] `W02.P05.S23` - Treat worker capacity refusal as backpressure rather than transport failure and resume admission when capacity returns; `src/vaultspec_a2a/control/dispatch.py`.
- [ ] `W02.P05.S24` - Reserve and settle the bounded half-open probe allowance atomically under concurrent success, failure and abandoned probe ownership; `src/vaultspec_a2a/control/circuit_breaker.py`.

## Wave `W03` - Preserve provider and context semantics

Correct provider input and native-control semantics under the amended base provider/context and taxonomy ADRs. Capability evidence remains owned by its existing plan; command/compaction claims depend on those verified facts.

### Phase `W03.P06` - Assemble safe prompt views

Budget actual input and commit compaction without replacing durable transcript authority.

- [ ] `W03.P06.S25` - Count complete message content, call arguments/results, tool declarations and reserved output with explicit units/source/confidence, refusing input that cannot safely fit; `src/vaultspec_a2a/context/token_budget.py`.
- [ ] `W03.P06.S26` - Budget the assembled worker prompt after persona, rules, mounts and tools are added on initial and follow-up invocations; `src/vaultspec_a2a/graph/nodes/worker.py`.
- [ ] `W03.P06.S27` - Budget the assembled supervisor prompt at its actual invocation boundary using the same accounting authority; `src/vaultspec_a2a/graph/nodes/supervisor.py`.
- [ ] `W03.P06.S28` - Build structurally validated compaction views retaining pinned instructions, workspace identity, pending actions, call/result groups and source-range summary provenance; `src/vaultspec_a2a/context/token_budget.py`.
- [ ] `W03.P06.S29` - Commit replacement prompt views transactionally while retaining the authoritative transcript and prior view after failure or interruption; `src/vaultspec_a2a/worker/graph_lifecycle.py`.
- [ ] `W03.P06.S30` - Resume from the committed prompt view while preserving queued-message order and cancellation priority through compaction boundaries; `src/vaultspec_a2a/worker/graph_lifecycle.py`.

### Phase `W03.P07` - Settle provider protocol and conditions

Preserve supplied meaning through initialization, streaming and retry decisions.

- [ ] `W03.P07.S31` - Validate returned ACP version before session creation and reject malformed/incompatible initialization or absent required optional support; `src/vaultspec_a2a/providers/_acp_session.py`.
- [ ] `W03.P07.S32` - Settle every supplied ACP stop reason promptly and preserve refusal, cancellation and budget-exhaustion meaning through the stream consumer; `src/vaultspec_a2a/providers/_acp_protocol.py`.
- [ ] `W03.P07.S80` - Propagate retained ACP stop meaning through the chat-model stream consumer and authoritative outcome path so resolved futures, partial output and transport success cannot become false completed work; `src/vaultspec_a2a/providers/acp_chat_model.py`.
- [ ] `W03.P07.S33` - Carry known setup/authentication/model-configuration wire conditions through AcpSessionError with truthful unknown/coarse fallback; `src/vaultspec_a2a/providers/_acp_session.py`.
- [ ] `W03.P07.S34` - Verify condition-derived retry attempts, supplied delays and elapsed bounds while refusing blind replay of uncertain external effects; `src/vaultspec_a2a/providers/conditions.py`.

### Phase `W03.P08` - Expose proven native controls

Join session command discovery to intentional execution without a generic shell or RPC escape.

- [ ] `W03.P08.S35` - Verify capability composition/served integration under 2026-08-02-provider-capability-evidence-plan P01.S01-S02 against actual constructors and production consumers; `capability composition dependency`.
- [ ] `W03.P08.S36` - Verify existing exact-capability evidence and invalidation under owner P02.S03-S04; retain new command and compaction claims as blocked until their later effect qualification; `capability proof dependency`.
- [ ] `W03.P08.S37` - Expose session-scoped command advertisements with explicit supported, blocked and unsupported dispositions; `src/vaultspec_a2a/providers/_acp_protocol.py`.
- [ ] `W03.P08.S38` - Execute negotiated native commands with validated arguments, busy disposition and observable outcomes; require independent native-compaction effects before claiming support; `src/vaultspec_a2a/providers/acp_chat_model.py`.
- [ ] `W03.P08.S81` - Implement the admitted Codex app-server lane's native-control mapping against its verified protocol and session identity, with explicit absent-control refusal, bounded outcomes and no arbitrary RPC escape; keep new claims blocked until effect proof; `src/vaultspec_a2a/providers/codex_chat_model.py`.

## Wave `W04` - Conform the consumer and binary lifecycle

Join corrected runtime behavior to the intended Dashboard contract under the amended edge and subordination ADRs. Actual packaged-pair qualification in the next Wave depends on these coordinated producer/consumer changes.

### Phase `W04.P09` - Bind addressed messaging and broker controls

Preserve targeted delivery and expose the required control operations through the real consumer.

- [ ] `W04.P09.S39` - Verify frozen roster and graph-structure prerequisites under 2026-08-05-served-capability-contract-plan W04.P08.S24 and W02.P04.S13 before targeting implementation; `roster dependency`.
- [ ] `W04.P09.S40` - Validate recipients against the frozen run roster before acceptance and retain recipient identity in durable message actions; `src/vaultspec_a2a/control/message_service.py`.
- [ ] `W04.P09.S41` - Route addressed input only to the validated live recipient and refuse unsupported targeting instead of broadcasting; `src/vaultspec_a2a/worker/graph_lifecycle.py`.
- [ ] `W04.P09.S42` - Integrate command discovery/execution and compaction status into the coordinated bounded gateway contract; `src/vaultspec_a2a/api/routes/gateway.py`.
- [ ] `W04.P09.S43` - Add the coordinated follow-up-message broker operation with scope validation and durable result forwarding; `Dashboard engine/crates/vaultspec-api/src/routes/ops/a2a.rs`.
- [ ] `W04.P09.S44` - Add the coordinated permission-response broker operation retaining request/option identity and typed conflicts; `Dashboard engine/crates/vaultspec-api/src/routes/ops/a2a.rs`.
- [ ] `W04.P09.S45` - Add the coordinated native-command broker operations with discovery, argument, busy and outcome handling; `Dashboard engine/crates/vaultspec-api/src/routes/ops/a2a.rs`.
- [ ] `W04.P09.S46` - Verify stream attachment, terminal reconciliation and explicit overflow resynchronization under owner 2026-08-05-served-capability-contract-plan W04.P09.S27; `stream contract dependency`.

### Phase `W04.P10` - Conform owned lifecycle

Make discovery, readiness and shutdown satisfy one identified consumer contract.

- [x] `W04.P10.S47` - Conform readiness/drain/shutdown routes and ownership capability handling to the intended consumer generation with fail-closed incompatible attachment; `src/vaultspec_a2a/api/routes/admin.py`.
- [ ] `W04.P10.S48` - Emit the intended generation's discovery filename, schema, identity and liveness fields and reject stale or foreign-service substitution; `src/vaultspec_a2a/lifecycle/discovery.py`.
- [ ] `W04.P10.S49` - Use cooperative server shutdown with admission closed first and one total deadline covering active work, streams and bounded forced escalation; `src/vaultspec_a2a/api/app.py`.
- [ ] `W04.P10.S50` - After A2A publishes fixed per-target versioned archives and SHA-256 sidecars, replace Dashboard source checkout/build/commit pinning with version-only fetch-verify-bundle, then qualify the released worker and positive module/MCP paths through the receipt-matched Dashboard launch; `A2A release workflow, Dashboard component lock and scripts/prove_artifact_lifecycle.sh`.

## Wave `W05` - Measure the complete qualification matrix

Run adopted A01-A34 assertions at their required boundaries under the remediation ADR. Keep distinct exact provider, binary and consumer identities; a missing prerequisite blocks the dependent measurement rather than changing the criterion.

### Phase `W05.P11` - Qualify local control and persistence

Use disposable real services and stores to measure the previously failed boundary conditions.

- [ ] `W05.P11.S51` - Measure A03 start/prepare/commit/release races with twenty identical and competing callers, counting durable runs and dispatch identities; `src/vaultspec_a2a/acceptance/tests`.
- [ ] `W05.P11.S52` - Measure A08-A10 eligibility, one-hundred-message ordering, twenty retries, Q+1 capacity and independent-run backpressure; `src/vaultspec_a2a/acceptance/tests`.
- [ ] `W05.P11.S53` - Measure A14 ten-repeat gateway/worker kill boundaries and A25 checkpoint/journal/event contention, disk-full and read-only refusal without false durable acknowledgement; `src/vaultspec_a2a/acceptance/tests`.
- [ ] `W05.P11.S54` - Measure A13 cancellation at capacity, silent work and concurrent completion plus A23/A26 ingest/resume task-group cleanup and early terminal delivery; `src/vaultspec_a2a/worker/tests`.
- [ ] `W05.P11.S55` - Measure A18 ten-repeat message/cancel/permission/process-loss compaction races against committed prompt views; `src/vaultspec_a2a/context/tests`.
- [ ] `W05.P11.S56` - Measure A20 bounded half-open fan-out and retry/failover behavior plus A24 valid-long-tool and true-stall run-derived deadlines; `src/vaultspec_a2a/control/tests`.

### Phase `W05.P12` - Qualify actual provider work

Prove selectable lanes and claimed effects at exact execution-mode boundaries.

- [ ] `W05.P12.S57` - Verify catalog selection and live-work dependencies P03.S19 and P03.S20 in 2026-08-02-provider-model-catalog-plan against the actual intended binary/consumer evidence before external qualification; `provider selection dependency`.
- [ ] `W05.P12.S58` - Prove three consecutive codex/codex-app-server turns through the intended Dashboard/binary pair, continuation identity and separately claimed tool/background capabilities; `src/vaultspec_a2a/acceptance/tests`.
- [ ] `W05.P12.S59` - Verify the full configured-mode inventory retains explicit blocked/unsupported dispositions and no unproven admission; add one separately identified qualification Step before activating any additional external lane; `src/vaultspec_a2a/providers/lane_admission.py`.
- [ ] `W05.P12.S60` - Measure A11/A12 typed clarification and permission on admitted real lanes, including opposing decisions, stale answers, decline and no message bypass; `src/vaultspec_a2a/acceptance/tests`.
- [ ] `W05.P12.S61` - Measure A31 addressed-recipient isolation and unknown/stopped refusal, plus accepted/running/terminal reconciliation for separately proven provider subagent/background work; `src/vaultspec_a2a/acceptance/tests`.
- [ ] `W05.P12.S62` - Certify A15-A17 native ordinary-command and compact-command effects, argument/busy refusal, full-input thresholds and ten-fact continuation on exact claimed lanes before enabling new capability claims; `src/vaultspec_a2a/acceptance/tests`.
- [ ] `W05.P12.S63` - Measure A19/A33/A34 real negotiated protocol, supplied terminal outcomes and safely available provider faults with durable reload fidelity; record inaccessible faults as blocked; `src/vaultspec_a2a/acceptance/tests`.

### Phase `W05.P13` - Qualify the packaged consumer

Exercise the actual identified release pair and measure loaded behavior, not helper-only success.

- [ ] `W05.P13.S64` - Measure A01/A02/A04/A21/A22 contract, CRUD state matrix, authentication/workspace isolation, dependency-specific readiness and stream recovery through Dashboard; `Dashboard engine/crates/vaultspec-api`.
- [ ] `W05.P13.S65` - Measure A26/A27 seated boot, source/PATH-independent execution, module/MCP operation, incompatible schema refusal, snapshot/rollback and owned drain/restart with child census; `Dashboard engine/crates/vaultspec-product`.
- [ ] `W05.P13.S66` - Measure A28 thirty minutes at sustained configured C with proven occupancy, bounded queues/connections/processes and post-quiescence RSS/child counts; `src/vaultspec_a2a/acceptance/tests`.
- [ ] `W05.P13.S75` - Measure A28 thirty minutes at 2C submitted load with disclosed overload, bounded queue drain, proven quiescence and post-load RSS/child counts; `src/vaultspec_a2a/acceptance/tests`.
- [ ] `W05.P13.S67` - Measure A29 at least one hundred status acknowledgement samples under named loaded Dashboard conditions against the adopted p95/p99 targets; `src/vaultspec_a2a/acceptance/tests`.
- [ ] `W05.P13.S73` - Measure A29 at least one hundred message acknowledgement samples under the same named loaded Dashboard conditions against the adopted p95/p99 targets; `src/vaultspec_a2a/acceptance/tests`.
- [ ] `W05.P13.S74` - Measure A29 at least one hundred cancellation acknowledgement samples under the same named loaded Dashboard conditions against the adopted p95/p99 targets; `src/vaultspec_a2a/acceptance/tests`.
- [ ] `W05.P13.S68` - Measure A30 secret-canary exclusion and bounded UTF-8 diagnostics across served errors, events and retained logs while preserving safe run/action identity; `src/vaultspec_a2a/acceptance/tests`.

## Wave `W06` - Review and close the campaign

Reconcile measured qualification and documentation under the remediation ADR. This Wave cannot close while required positive behavior or any applicable evidence boundary remains missing.

### Phase `W06.P14` - Reconcile review and readiness

Close only findings whose own discriminators were rerun and whose dependencies truly landed.

- [ ] `W06.P14.S69` - Verify final consumer guide delivery under 2026-08-05-served-capability-contract-plan W03.P06.S47 and W02.P03.S10 against measured controls and limitations; `client guide dependency`.
- [ ] `W06.P14.S70` - Run final formal implementation review, classify every new finding and reconcile ER01-ER28 closure evidence with the rolling audit queue; `remediation audit queue`.
- [ ] `W06.P14.S71` - Reconcile every A01-A34 assertion and exact-mode applicability against authoritative results, preserving blocked/partial evidence and withholding readiness until all applicable criteria pass; `qualification evidence`.
- [ ] `W06.P14.S72` - Run required repository checks and Core plan/document validation, then reconcile execution records and unchecked dependency gates before requesting release qualification review; `remediation execution records`.

## Parallelization

W02 may begin after W01.P01.S01-S02 establish the baseline and relevant local contracts. W01 prerequisite follow-up and S04-S08 environment repairs may remain open while independent local corrections proceed; they block their dependent proofs and final closure, not unrelated remediation. Subsequent Waves follow their stated runtime dependencies, and no Wave is marked complete with an open Step. Within Freeze execution prerequisites, test-environment repairs may proceed independently of the consumer contract inventory after baseline identities are captured. Within Repair durable control and lifecycle, database election precedes terminal reconciliation; receipt evidence precedes queue recovery. Cancellation and breaker changes may proceed in parallel only with separate file ownership, since worker/app.py and executor.py are shared. Within Preserve provider and context semantics, condition preservation and negotiation may proceed separately from prompt-view work; native command execution depends on committed prompt-view semantics for compaction. Consumer broker additions depend on the corresponding runtime operations and a coordinated consumer contract. All qualification follows the intended binary/consumer integration. External-provider qualification may run alongside isolated local drills with separate workspaces and credentials, never by sharing fault targets. Review closes a Wave only after its queue and execution records are current.

## Verification

The campaign is complete only when every Step is checked, every applicable A01-A34 assertion passes at its required source/local/provider/Dashboard boundary, and no critical or high finding remains unresolved. Related criteria research supplies the adopted numeric thresholds; capture configured queue limits, run-derived deadlines, process identities and host/load before measurement. A source test, typed model, catalog enumeration, unavailable prerequisite, skipped test or deterministic lane cannot certify external work. Optional unsupported capabilities qualify by truthful refusal only where the criterion permits it; required positive operations cannot qualify by disabling them.

Every ER finding retains its original failing evidence and gains the exact corrected revision, command, discriminator, count/timing and boundary before closure. Existing owner dependencies must be verified against actual implementation, not merely checked plan boxes. Missing safe fault controls, exact-provider credentials or the intended Dashboard generation leave dependent Steps unchecked and qualification BLOCKED. Report passed/applicable and measured/applicable separately, retaining PARTIAL and NOT MEASURED cases. Run the required repository quality checks and project-locked Core plan/document checks; record formal review and the rolling queue with no unclassified finding. This document remains at the user review boundary until explicitly approved.

### Finding ownership and closure gates

Implementation/dependency Steps below retain the audit's original severity and owner boundaries. Closure gates are additional evidence, not permission to close a finding on a checked implementation row alone. Active owner identifiers are stated in the dependency Step; historical Step states remain intact.

| Finding | Implementation or dependency Steps | Closing evidence Steps |
| --- | --- | --- |
| ER01 | `W02.P03.S78`, `W02.P03.S12`, `W02.P03.S13` | `W05.P11.S53` |
| ER02 | `W02.P03.S76`, `W02.P03.S77`, `W02.P03.S09`, `W02.P03.S13`, `W02.P03.S14` | `W05.P11.S54` |
| ER03 | `W02.P04.S16`, `W02.P04.S17`, `W02.P04.S18` | `W05.P11.S52`, `W05.P11.S53` |
| ER04 | `W02.P05.S19` | `W05.P11.S54` |
| ER05 | `W02.P05.S20` | `W05.P11.S54` |
| ER06 | `W04.P09.S46` | `W05.P13.S64` |
| ER07 | `W03.P06.S28`, `W03.P06.S29`, `W03.P06.S30` | `W05.P11.S55`, `W05.P12.S62` |
| ER08 | `W03.P06.S25`, `W03.P06.S26`, `W03.P06.S27` | `W05.P12.S62` |
| ER09 | `W04.P09.S39`, `W04.P09.S40`, `W04.P09.S41` | `W05.P12.S61` |
| ER10 | `W03.P07.S32`, `W03.P07.S80` | `W05.P12.S63` |
| ER11 | `W03.P07.S31` | `W05.P12.S63` |
| ER12 | `W03.P07.S33`, `W03.P07.S34` | `W05.P12.S63` |
| ER13 | `W03.P08.S35`, `W03.P08.S36` | `W05.P12.S58`, `W05.P12.S59` |
| ER14 | `W03.P08.S37`, `W03.P08.S38`, `W03.P08.S81`, `W04.P09.S42`, `W04.P09.S45` | `W05.P12.S62` |
| ER15 | `W04.P10.S47`, `W04.P10.S49` | `W05.P13.S65` |
| ER16 | `W04.P10.S49` | `W05.P13.S65` |
| ER17 | `W04.P10.S50`, `W05.P12.S57` | `W05.P13.S65` |
| ER18 | `W01.P02.S04` | `W06.P14.S72` |
| ER19 | `W01.P02.S05` | `W05.P12.S57` |
| ER20 | `W01.P02.S06` | `W06.P14.S72` |
| ER21 | `W01.P02.S07` | `W01.P02.S07`, `W05.P13.S67` |
| ER22 | `W01.P02.S08` | `W06.P14.S72` |
| ER23 | `W01.P01.S02`, `W04.P10.S47` | `W05.P13.S65` |
| ER24 | `W01.P01.S02`, `W04.P10.S48` | `W05.P13.S65` |
| ER25 | `W02.P05.S21`, `W02.P05.S22`, `W02.P03.S14` | `W05.P11.S54` |
| ER26 | `W02.P05.S23` | `W05.P11.S56`, `W05.P13.S75` |
| ER27 | `W02.P05.S24` | `W05.P11.S56`, `W05.P13.S75` |
| ER28 | `W02.P04.S15`, `W02.P04.S79` | `W05.P11.S53`, `W05.P13.S75` |

The plan is saved for review with 81 open Steps. ADRs are accepted under the owner's auto-approval; no Step is authorized for execution until the owner approves this plan. Schema/control changes require the intended consumer contract established in W01.P01.S02; supplier-only changes cannot declare consumer integration complete.

Core inserted S73-S81 next to their prerequisite or related operation without renumbering existing IDs. Their non-monotonic display order is intentional and explains PLAN022; execution follows the displayed dependency order, not numeric sorting. The original identifiers and all unchecked states are preserved.

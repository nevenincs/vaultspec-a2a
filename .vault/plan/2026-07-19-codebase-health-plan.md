---
tags:
  - '#plan'
  - '#codebase-health'
date: '2026-07-19'
modified: '2026-07-22'
tier: L3
related:
  - '[[2026-07-19-codebase-health-adr]]'
  - '[[2026-07-19-codebase-health-research]]'
  - '[[2026-07-19-codebase-health-audit]]'
  - '[[2026-07-18-desktop-product-profile-adr]]'
  - '[[2026-07-18-desktop-product-profile-plan]]'
  - '[[2026-07-14-a2a-edge-conformance-adr]]'
  - '[[2026-03-31-integration-testing-smoke-tests-api-verification-adr]]'
  - '[[2026-07-15-dev-process-registry-adr]]'
  - '[[2026-07-19-repository-tooling-hardening-adr]]'
  - '[[2026-07-19-repository-tooling-hardening-plan]]'
  - '[[2026-07-19-observability-lanes-adr]]'
  - '[[2026-07-19-observability-lanes-plan]]'
  - '[[2026-07-17-tool-cores-adr]]'
---

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the
       related: field above.
     - The related: field carries the AUTHORISING documents
       (ADR, research, reference, prior plan) for every Step in
       this plan. Steps inherit this chain; per-row reference
       footers do not exist.
     - NEVER use [[wiki-links]] or markdown links in the
       document body. -->

# `codebase-health` plan

Failure-atomic hardening and dashboard-owned product certification for the
audited A2A service.

## Description

This L3 plan executes the accepted codebase-health ADR and its research and
audit across the A2A service and its sole product consumer,
`vaultspec-dashboard`. It closes runtime-integrity, cross-store deletion,
public-edge, provider-containment, evidence, duplication, dead-code, and
complexity findings without reopening accepted topology decisions.

The desktop-product-profile ADR and plan govern the runtime prerequisites used
by W01, W02, W03, and W05. The A2A-edge ADR governs W02 and the W05 composite
contract. The integration-testing ADR governs the real-stack evidence in W05.
The dev-process-registry ADR governs `W01.P01` and `W01.P02`. The
repository-tooling ADR and plan govern the prerequisite gates in `W01.P01`,
`W04.P12`, `W04.P16`, and `W05.P20`. The observability ADR and completed plan
govern bounded evidence consumed by `W05.P20`. The tool-cores ADR governs the
protocol boundary consumed by W03.

The active plans remain authoritative for work they already own. W01 consumes
desktop steps S30 through S62 and S89 through S92 plus repository-tooling S07.
W02 consumes desktop S32, S36 through S51, and S63 through S70. W03 consumes
desktop S60 through S62 and the completed tool-core protocol work. W04 consumes
repository-tooling S09 and S11 without duplicating generic typing, dependency,
test-selection, or documentation-pipeline work. W05 follows desktop S81 through
S85 and repository-tooling S10 and S12.

Each prerequisite is an evidence gate. If a parent-plan implementation leaves
an audited finding open, the finding is appended to this audit queue before a
residual change is assigned; this plan does not silently take concurrent
ownership of the same code. Every implementation wave ends in a formal review
and classified queue update, as required by the repository's rolling audit
cycle.

## Steps

## Wave `W01` - establish failure-atomic control state

Backed by the codebase-health ADR research and audit plus the desktop and process-registry decisions, this Wave curates authority and closes failure-atomic control state before downstream Wave W02 may begin.

### Phase `W01.P01` - reconcile authority and prerequisite evidence

Establish one usable decision chain and prove that prerequisite ownership work has landed without duplicating its implementation.

- [x] `W01.P01.S01` - Curate the service-lifecycle supersession chain so the product lifecycle and tooling decisions have non-conflicting authority; `.vault/adr, .vault/index`.
- [ ] `W01.P01.S02` - Certify the landed desktop singleton credential and owned-process prerequisites without treating them as proof of worker pairing identity; `.vault/exec, .vault/audit, src/vaultspec_a2a/desktop_tests`.
- [x] `W01.P01.S03` - Certify the process-registry prerequisite represented by repository-tooling plan step S07 before changing lifecycle registry consumers; `.vault/exec, .vault/audit, just/dev/service.just`.
- [x] `W01.P01.S93` - Implement gateway lifetime identity worker generation identity and explicit paired-gateway identity in authenticated readiness; `src/vaultspec_a2a/api/schemas/gateway.py, src/vaultspec_a2a/control/worker_management.py, src/vaultspec_a2a/api/internal.py, src/vaultspec_a2a/worker/app.py`.
- [x] `W01.P01.S94` - Fail closed on blank stale mismatched or unauthenticated pairing evidence and permit eviction only for the owner-authorized desktop prior generation; `src/vaultspec_a2a/control/worker_management.py, src/vaultspec_a2a/control/health.py`.
- [ ] `W01.P01.S95` - Prove authenticated two-gateway one-worker pairing with real processes; `src/vaultspec_a2a/desktop_tests/test_worker_provenance.py`.
- [ ] `W01.P01.S153` - Prove plain worker health never authorizes adoption with real processes; `src/vaultspec_a2a/desktop_tests/test_worker_provenance.py`.
- [ ] `W01.P01.S154` - Prove blank worker pairing never authorizes adoption with real processes; `src/vaultspec_a2a/desktop_tests/test_worker_provenance.py`.
- [ ] `W01.P01.S155` - Prove unauthenticated legacy readiness never authorizes adoption with real processes; `src/vaultspec_a2a/desktop_tests/test_worker_provenance.py`.
- [ ] `W01.P01.S156` - Prove failed owner-authorized eviction returns conflict without adoption with real processes; `src/vaultspec_a2a/desktop_tests/test_worker_provenance.py`.
- [ ] `W01.P01.S157` - Prove Compose provenance mismatch fails closed without eviction with real processes; `src/vaultspec_a2a/service_tests/test_compose_profile_regression.py`.

### Phase `W01.P02` - make lifecycle startup transactional

Publish only readiness-proven generations and reap every owned descendant when a post-spawn operation fails.

- [ ] `W01.P02.S04` - Make resume reserve spawn verify readiness and commit one process generation before publication; `src/vaultspec_a2a/lifecycle/manager.py, src/vaultspec_a2a/lifecycle/registry.py`.
- [ ] `W01.P02.S05` - Reap the complete owned process tree when serve-up fails after readiness but before ownership commit; `src/vaultspec_a2a/lifecycle/manager.py, src/vaultspec_a2a/utils/process.py`.
- [ ] `W01.P02.S06` - Verify the landed desktop owned-tree implementation reaps the complete worker tree on startup readiness timeout; `.vault/exec, .vault/audit, src/vaultspec_a2a/desktop_tests/test_owned_process_tree.py`.
- [ ] `W01.P02.S07` - Prove resume failure atomicity with a real child process; `tests/lifecycle, src/vaultspec_a2a/desktop_tests`.
- [ ] `W01.P02.S96` - Require confirmed old-tree termination before spawning or publishing a resume replacement generation; `src/vaultspec_a2a/lifecycle/manager.py, src/vaultspec_a2a/lifecycle/registry.py, src/vaultspec_a2a/utils/process.py`.
- [ ] `W01.P02.S97` - Prove resume kill failure leaves the prior registry generation unchanged and creates no overlapping child; `tests/lifecycle/test_manager_processes.py, src/vaultspec_a2a/desktop_tests`.
- [ ] `W01.P02.S107` - Make rerun reserve spawn verify readiness and commit one process generation before publication; `src/vaultspec_a2a/lifecycle/manager.py, src/vaultspec_a2a/lifecycle/registry.py`.
- [ ] `W01.P02.S149` - Prove rerun failure atomicity with a real child process; `tests/lifecycle, src/vaultspec_a2a/desktop_tests`.
- [ ] `W01.P02.S150` - Prove serve-up failure atomicity with a real child process; `tests/lifecycle, src/vaultspec_a2a/desktop_tests`.
- [ ] `W01.P02.S151` - Require confirmed old-tree termination before spawning or publishing a rerun replacement generation; `src/vaultspec_a2a/lifecycle/manager.py, src/vaultspec_a2a/lifecycle/registry.py, src/vaultspec_a2a/utils/process.py`.
- [ ] `W01.P02.S152` - Prove rerun kill failure leaves the prior registry generation unchanged and creates no overlapping child; `tests/lifecycle/test_manager_processes.py, src/vaultspec_a2a/desktop_tests`.

### Phase `W01.P03` - coordinate cross-store thread deletion

Replace irreversible hard deletion with a durable resumable saga whose control state remains authoritative until cleanup finishes.

- [ ] `W01.P03.S08` - Add deleting state cleanup-manifest and cleanup-result persistence to the control schema; `src/vaultspec_a2a/database, src/vaultspec_a2a/control/repositories`.
- [ ] `W01.P03.S09` - Implement the idempotent repository operation that creates one deletion saga; `src/vaultspec_a2a/control/repositories`.
- [ ] `W01.P03.S10` - Coordinate checkpoint artifact and control-row deletion from the durable cleanup manifest; `src/vaultspec_a2a/control/thread_service.py, src/vaultspec_a2a/control/cleanup`.
- [ ] `W01.P03.S11` - Hide deleting threads from normal run lookup and list operations while retaining cleanup visibility; `src/vaultspec_a2a/control/thread_service.py, src/vaultspec_a2a/control/thread_state_service.py`.
- [ ] `W01.P03.S12` - Run checkpoint and artifact cleanup independently so one failure cannot skip later cleanup items; `src/vaultspec_a2a/control/cleanup, src/vaultspec_a2a/checkpointer`.
- [ ] `W01.P03.S13` - Resume the same deletion saga when the delete endpoint receives a replayed request; `src/vaultspec_a2a/api/routes/threads.py, src/vaultspec_a2a/control/thread_service.py`.
- [ ] `W01.P03.S14` - Prove deletion retries crash recovery hidden-state behavior and finalization against real control and checkpoint stores; `tests/control, tests/api`.
- [ ] `W01.P03.S108` - Implement the idempotent repository operation that claims one deletion saga; `src/vaultspec_a2a/control/repositories`.
- [ ] `W01.P03.S109` - Implement the idempotent repository operation that advances one deletion cleanup item; `src/vaultspec_a2a/control/repositories`.
- [ ] `W01.P03.S110` - Implement the idempotent repository operation that finalizes one completed deletion saga; `src/vaultspec_a2a/control/repositories`.

### Phase `W01.P04` - review and queue control-state findings

Review the landed control-state implementation and preserve every newly surfaced issue in the rolling audit trail.

- [ ] `W01.P04.S15` - Run the formal safety intent and quality review for Wave W01 against the implemented diff and real tests; `.vault/audit, .vault/exec`.
- [ ] `W01.P04.S16` - Classify every Wave W01 review finding and append unresolved work to the codebase-health audit queue; `.vault/audit/2026-07-19-codebase-health-audit.md, .vault/exec`.

## Wave `W02` - serve an authenticated positive dashboard edge

Backed by the codebase-health A2A-edge and desktop decisions, this Wave consumes reviewed W01 state and the desktop credential contract to establish the authenticated positive dashboard edge required by downstream Wave W03.

### Phase `W02.P05` - bind replay identity and coherent status

Make idempotency behavior-complete and derive each run-status response from one immutable checkpoint view.

- [x] `W02.P05.S17` - Define a canonical run-start fingerprint over every behavior-affecting request field; `src/vaultspec_a2a/api/schemas/gateway.py, src/vaultspec_a2a/control/run_start_policy.py`.
- [x] `W02.P05.S18` - Persist the run-start fingerprint and return conflict for mismatched replay on both normal and integrity-error paths; `src/vaultspec_a2a/api/routes/gateway.py, src/vaultspec_a2a/control/repositories`.
- [x] `W02.P05.S19` - Unify launch discovery and acceptance on one profile eligibility decision; `src/vaultspec_a2a/providers/model_profiles.py, src/vaultspec_a2a/api/routes/gateway.py, src/vaultspec_a2a/authoring/discovery.py`.
- [x] `W02.P05.S20` - Read one project checkpoint tuple and derive all run-status fields from that immutable snapshot; `src/vaultspec_a2a/control/thread_state_service.py`.
- [ ] `W02.P05.S21` - Prove request-fingerprint conflicts profile parity and single-snapshot run status against real persistence; `tests/api, tests/control`.

### Phase `W02.P06` - allowlist progress and bound stream resources

Replace payload-shaped relaying with one versioned DTO and enforce resource limits before and after authentication.

- [ ] `W02.P06.S22` - Define the versioned positive progress DTO with identifiers lifecycle state bounded counters approved summaries and one bounded token-delta field; `src/vaultspec_a2a/api/schemas/gateway.py, src/vaultspec_a2a/streaming`.
- [ ] `W02.P06.S23` - Transform gateway events through the positive DTO while excluding prompts documents artifacts edit diffs and raw provider payloads; `src/vaultspec_a2a/streaming/aggregator.py, src/vaultspec_a2a/streaming/transformer.py`.
- [x] `W02.P06.S24` - Authenticate the progress stream and enforce global connection limits before principal lookup; `src/vaultspec_a2a/api/routes/gateway.py, src/vaultspec_a2a/api/dependencies.py`.
- [ ] `W02.P06.S25` - Enforce per-principal stream and subscription quotas after authentication; `src/vaultspec_a2a/streaming/subscribers.py, src/vaultspec_a2a/api/routes/thread_stream.py`.
- [x] `W02.P06.S26` - Parse numeric and ISO heartbeat values strictly and reject stale malformed non-finite and implausibly future values; `src/vaultspec_a2a/authoring/discovery.py`.
- [ ] `W02.P06.S27` - Prove progress allowlisting with a real authenticated stream client; `tests/streaming, tests/api`.
- [ ] `W02.P06.S98` - Enforce the positive progress allowlist again at the SSE frame and API event-adapter output boundary; `src/vaultspec_a2a/streaming/sse_frames.py, src/vaultspec_a2a/api/event_adapter.py`.
- [ ] `W02.P06.S99` - Prove forbidden fields cannot cross the encoded A2A SSE boundary; `tests/streaming, tests/api`.
- [ ] `W02.P06.S159` - Prove bounded token deltas with a real authenticated stream client; `tests/streaming, tests/api`.
- [ ] `W02.P06.S160` - Prove global and per-principal quotas with real authenticated stream clients; `tests/streaming, tests/api`.
- [ ] `W02.P06.S161` - Prove malformed and stale heartbeat rejection against real discovery records; `tests/authoring`.

### Phase `W02.P07` - retire legacy dependencies from the dashboard path

Keep transition surfaces credential-gated and unadvertised while moving the dashboard store and engine facade to the supported product contract.

- [ ] `W02.P07.S28` - Disable legacy product routes in Compose when no attach credential is configured after consuming certified desktop route authentication; `src/vaultspec_a2a/api/routes, service`.
- [ ] `W02.P07.S29` - Remove the credential-gated legacy event WebSocket from dashboard discovery after consuming certified desktop WebSocket authentication; `src/vaultspec_a2a/lifecycle/discovery.py, src/vaultspec_a2a/api/app.py`.
- [ ] `W02.P07.S100` - Write the dashboard-local research that grounds store engine workflow audit and release-setting changes; `../../vaultspec-dashboard-worktrees/main/.vault/research`.
- [ ] `W02.P07.S158` - Write the dashboard-local ADR from the approved research decision boundary; `../../vaultspec-dashboard-worktrees/main/.vault/adr, ../../vaultspec-dashboard-worktrees/main/.vault/research`.
- [ ] `W02.P07.S164` - Obtain explicit acceptance of the dashboard-local ADR; `../../vaultspec-dashboard-worktrees/main/.vault/adr`.
- [ ] `W02.P07.S165` - Write the dashboard-local implementation plan from the accepted ADR; `../../vaultspec-dashboard-worktrees/main/.vault/plan, ../../vaultspec-dashboard-worktrees/main/.vault/adr`.
- [ ] `W02.P07.S166` - Obtain explicit approval of the dashboard-local implementation plan before dashboard mutation; `../../vaultspec-dashboard-worktrees/main/.vault/plan`.
- [ ] `W02.P07.S30` - Consume only the positive progress DTO in the dashboard live A2A store adapter; `../../vaultspec-dashboard-worktrees/main/frontend/src/stores/server/liveAdapters/a2aRelay.ts`.
- [ ] `W02.P07.S31` - Expose authenticated prepare behavior through the dashboard engine run-control facade without direct worker or provider control; `../../vaultspec-dashboard-worktrees/main/engine/crates/vaultspec-api/src/routes/ops/a2a.rs`.
- [ ] `W02.P07.S167` - Expose authenticated start behavior through the dashboard engine run-control facade without direct worker or provider control; `../../vaultspec-dashboard-worktrees/main/engine/crates/vaultspec-api/src/routes/ops/a2a.rs`.
- [ ] `W02.P07.S168` - Expose authenticated status behavior through the dashboard engine run-control facade without direct worker or provider control; `../../vaultspec-dashboard-worktrees/main/engine/crates/vaultspec-api/src/routes/ops/a2a.rs`.
- [ ] `W02.P07.S169` - Expose authenticated cancel behavior through the dashboard engine run-control facade without direct worker or provider control; `../../vaultspec-dashboard-worktrees/main/engine/crates/vaultspec-api/src/routes/ops/a2a.rs`.
- [ ] `W02.P07.S32` - Prove bounded token relay through the real dashboard store and engine facade; `../../vaultspec-dashboard-worktrees/main/frontend/src/stores/server/agent, ../../vaultspec-dashboard-worktrees/main/engine/crates/vaultspec-api/tests`.
- [ ] `W02.P07.S111` - Expose authenticated progress behavior through the dashboard engine stream facade without direct worker or provider control; `../../vaultspec-dashboard-worktrees/main/engine/crates/vaultspec-api/src/routes/ops/a2a_stream.rs`.
- [ ] `W02.P07.S112` - Prove progress reconnection through the real dashboard store and engine facade; `../../vaultspec-dashboard-worktrees/main/frontend/src/stores/server/agent, ../../vaultspec-dashboard-worktrees/main/engine/crates/vaultspec-api/tests`.
- [ ] `W02.P07.S113` - Prove forbidden-content exclusion through the real dashboard store and engine facade; `../../vaultspec-dashboard-worktrees/main/frontend/src/stores/server/agent, ../../vaultspec-dashboard-worktrees/main/engine/crates/vaultspec-api/tests`.
- [ ] `W02.P07.S162` - Prove forbidden fields cannot reach a real dashboard consumer; `../../vaultspec-dashboard-worktrees/main/frontend/src/stores/server/agent, ../../vaultspec-dashboard-worktrees/main/engine/crates/vaultspec-api/tests`.

### Phase `W02.P08` - review and queue edge findings

Review the two-repository edge implementation and preserve all residual contract or security findings.

- [ ] `W02.P08.S33` - Run the formal architecture security resource-bound and quality review for Wave W02 in both repositories; `.vault/audit, .vault/exec, ../../vaultspec-dashboard-worktrees/main/.vault/audit`.
- [ ] `W02.P08.S34` - Classify every Wave W02 review finding and append unresolved work to the owning audit queue; `.vault/audit/2026-07-19-codebase-health-audit.md, ../../vaultspec-dashboard-worktrees/main/.vault/audit`.

## Wave `W03` - contain provider and protocol failures

Backed by the codebase-health desktop and tool-core decisions, this Wave consumes reviewed W02 contracts and the owned provider-tree prerequisite to contain provider and protocol failures before downstream Wave W04.

### Phase `W03.P09` - make MCP configuration admission unambiguous

Use one canonical server model and reject duplicate identities before generating provider-specific configuration.

- [x] `W03.P09.S35` - Consolidate harness MCP server normalization on one canonical schema and resolver; `src/vaultspec_a2a/providers/_acp_mcp.py, src/vaultspec_a2a/mcp`.
- [x] `W03.P09.S36` - Reject duplicate MCP server identities before emitting Codex or ACP configuration; `src/vaultspec_a2a/providers/_acp_mcp.py, src/vaultspec_a2a/providers/_acp_project_mcp.py`.
- [x] `W03.P09.S37` - Prove duplicate MCP identity rejection through the real configuration parser; `tests/providers, tests/mcp`.
- [ ] `W03.P09.S114` - Prove valid Codex MCP configuration through the real Codex entrypoint; `tests/providers, tests/mcp`.
- [ ] `W03.P09.S115` - Prove valid ACP MCP configuration through the real ACP entrypoint; `tests/providers, tests/mcp`.

### Phase `W03.P10` - bound subprocess and background protocol work

Ensure provider output cannot deadlock, background failures cannot hang a turn, and cleanup attempts every sensitive resource independently.

- [x] `W03.P10.S38` - Continuously drain Codex standard error into a bounded redacted diagnostic buffer; `src/vaultspec_a2a/providers/codex_chat_model.py, src/vaultspec_a2a/providers/_subprocess.py`.
- [x] `W03.P10.S39` - Propagate ACP background RPC handler failures as protocol errors or terminal session failures; `src/vaultspec_a2a/providers/_acp_protocol.py, src/vaultspec_a2a/providers/acp_chat_model.py`.
- [x] `W03.P10.S40` - Apply bounded deadlines to provider turns requests and cleanup operations; `src/vaultspec_a2a/providers/acp_chat_model.py, src/vaultspec_a2a/providers/codex_chat_model.py`.
- [ ] `W03.P10.S41` - Attempt Codex credential cleanup independently while aggregating failures; `src/vaultspec_a2a/providers/codex_chat_model.py`.
- [ ] `W03.P10.S42` - Attempt ACP credential cleanup independently while aggregating failures; `src/vaultspec_a2a/providers/acp_chat_model.py, src/vaultspec_a2a/providers/_acp_auth.py`.
- [ ] `W03.P10.S43` - Prove standard-error backpressure handling with a real provider subprocess; `tests/providers, src/vaultspec_a2a/desktop_tests`.
- [ ] `W03.P10.S116` - Attempt Codex temporary-configuration cleanup independently while aggregating failures; `src/vaultspec_a2a/providers/codex_chat_model.py`.
- [ ] `W03.P10.S117` - Attempt Codex background-task cleanup independently while aggregating failures; `src/vaultspec_a2a/providers/codex_chat_model.py`.
- [ ] `W03.P10.S118` - Attempt Codex process cleanup independently while aggregating failures; `src/vaultspec_a2a/providers/codex_chat_model.py`.
- [ ] `W03.P10.S119` - Attempt ACP temporary-configuration cleanup independently while aggregating failures; `src/vaultspec_a2a/providers/acp_chat_model.py, src/vaultspec_a2a/providers/_acp_auth.py`.
- [ ] `W03.P10.S120` - Attempt ACP background-task cleanup independently while aggregating failures; `src/vaultspec_a2a/providers/acp_chat_model.py`.
- [ ] `W03.P10.S121` - Attempt ACP process cleanup independently while aggregating failures; `src/vaultspec_a2a/providers/acp_chat_model.py`.
- [ ] `W03.P10.S122` - Prove RPC handler failure terminates a real provider session; `tests/providers, src/vaultspec_a2a/desktop_tests`.
- [ ] `W03.P10.S123` - Prove provider deadline expiry terminates a real provider session; `tests/providers, src/vaultspec_a2a/desktop_tests`.
- [ ] `W03.P10.S124` - Prove cleanup continuation after one cleanup failure with a real provider subprocess; `tests/providers, src/vaultspec_a2a/desktop_tests`.

### Phase `W03.P11` - review and queue provider findings

Review the provider containment implementation and carry all remaining reliability or secret-lifecycle risks into the audit queue.

- [ ] `W03.P11.S44` - Run the formal safety security resource-bound and quality review for Wave W03 against real subprocess evidence; `.vault/audit, .vault/exec`.
- [ ] `W03.P11.S45` - Classify every Wave W03 review finding and append unresolved work to the codebase-health audit queue; `.vault/audit/2026-07-19-codebase-health-audit.md, .vault/exec`.

## Wave `W04` - retire duplication dead surfaces and structural debt

Backed by the codebase-health audit and repository-tooling decision and plan, this Wave consumes reviewed blocker Waves W01 through W03 and retires evidence duplication dead surfaces and complexity debt before downstream Wave W05.

### Phase `W04.P12` - restore evidence and bounded query behavior

Consume the tooling debt work, repair the concrete stale and non-hermetic cases, and bound dashboard-facing state reads.

- [x] `W04.P12.S46` - Certify repository-tooling step S09 removed the audited prohibited doubles skips mutations suppressions and dependency-gate drift; `.vault/exec, .vault/audit, tests, pyproject.toml`.
- [ ] `W04.P12.S47` - Update the Kimi profile expectation from the governing production contract; `src/vaultspec_a2a/api/tests/test_gateway_live.py`.
- [x] `W04.P12.S48` - Bind MCP-unavailable error-path tests to an owned closed loopback socket without production-state mutation; `tests/mcp, tests/api`.
- [x] `W04.P12.S49` - Make one repair-policy module authoritative for runtime transitions and direct production-import tests; `src/vaultspec_a2a/thread/repair_policy.py, src/vaultspec_a2a/control/repair_transitions.py, tests`.
- [x] `W04.P12.S50` - Replace sequential per-thread checkpoint reads with bounded bulk reads limited concurrency and one request deadline; `src/vaultspec_a2a/control/thread_service.py, src/vaultspec_a2a/control/repositories`.
- [x] `W04.P12.S51` - Prove thread-list ordering partial-state policy concurrency bounds and request deadline against real stores; `tests/control, tests/api`.
- [ ] `W04.P12.S101` - Replace prohibited fake mock and stub based tests with direct production imports and real behavior; `tests, src/vaultspec_a2a`.
- [ ] `W04.P12.S102` - Replace prohibited skip and expected-failure shortcuts with executable environment gates or real fixtures; `tests, src/vaultspec_a2a`.
- [ ] `W04.P12.S103` - Remove prohibited monkeypatch and runtime code-mutation tests in favor of owned configuration and process boundaries; `tests, src/vaultspec_a2a`.
- [ ] `W04.P12.S104` - Replace tautological and shadow-logic tests with assertions against imported production behavior; `tests, src/vaultspec_a2a`.
- [ ] `W04.P12.S105` - Remove audited type suppressions by correcting production and test contracts; `src/vaultspec_a2a, tests`.
- [ ] `W04.P12.S125` - Update the thread-error expectation from the governing production contract; `src/vaultspec_a2a/thread/tests/test_errors.py`.
- [ ] `W04.P12.S126` - Update the feedback-batch expectation from the governing production contract; `src/vaultspec_a2a/thread/tests/test_state.py`.

### Phase `W04.P13` - centralize duplicated behavior

Share only state-transition and backpressure behavior while retaining deliberate transport and domain separation.

- [ ] `W04.P13.S52` - Introduce one typed dispatch-failure classification and state-transition function; `src/vaultspec_a2a/control/dispatch.py`.
- [ ] `W04.P13.S53` - Introduce one bounded drop-oldest fanout implementation; `src/vaultspec_a2a/streaming/subscribers.py`.
- [ ] `W04.P13.S54` - Introduce one strict integer-coercion helper for discovery metadata; `src/vaultspec_a2a/lifecycle/discovery.py`.
- [x] `W04.P13.S55` - Centralize behavior-bearing cancellation message and gateway response mapping without merging wire and domain schemas; `src/vaultspec_a2a/api/routes`.
- [x] `W04.P13.S56` - Record package facades and parallel wire-domain field blocks as deliberate non-duplicates after ownership review; `.vault/audit/2026-07-19-codebase-health-audit.md, src/vaultspec_a2a/graph, src/vaultspec_a2a/providers`.
- [x] `W04.P13.S127` - Route message dispatch failure through the shared typed transition function; `src/vaultspec_a2a/control/message_service.py`.
- [x] `W04.P13.S128` - Route thread dispatch failure through the shared typed transition function; `src/vaultspec_a2a/control/thread_service.py`.
- [x] `W04.P13.S129` - Route permission dispatch failure through the shared typed transition function; `src/vaultspec_a2a/control/permission_service.py`.
- [x] `W04.P13.S130` - Route subscriber delivery through the shared bounded fanout implementation; `src/vaultspec_a2a/streaming/subscribers.py`.
- [x] `W04.P13.S131` - Route WebSocket delivery through the shared bounded fanout implementation; `src/vaultspec_a2a/api/websocket.py`.
- [x] `W04.P13.S132` - Route authoring lifecycle integer coercion through the shared strict helper; `src/vaultspec_a2a/authoring/lifecycle.py`.
- [x] `W04.P13.S133` - Route lifecycle discovery integer coercion through the shared strict helper; `src/vaultspec_a2a/lifecycle/discovery.py`.

### Phase `W04.P14` - remove proven orphan surfaces

Recheck both repositories for compatibility ownership and then remove each audited export or subsystem that still has no consumer.

- [x] `W04.P14.S57` - Prove runtime and dashboard ownership or non-ownership for `GitManager`, `MergeStrategy`, `WorktreeInfo`, `WorkspaceError`, `MergeConflictError`, and the live `_git_mutex`; `src/vaultspec_a2a/workspace/git_manager.py, src/vaultspec_a2a/thread/errors.py, src/vaultspec_a2a/thread/__init__.py, ../../vaultspec-dashboard-worktrees/main, .vault/audit`.
- [ ] `W04.P14.S174` - Move `_git_mutex` from `workspace/git_manager.py` to `workspace/concurrency.py`, route the ACP handler and Git manager through it, and prove real concurrent ACP writes and Git operations remain serialized; `src/vaultspec_a2a/workspace/concurrency.py, src/vaultspec_a2a/workspace/git_manager.py, src/vaultspec_a2a/providers/_acp_rpc_handlers.py, src/vaultspec_a2a/providers/tests/test_acp_authoring.py, src/vaultspec_a2a/workspace/tests/test_workspace.py`.
- [x] `W04.P14.S134` - Prove runtime and dashboard ownership or non-ownership for `AgentState`; `src/vaultspec_a2a/graph/enums.py, ../../vaultspec-dashboard-worktrees/main, .vault/audit`.
- [x] `W04.P14.S58` - Remove the unowned `AgentState` export and its export-only tests; `src/vaultspec_a2a/graph/enums.py, tests`.
- [x] `W04.P14.S135` - Prove runtime and dashboard ownership or non-ownership for `AcpProtocolError`; `src/vaultspec_a2a/providers/acp_exceptions.py, ../../vaultspec-dashboard-worktrees/main, .vault/audit`.
- [x] `W04.P14.S59` - Remove the unowned `AcpProtocolError` export and its export-only tests; `src/vaultspec_a2a/providers/acp_exceptions.py, tests`.
- [x] `W04.P14.S136` - Prove runtime and dashboard ownership or non-ownership for `discover_agent_preset_ids`; `src/vaultspec_a2a/team/team_config.py, ../../vaultspec-dashboard-worktrees/main, .vault/audit`.
- [x] `W04.P14.S60` - Remove the unowned `discover_agent_preset_ids` export and its export-only tests; `src/vaultspec_a2a/team/team_config.py, tests`.
- [x] `W04.P14.S137` - Prove runtime and dashboard ownership or non-ownership for `acceptance_gate_reason`; `src/vaultspec_a2a/providers/model_profiles.py, ../../vaultspec-dashboard-worktrees/main, .vault/audit`.
- [x] `W04.P14.S61` - Remove the unowned `acceptance_gate_reason` export and its export-only tests; `src/vaultspec_a2a/providers/model_profiles.py, tests`.
- [x] `W04.P14.S138` - Prove runtime and dashboard ownership or non-ownership for `projected_declared_names`; `src/vaultspec_a2a/providers/_acp_project_mcp.py, ../../vaultspec-dashboard-worktrees/main, .vault/audit`.
- [x] `W04.P14.S62` - Remove the unowned `projected_declared_names` export and its export-only tests; `src/vaultspec_a2a/providers/_acp_project_mcp.py, tests`.
- [ ] `W04.P14.S63` - After `S57` proves dashboard non-ownership and `S174` relocates `_git_mutex`, remove `GitManager`, `MergeStrategy`, `WorktreeInfo`, `WorkspaceError`, and `MergeConflictError`, their facade exports, and their export-only or worktree-only tests; `src/vaultspec_a2a/workspace/git_manager.py, src/vaultspec_a2a/workspace/__init__.py, src/vaultspec_a2a/workspace/tests, src/vaultspec_a2a/thread/errors.py, src/vaultspec_a2a/thread/__init__.py, src/vaultspec_a2a/thread/tests/test_errors.py`.
- [x] `W04.P14.S64` - Remove the unused `print_trace_summary` helper and its latent integration surface; `src/vaultspec_a2a/utils/trace.py, tests`.
- [x] `W04.P14.S176` - Prove runtime and dashboard ownership or non-ownership for `now_utc`, `parse_iso`, and `human_delta`; `src/vaultspec_a2a/utils/timestamp.py, src/vaultspec_a2a/utils/__init__.py, ../../vaultspec-dashboard-worktrees/main, .vault/audit`.
- [x] `W04.P14.S175` - After `S176` proves A2A and dashboard non-ownership, remove `utils/timestamp.py`, its facade exports, and its export-only tests; `src/vaultspec_a2a/utils/timestamp.py, src/vaultspec_a2a/utils/__init__.py, src/vaultspec_a2a/utils/tests/test_timestamp.py`.

### Phase `W04.P15` - split each complexity hotspot

Decompose every remaining audited function above complexity score twenty at stable policy or translation seams while retaining real-behavior coverage.

- [x] `W04.P15.S65` - Split `process_langgraph_event` into bounded event-family translators; `src/vaultspec_a2a/streaming/aggregator.py, tests/streaming`.
- [ ] `W04.P15.S66` - Split `ProviderFactory.create` into explicit provider admission and construction paths; `src/vaultspec_a2a/providers/factory.py, tests/providers`.
- [ ] `W04.P15.S67` - Split `compose_harness_mcp_servers` into normalization, validation, and projection stages; `src/vaultspec_a2a/providers/_acp_mcp.py, tests/providers`.
- [ ] `W04.P15.S68` - Split `respond_to_permission` into authorization, transition, and dispatch stages; `src/vaultspec_a2a/control/permission_service.py, tests/control`.
- [ ] `W04.P15.S69` - Split `normalize_tool_input_schema` into explicit schema-shape translators; `src/vaultspec_a2a/streaming/transformer.py, tests/streaming`.
- [ ] `W04.P15.S70` - Split `sync_worker_event` into event validation, persistence, and projection stages; `src/vaultspec_a2a/control/event_handlers.py, tests/control`.
- [ ] `W04.P15.S71` - Split `project_checkpoint_tuple` into immutable checkpoint extraction and response projection stages; `src/vaultspec_a2a/control/thread_state_service.py, tests/control`.
- [ ] `W04.P15.S72` - Recalculate complexity and prove every decomposed path preserves real behavior without suppressive thresholds; `src/vaultspec_a2a, tests, .vault/audit`.

### Phase `W04.P16` - repair documentation and mechanical drift

Use the documentation pipeline for the headless service surface and perform only targeted vault repair after concurrent writers finish.

- [x] `W04.P16.S73` - Rewrite service deployment documentation and environment examples to describe the headless runtime through the documentation workflow; `service/README.md, service/docker/README.md, service/.env.example`.
- [ ] `W04.P16.S74` - Repair remaining feature-index drift after active vault writers finish; `.vault/index`.
- [ ] `W04.P16.S139` - Repair remaining generated-template annotation drift after active vault writers finish; `.vault/adr, .vault/audit, .vault/plan, .vault/research`.
- [ ] `W04.P16.S140` - Repair remaining orphan-plan lifecycle drift after active vault writers finish; `.vault/plan, .vault/index`.

### Phase `W04.P17` - review and queue maintainability findings

Review the evidence, removals, deduplication, decomposition, and documentation changes before certification work begins.

- [ ] `W04.P17.S75` - Run the formal intent compatibility quality and documentation review for Wave W04; `.vault/audit, .vault/exec`.
- [ ] `W04.P17.S76` - Classify every Wave W04 review finding and append unresolved work to the codebase-health audit queue; `.vault/audit/2026-07-19-codebase-health-audit.md, .vault/exec`.

## Wave `W05` - certify the assembled dashboard product

Backed by the codebase-health A2A-edge integration-testing desktop repository-tooling and observability decisions, this terminal Wave consumes all reviewed hardening Waves and certifies the assembled dashboard product.

### Phase `W05.P18` - publish the real A2A certification fixture

Provide reusable real gateway worker provider and persistence infrastructure plus one scenario for each cross-repository contract boundary.

- [ ] `W05.P18.S77` - Build a deterministic real-process fixture that launches an authenticated gateway worker provider and real persistence stores; `src/vaultspec_a2a/acceptance, tests/acceptance`.
- [ ] `W05.P18.S78` - Certify authenticated prepare behavior through the supported public surface; `tests/acceptance/test_dashboard_contract.py`.
- [ ] `W05.P18.S170` - Certify authenticated start behavior through the supported public surface; `tests/acceptance/test_dashboard_contract.py`.
- [ ] `W05.P18.S171` - Certify authenticated status behavior through the supported public surface; `tests/acceptance/test_dashboard_contract.py`.
- [ ] `W05.P18.S172` - Certify authenticated cancel behavior through the supported public surface; `tests/acceptance/test_dashboard_contract.py`.
- [ ] `W05.P18.S173` - Certify authenticated progress behavior through the supported public surface; `tests/acceptance/test_dashboard_contract.py`.
- [ ] `W05.P18.S79` - Certify progress reconnection ordering bounded token deltas and forbidden-content exclusion; `tests/acceptance/test_dashboard_stream.py`.
- [ ] `W05.P18.S80` - Certify deletion interruption replay cleanup recovery and final invisibility across real stores; `tests/acceptance/test_dashboard_deletion.py`.
- [ ] `W05.P18.S81` - Certify proposal review permission resume and terminal settlement through the public facade; `tests/acceptance/test_dashboard_proposal_review.py`.
- [ ] `W05.P18.S82` - Certify Compose provenance mismatch fails closed without worker adoption or eviction; `src/vaultspec_a2a/service_tests/test_compose_profile_regression.py`.

### Phase `W05.P19` - own composite certification in the dashboard

Replace synthetic happy-path coverage with the real A2A fixture and make the assembling repository enforce the combined contract.

- [ ] `W05.P19.S83` - Replace the dashboard engine synthetic resident happy path with the real A2A certification fixture; `../../vaultspec-dashboard-worktrees/main/engine/crates/vaultspec-api/src/routes/ops/a2a.rs, ../../vaultspec-dashboard-worktrees/main/engine/crates/vaultspec-api/tests`.
- [ ] `W05.P19.S84` - Add the dashboard store live happy-path test against the authenticated engine and A2A stack; `../../vaultspec-dashboard-worktrees/main/frontend/src/stores/server/agent/a2aTeam.live.test.ts`.
- [ ] `W05.P19.S85` - Create the dashboard-owned `a2a-composite-certification` job for engine, gateway, worker, provider, streaming, deletion recovery, and proposal review; `../../vaultspec-dashboard-worktrees/main/.github/workflows/a2a-composite-certification.yml`.
- [ ] `W05.P19.S86` - Make `a2a-composite-certification` a required dashboard release check with bounded logs, artifacts, and timeouts; `../../vaultspec-dashboard-worktrees/main/.github/workflows/a2a-composite-certification.yml, ../../vaultspec-dashboard-worktrees/main/.vault/plan`.

### Phase `W05.P20` - run release evidence

Execute both repositories' canonical gates and prove the versioned contract cannot silently drift.

- [ ] `W05.P20.S147` - Run the pre-removal dashboard-owned a2a-composite-certification workflow; `../../vaultspec-dashboard-worktrees/main/.github/workflows/a2a-composite-certification.yml, ../../vaultspec-dashboard-worktrees/main/.vault/plan`.
- [ ] `W05.P20.S106` - Remove the legacy product routes after the pre-removal dashboard composite proves no dependency; `src/vaultspec_a2a/api/routes, ../../vaultspec-dashboard-worktrees/main/frontend, ../../vaultspec-dashboard-worktrees/main/engine`.
- [ ] `W05.P20.S163` - Remove the legacy event WebSocket after the pre-removal dashboard composite proves no dependency; `src/vaultspec_a2a/api/app.py, ../../vaultspec-dashboard-worktrees/main/frontend, ../../vaultspec-dashboard-worktrees/main/engine`.
- [ ] `W05.P20.S87` - Run the canonical A2A code-quality gate with just dev code check; `Justfile, just/dev/code.just, src, tests`.
- [ ] `W05.P20.S88` - Run the dashboard full touched-language lint gate with just dev lint all; `../../vaultspec-dashboard-worktrees/main/just, ../../vaultspec-dashboard-worktrees/main/frontend, ../../vaultspec-dashboard-worktrees/main/engine`.
- [ ] `W05.P20.S89` - Fail certification on positive-schema fingerprint authentication or capability drift between the two repositories; `schemas, tests/acceptance, ../../vaultspec-dashboard-worktrees/main/engine, ../../vaultspec-dashboard-worktrees/main/frontend`.
- [ ] `W05.P20.S141` - Run the canonical A2A dependency gate with just dev deps check; `Justfile, just/dev/deps.just, pyproject.toml, uv.lock`.
- [ ] `W05.P20.S142` - Run the canonical A2A unit gate with just dev test unit; `Justfile, just/dev/test.just, src, tests`.
- [ ] `W05.P20.S143` - Run the canonical A2A service gate with just dev test service; `Justfile, just/dev/test.just, src/vaultspec_a2a/service_tests`.
- [ ] `W05.P20.S144` - Run the A2A real-process acceptance suites with uv run --no-sync pytest tests/acceptance src/vaultspec_a2a/desktop_tests src/vaultspec_a2a/service_tests -ra; `tests/acceptance, src/vaultspec_a2a/desktop_tests, src/vaultspec_a2a/service_tests`.
- [ ] `W05.P20.S145` - Run the dashboard frontend gate with just dev test frontend; `../../vaultspec-dashboard-worktrees/main/frontend, ../../vaultspec-dashboard-worktrees/main/just`.
- [ ] `W05.P20.S146` - Run the dashboard Rust gate with just dev test rust; `../../vaultspec-dashboard-worktrees/main/engine, ../../vaultspec-dashboard-worktrees/main/just`.
- [ ] `W05.P20.S148` - Rerun the dashboard-owned a2a-composite-certification workflow after legacy-surface removal; `../../vaultspec-dashboard-worktrees/main/.github/workflows/a2a-composite-certification.yml, ../../vaultspec-dashboard-worktrees/main/.vault/plan`.

### Phase `W05.P21` - review and close the rolling audit cycle

Perform the final cross-repository review, classify every residual, and close only findings supported by implementation and release evidence.

- [ ] `W05.P21.S90` - Run the final formal architecture security resource-bound compatibility and quality review across both repositories; `.vault/audit, .vault/exec, ../../vaultspec-dashboard-worktrees/main/.vault/audit`.
- [ ] `W05.P21.S91` - Classify every final review finding and append unresolved items to the correct repository audit queue; `.vault/audit/2026-07-19-codebase-health-audit.md, ../../vaultspec-dashboard-worktrees/main/.vault/audit`.
- [ ] `W05.P21.S92` - Reconcile the audit research ADR plan execution records and feature index against the final evidence; `.vault/audit, .vault/research, .vault/adr, .vault/plan, .vault/exec, .vault/index`.

## Parallelization

Waves are hard-ordered from W01 through W05. `W01.P01` must close before
`W01.P02` and `W01.P03`; those two phases may then run in parallel, and
`W01.P04` runs after both.

`W02.P05` and `W02.P06` may run in parallel only after desktop-product-profile
`W03.P07.S32`, `W03.P08.S36` through `W03.P08.S46`, `W03.P09.S47` through
`W03.P09.S51`, and `W04.P12.S63` through `W04.P12.S70` close. The dashboard
lifecycle sequence `W02.P07.S100`, `W02.P07.S158`, and `W02.P07.S164` through
`W02.P07.S166` must close in order before `W02.P07.S30`, `W02.P07.S31`,
`W02.P07.S32`, `W02.P07.S111` through `W02.P07.S113`, `W02.P07.S162`, or
`W02.P07.S167` through `W02.P07.S169` changes dashboard state. `W02.P08` runs
after `W02.P05`, `W02.P06`, and `W02.P07`.

`W03.P09` and `W03.P10` may run in parallel only after
desktop-product-profile `W04.P11.S60` through `W04.P11.S62` close. `W03.P11`
runs after both. `W04.P12` and `W04.P13` may run in parallel after
repository-tooling `W03.P05.S09` closes. In `W04.P14`, each ownership-proof
step precedes its matching removal. Run `S57`, `S174`, and `S63` sequentially
in that order. Start `S63` only after `S174`'s concurrency tests pass. `S176`
precedes `S175`. The `W04.P15` hotspot steps may run in parallel only when
their modules have no unreviewed W02 or W03 changes.
`W04.P16` waits for repository-tooling `W04.P07.S11` and all concurrent vault
writers; `W04.P17` runs last.

`W05.P18.S77` precedes the remaining `W05.P18` scenarios, which may then run in
parallel. `W05.P19` starts after every `W05.P18` scenario passes.
`W05.P20.S147` proves dashboard non-dependency before `W05.P20.S106` and
`W05.P20.S163` remove legacy surfaces. `W05.P20.S148` reruns certification
after both removals.
`W05.P20` completes before `W05.P21` begins.

## Verification

- `uv run --no-sync vaultspec-core vault plan check
  .vault/plan/2026-07-19-codebase-health-plan.md` returns zero with all 176
  canonical steps present. Its sole PLAN022 warning must continue to describe
  the reviewed CLI append-only insertions. `uv run --no-sync vaultspec-core
  vault check all -f codebase-health --no-hints` passes.
- `just dev hooks run markdownlint --files
  .vault/plan/2026-07-19-codebase-health-plan.md` invokes the repository-pinned
  `markdownlint-cli@0.44.0` hook and reports zero issues.
- Each wave has a formal review, severity and type classification, audit-queue
  update, and step records under `.vault/exec/2026-07-19-codebase-health/`
  before the next wave starts.
- `foreign-worker-adoption-after-failed-eviction`,
  `hard-delete-cross-store-nonatomic`, `restart-registers-before-readiness`,
  `serve-up-commit-failure-leaks-child`,
  `worker-startup-timeout-orphans-process-tree`,
  `resident-discovery-is-not-a-singleton`,
  `stale-acceptance-gate-disables-dashboard-profiles`,
  `duplicate-harness-server-invalid-codex-toml`,
  `codex-stderr-backpressure-deadlock`,
  `acp-background-rpc-errors-only-log-and-hang`,
  `test-policy-regression-after-closeout`,
  `unauthenticated-public-control-plane`, and
  `sse-content-exclusion-regression` are closed by real-process or real-store
  evidence, not by mocks, skips, expected failures, shadow logic, or
  suppressions.
- Runtime startup publishes only readiness-proven identity pairs and leaves no
  owned descendant after any tested failure boundary.
- Interrupted deletion resumes one durable saga, hides deleting threads from
  product reads, and removes control rows only after all required cleanup
  succeeds.
- Run replay rejects any behavior-affecting fingerprint mismatch with HTTP 409,
  and each run-status response derives from one checkpoint snapshot.
- Authenticated progress accepts only the versioned positive DTO, preserves
  the bounded token-delta field, excludes forbidden bodies and diffs, and
  enforces global and per-principal resource bounds.
- Codex and ACP real-subprocess tests prove duplicate MCP rejection, continuous
  standard-error draining, bounded protocol failure, deadlines, and independent
  cleanup.
- Dead exports and the Git manager are removed only after A2A and dashboard
  ownership searches prove no compatibility owner; deliberate facades and
  wire-domain separation remain documented.
- `uv run --no-sync radon cc src/vaultspec_a2a -s -n C` reports no retained
  audited hotspot above 20, and direct-production-import tests cover every
  decomposition.
- `just dev code check`, `just dev deps check`, `just dev test unit`, and
  `just dev test service` pass in the A2A repository. `uv run --no-sync pytest
  tests/acceptance src/vaultspec_a2a/desktop_tests
  src/vaultspec_a2a/service_tests -ra` passes.
- `just dev lint all`, `just dev test frontend`, and `just dev test rust` pass
  from `../../vaultspec-dashboard-worktrees/main`.
- The dashboard `a2a-composite-certification` workflow passes before and after
  legacy removal and is a required release check. Its evidence covers the
  authenticated engine, gateway, worker, provider, streaming, reconnection,
  deletion-recovery, and proposal-review path.
- The final audit, ADR, research, plan, execution records, and feature index
  agree on what closed, what remains queued, and which repository owns it.

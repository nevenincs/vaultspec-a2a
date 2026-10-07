---
tags:
  - '#audit'
  - '#codebase-remediation'
date: '2026-10-06'
modified: '2026-10-07'
body_schema: 'body-v2'
body_hash: 'sha256:511da00ea9bde80b0c5ddae1fe18b4bfaad7c3cfe086a275b7ed8bccdae0b811'
related:
  - "[[2026-10-06-codebase-remediation-plan]]"
---
# `codebase-remediation` audit: `remediation finding ledger`

## Scope

This audit is the finding ledger of the codebase remediation pathway (architect draft r2, 2026-10-06). It holds 206 items: 191 findings from the seven stage-3 research clusters R1-R7 (16 high, 85 medium, 90 low) and 15 architect additions X1-X15. It also holds the 22 open probes P2-P23. The research reports and the pathway draft live in gitignored scratch, so this record is the findings' one durable home; the sequencing plan is `2026-10-06-codebase-remediation-plan` (draft, not approved).

The research was read-only. Claims are verified against HEAD 8a6fbe62: the architect re-read every high-severity and every named correctness claim before ranking. Entries marked architect-verified rest on that re-read; entries marked investigator-only stay hypotheses until their probe or Step test runs. Discovery ran without semantic search because the `vaultspec-rag` service was down, so behavioural duplicates may be missed; guards Q.1/S108 and Q.2/S109 catch residue mechanically. Paths are relative to `src/vaultspec_a2a/` unless they start with a repository-root entry (`dev/`, `scripts/`, `packaging/`, `.github/`, `service/`, `docs/`, `schemas/`, `.vault/`) or name a root file.

## Findings

Each entry is `### <id-slug> | <level> | <summary>` followed by one paragraph: the ledger id, status, type, the r2 disposition and the decisive evidence locators. A catalogue Step id carries its plan Step id after a slash (DL.1/S17 is plan row S17). Status is one of `open`, `fixed@<sha>`, `owned <plan-stem> <Step>`, `duplicate <id>` or `decision D<n>`; a parenthesis after `open` names parts that another plan owns.

Seeded totals: 171 open, 4 fixed, 10 owned by Steps of other plans, 13 duplicates and 8 decision-only. Already fixed: R4-F1 at 8a6fbe62 (partial; the residue is owned by FX.1/S06), R7-F30 at e19c501d, X13 at 3fa8df3d, and X14 (the C1 concurrent-edit episode) resolved by those three commits.

A closing Step replaces the status token with `fixed <Step>@<sha>`, `owned <plan> <Step>`, `declined D<n>`, `duplicate <id>` or `refuted P<n>`, then appends an `Update` sentence with its verification command and result. It leaves the seeded disposition and evidence unchanged. New findings are appended under the matching group with severity, type and status.

## R1 - edge contract and legacy surface

### r1-f1-ws-schemas | medium | Orphaned WebSocket JSON schemas outlive their removed contract

R1-F1. Status: open. Type: dead-code. Disposition: Step DL.1/S17. Evidence: `schemas/ws-client-messages.json`, `schemas/ws-server-events.json`; the generator was deleted in be406160 and the source models in a8fccf98; `rg "ws-client-messages|ws-server-events"` finds 0 hits here and in the dashboard; stale against `api/schemas/events.py:237-251`; only prose reference `desktop/contract.py:246-247`.

### r1-f2-dual-wire-mapping | high | Two domain-to-wire event mappings produce different wire shapes

R1-F2. Status: open. Type: duplication. Disposition: P9, then Step DL.3/S19 deletes the dead progress path (wire-neutral); the heartbeat model goes to Step E.2/S53 per D15; RTH W07.P13.S32 is re-scoped. Evidence: production path `worker/executor.py:283-288`, `ipc/serializers.py:29-70`, `worker/ipc.py:313-318,398`, `api/internal.py:253`; dead path `api/event_adapter.py:102-336` onto `api/schemas/events.py:101-321`, reached only at `api/thread_stream.py:177-183` and `api/_replay_writer_seat.py:43-57`; float timestamp `graph/events.py:43` against ISO `api/event_adapter.py:67-69`.

### r1-f3-permission-bounds | medium | Permission frame fields carry three unlinked bounds

R1-F3. Status: open. Type: contract-drift. Disposition: Step E.1/S52; `MAX_TOOL_CALL_CHARS` is deleted in DL.3/S19. Evidence: `thread/constants.py:26-40` (4096) against the served `streaming/sse_frames.py:366-369` (512 and 128) and `api/schemas/events.py:59` (256).

### r1-f4-restated-bounds | medium | Text bounds and identifier grammars are restated as literals across layers

R1-F4. Status: open. Type: duplication. Disposition: Step E.1/S52; the `_legacy_lease_id` branch waits for P21. Evidence: message `thread/clarification.py:142` against `api/schemas/gateway.py:717` and `ipc/schemas.py:154,173`; role id `thread/actor_tokens.py:42-43`, `worker/authoring_relay.py:37`, `api/schemas/gateway.py:194`, `streaming/sse_frames.py:324`; run id `api/schemas/gateway.py:97`, `database/thread_repository.py:175`, `api/routes/gateway.py:589-601`.

### r1-f5-run-start-refusals | medium | Run-start passes unmapped dispatch failures through as 201 and publishes no 409 or 502

R1-F5. Status: open. Type: correctness-risk. Disposition: P4, then Step FX.6/S12 (contract event CE1, D21). Evidence: `api/routes/gateway.py:722-741` handles five members; `api/routes/_gateway_action_endpoints.py:240-270`; worker conditions adopted at `control/dispatch.py:732-747`; 201 at `api/routes/_gateway_run_start.py:504-511`; no `responses` at `:118-124`. Architect-verified against the cited code.

### r1-f6-internal-ws | medium | Internal worker WebSocket and single-event POST have no production client

R1-F6. Status: open. Type: dead-code. Disposition: P9, then Step DL.2/S18 (primary for R2-F8 and R7-F22). Evidence: the worker sends only `worker/ipc.py:398,612`; `app.state.worker_ws` is written at `api/internal.py:342,390` and never read; `internal_max_frame_bytes` `control/infra_config.py:864-867`; single POST `api/internal.py:404-444` has test callers only; `websockets` pin `pyproject.toml:51,422-423`.

### r1-f7-event-envelope | medium | Worker-to-gateway event envelope and batch have no declared model

R1-F7. Status: open. Type: contract-drift. Disposition: Step E.3/S54. Evidence: hand-built envelopes `worker/ipc.py:104-112,313-318`; raw `.get` reads `api/internal.py:426-429,473-503`; docstrings name nonexistent types at `api/internal.py:5-9,409-410`.

### r1-f8-openapi-drift | medium | Published openapi.json misdescribes the stream, run-start, internal routes and health

R1-F8. Status: open (part (a) owned by 2026-08-05-served-capability-contract-plan W04.P09.S27; the client guide owned by 2026-08-05-served-capability-contract-plan W03.P06.S47). Type: contract-drift. Disposition: (a) stream response and schema owned SCC W04.P09.S27 (consumes D15); guide owned SCC W03.P06.S47; (c) `/internal` unpublished in Step DL.2/S18; (d) `/health` typing, the `route_signature` filter and the subsumed tests in Step E.4/S57, which is also the D8 fallback for (a). Evidence: stream `api/routes/_gateway_read_endpoints.py:445-492`, `openapi.json:389-392`; internal routes published at `api/internal.py:157-170` and `openapi.json:1111-1298`; untyped `/health` `api/app.py:934-938`; `route_signature` `api/routes/_gateway_action_endpoints.py:711-728`.

### r1-f9-auth-bypass | medium | Test-only authentication bypass ships in production create_app

R1-F9. Status: open. Type: dead-code. Disposition: Step DL.4/S20. Evidence: `api/app.py:887-922,294-297`, `api/auth.py:67-68,108-111`, `api/dependencies.py:59-60`; set True only at `api/tests/conftest.py:348`; production callers `cli/main.py:299`, `api/app.py:868` never pass it.

### r1-f10-bounds-gate-skips | medium | The cross-repo bounds gate skips everywhere except one workstation

R1-F10. Status: open. Type: missing-test. Disposition: D15 (verification ownership), then path-param bounds in Step FX.6/S12 and the structural OpenAPI assertion in Step Q.5/S112; P20 confirms the CI skip. Evidence: `api/tests/test_engine_edge_bounds_agreement.py:56-61,73-77`; Linux CI runners `.github/workflows/test.yml:32,70,199,252`; unbounded `request_id` at `api/routes/_gateway_action_endpoints.py:425,502`.

### r1-f11-snapshot-mirrors | medium | Snapshot models are mirrored and held together by a parity test

R1-F11. Status: duplicate R2-F14. Type: duplication. Disposition: Duplicate of R2-F14 (Step M.6/S63). Evidence: `api/schemas/tests/test_snapshot_parity.py:1-18,41-56`; lossy seam `api/routes/_gateway_read_endpoints.py:573-581`.

### r1-f12-ui-configs | low | UI-era configuration remains after the headless purge

R1-F12. Status: open. Type: dead-code. Disposition: Step DL.1/S17. Evidence: `.stylelintrc.json`, `.prettierrc`, `lychee.toml`; `.gitignore:66`; `.gitattributes:6-7,10,24,34`; `.env.example:34,46`; `rg -i "stylelint|prettier|lychee" Justfile prek.toml .github dev` finds 0 hits.

### r1-f13-dead-entrypoints | low | Duplicate and dead process entrypoints

R1-F13. Status: open. Type: dead-code. Disposition: Step DL.1/S17. Evidence: forwarder `scripts/engine_serve.py:13-16` (sole caller `procs.toml:37`); zero-caller guard `api/app.py:996-997`; `worker/app.py:603-604` duplicates `worker/__main__.py:1-6`.

### r1-f14-stale-docs | low | Stale WebSocket and legacy-surface docstrings misdescribe the architecture

R1-F14. Status: open. Type: naming. Disposition: Step DL.11/S22. Evidence: `api/event_adapter.py:1-7`, `graph/events.py:3-5`, `streaming/types.py:33-36`, `streaming/fanout.py:4-6`, `control/event_handlers.py:1123`, `api/app.py:1-11`, `api/thread_stream.py:117,125`, `api/tests/test_wire_event_keys.py:28-30`.

### r1-f15-trace-injection | low | Telemetry helpers carry WebSocket names and trace injection is wrapped three times

R1-F15. Status: open. Type: duplication. Disposition: Step DL.10/S21 (primary for trace injection; R7-F20 holds the debris). Evidence: `telemetry/middleware.py:171-250`; `api/_utils.py:14-23`; `worker/ipc.py:296-301`.

### r1-f16-frame-kinds | low | Frame kinds are literals and every transport frame states its kind three times

R1-F16. Status: open. Type: duplication. Disposition: Step E.2/S53; the dual `type`/`event_type` keys are kept (D15). Evidence: `thread_terminal` at `api/thread_stream.py:278-279,286,464,579`, `thread/snapshots.py:191`, `streaming/fanout.py:40`, `streaming/sse_frames.py:347`; hand-built triples `api/thread_stream.py:186-286`; identity map `thread/snapshots.py:111-113`.

### r1-f17-content-length | low | In-route Content-Length checks duplicate the body-limit middleware

R1-F17. Status: open. Type: duplication. Disposition: Step DL.2/S18 (primary for R7-F21). Evidence: `api/internal.py:412-424,456-471` against `ipc/body_limit.py:27-35,46-51`; stale literal "max 1 MB" at `api/internal.py:419`.

### r1-f18-test-reimplementation | low | Tests reimplement route_signature and parse SSE nine ways

R1-F18. Status: open (SSE parser half duplicate R6-F10). Type: duplication. Disposition: SSE parsers duplicate R6-F10; the `route_signature` reimplementation and the misnamed acceptance file go to Step K.4/S49. Evidence: `api/tests/test_v1_attach_whitelist.py:94-99` against `api/routes/_gateway_action_endpoints.py:711-728`; misnamed `api/tests/test_acceptance_five_verb.py:1-13`.

## R2 - read model and stream topology

### r2-f1-sequence-authority | high | last_sequence comes from the emitter counter, not the allocator that numbers SSE ids

R2-F1. Status: open. Type: correctness-risk. Disposition: P3, then D4 (fast-track AD.1/S04), then Step FX.3/S08. Evidence: settle capture `control/event_handlers.py:809-812`; live fallback `control/thread_state_service.py:427-431`; counter skips and holds `streaming/emitters.py:785-786,856-871`; allocator `streaming/subscribers.py:180-192,532-562`; reseed `streaming/subscribers.py:163-167`. Architect-verified against the cited code.

### r2-f2-parked-interrupts | high | The parked-interrupt set is derived in six places with divergent rules

R2-F2. Status: open. Type: duplication. Disposition: Step M.2/S59 (coordinate TPM P06.S19). Evidence: `thread/snapshots.py:685-779`; `thread/clarification.py:567-595`; `control/projection.py:235-360`; `worker/state_projection.py:109-131,235-346`; `streaming/_interrupt_projection.py:95-156`; `thread/checkpoint_evidence.py:196-210`; divergent fallbacks `thread/snapshots.py:703-707` against `streaming/_interrupt_projection.py:144-156`.

### r2-f3-clarification-shapes | medium | The pending clarification is projected into two different wire shapes

R2-F3. Status: open. Type: duplication. Disposition: Step M.3/S60 (primary for R4-F6; CE2). Evidence: run-status `thread/clarification.py:244-333`, `api/schemas/gateway.py:580`; history `thread/snapshots.py:213-280,389-415`, `api/schemas/snapshots.py:77-96,150`.

### r2-f4-terminal-disclosure | medium | Terminal runs still disclose a parked clarification and pause cause

R2-F4. Status: open. Type: correctness-risk. Disposition: P2, then Step FX.2/S07. Evidence: durable clear `control/projection.py:561-568` precedes the merge at `:355-360`; `pause_cause` at `:377-378`; ungated route read `api/routes/_gateway_read_endpoints.py:428-430`; respond refusal `control/clarification_service.py:665`. Verified statically; reachability needs P2.

### r2-f5-discarded-permission-content | medium | Checkpoint-derived permission content is always discarded while its text drifts in three copies

R2-F5. Status: open. Type: dead-code. Disposition: Step M.2/S59. Evidence: `control/thread_state_service.py:445-460`; `control/projection.py:235-338,345-351,395-401`; live producer `streaming/_interrupt_projection.py:189-259,313-326`.

### r2-f6-aggregator-split | high | One EventAggregator serves disjoint halves in two processes and re-implements the emitters

R2-F6. Status: open. Type: duplication. Disposition: Step R.1/S55. Evidence: `streaming/aggregator.py:101-503`; worker instance `worker/_executor_state.py:64`, gateway instance `api/app.py:803`; `streaming/emitters.py:529-548` against `:896-919`; write-only mirror `control/event_handlers.py:1162-1163`.

### r2-f7-in-process-path | medium | The in-process DomainEvent-to-wire path is unreachable in the gateway

R2-F7. Status: duplicate R1-F2. Type: dead-code. Disposition: Duplicate of R1-F2 (Step DL.3/S19). Evidence: `api/event_adapter.py:67-336`; `api/thread_stream.py:177-183`; `streaming/fanout.py:64`.

### r2-f8-ingress-routes | medium | Two gateway worker-ingress routes have no producer

R2-F8. Status: duplicate R1-F6. Type: dead-code. Disposition: Duplicate of R1-F6 (Step DL.2/S18); CBH W05.P20.S163 closes as satisfied by a8fccf98. Evidence: `api/internal.py:321-390,404-444`; `worker/ipc.py:397-401,611-613`.

### r2-f9-aggregator-forwarders | low | EventAggregator facade forwarders have no production caller

R2-F9. Status: open. Type: dead-code. Disposition: Step R.1/S55. Evidence: `streaming/aggregator.py:102-107,137-179,260,350,356,419-440`; `streaming/emitters.py:100-128,350-354`; `streaming/subscribers.py:419-423,482-486,513-519`.

### r2-f10-checkpoint-reads | medium | The timed latest-checkpoint read is implemented nine times with divergent bounds

R2-F10. Status: open. Type: duplication. Disposition: Step M.1/S58 (primary for R4-F14); ERR W02.P03.S11 is amended to consume it. Evidence: `control/thread_state_service.py:142-172,295-300`; `thread/checkpoint_evidence.py:234-258`; `control/verdict_subscriber.py:409-420,569`; `worker/graph_lifecycle.py:578-609`; `worker/state_projection.py:648-675`; `control/thread_listing.py:163-176`; `control/health.py:763`; `database/checkpoint_retention.py:130`.

### r2-f11-degraded-reasons | medium | Degraded-reason marking has no single owner and one cause is reported twice

R2-F11. Status: open. Type: duplication. Disposition: Step M.4/S61. Evidence: `control/projection.py:73-74,91-92,118-119,184-186,408-409,521-522`; `control/snapshot.py:98,258-268`; `control/thread_state_service.py:337,350,452-457`; bypassed enum `thread/enums.py:135-160`.

### r2-f12-listing-rules | medium | Run listing derives repair, readiness and approval with rules that diverge from run-status

R2-F12. Status: open. Type: duplication. Disposition: Step M.4/S61. Evidence: `control/thread_listing.py:199-249` against `control/projection.py:190-225,570-614`; `control/team_service.py:33-35,139`.

### r2-f13-dead-maps | low | Dead CHECKPOINT_ERROR_REPAIR_MAP entries and an identity TERMINAL_STATUS_MAP

R2-F13. Status: open. Type: dead-code. Disposition: Step DL.5/S23. Evidence: `thread/snapshots.py:111-113,126-131,995`; pinned dead values `thread/tests/test_snapshots.py:259-272`; alias `control/event_handlers.py:75,619`.

### r2-f14-snapshot-triples | medium | The run snapshot and the execution task are each declared three times

R2-F14. Status: open. Type: duplication. Disposition: D6, then P18, then Step M.6/S63 (primary for R1-F11). Evidence: `thread/snapshots.py:460-520`; `api/schemas/snapshots.py:138-224`; `api/schemas/gateway.py:478-580`; projections `api/routes/_gateway_read_endpoints.py:364-431,573-581`; parity guard `api/schemas/tests/test_snapshot_parity.py:1-18`.

### r2-f15-authoring-capability | low | Run-status re-implements authoring_capability and reloads preset TOML

R2-F15. Status: owned 2026-08-05-served-capability-contract-plan W01.P02.S04. Type: duplication. Disposition: Owned SCC W01.P02.S04 if SCC is approved at gate G-W04; otherwise Step M.5/S62 under the D8 rule. Evidence: `control/thread_state_service.py:188-222` against `team/team_config.py:182-219`.

### r2-f16-custom-mode | low | The custom stream mode has a consumer but no producer

R2-F16. Status: open. Type: dead-code. Disposition: D17, then Step R.2/S56. Evidence: `streaming/custom_writes.py:54-70`; `streaming/transformer.py:52,351-394`; only caller `streaming/tests/_error_injecting_graph.py:32,98`.

### r2-f17-unserved-fields | low | Execution-state fields are computed, persisted and never served

R2-F17. Status: open. Type: dead-code. Disposition: Code in Step DL.5/S23; columns in Step S.5/S74. Evidence: `worker/state_projection.py:391-397,726-744`; `database/thread_repository.py:947,959`; `control/projection.py:440-446,479-504`; `control/event_handlers.py:1082-1100`.

### r2-f18-trace-ids | low | run_events trace_id and span_id are never written despite stream-resumption S5

R2-F18. Status: open. Type: contract-drift. Disposition: D4 (populate the trace ids), then Step R.2/S56. Evidence: `streaming/run_event_writer.py:132-140`; `database/run_event_repository.py:58-59`; allocation point `streaming/subscribers.py:324-333`.

### r2-f19-trim-to-window | low | RunEventStore.trim_to_window is test-only

R2-F19. Status: open. Type: dead-code. Disposition: Step DL.6/S24. Evidence: `database/run_event_repository.py:176-178,257-266`; only caller `database/tests/test_run_event_repository.py:193-196`.

### r2-f20-resumability | low | Two stream-resumability predicates can disagree

R2-F20. Status: open. Type: duplication. Disposition: Step R.2/S56. Evidence: `api/routes/_gateway_read_endpoints.py:295-329` against `api/_stream_replay.py:91-105`.

### r2-f21-eviction-routing | low | Eviction and execution-state routing are implemented twice and log_extra is vestigial

R2-F21. Status: open. Type: duplication. Disposition: The inner call and `log_extra` in Step DL.5/S23; the eviction helper in Step R.2/S56. Evidence: `worker/ipc.py:349-364` against `streaming/fanout.py:67-105`; `api/internal.py:225-229` and `control/event_handlers.py:1151-1155`; `streaming/fanout.py:133,141-144`.

### r2-f22-stale-topology-docs | low | Docstrings and records describe topology that no longer exists

R2-F22. Status: open. Type: naming. Disposition: Docstrings in Step DL.11/S22; worker-ADR sections 2.2 and 2.7 by D17 (AD.16/S43). Evidence: `api/app.py:779`; `api/dependencies.py:84`; `streaming/subscribers.py:3,376`; `control/snapshot.py:1`; `control/thread_state_service.py:64-67`; `api/_stream_replay.py:33`; `worker/app.py:258`.

### r2-f23-metadata-reparse | low | Run-status re-parses thread metadata five times per request

R2-F23. Status: open. Type: duplication. Disposition: Step M.5/S62. Evidence: `control/thread_state_service.py:449,495`; `api/routes/_gateway_read_endpoints.py:348,355-423`.

### r2-f24-token-totals | low | Token totals have a writer but no reader

R2-F24. Status: duplicate R3-F14. Type: dead-code. Disposition: Duplicate of R3-F14 (Step S.7/S73). Evidence: `worker/cost_port.py:43-57`; `database/artifact_repository.py:148,166`; allowlist `tests/test_structural_duplication.py:96-100`.

## R3 - durable state ownership

### r3-f1-write-authority | high | Write-authority ownership is restated at 14 or more SQL and Python sites

R3-F1. Status: open. Type: duplication. Disposition: Step A.1/S64. Evidence: SQL `database/thread_repository.py:628-641,690-706`, `database/graph_receipt_repository.py:54-63`, `control/recovery.py:104-114,193-203,268`, `control/direct_control_recovery.py:131-133`; Python `control/action_lease.py:571-576`, `control/dispatch_receipts.py:88-94,146-149`, `control/cancel_service.py:471-475,508-512`, `control/event_handlers.py:180-184,881-885`; successor rule `database/thread_repository.py:142-165,533-551`. The site counts are investigator-only.

### r3-f2-action-verb-map | medium | The action-type-to-verb map is defined four times and the recoverable set twice

R3-F2. Status: open. Type: duplication. Disposition: Step A.4/S67 (primary for the R4-F32 map half). Evidence: `control/dispatch_receipts.py:35-40`; `control/_event_application.py:120-126`; `control/direct_control_recovery.py:77-84,256-263`; `ipc/schemas.py:215-235`; `thread/action_receipts.py:38-43`; `thread/enums.py:206-212`.

### r3-f3-task-queue | medium | The persistent task queue has no production producer

R3-F3. Status: open. Type: dead-code. Disposition: D10, then Step S.4/S71 (code) and Step S.5/S74 (table). Evidence: `rg "seed_task_queue"` finds only `database/task_queue_repository.py:73` and `database/__init__.py:146`; module note `database/task_queue_repository.py:11-13`; fixture-only emission `graph/nodes/_worker_tool_calls.py:56-69`. Type also contract-drift.

### r3-f4-repair-journal | medium | The startup repair journal is vestigial and its pruner is off in production

R3-F4. Status: open. Type: dead-code. Disposition: Code in Step DL.6/S24; the enum and CHECK after P21 and P15 in Step S.5/S74. Evidence: enum `thread/enums.py:202-203`; pruner `database/permission_repository.py:624-734`; `database/reconciliation.py:27-28,68-78`; production caller passes 0 at `api/app.py:634`; populated-store refusal `database/migrations/versions/0021_control_action_deadline_invariant.py:35-49`.

### r3-f5-epoch-generation | medium | recovery_epoch and repair_generation never advance and worker_generation has three meanings

R3-F5. Status: open. Type: dead-code. Disposition: P15, then Step S.5/S74 (flags, comparisons, columns); the staleness duplicate folds into Step M.4/S61. Evidence: `rg "increment_recovery_epoch=|increment_generation="` finds only `api/tests/test_projection.py:596`; columns `database/models.py:449-450,774`; flags `database/thread_repository.py:808-846,961,973`; always-equal comparisons `control/projection.py:612`, `control/thread_listing.py:219`. Type also semantic-ambiguity.

### r3-f6-unfenced-writers | medium | Three thread-status writes bypass the fenced election

R3-F6. Status: owned 2026-09-05-embedded-runtime-remediation-plan W02.P03.S82. Type: correctness-risk. Disposition: Owned ERR W02.P03.S82; ERR is unapproved, so the D8 rule applies at gate G-W04. A.1/S64 lands first so S82 deletes onto the single election helper. Evidence: `database/thread_repository.py:744-800`; callers `control/_event_application.py:258`, `control/repair_transitions.py:52`, `control/verdict_subscriber.py:165`; audit `.vault/audit/2026-09-24-architecture-review-audit.md:286-288`.

### r3-f7-terminal-settlement | medium | The terminal settlement sequence is copied three times

R3-F7. Status: open. Type: duplication. Disposition: Step A.2/S65 (primary for R4-F16). Evidence: `control/event_handlers.py:140-238,241-335`; `control/recovery_authority.py:298-352`; dead fields `thread/terminal_effects.py:23-25,44-48`.

### r3-f8-repair-policy | medium | Repair-state policy has four homes and execution_readiness mirrors repair_status

R3-F8. Status: open. Type: duplication. Disposition: Step A.3/S66; reopens checked CBH W04.P12.S49, recorded in the codebase-health audit. Evidence: `thread/repair_policy.py:26-75`; `thread/terminal_effects.py:42-49`; `thread/permission_fsm.py:66-120`; `control/repair_transitions.py:96-194`; `control/direct_control_recovery.py:368-374,414-420`; `control/recovery_authority.py:173-179`.

### r3-f9-repository-layering | medium | SQL for the same tables is split between database and 12 or more control modules

R3-F9. Status: open. Type: duplication. Disposition: D5, then Step S.1/S68. Evidence: ORM references `control/recovery.py` 76 and `control/repositories/continuation_queue.py` 22; upward import `database/reconciliation.py:8-13`; `database/permission_repository.py:1,34-59`; `database/artifact_repository.py:1`; facade bypass `api/routes/_gateway_read_endpoints.py:48`, `api/app.py:62-63`.

### r3-f10-lease-mechanics | low | Lease mechanics are implemented three ways with three timeouts

R3-F10. Status: open. Type: duplication. Disposition: Step S.2/S69. Evidence: `database/permission_repository.py:475-575`; `control/recovery.py:333-337,359-363`; `control/repositories/deletion_saga.py:90,520-528`; timeouts `control/action_lease.py:46`, `control/direct_control_recovery.py:87`.

### r3-f11-recovery-recorders | low | Recovery failure and deadline recorders duplicate ownership and locking logic

R3-F11. Status: open. Type: duplication. Disposition: Step S.1/S68. Evidence: `control/recovery.py:104-171` against `:185-241`; identity tuples `:130-135` and `:206-211`.

### r3-f12-postgres | high | Postgres is the accepted production backend but nothing in the implementation requires it

R3-F12. Status: open. Type: contract-drift. Disposition: D1, then Step S.3/S70 (dependencies in Step Z.1/S107). Evidence: settings `control/infra_config.py:179-191`; binary excludes `packaging/pyinstaller/vaultspec-a2a.spec:41,76-78`; Postgres-only code `database/checkpoints.py:134-570`, `database/checkpoint_retention.py:180-283`, `control/config.py:397-527`; `rg -n -i postgres .github` is empty; ADR `.vault/adr/2026-03-10-postgres-dual-backend-adr.md`.

### r3-f13-artifacts-table | medium | The artifacts table has no writer

R3-F13. Status: open. Type: dead-code. Disposition: Code in Step DL.6/S24; model and table in Step S.5/S74. Evidence: `rg "create_artifact|get_artifact\("` finds only `database/artifact_repository.py:38,47,65` and `database/__init__.py:19,228`; empty loop `control/thread_service.py:575` into `control/cleanup/executor.py:161-170`; model `database/models.py:462-464,499-524`.

### r3-f14-accounting | medium | Token and cost accounting is written to two sinks and read by neither

R3-F14. Status: open. Type: semantic-ambiguity. Disposition: D14, then Step S.7/S73 (column drop in Step S.5/S74); primary for R2-F24. Evidence: `graph/nodes/worker.py:974-984`; `worker/cost_port.py:9-15,33-72`; `context/token_budget.py:153-164`; `database/models.py:134-205`; `database/migrations/versions/0014_cost_tracking_exact_money.py:18-21`.

### r3-f15-idempotency-keys | medium | Journal idempotency keys are built in about nine places

R3-F15. Status: open. Type: duplication. Disposition: Step C.5/S103 (primary for the R4-F30 builders). Evidence: `control/graph_definition.py:44`; `control/thread_service.py:402,426`; `control/verdict_subscriber.py:126,156`; `control/event_handlers.py:935`; `control/_event_application.py:72`; `control/permission_service.py:505`; `control/clarification_service.py:79,256-262`; `control/_permission_response_contract.py:26-36`; declared home `thread/idempotency.py:39-51`.

### r3-f16-evidence-vocabulary | low | Evidence vocabulary types, fingerprints and channel names exist more than once

R3-F16. Status: open. Type: duplication. Disposition: P16, then Step A.4/S67 (primary for R4-F38). Evidence: `thread/action_receipts.py:22-23,77-86`; `thread/failure_evidence.py:31-37`; `thread/cancellation_evidence.py:18`; `worker/executor.py:195-198,222-223`; `thread/checkpoint_evidence.py:29-32`; `control/graph_definition.py:33-34` against `control/dispatch_receipts.py:61-63`.

### r3-f17-receipt-blob | low | graph_receipt_json repeats row columns and needs three consistency validators

R3-F17. Status: decision D18. Type: duplication. Disposition: D18 declines the blob change (the leases ADR mandates the immutable receipt); the three validators fold into `GraphActionReceipt.matches()` in Step A.4/S67. Evidence: `thread/action_receipts.py:35-47`; `database/models.py:631-647`; validators `control/dispatch_receipts.py:81-87`, `database/graph_receipt_repository.py:25-36`, `control/graph_definition.py:22-35`.

### r3-f18-journal-deadlines | medium | Non-dispatchable permission rows invent recovery deadlines and decisions live in three stores

R3-F18. Status: open. Type: semantic-ambiguity. Disposition: D18, then the CHECK exemption in Step S.5/S74; `permission_logs` as the single decision record is owned by 2026-10-01-tool-permission-model-plan P06.S16 (amended). Evidence: `control/permission_service.py:136-145,500-509`; `database/migrations/versions/0021_control_action_deadline_invariant.py:45-49`; stores `database/permission_repository.py:220-235`, `control/permission_service.py:845-856`, `control/_event_application.py:67-75`.

### r3-f19-test-only-methods | low | Test-only production methods and a legacy positional-argument binder

R3-F19. Status: open. Type: dead-code. Disposition: Test-only methods in Step DL.6/S24; the binder by D7 in Step Y.1/S106. Evidence: `worker/token_store.py:57-63`; `worker/catalog_store.py:52-58`; `control/action_lease.py:62-395`; `pyproject.toml:545,555`.

### r3-f20-check-predicates | low | CHECK predicates and the receipt-id bound are spelled twice

R3-F20. Status: open. Type: duplication. Disposition: The receipt-id bound in Step A.1/S64; CHECK-from-dict in Step S.6/S72. Evidence: `database/models.py:310-325,591-601` against `database/write_authority_schema.py:24-34` and `database/control_action_schema.py:41-51`; bound 64 at `database/models.py:257,323-324,370,713,737` and `thread/action_receipts.py:22`; queue cap `domain_config.py:211-217` against `control/direct_control_recovery.py:86`.

### r3-f21-database-admin | low | database/admin.py is an orphan operator CLI with a second, unlocked migrate path

R3-F21. Status: open. Type: dead-code. Disposition: D19 (fold-and-delete), then Step DL.13/S26 (owner O11). Type also duplication. Evidence: `rg "database\.admin|database/admin"` finds only `database/admin.py:5,367`, `database/migrations/env.py:81` and tests; `database/admin.py:69-73` skips the lock held at `database/migrate.py:92-96`; `checkpoint_wal` `database/session.py:190-238` is called only from `database/admin.py:141,183`.

### r3-f22-r1-digest | low | The legacy r1 replay-digest rule and unstamped fallback are unreachable at head

R3-F22. Status: open. Type: dead-code. Disposition: P21, then Step DL.6/S24. Evidence: `api/run_admission.py:97-99,103,120-123,216-217`; `api/routes/gateway.py:505-512`; migrations 0017 and 0021 refuse populated stores.

### r3-f23-receipt-naming | low | Receipt has five meanings and persistence module names hide their contents

R3-F23. Status: open. Type: naming. Disposition: Module renames in Step S.1/S68; the test rename in Step Y.4/S98. Evidence: `service_tests/test_receipt_role_rules.py:1-7,47-60`; `database/permission_repository.py:1`; `database/artifact_repository.py:1`; `database/models.py:586`.

### r3-f24-enum-coercers | low | Six near-identical enum coercers and a hand-listed save_model

R3-F24. Status: open. Type: duplication. Disposition: Step S.6/S72. Evidence: `database/_helpers.py:44-60,81-129`.

### r3-f25-run-registry | low | The per-run in-memory registry is implemented twice

R3-F25. Status: open. Type: duplication. Disposition: Step Y.1/S106. Evidence: `worker/token_store.py:31-74` against `worker/catalog_store.py:14-16,31-69`.

## R4 - interrupt and control semantics

### r4-f1-clarification-park | high | A clarification park never elected INPUT_REQUIRED, so follow-ups queued and restart reconciled the park

R4-F1. Status: fixed@8a6fbe62 (partial; residue owned by FX.1/S06). Type: contract-drift. Disposition: Fixed@8a6fbe62 (partial): the live T1 test exists and fails on HEAD~. Remainder in Step FX.1/S06 (T2 restart, real-park replacement of the hand-seeded fixture, RCP P04.S12 audit record); generalization in Step C.2/S100 (`reconcile_run_pause`). Evidence: pre-fix elections only at `control/event_handlers.py:839-841,920-970`; admission `thread/message_policy.py:27-29,141-142`; restart path `database/reconciliation.py:55-63` into `control/recovery_authority.py:157-180,427-428`; hand-seeded fixture `api/tests/test_run_continuation_admission.py:191-264`; fix `control/clarification_service.py` `reconcile_clarification_pause`. Architect-verified against the cited code.

### r4-f2-two-pause-mechanisms | high | Two control-plane pause mechanisms sit over one graph mechanism

R4-F2. Status: open. Type: duplication. Disposition: D11, then Step C.2/S100. Evidence: permission mirror `control/event_handlers.py:888-1001`, `database/permission_repository.py:122-160`; validation `control/permission_service.py:357-690`; checkpoint-only clarification `control/clarification_service.py:427-470,490-544`; one graph mechanism `graph/nodes/_worker_permissions.py:267`, `graph/nodes/clarification.py:369`, `worker/executor.py:202-229`.

### r4-f3-resume-settlement | medium | Clarification RESUME has no steady-state settlement owner and two recovery owners

R4-F3. Status: open. Type: correctness-risk. Disposition: P5, then Step FX.12/S11 if P5 shows a second RESUME dispatch, else Step C.4/S102; ERR W02.P03.S12 is verified and closed by its owner. Evidence: `control/_event_application.py:236-265`; `control/verdict_subscriber.py:154-159`; `control/clarification_service.py:521-530,729-743,746-798`; generic redelivery `control/recovery.py:253-283`, `control/direct_control_recovery.py:721-749`; lease `control/action_lease.py:46`. Investigator-only: a hypothesis until its probe or Step test runs.

### r4-f4-permission-supersession | medium | Concurrent permission requests supersede each other and strand a parallel branch

R4-F4. Status: open. Type: correctness-risk. Disposition: Step C.2/S100 (latent: no shipped preset declares two or more `research_threads`). Evidence: `control/event_handlers.py:951-956,971-975`; `control/permission_service.py:451-483,522-540`; `worker/executor.py:124-136`; `graph/_compiler_research.py:302-307`; `team/team_config.py:462`. Investigator-only: a hypothesis until its probe or Step test runs.

### r4-f5-fabricated-options | medium | Optionless permission requests get fabricated options and stall the run

R4-F5. Status: open. Type: correctness-risk. Disposition: Step FX.10/S10 (after SCR S04). Evidence: `streaming/_interrupt_projection.py:278-284,306-308,313-326`; `streaming/emitters.py:577-588`; persisted at `control/event_handlers.py:929,976-984`; worker re-park `graph/nodes/_worker_permissions.py:110-129,193-200,274-275`. Verified statically; latent.

### r4-f6-questionnaire-mirrors | medium | The clarification questionnaire is declared three times and history uses a lenient mirror

R4-F6. Status: duplicate R2-F3. Type: duplication. Disposition: Duplicate of R2-F3 (Step M.3/S60). Evidence: `thread/clarification.py:244-341`; `thread/snapshots.py:213-283,390-417`; `api/schemas/snapshots.py:77-97`.

### r4-f7-option-kinds | medium | ACP option-kind classification is re-derived at five sites

R4-F7. Status: open. Type: duplication. Disposition: Step C.3/S101; TPM P06.S19 consumes `graph/acp_options`. Evidence: `graph/enums.py:150-205`; `providers/_acp_rpc_handlers.py:296-339,375-394`; `graph/nodes/_worker_permissions.py:58-74`; `streaming/types.py:326`; `streaming/emitters.py:581-585`.

### r4-f8-dispatch-preamble | medium | Follow-on dispatch preamble and lease tail are copied six times and clarification status drifted

R4-F8. Status: open. Type: duplication. Disposition: Status drift in Step FX.6/S12; preamble and tail fold in Step C.1/S99. Evidence: preambles `control/clarification_service.py:555-596`, `control/permission_service.py:717-777`, `control/message_service.py:223-285`, `control/verdict_subscriber.py:600-642`; drift `control/clarification_service.py:720-726` against `api/routes/_gateway_action_endpoints.py:246-268`.

### r4-f9-recursion-ceiling | medium | Follow-up turns escape the operator recursion ceiling

R4-F9. Status: open. Type: contract-drift. Disposition: Step FX.7/S09 (minimal); the freeze in the envelope in Step C.1/S99 (primary for R5-F12). Evidence: `worker/executor.py:111-121`; `control/message_service.py:283`; ceiling elsewhere `api/routes/_gateway_action_endpoints.py:471,537`, `api/routes/_gateway_run_start.py:307`. Architect-verified against the cited code.

### r4-f10-park-replay | medium | A permission park abandons and replays the provider turn while answering refused

R4-F10. Status: decision D12 (then owned by 2026-10-01-tool-permission-model-plan P03). Type: semantic-ambiguity. Disposition: D12, then a TPM P03 plan amendment adds two Steps: the implementation, then a credential-run Codex completed-turn proof of the abandon outcome. The Claude proof is gated on PBP P02.S21. If TPM declines, the fallback is C.8 and CV.5 in this plan. Evidence: `providers/acp_chat_model.py:681-705`; `graph/nodes/worker.py:825-941`; refusal on park `providers/_acp_rpc_handlers.py:572-580`, `providers/_codex_app_server_client.py:371-385`; idle-timeout path `providers/codex_chat_model.py:756-779`.

### r4-f11-rung-guards | medium | ACP and Codex rungs duplicate the pre-rung guards in different orders

R4-F11. Status: owned 2026-10-01-tool-permission-model-plan P02.S06, P03.S08, P03.S09. Type: duplication. Disposition: Owned TPM P02.S06, P03.S08 and P03.S09; TPM starts only after AD.10/S37, AD.11/S38 and AD.3/S30 are accepted and S.1/S68 has landed (gate G-W05). Evidence: `providers/_acp_rpc_handlers.py:462-509,550-587` against `providers/_codex_permission.py:214-309`.

### r4-f12-verdict-subscriber | high | The served research_adr preset strands at Gate 1 when the verdict subscriber is off

R4-F12. Status: open. Type: correctness-risk. Disposition: P8, then D9 (fast-track AD.2/S05), then Step FX.8/S14. Evidence: default off `control/infra_config.py:694-702`; started only at `api/app.py:644`; refusal `control/permission_service.py:321-354`; supervised preset `team/presets/teams/vaultspec-adr-research.toml:17,21`; parking gates `graph/nodes/phase_gate.py:291-330`. Architect-verified against the cited code.

### r4-f13-verdict-scans | medium | Verdict correlation scans checkpoints instead of the durable permission row

R4-F13. Status: open. Type: duplication. Disposition: Step C.4/S102 (after the S.1/S68 repository query). Evidence: `control/verdict_subscriber.py:377-398,479-485,543-562`; cap `control/_verdict_subscriber_config.py:72`; correlation key path `graph/nodes/phase_gate.py:302` into `control/event_handlers.py:844-870`.

### r4-f14-channel-reads | medium | Timed checkpoint read and channel extraction is re-implemented at six sites

R4-F14. Status: duplicate R2-F10. Type: duplication. Disposition: Duplicate of R2-F10 (Step M.1/S58). Evidence: `control/verdict_subscriber.py:230-244,400-434,564-582`; `control/clarification_service.py:273-289`; `database/checkpoints.py:50-57`.

### r4-f15-busy-retry | medium | SQLite busy-retry is implemented twice without a typed refusal

R4-F15. Status: owned 2026-09-05-embedded-runtime-remediation-plan W02.P04.S79. Type: duplication. Disposition: Owned ERR W02.P04.S79 (extended to the cancel copy) if ERR is approved at gate G-W04; otherwise Step C.6/S104 under the D8 rule. Evidence: `control/cancel_service.py:399-415`; `api/routes/_gateway_run_start.py:298-327`.

### r4-f16-terminal-effects | medium | terminal_effects is a vestigial second repair policy and the settlement tail is copied

R4-F16. Status: duplicate R3-F7. Type: duplication. Disposition: Duplicate of R3-F7 (Step A.2/S65). Evidence: `thread/terminal_effects.py:25,48`; `control/event_handlers.py:205-240,310-333`; `control/recovery_authority.py:333-353`.

### r4-f17-actionable-permissions | medium | Three surfaces decide differently which pending permissions are actionable

R4-F17. Status: open. Type: semantic-ambiguity. Disposition: Step M.4/S61. Evidence: `control/team_service.py:125-141`; `control/projection.py:507-585`; `control/thread_listing.py:231-250`; fixtures seed only `input_required` at `api/tests/test_endpoints.py:1658,1744,1816,1906`.

### r4-f18-question-coercer | low | The model-proposal question coercer has no production caller

R4-F18. Status: open. Type: dead-code. Disposition: Step DL.5/S23. Evidence: `graph/nodes/clarification.py:92,120-241`; tests `graph/tests/nodes/test_clarification.py:34-817`.

### r4-f19-answers-channel | low | The clarification_answers state channel is write-only

R4-F19. Status: open. Type: dead-code. Disposition: D17, then Step C.5/S103. Evidence: writer `graph/nodes/clarification.py:394-395`; reducer `thread/state.py:159-173,358-362`; receipts live in `thread/state.py:364-368`.

### r4-f20-clarification-rules | low | Clarification rules are restated beside their canonical home

R4-F20. Status: open. Type: duplication. Disposition: Step E.1/S52. Evidence: `api/schemas/gateway.py:717,894-896` against `thread/clarification.py:142,377-383`; topology check `team/team_config.py:576-598` against `graph/compiler.py:565-571`.

### r4-f21-request-id-derivation | low | Interrupt request-id derivation is implemented twice with dead fallbacks

R4-F21. Status: duplicate R2-F2. Type: duplication. Disposition: Duplicate of R2-F2 (Step M.2/S59). Evidence: `streaming/_interrupt_projection.py:144-156`; `thread/snapshots.py:703-707`; `worker/state_projection.py:109-130`.

### r4-f22-resume-codecs | low | Resume-value codecs are split across layers and graph imports control

R4-F22. Status: open. Type: duplication. Disposition: Step C.5/S103. Evidence: `control/permission_dispatch.py:16-66` imported by `graph/nodes/_worker_permissions.py:23` and `worker/executor.py:17,148`; typed models `thread/clarification.py:343-484`.

### r4-f23-foreign-answer-guard | low | The ask-again-on-foreign-answer guard is open-coded in each gate

R4-F23. Status: open. Type: duplication. Disposition: Step C.5/S103. Evidence: `graph/nodes/supervisor.py:744-753`; `graph/nodes/phase_gate.py:316-329`; `graph/nodes/clarification.py:366-380`.

### r4-f24-result-types | low | Control result types and their lint-evasion machinery are duplicated

R4-F24. Status: open. Type: duplication. Disposition: The outcome type in Step C.1/S99; the R0902 root cause by D7 in Step Y.1/S106. Evidence: `control/clarification_service.py:82-207`; `control/cancel_service.py:86-200`; `control/_verdict_subscriber_config.py:48-128`; `control/action_lease.py:62-395`; `pyproject.toml:545,555`.

### r4-f25-options-decode | low | allowed_options_json is decoded by four wrappers

R4-F25. Status: open. Type: duplication. Disposition: Step C.3/S101. Evidence: `control/permission_options.py:12-27`; `control/_permission_response_contract.py:62-65`; `control/team_service.py:33-35`; `thread/permission_fsm.py:45-51`.

### r4-f26-permission-fallbacks | low | The permission service re-resolves the route's row and keeps unreachable fallbacks

R4-F26. Status: open. Type: dead-code. Disposition: Step C.1/S99. Evidence: route preload `api/routes/_gateway_action_endpoints.py:453-462`; service `control/permission_service.py:186,283,296-300,378-411,807-819`; claim match `database/permission_repository.py:465-469`.

### r4-f27-stale-locators | low | Tool-permission ADR and plan locators and migration names are stale

R4-F27. Status: owned 2026-10-01-tool-permission-model-plan (plan edit before P01.S01). Type: contract-drift. Disposition: Owned TPM through a plan edit before P01.S01; the permission-log move transfers to Step S.1/S68. Evidence: code now at `graph/nodes/_worker_permissions.py:41-55,58-74,204-279`; taken migration ids under `database/migrations/versions/` (0023-0025); log writer `database/artifact_repository.py:91-125`.

### r4-f28-prune-test | low | No test proves a parked interrupt survives pruning

R4-F28. Status: open. Type: missing-test. Disposition: Step CV.1/S113. Evidence: `control/tests/test_settled_history_pruning.py:96-152`; `database/tests/test_checkpoint_retention.py:162-185`.

### r4-f29-unbounded-request-id | low | Respond routes accept unbounded path request_id values

R4-F29. Status: open. Type: contract-drift. Disposition: P6, then Step FX.6/S12. Evidence: `api/routes/_gateway_action_endpoints.py:425,503,512-525`; `thread/clarification.py:153-156`; only `RequestValidationError` is handled at `api/app.py:918`. The 500 outcome is investigator-only.

### r4-f30-key-builders | low | Idempotency key builders are scattered and header bounds are inconsistent

R4-F30. Status: open (builder half duplicate R3-F15). Type: duplication. Disposition: Builders duplicate R3-F15; header bounds in Step FX.6/S12. Evidence: unbounded headers `api/routes/_gateway_action_endpoints.py:145` against `:169-172`; inline prefixes `control/clarification_service.py:79`, `control/permission_service.py:505`, `control/event_handlers.py:935`.

### r4-f31-draft-thread | low | The draft-thread path is unreachable

R4-F31. Status: open. Type: dead-code. Disposition: Step DL.5/S23. Evidence: `thread/creation.py:38`; `control/thread_service.py:244,396-413`; `api/schemas/gateway.py:165`.

### r4-f32-cancel-constants | low | Cancel eligibility, the action map and the receipt exemption are restated

R4-F32. Status: open (map half duplicate R3-F2). Type: duplication. Disposition: The map and `_RECOVERABLE_TYPES` duplicate R3-F2; cancel eligibility and the receipt exemption in Step C.6/S104. Evidence: `thread/cancel_policy.py:27-35`; `thread/enums.py:294-305`; `thread/transitions.py:12-86`; exemption copies `control/dispatch.py:184-188`, `worker/app.py:315-325`, `ipc/schemas.py:222-240`.

### r4-f33-cancel-httpexception | low | The control layer raises HTTPException for cancel failures behind a tautological test

R4-F33. Status: open. Type: naming. Disposition: Step FX.6/S12. Evidence: `control/cancel_service.py:1-6,63,224-289`; caller `api/routes/_gateway_read_endpoints.py:517,534`; tautology `control/tests/test_cancel_failure_mapping.py:77-91`.

### r4-f34-teardown-helpers | low | Worker terminal teardown and task-cancel helpers are duplicated

R4-F34. Status: open. Type: duplication. Disposition: Step C.6/S104 (coordinate ERR W02.P05.S21 and S22, which own the task-group code). Evidence: `worker/executor.py:490-495,645-647`; `worker/_dispatch_settlement.py:277-279,582-584`; `providers/_cleanup.py:30-49` against `providers/_stdio_rpc.py:93-104`.

### r4-f35-native-control | low | Provider-native interrupt and command paths have no production caller

R4-F35. Status: owned 2026-09-05-embedded-runtime-remediation-plan W03.P08.S36. Type: dead-code. Disposition: Owned ERR W03.P08.S36 if ERR is approved at gate G-W04 (recommend delete); otherwise Step L.3/S79 under the D8 rule. Evidence: `providers/codex_chat_model.py:488`; `providers/acp_chat_model.py:707`; tests only `providers/tests/test_acp_native_commands.py`.

### r4-f36-verdict-gap-path | low | The verdict gap path re-implements the parked reconcile with a disagreeing status map

R4-F36. Status: open. Type: duplication. Disposition: Step C.4/S102. Evidence: `control/verdict_subscriber.py:169-216,522-537`; `authoring/lifecycle.py:63-66,214-220`.

### r4-f37-verdict-tests | low | Verdict tests monkeypatch settings, live loops skip by default and two review budgets exist

R4-F37. Status: open. Type: missing-test. Disposition: Step C.7/S105 (monkeypatch and budget) and Step CV.3/S115 (live loop in CI). Evidence: `control/tests/test_verdict_subscriber.py:82-84`; `control/tests/test_verdict_subscriber_live.py:113-115`; `control/tests/test_verdict_loop_live.py:159-161`; `graph/tests/test_review_budget.py:16,60,215,279`; budgets `graph/compiler.py:605-616`, `graph/_compiler_research.py:382-386`.

### r4-f38-evidence-primitives | low | Evidence primitives are restated across thread modules

R4-F38. Status: duplicate R3-F16. Type: duplication. Disposition: Duplicate of R3-F16 (Step A.4/S67). Evidence: `thread/action_receipts.py:22-23,77-86`; `thread/clarification.py:416-433`; `thread/executable_graph.py:78-82`; `ipc/schemas.py:162-164`.

## R5 - admission and provider eligibility

### r5-f1-credential-eligibility | high | Readiness serves credential-only eligibility that disagrees with lane admission

R5-F1. Status: open. Type: duplication. Disposition: P7, then Step FX.4/S13 under accepted `2026-10-01-provider-binary-policy-adr` D2 (D8); SCC W05.P10.S30 is re-scoped to dashboard lockstep; DNI S12 is amended to consume the predicate. Evidence: `control/health.py:473-500,648-656`; `providers/provider_readiness.py:78-136`; `providers/lane_admission.py:26-30,194-217` proves Codex only; test asserts the defect at `control/tests/test_provider_eligibility_credentials.py:90,112`. Architect-verified against the cited code.

### r5-f2-lane-assignment | high | The frozen lane-assignment key schema is restated in five modules

R5-F2. Status: open. Type: duplication. Disposition: Step L.1/S76. Evidence: `providers/team_selection.py:99-114,141-173,319-421`; `providers/_team_selection_record.py:96-100,125-138,212,223-233`; `ipc/schemas.py:105-119,257-287`; `graph/_compiler_models.py:121,128-231`.

### r5-f3-execution-ready | medium | The execution-ready verdict is composed three ways

R5-F3. Status: open. Type: duplication. Disposition: Step G.1/S75; DNI S12 consumes it. Evidence: `control/health.py:556-580,589-593`; `control/admission.py:225-229`; `control/run_start_policy.py:62-85`; redundant G3 `providers/binary_version.py:115-117,126`.

### r5-f4-double-freeze | medium | Commit runs G3, preset load and selection freeze twice

R5-F4. Status: open. Type: duplication. Disposition: P17, then Step G.1/S75. Evidence: `api/routes/_gateway_run_start.py:255,258,272-274,679-685,727-770,803`. Investigator-only: a hypothesis until its probe or Step test runs.

### r5-f5-failure-mapping | medium | FailureType maps to HTTP in three disagreeing places

R5-F5. Status: duplicate R1-F5. Type: contract-drift. Disposition: Duplicate of R1-F5 (Step FX.6/S12). Evidence: `api/routes/gateway.py:722-741`; `api/routes/_gateway_action_endpoints.py:246-266,541-545`; `control/clarification_service.py:724`.

### r5-f6-selection-modules | medium | Team selection is split into two modules with an import cycle and a second reader

R5-F6. Status: open. Type: duplication. Disposition: Step L.1/S76. Evidence: `providers/_team_selection_record.py:19-26,87-120`; `providers/team_selection.py:312-333,443-461`; second reader `api/routes/gateway.py:689-710` against `control/execution_authority.py:70-72`.

### r5-f7-factory-rules | medium | The factory restates native-control and execution-mode rules

R5-F7. Status: open. Type: duplication. Disposition: Step L.2/S77. Evidence: `providers/factory.py:97-143,639-642,673,704-711,722,772,826,864-870,884,1000-1010`; `providers/lane_admission.py:224`; `providers/codex_chat_model.py:245`.

### r5-f8-unservable-lanes | medium | OpenAI, Zhipu and Antigravity lanes are unservable yet carry production cost

R5-F8. Status: open. Type: dead-code. Disposition: The warm entry in Step DL.7/S25; retirement by D3 in Step L.3/S79. Evidence: no proof declaration `providers/lane_admission.py:194-201`; `providers/factory.py:149-160,586-605,900-928`; cold-catalog spawn `providers/antigravity_catalog.py:53,151-171`; warmup `providers/warmup.py:38-41`; production `create` callers only `graph/_compiler_models.py:93,264`.

### r5-f9-zai-catalog | medium | Z.ai cannot be re-enrolled because its catalog is hard-wired unavailable

R5-F9. Status: open. Type: contract-drift. Disposition: D3 (keep Z.ai), then P23, then Step L.5/S80; unblocks the PBP P02.S21 Z.ai half. Evidence: `providers/factory.py:586-605,1043-1047`; unpassable live proof `providers/tests/test_zai_catalog_live.py:66-75`; shared discovery `providers/factory.py:332-395`.

### r5-f10-kimi-launcher | medium | Kimi has no binary-proof binding, a bare launcher fallback and lost per-run isolation

R5-F10. Status: open. Type: correctness-risk. Disposition: Step L.6/S81; must land before KIM P05.S16-S18. Evidence: `providers/factory.py:840-897,1037-1039`; `providers/_factory_commands.py:141-144,410-416,436-442`; Windows `cmd.exe` resolution `providers/_subprocess.py:316-329`; compile gate `graph/_compiler_models.py:92`. The `cmd.exe` path is investigator-only.

### r5-f11-double-construction | medium | Every worker model is constructed twice per compile

R5-F11. Status: open. Type: duplication. Disposition: Step L.2/S77. Evidence: `worker/graph_lifecycle.py:151-219,709-711`; `graph/compiler.py:361`; `providers/factory.py:700-702,753-758`.

### r5-f12-reentry-assembly | medium | Re-entry dispatch assembly is copied four times and diverges on the recursion ceiling

R5-F12. Status: duplicate R4-F9. Type: correctness-risk. Disposition: Duplicate of R4-F9 (Steps FX.7/S09 and C.1/S99). Evidence: `control/message_service.py:225-264`; `control/clarification_service.py:572-596`; `control/permission_service.py:742-786`; `control/verdict_subscriber.py:610-645`.

### r5-f13-catalog-pipeline | low | Per-lane catalog modules duplicate the shared discovery pipeline

R5-F13. Status: open. Type: duplication. Disposition: Step L.4/S78. Evidence: `providers/acp_catalog.py:55-57,121-141,530-561`; `providers/codex_catalog.py:55-59,87-100,487-544`; `providers/kimi_catalog.py:55,303-354`; `providers/_provider_catalog_cache.py:216-221`; `providers/provider_catalog.py:594-595`.

### r5-f14-catalog-bounds | low | Catalog bounds are restated as literals outside the domain

R5-F14. Status: open. Type: duplication. Disposition: Step E.1/S52. Evidence: `api/schemas/provider_catalog.py:25-120`; `api/schemas/gateway.py:123-131,194-198,274-276`; `providers/provider_catalog_service.py:371,381`; `graph/_compiler_models.py:121,192`.

### r5-f15-readiness-branches | low | probe_provider_readiness has branches production never reaches

R5-F15. Status: open. Type: dead-code. Disposition: The in-process branch in Step DL.7/S25 (after FX.4/S13); the OpenAI and Zhipu branches by D3 in Step L.3/S79; the Z.ai branch is kept, reachable once FX.4/S13 derives candidates. Evidence: `providers/provider_readiness.py:45-59,90-94,101-110`; production probes only `control/health.py:493-499`; `providers/tests/test_desktop_native_execution.py:72-76`.

### r5-f16-graph-revalidation | low | FrozenGraphDefinition is re-validated repeatedly

R5-F16. Status: open. Type: duplication. Disposition: Step L.2/S77. Evidence: `ipc/schemas.py:246-255`; `worker/graph_lifecycle.py:474,660`; `thread/executable_graph.py:64-67,84-119,136`.

### r5-f17-module-names | low | Several module names mislead

R5-F17. Status: open. Type: naming. Disposition: Step Y.4/S98. Evidence: `control/provider_execution.py` against `providers/_provider_execution.py`; `control/team_service.py`; `worker/catalog_store.py`; empty `__all__` `api/schemas/gateway_readiness.py:10`.

### r5-f18-stale-readiness-docs | low | Readiness docstrings and plan records are stale

R5-F18. Status: open (`eligible=True` owned by 2026-08-05-served-capability-contract-plan W05.P10.S44; the Codex 0.160.0 record owned by 2026-10-01-provider-binary-policy-plan). Type: contract-drift. Disposition: Docstrings in Step FX.4/S13; `eligible=True` owned SCC W05.P10.S44; the Codex 0.160.0 text owned by the PBP plan record update. Evidence: `api/schemas/gateway_readiness.py:74-77`; `api/schemas/gateway.py:961-962`; `api/routes/_gateway_run_start.py:536`; `control/run_start_policy.py:82`; proven range `providers/lane_admission.py:212-214`.

### r5-f19-credential-vocabulary | low | Credential names are declared three times and owner-only writes twice

R5-F19. Status: open. Type: duplication. Disposition: The vocabulary in Step L.7/S82 (after SCR S08); the owner-only write in Step H.5/S93. Evidence: `control/env_registry.py:89-117`; `workspace/environment.py:86-115`; `dev/credentials.py:112-126`; `desktop/credentials.py:226` against `providers/_codex_auth.py:102-105`.

### r5-f20-two-digests | low | One frozen selection carries two digests

R5-F20. Status: open. Type: duplication. Disposition: D23 (keep both and document), then Step L.1/S76. Evidence: `providers/_team_selection_record.py:170-192`; `providers/team_selection.py:56-64`; checkpoint binding `worker/graph_lifecycle.py:479,620,967`.

### r5-f21-execution-authority | medium | In-flight owning plans lack execution authority

R5-F21. Status: decision D8. Type: semantic-ambiguity. Disposition: D8 (governance; owner O1). Evidence: proposed `.vault/adr/2026-08-05-served-capability-contract-adr.md` and `.vault/adr/2026-08-05-served-capability-contract-canonical-vocabulary-adr.md`; `rg -n "Approved 20"` finds no Approved line in the SCC, PCE, PMC and KIM plans.

## R6 - test infrastructure and fixtures

### r6-f1-test-support-homes | high | Four competing homes exist for cross-tier test support

R6-F1. Status: open. Type: duplication. Disposition: Step K.1/S46. Evidence: `tests/gateway_boot.py:15-25` (20 importers); `testing/tests/_support/` (13/11/5/4/3/1/1 importers); `graph/tests/_state_graph_helpers.py` (29 files); `control/tests/_catalog_authority.py` (23 files); `service_tests/test_pw7_acceptance.py:525,1166-1861`.

### r6-f2-boot-duplication | high | Real-process boot is duplicated about 13 times beside a parallel stack

R6-F2. Status: open. Type: duplication. Disposition: Step K.2/S47. Evidence: canonical `tests/gateway_boot.py:254-533`; parallel `service_tests/harness.py:126,159,177,228,418-472,513-520`; copies `acceptance/tests/_harness.py:315-392`, `service_tests/_live_desktop_gateway.py:31-66` and eight `desktop_tests/` files; unsafe port reuse `control/tests/test_unready_worker_reap.py:63-66`.

### r6-f3-model-standins | high | Three model stand-in mechanisms do one job

R6-F3. Status: open. Type: duplication. Disposition: D2, then Step F.1/S84 and Step F.4/S87. Evidence: `providers/mock_chat_model.py:205-325`; `service/docker/vidaimock.Dockerfile:7,71`; production special case `graph/nodes/_worker_tool_calls.py:95-170,200`; `providers/deterministic_chat_model.py:46-66,243-367`; `graph/tests/conftest.py:70-91`. The CI VidaiMock usage is investigator-only.

### r6-f4-test-lanes-ship | high | Test-only lanes ship in the product

R6-F4. Status: open. Type: contract-drift. Disposition: D2, then P11, then Step F.2/S85. Evidence: not excluded `pyproject.toml:229-268`; branches `providers/factory.py:106,120,155,932-942,1019,1111`, `providers/in_process_catalog.py:70-143`, `providers/lane_admission.py:230-256`, `graph/nodes/_worker_tool_calls.py:95-170`.

### r6-f5-committed-bundles | high | Committed acceptance run bundles cite plan steps and leak machine paths

R6-F5. Status: open. Type: contract-drift. Disposition: Step DL.8/S27; the approved bundle destination is owner question O4. Evidence: 31 tracked files under `acceptance/tests/artifacts/runs/`; writer `acceptance/tests/test_deterministic_completion.py:98-111,215-238`; only `c0e019c2` was approved (dashboard audit `2026-08-01-a2a-integration-verification-audit.md:66-80`).

### r6-f6-run-status-pollers | medium | Run-status polling is re-implemented about eight times with a phantom error status

R6-F6. Status: open. Type: duplication. Disposition: Step K.3/S48. Evidence: canonical `acceptance/tests/conftest.py:42-99`; copies `service_tests/_state.py:36-52`, `service_tests/test_lifecycle.py:13-29`, `service_tests/test_real_worker_run_completion.py:152-167`, `service_tests/test_dispatch_assignment_agreement.py:124-138`, `api/tests/test_catalog_restart_redispatch.py:340-350`; tape-server address `control/infra_config.py:43`.

### r6-f7-catalog-selection | medium | Catalog fetch-and-select is re-implemented about twelve times

R6-F7. Status: open. Type: duplication. Disposition: Step K.3/S48. Evidence: `testing/tests/_support/catalog_selection.py:56-61,110-122,136-226`; wrappers `service_tests/harness.py:795-839`, `acceptance/tests/_harness.py:134-166`, `desktop_tests/_catalog.py:35-51`; stricter twin `service_tests/_provider_catalog_live.py:147-232`.

### r6-f8-request-builders | medium | Run-start, prepare and commit request builders are duplicated

R6-F8. Status: open. Type: duplication. Disposition: Step K.3/S48. Evidence: canonical `acceptance/tests/_harness.py:186-307`; copies `desktop_tests/test_run_admission.py:147-310`, `desktop_tests/test_worker_provenance.py:167-189`, `desktop_tests/test_ownership_prerequisites.py:149-171`, `service_tests/harness.py:841-884`.

### r6-f9-loopback-uvicorn | medium | In-process uvicorn on port 0 is defined three times plus variants

R6-F9. Status: open. Type: duplication. Disposition: Step K.4/S49. Evidence: `api/tests/conftest.py:490`; `api/tests/test_gateway_live.py:681`; `api/tests/test_acceptance_five_verb.py:88`; `testing/tests/_support/listeners.py:63-80`.

### r6-f10-sse-readers | medium | Two shared SSE readers diverge and nine ad-hoc parsers exist

R6-F10. Status: open. Type: duplication. Disposition: Step K.4/S49 (primary for the R1-F18 parsers). Evidence: `testing/tests/_support/sse.py:32-61`; `api/tests/_sse_reader.py:42-91`; private decoder `authoring/client.py:54-91`; encoder `streaming/sse_frames.py:506-552`.

### r6-f11-stategraph-boundary | medium | The typed StateGraph test boundary exists in five forms

R6-F11. Status: open. Type: duplication. Disposition: Step K.4/S49. Evidence: `graph/compiler.py:104-215`; `graph/tests/_state_graph_helpers.py:28-89`; `thread/tests/_graph_helpers.py:33-73`; `streaming/tests/test_clarification_relay.py:58-74`; `api/tests/clarification_harness.py:62-71`.

### r6-f12-marker-hooks | medium | Layer-marker hooks are hand-rolled and impure streaming tests run as unit

R6-F12. Status: open. Type: correctness-risk. Disposition: P12, then Step FX.11/S16 (streaming) and Step K.5/S50 (all hooks). Evidence: `testing/markers.py:43-70`; `streaming/tests/conftest.py:8-13`; merge gate `dev/toolchain.py:765-781` and `.github/workflows/merge-gate.yml:84-85`. Architect-verified against the cited code.

### r6-f13-db-fixtures | medium | DB fixtures have 54 definitions across 33 files

R6-F13. Status: open. Type: duplication. Disposition: Step K.5/S50. Evidence: `database/tests/test_database.py:88-109`; `materialize_schema` `conftest.py:748-789`; `api/tests/conftest.py:100-161`; `database/tests/_backends.py:179`.

### r6-f14-reimplemented-logic | medium | Tests re-implement production logic

R6-F14. Status: open. Type: contract-drift. Disposition: Step K.6/S51. Evidence: `graph/tests/conftest.py:94-110` against `providers/team_selection.py:140-172`; `api/tests/conftest.py:172-256,276-290` against `worker/app.py:382-383`.

### r6-f15-langchain-fakes | medium | langchain fake models remain although CBH S101 is closed

R6-F15. Status: open. Type: contract-drift. Disposition: D2, then Step F.3/S86; reopens checked CBH W04.P12.S101, recorded in the codebase-health audit. Evidence: `rg -n "fake_chat_models import" src` finds 11 files, for example `worker/tests/test_executor.py:25`, `graph/tests/conftest.py:8`, `streaming/tests/test_public_stream_ingest.py:31`; `pf` fixture `graph/tests/conftest.py:86-91`.

### r6-f16-adhoc-skips | medium | Ad-hoc pytest.skip calls bypass the external-prerequisite rule

R6-F16. Status: open. Type: contract-drift. Disposition: Step K.3/S48. Evidence: 22 sites by `rg -c "pytest\.skip\(" service_tests acceptance desktop_tests`; `acceptance/tests/_harness.py:160-161`; prerequisite ids `conftest.py:292-433`; hard-coded Codex probe `service_tests/test_clarification_loop_stitched.py:194-198`.

### r6-f17-boundary-gates | medium | Boundary gates are incomplete for the wheel and absent for the shipped binary

R6-F17. Status: open. Type: missing-test. Disposition: P11, then Step F.5/S83. Evidence: `desktop_tests/test_component_contract.py:193-201`; `pyproject.toml:233-240`; editable freeze `.github/workflows/release.yml:195`; `packaging/pyinstaller/vaultspec-a2a.spec:62-85`; `tests/test_dev_harness_import_boundary.py:24-27,118`.

### r6-f18-duplication-guards | medium | Duplication guards cannot see dev, cross-tier or diverged clones

R6-F18. Status: open. Type: missing-test. Disposition: AST widening in Step Q.1/S108; JSCPD blocking by D7 in Step Q.2/S109. Evidence: `tests/test_structural_duplication.py:19-22,46,213-235`; `dev/audit/duplication.py:60,63,72,414-427`; `.github/workflows/test.yml:137-140`.

### r6-f19-mock-naming | low | The mock lane is named in-process and deterministic but is an HTTP proxy

R6-F19. Status: open. Type: semantic-ambiguity. Disposition: Step F.4/S87 (obviated by D2). Evidence: `providers/in_process_catalog.py:73,82,92-95`; `providers/provider_catalog_service.py:55`; `providers/mock_chat_model.py:209,227-228`; ignored selectors `providers/factory.py:932-937`.

### r6-f20-dead-presets | low | Two fixture presets have no test that drives them

R6-F20. Status: open. Type: dead-code. Disposition: Step DL.8/S27. Evidence: `team/presets/teams/mock-failure-tool.toml`, `team/presets/teams/mock-invalid.toml` and their agents and tapes; skip `team/tests/test_clarification_declaration.py:243-244`.

### r6-f21-unused-test-symbols | low | Test-infrastructure symbols have no real consumer

R6-F21. Status: open. Type: dead-code. Disposition: Step DL.8/S27. Evidence: `testing/plugin.py:363-420`; `testing/endpoints.py:126-135`; `testing/__init__.py:34,125,257`; `service_tests/harness.py:918-938`; `service_tests/conftest.py:58-61`.

### r6-f22-http-peers | medium | HTTP peer and stand-in mechanics are copied

R6-F22. Status: open. Type: duplication. Disposition: Step K.2/S47. Evidence: `service_tests/test_worker_attach_provenance.py:23-92` against `desktop_tests/test_worker_provenance.py:55-113`; `authoring/tests/_engine_peer.py:51-89`; `testing/tests/_support/http_handlers.py:40-54` against `testing/tests/_support/listeners.py:122-141`.

### r6-f23-acp-fixtures | low | ACP fixture pieces are duplicated

R6-F23. Status: open. Type: duplication. Disposition: Step K.6/S51. Evidence: `providers/tests/_acp_frames.py:29-61`; `graph/tests/acp_simulator.py:67-88`; `providers/tests/test_acp_native_commands.py:20-70`; `providers/tests/test_launcher_confinement.py:46-70`.

### r6-f24-research-roles | low | The deterministic model restates RESEARCH_ADR_ROLES

R6-F24. Status: open. Type: duplication. Disposition: Step F.2/S85. Evidence: `providers/deterministic_chat_model.py:38,76-98`; sync test `providers/tests/test_deterministic_chat_model.py:160`.

### r6-f25-fixture-boundary-test | low | The fixture-boundary test has a redundant case and a duplicate Docker resolver

R6-F25. Status: open. Type: dead-code. Disposition: The redundant test in Step DL.8/S27; the Docker resolver in Step F.4/S87. Evidence: `service_tests/test_development_fixture_boundary.py:23-27,61,99-104`; `service_tests/harness.py:98-105`.

### r6-f26-mockllm-adr | low | The decoupled-mockllm ADR is still proposed and cites a stale tape path

R6-F26. Status: decision D2. Type: contract-drift. Disposition: D2 (AD.4/S31 retires it). Evidence: heading status `proposed` in `.vault/adr/2026-03-31-decoupled-mockllm-adr.md`; cited path `src/vaultspec_a2a/core/presets/mock/tapes/` against the real `team/presets/mock/tapes/`.

### r6-f27-dev-subprocess | medium | Captured-subprocess logic is hand-rolled about eleven times in dev

R6-F27. Status: open. Type: duplication. Disposition: Step Q.4/S111. Evidence: `dev/process.py:74-99`; `dev/init/process.py:85-104,162-198`; `dev/doctor/_probe.py:26-65`; `dev/vault_annotations_gate.py:61-67`; `dev/ci_claude_cli.py:27-29`.

### r6-f28-ci-formats-copy | low | dev/guards/test_ci_formats.py duplicates dev/tests/test_ci_formats.py

R6-F28. Status: open. Type: dead-code. Disposition: Step DL.9/S28. Evidence: the files differ at line 15 only; dead branches `dev/ci_formats.py:70-75`; sole caller `dev/runner.py:118`.

### r6-f29-init-hooks | low | dev/init/hooks.py is dead and conflicts with dev/repo/hooks.py

R6-F29. Status: open. Type: dead-code. Disposition: Step DL.9/S28. Evidence: zero callers besides `dev/init/hooks.py:121`; missing default config `:127`; live `dev/repo/hooks.py:72-102`.

### r6-f30-dead-dev-tools | low | Three superseded or uninvoked dev tools remain

R6-F30. Status: open. Type: dead-code. Disposition: Step DL.9/S28 (the vulture dependency in Step DL.12/S29). Evidence: `dev/audit/dead_code_burndown.py` via `Justfile:475-476`; `dev/audit/dead_code.py:24-31`; `pyproject.toml:168`; `dev/tests/test_pep561_markers.py:16`.

### r6-f31-dev-constants | medium | Dev constants and skeletons are restated and drift

R6-F31. Status: open. Type: duplication. Disposition: Step Q.4/S111. Evidence: tiers `dev/paths.py:45-50` against `dev/toolchain.py:76,81-94` and `pyproject.toml:535-538,564`; `PYTHON_PATHS` `dev/toolchain.py:58`, `dev/quality/types.py:51-55`, `prek.toml:47`; exit codes `dev/actionlint.py:99-102` against `dev/EXIT-CODES.md:73,82-86`.

### r6-f32-gate-overlap | medium | Quality gates overlap

R6-F32. Status: owned 2026-07-19-repository-tooling-hardening-plan W08.P15.S40, S41. Type: duplication. Disposition: D7, then owned RTH W08.P15.S40 and S41 (amended; the false-pass exit fix folds into S40). Evidence: `dev/health/report.py:396-410` against `dev/toolchain.py:405-418`; `pyproject.toml:544,552`; false pass `dev/health/__main__.py:67-72`.

### r6-f33-anchors-guard | low | The storage_anchors guard is wired only as a harness test

R6-F33. Status: open. Type: missing-test. Disposition: Step Q.3/S110. Evidence: `dev/toolchain.py:510-558`; `Justfile:374`; `dev/guards/storage_anchors.py:116,364-390`; `dev/tests/test_storage_anchors.py:201-225`.

## R7 - host, desktop and cross-cutting

### r7-f1-bearer-disclosure | medium | The worker-IPC bearer is presented to unverified worker-port occupants

R7-F1. Status: open. Type: correctness-risk. Disposition: (a) and (b) in Step FX.5/S15; (c) proof-of-possession is rejected by D13 in favour of descendant-ownership. Evidence: `control/_worker_health.py:428,553-559,585,629`; `control/_worker_readiness.py:130-132`; leak-asserting test `control/tests/test_worker_provenance.py:224-296`; contrast `lifecycle/manager.py:800-804`. Architect-verified against the cited code.

### r7-f2-spawn-protocols | medium | Process-tree ownership has three kill strategies and four spawn protocols

R7-F2. Status: open. Type: duplication. Disposition: Step H.1/S88; RTH W07.P13.S33 is sequenced after it. Evidence: contract `utils/process.py:262-266`; providers `providers/_subprocess.py:303-345,362-418,461-466`; unsuspended worker `control/worker_management.py:161-168`, `control/_worker_readiness.py:82-87`; `lifecycle/engine_serve.py:208-215`; psutil path `control/_worker_process_stop.py:36-121,161-178`.

### r7-f3-introspection-backends | medium | Two process-introspection backends coexist

R7-F3. Status: open. Type: duplication. Disposition: D13, then P19, then Step H.2/S92. Evidence: psutil `pyproject.toml:39`, `control/_worker_process_stop.py:9-121`, `testing/children.py:38,85-97`; hand-rolled `utils/_process_tree.py:109-232,235-318,356-771`, `utils/process.py:74-169`, `lifecycle/singleton.py:161-224`.

### r7-f4-liveness-wrappers | low | Forwarding wrappers and parallel probes surround process and port liveness

R7-F4. Status: open. Type: duplication. Disposition: Step H.3/S89. Evidence: `lifecycle/manager.py:126-145,657-685,911-922`; `lifecycle/discovery.py:349-379,469-485`; `cli/service.py:261-267`; `control/_worker_health.py:357-372,387-442`; shims `utils/process.py:13-57`, `utils/_process_tree.py:878-893`.

### r7-f5-engine-reap | low | The engine child can survive a reap that reports success

R7-F5. Status: open. Type: correctness-risk. Disposition: Step H.1/S88. Evidence: `lifecycle/engine_serve.py:212-215,248-257`; `utils/process.py:584-585`. Investigator-only: a hypothesis until its probe or Step test runs.

### r7-f6-double-kill | low | A repeated kill_process_tree takes the per-pid path and teardown logs an unused strategy

R7-F6. Status: open. Type: correctness-risk. Disposition: P14, then Step H.1/S88. Evidence: `utils/process.py:575-578`; `providers/_subprocess.py:444-466`; `providers/_acp_teardown.py:77-89`. Investigator-only: a hypothesis until its probe or Step test runs.

### r7-f7-test-only-branches | medium | Control carries worker-shutdown branches that only tests reach

R7-F7. Status: open. Type: dead-code. Disposition: Step DL.7/S25 (after FX.5/S15). Evidence: `control/worker_management.py:64-70,153-155,357-363,484-491,510-515,533-548,856-874`; test-only installs `control/tests/test_worker_watchdog_resilience.py:121,288`, `desktop_tests/test_worker_provenance.py:419`.

### r7-f8-desktop-settlement | low | Desktop settlement is unreachable and its certification is tautological

R7-F8. Status: open (reachability owned by 2026-10-04-desktop-native-isolation-plan S12). Type: missing-test. Disposition: Reachability owned DNI S12; the tautological test and dead parameter in Step DL.11/S22; T-F8 in Step CV.2/S114. Evidence: `control/event_handlers.py:369-413,828`; armed refusal `api/routes/_gateway_run_start.py:106-110`; `desktop_tests/test_terminal_settlement.py:122-160,399-449`; untested `desktop/settlement.py:66-99,130-137,174-181`; dead parameter `acceptance/tests/_harness.py:316,359-360`.

### r7-f9-native-isolation | low | The native isolation chain is unreachable in production and two refusals are untested

R7-F9. Status: open (reachability owned by 2026-10-04-desktop-native-isolation-plan S12). Type: missing-test. Disposition: Reachability owned DNI S12; T-F9a/b and the setuid fold in Step CV.2/S114. Evidence: `providers/_provider_execution.py:68`; `control/provider_execution.py:18-22`; `desktop/native_isolation.py:426-428,498-504`; `desktop/_linux_helper.py:14-41`; `scripts/build_linux_isolation.py:55-62`.

### r7-f10-owner-predicates | low | Owner-restriction predicates use three rules and link checks are re-coded six times

R7-F10. Status: open. Type: semantic-ambiguity. Disposition: Step H.5/S93. Evidence: `desktop/_platform_acl.py:261,273-303,376-378`; `desktop/profile.py:382,418`; `desktop/credentials.py:215`; `desktop/_filesystem_authority.py:130-132`; `providers/_codex_config_home.py:194-202`; bare chmod `providers/_codex_auth.py:103-106`, `authoring/_journal_index.py:68`, `authoring/_tool_calls.py:78`.

### r7-f11-private-reads | medium | Private secret files are read four ways with divergent hardening

R7-F11. Status: open. Type: duplication. Disposition: Step H.5/S93. Evidence: `desktop/credentials.py:144-179`; `lifecycle/discovery.py:138-186`; `authoring/_engine_trust.py:77-108`; unhardened `lifecycle/boot.py:97-116`.

### r7-f12-bearer-helpers | low | Bearer checks, IPC header builders and discovery enums are duplicated

R7-F12. Status: open. Type: duplication. Disposition: Step H.4/S90. Evidence: `utils/ipc_auth.py:78-79`; `api/auth.py:74-75`; `worker/authoring_relay.py:60-63,77-81`; headers `api/app.py:596-600`, `control/_worker_health.py:375-384`, `worker/ipc.py:175-177`, `lifecycle/manager.py:642-654`; enums `lifecycle/discovery.py:103-109,568-574`.

### r7-f13-field-binders | medium | A legacy field-binder pattern is copied four times because of pylint R0902

R7-F13. Status: open. Type: duplication. Disposition: D7, then Step Y.1/S106. Evidence: `control/action_lease.py:100`; `desktop/profile.py:57-108,148-265`; `lifecycle/_desktop_discovery_record_parts.py:12-123`; `telemetry/instrumentation.py:142-294`; accepted group `tests/test_structural_duplication.py:71-81`; `pyproject.toml:545,555`.

### r7-f14-state-paths-mirror | medium | DesktopStatePaths mirrors StateLayout and two reserved dirs have no consumer

R7-F14. Status: open. Type: duplication. Disposition: P22, then Step Y.2/S96 (after SCR S03 and S05). Evidence: `desktop/profile.py:148-296`; `control/state_layout.py:154-253`; `receipts_dir` and `snapshots_dir` appear only at `control/state_layout.py:215,225,245,247`.

### r7-f15-project-root | medium | Project-root identity is normalised four ways and the provider version mangles UNC paths

R7-F15. Status: open. Type: duplication. Disposition: P13, then Step H.6/S91. Evidence: `ipc/schemas.py:66-97`; `control/workspace.py:24-74`; `providers/_acp_types.py:171-201,256-288`; `providers/_project_scope.py:80-97`; `database/thread_repository.py:178-191`.

### r7-f16-git-mutex | low | The global git workspace mutex serialises every ACP write

R7-F16. Status: open. Type: dead-code. Disposition: D24, then Step H.8/S95. Evidence: `workspace/concurrency.py:3-9`; sole acquirer `providers/_acp_rpc_handlers.py:673,693`; monkeypatching test `providers/tests/test_acp_authoring.py:413-421`.

### r7-f17-provenance-names | low | Two test_worker_provenance files share a name for different branches

R7-F17. Status: open. Type: naming. Disposition: Step Y.4/S98. Evidence: `control/tests/test_worker_provenance.py:1-7,94-296`; `desktop_tests/test_worker_provenance.py:1-17,223-535`.

### r7-f18-asyncio-compat | low | configure_asyncio_runtime does nothing

R7-F18. Status: open. Type: dead-code. Disposition: Step DL.1/S17. Evidence: `utils/asyncio_compat.py:8-15`; call sites `api/app.py:85,867`, `worker/app.py:57,575`.

### r7-f19-version-lookup | low | The installed-version lookup is implemented twice with different fallbacks

R7-F19. Status: open. Type: duplication. Disposition: Step DL.1/S17. Evidence: `utils/version.py:15-25` against `api/routes/_gateway_action_endpoints.py:823,858-865`.

### r7-f20-telemetry-debris | low | Telemetry carries naming and code debris

R7-F20. Status: open. Type: dead-code. Disposition: Step DL.10/S21. Evidence: `telemetry/middleware.py:165-166,172-220`; `telemetry/aggregator_hook.py:51-53`; tautological `telemetry/tests/test_telemetry.py:300-310`.

### r7-f21-body-limit-residue | low | Body-limit residue: route re-checks, literals and an ipc-to-control import

R7-F21. Status: duplicate R1-F17. Type: duplication. Disposition: Duplicate of R1-F17; the ipc leaf-import fix lands in Step DL.2/S18. Evidence: `ipc/body_limit.py:8,30,51-55`; `api/internal.py:413-424,455-470`; `ipc/__init__.py:11-25`.

### r7-f22-ws-hangers | medium | The internal WebSocket carries a setting, an auth path, a planned Step and a dependency

R7-F22. Status: duplicate R1-F6. Type: dead-code. Disposition: Duplicate of R1-F6 (Step DL.2/S18); ARV P06.S48 is re-scoped to HTTP only. Evidence: `worker/ipc.py:3-8,398,612`; `api/internal.py:5,321,327-335,404-443`; `control/infra_config.py:864-867`; `pyproject.toml:50`.

### r7-f23-settings-singletons | medium | Two settings singletons both expose every domain field

R7-F23. Status: open. Type: duplication. Disposition: D16, then Step Y.3/S97. Evidence: `control/config.py:53-61`; `domain_config.py:83,313-334`; dual reads `api/thread_stream.py:646` and `streaming/subscribers.py:386`; override touches only `settings` at `testing/environment.py:65-81`.

### r7-f24-settings-odds | low | Resident ports, env-name accessors and a runtime secret live in settings

R7-F24. Status: open. Type: duplication. Disposition: Step Y.3/S97. Evidence: `control/infra_config.py:643-660` against `procs.toml:13-14`; `control/config.py:577-582` against `control/infra_config.py:1007-1009`; runtime secret `api/app.py:275,277`.

### r7-f25-redaction | medium | Secret redaction is implemented five times with different rules

R7-F25. Status: open. Type: duplication. Disposition: Step H.7/S94 (after SCR S06; the S06 output folds in). Evidence: `utils/logging.py:236-287`; `providers/_subprocess.py:65-100`; `control/settings_base.py:507-553`; `control/infra_config.py:117-142`; `telemetry/middleware.py:141-149`.

### r7-f26-harness-naming | low | Harness names both the agent harness and the test harnesses

R7-F26. Status: open. Type: naming. Disposition: Step Y.4/S98. Evidence: `team/team_config.py:370-399`; `context/harness.py:1-163`; `service_tests/harness.py:1`; `acceptance/tests/_harness.py:1-12`; `testing/harness_names.py:1-20`.

### r7-f27-settlement-naming | low | Settlement names at least seven distinct operations

R7-F27. Status: open. Type: naming. Disposition: Step Y.4/S98; the env alias is kept for one release (CE2). Evidence: `worker/_dispatch_settlement.py:1-12,169`; `control/event_handlers.py:651-692,750`; `desktop/settlement.py:1-20`; `control/repositories/continuation_queue.py:17-21,297-317`.

### r7-f28-token-naming | low | One secret has many token names and different things share one name

R7-F28. Status: open. Type: naming. Disposition: Step Y.4/S98. Evidence: `api/app.py:275,914`; `control/infra_config.py:385,680-688`; `api/auth.py:28-40`; `api/internal.py:118-125`; `worker/token_store.py:31-74`; `database/models.py:570,643`.

### r7-f29-pairing-module | low | lifecycle/pairing.py bundles two unrelated pairings

R7-F29. Status: open. Type: naming. Disposition: Step Y.4/S98. Evidence: `lifecycle/pairing.py:1-17,45-250,253-335`; callers `api/app.py:375`, `worker/app.py:195`, `control/_worker_health.py:17-21,472-490,597`.

### r7-f30-restore-guard | medium | The database restore guard read an authenticated live service as not running

R7-F30. Status: fixed@e19c501d. Type: correctness-risk. Disposition: Fixed@e19c501d (connect-probe guard plus regression tests). Step DL.13/S26 (D19) then removes the guarded verbs; the surviving `migrate --compact` refuses live stores by lock probe, not HTTP. Evidence: pre-fix probe `database/admin.py:236-249`; bearer-protected endpoints `api/internal.py:156-160,393` and `worker/app.py:488`; fix `_refuse_while_service_listening` in e19c501d. Architect-verified against the cited code.

### r7-f31-sibling-branches | low | Two sibling branches carry content already in main

R7-F31. Status: decision D25. Type: dead-code. Disposition: D25 (owner git action, owner question O6). Evidence: `fix/desktop-private-state` (91971e87) landed in 3f4a8f6a; `fix/internal-http-body-limit` merged in 76335234; audit `.vault/audit/2026-10-04-desktop-product-profile-sensitive-state-security-audit.md:54`.

### r7-f32-file-lock-test | low | utils/file_lock has no direct crash-release test

R7-F32. Status: open. Type: missing-test. Disposition: Step CV.2/S114. Evidence: `utils/file_lock.py:3-5`; indirect coverage `providers/tests/test_codex_credential_writeback.py:335-385`, `lifecycle/tests/test_singleton.py:144-178`; no `utils/tests/test_file_lock.py`.

## Architect additions

### x1-clarify-preset-ships | medium | The only clarification-producing fixture preset is not wheel-excluded

X1. Status: open. Type: contract-drift. Disposition: Step F.2/S85 (exclude) and the Step F.5/S83 gate. Evidence: `team/presets/teams/vaultspec-adr-research-clarify.toml`; exclude list `pyproject.toml:229-267`.

### x2-unapproved-owning-plans | high | Owning plans lack approval while their Steps are checked

X2. Status: decision D8. Type: governance. Disposition: D8 and owner question O1. Evidence: `.vault/plan/2026-09-05-embedded-runtime-remediation-plan.md:274` says unapproved with 30 of 90 Steps checked; RTH, CBH, SCC, PMC, PCE, KIM and TC8 carry no Approved line.

### x3-tool-cores-rows | low | Three tool-cores rows cover one hosted-lane web-search concern

X3. Status: decision D3. Type: governance. Disposition: Closed by D3: TC8 closes P02.S19-S21 and P03.S18 as obviated once AD.5/S32 is accepted (owner O5). Evidence: `.vault/plan/2026-08-01-tool-cores-plan.md` P02.S19, P02.S20, P02.S21.

### x4-stream-quotas-satisfied | low | The codebase-health stream-quota Step appears already satisfied

X4. Status: owned 2026-07-19-codebase-health-plan W02.P06.S25. Type: contract-drift. Disposition: CBH verifies the Step against its acceptance, then closes or re-scopes it. Evidence: `streaming/subscribers.py:386`; `api/thread_stream.py:646`.

### x5-dispatch-budget | medium | The dispatch envelope size budget audit item has no owner

X5. Status: open. Type: correctness-risk. Disposition: Step C.1/S99 owns the dispatch envelope size budget. Evidence: unowned item generated-dispatch-budget in `.vault/audit/2026-10-04-worker-process-architecture-audit.md`.

### x6-dni-013 | low | DNI-013 native role-home recovery has no Step

X6. Status: owned 2026-10-04-desktop-native-isolation-plan (new Step). Type: governance. Disposition: The DNI plan adds a Step (owner of that plan). Evidence: `.vault/audit/2026-10-04-desktop-native-isolation-audit.md:136`.

### x7-worker-turn-composer | medium | Worker-turn composition is duplicated between the research compiler and the worker node

X7. Status: open. Type: duplication. Disposition: Step L.2/S77. Evidence: `graph/_compiler_research.py:264-360` against `graph/nodes/worker.py:825-995`.

### x8-dev-imports-service-tests | low | dev/providers.py imports a service-test module

X8. Status: open. Type: contract-drift. Disposition: Step K.1/S46. Evidence: `dev/providers.py:34-36` imports `service_tests._provider_catalog_live`.

### x9-claude-ci-version | low | CI hard-codes the Claude version while Codex derives it

X9. Status: owned 2026-10-01-provider-binary-policy-plan P02.S21. Type: duplication. Disposition: Owned PBP P02.S21: re-enrollment records the version and CI derives it. Evidence: `dev/ci_claude_cli.py:9` against `PROVEN_TURN_LANES` in `providers/lane_admission.py`.

### x10-mcp-ui-servers | low | The tracked .mcp.json carries UI-era MCP servers

X10. Status: decision D20. Type: dead-code. Disposition: D20: the owner changes the Core-owned projection through `vaultspec-core spec mcps` (Step AD.18/S45). Evidence: `.mcp.json` lists playwright, shadcn-ui, chrome-devtools and figma.

### x11-permission-prune-age | low | The worker prunes pending permissions after five minutes regardless of state

X11. Status: open. Type: correctness-risk. Disposition: Step R.1/S55. Evidence: `worker/executor.py:497-498`.

### x12-preset-loaded-thrice | low | Admission loads the preset three times and three replay mechanisms are undocumented

X12. Status: open. Type: duplication. Disposition: Step G.1/S75. Evidence: `api/routes/gateway.py:649`; `control/thread_service.py:204,244`.

### x13-permission-session-check | medium | session/request_permission skipped the session-ownership check

X13. Status: fixed@3fa8df3d. Type: correctness-risk. Disposition: Fixed@3fa8df3d; no Step. Evidence: `providers/_acp_rpc_handlers.py:530-541`; tests `providers/tests/test_acp_callback_ownership.py`.

### x14-concurrent-edits | high | Concurrent edits overlapped remediation files

X14. Status: fixed@8a6fbe62 (C1 resolved by e19c501d, 3fa8df3d and 8a6fbe62). Type: governance. Disposition: Resolved: C1 was the orchestrator's own work, committed as e19c501d, 3fa8df3d and 8a6fbe62 after a full regression run (3475 passed, 18 pre-existing prerequisite skips). The git-status-first rule stays in every brief. Evidence: commits e19c501d, 3fa8df3d, 8a6fbe62.

### x15-poller-copy | low | 8a6fbe62 added another run-status poller

X15. Status: open. Type: duplication. Disposition: Step K.3/S48 absorbs it. Evidence: `api/tests/test_clarification_loop_live.py:662`.

## Probes

Each probe settles a question that only a run can answer, and gates the named Step. Probes run in an isolated scratch worktree; P21 and P22 are owner-run (O8) and P23 is credential-run. A verdict replaces `open` with `confirmed`, `refuted` or `inconclusive` and appends an output excerpt and the gated Step's go or no-go. A refuted probe cancels or re-scopes its gated Step. P1 is retired: R4-F1 is fixed@8a6fbe62 and its live T1 test fails on HEAD~; its restart half became FX.1/S06's T2.

### p2-terminal-disclosure | medium | Decide whether a cancelled parked run still discloses its clarification

P2. Status: open. Settles: R2-F4 reachability. Gates: FX.2/S07. Run by: PR.1/S01. Command: write `api/tests/test_terminal_interrupt_disclosure.py` (R2 T2(b)) in scratch and run it.

### p3-sequence-gap | high | Measure the gap between served last_sequence and stream ids

P3. Status: open. Settles: R2-F1 gap size. Gates: FX.3/S08. Run by: PR.1/S01. Command: write `api/tests/test_run_status_sequence_agreement.py` (R2 T1) in scratch and run it.

### p4-run-start-201 | medium | Decide whether run-start answers 201 on a worker-classified refusal

P4. Status: open. Settles: R1-F5 live reachability. Gates: FX.6/S12. Run by: PR.1/S01. Command: extend `api/tests/test_run_action_refusal_vocabulary.py` to `POST /v1/runs` against its saturated worker and run it.

### p5-second-resume | medium | Decide whether a clarification RESUME is dispatched twice

P5. Status: open. Settles: R4-F3. Gates: FX.12/S11 against C.4/S102. Run by: PR.1/S01. Command: `uv run --no-sync pytest src/vaultspec_a2a/service_tests/test_clarification_loop_stitched.py -k parks_discloses_answers_and_resumes -x`, then query `control_actions` (`clarification-response:%`) and `recovery_attempts`.

### p6-malformed-request-id | low | Decide whether a malformed clarification id answers 500 or 422

P6. Status: open. Settles: R4-F29. Gates: FX.6/S12. Run by: PR.1/S01. Command: post `/v1/runs/{id}/clarifications/a!b/respond` in `api/tests/test_clarification_endpoint.py`.

### p7-host-eligibility | high | Show which providers readiness lists as eligible on a real host

P7. Status: open. Settles: R5-F1 on host. Gates: FX.4/S13. Run by: PR.1/S01. Command: `uv run --no-sync python -c "from vaultspec_a2a.control.health import _eligible_provider_names as f; print(f())"`.

### p8-gate-one-strand | high | Show the research_adr park at research_gate with default env

P8. Status: open. Settles: R4-F12. Gates: FX.8/S14. Run by: PR.1/S01. Command: boot with default env; `GET /v1/presets`; start `vaultspec-adr-research`; observe the park at `research_gate`.

### p9-no-gateway-sequenced-event | high | Prove no gateway SequencedEvent, internal WebSocket or single-event client exists

P9. Status: open. Settles: R1-F2 and R1-F6 deletion safety. Gates: DL.2/S18 and DL.3/S19. Run by: PR.1/S01. Command: in scratch delete the branches at `api/thread_stream.py:177-183`, `api/_replay_writer_seat.py:53-56` and the WS route; `uv run --no-sync pytest src/vaultspec_a2a/api src/vaultspec_a2a/acceptance src/vaultspec_a2a/service_tests -x -q`; grep gateway INFO logs for `Worker connected to internal WS` and `POST /internal/events` without `/batch`.

### p10-websockets-holders | medium | Find any direct runtime holder of the websockets package

P10. Status: open. Settles: R1-F6 dependency half (D22). Gates: DL.12/S29. Run by: PR.2/S02. Command: `uv tree --invert --package websockets`; `uv run --no-sync --group tooling deptry .` with the pin removed.

### p11-onedir-contents | high | List what the frozen onedir actually carries

P11. Status: open. Settles: R6-F4 and R6-F17. Gates: F.5/S83 and F.2/S85. Run by: PR.2/S02. Command: R6 scratch build command (`scripts/build_binary.py --dist tmp/r6-bin` plus an `fd` filter).

### p12-impure-unit-tests | medium | List impure streaming tests collected under the unit marker

P12. Status: open. Settles: R6-F12. Gates: FX.11/S16. Run by: PR.2/S02. Command: `uv run --no-sync python -m pytest --collect-only -q -m unit src/vaultspec_a2a/streaming/tests`.

### p13-unc-canonicaliser | medium | Show the UNC canonicaliser divergence on a long UNC path

P13. Status: open. Settles: R7-F15. Gates: H.6/S91. Run by: PR.2/S02. Command: R7 U4 one-liner.

### p14-double-kill | low | Decide whether a production double kill_process_tree occurs

P14. Status: open. Settles: R7-F6. Gates: H.1/S88. Run by: PR.2/S02. Command: R7 U6 runner command; search for duplicate `ACP subprocess termination starting` per pid.

### p15-threads-column-drop | medium | Check a threads column drop keeps the DESC partial indexes

P15. Status: open. Settles: migration 0026 safety (R3-F4, R3-F5, K3). Gates: S.5/S74. Run by: PR.2/S02. Command: draft 0026 in scratch; `pytest src/vaultspec_a2a/database/tests/test_schema_integrity.py src/vaultspec_a2a/database/tests/test_migrations.py`.

### p16-fingerprint-inputs | low | Decide which payload fingerprint input is canonical

P16. Status: open. Settles: R3-F16. Gates: A.4/S67. Run by: PR.2/S02. Command: the R3 unresolved test in `control/tests/test_dispatch_receipts.py`.

### p17-commit-double-freeze | medium | Show commit double-freeze divergence under a short catalog TTL

P17. Status: open. Settles: R5-F4. Gates: G.1/S75. Run by: PR.2/S02. Command: `uv run --no-sync pytest src/vaultspec_a2a/desktop_tests/test_run_admission.py -q` with a short catalog TTL.

### p18-openapi-names | medium | Check OpenAPI component names survive serving thread dataclasses

P18. Status: open. Settles: R2-F14 (D6 name preservation). Gates: M.6/S63. Run by: PR.2/S02. Command: scratch: swap `ThreadStateSnapshot` for `ThreadStateData`; regenerate; `git diff --stat openapi.json`.

### p19-descendant-listener | medium | Check psutil descendant-listener detection without elevation

P19. Status: open. Settles: R7-F3 and D13 per OS. Gates: H.2/S92. Run by: PR.2/S02. Command: scratch script: spawn a child HTTP listener; `psutil.Process(child).net_connections(kind="tcp")` on the Windows and Linux CI runners, and macOS if supported (O9).

### p20-bounds-ci-skip | medium | Confirm the bounds agreement test skips in CI

P20. Status: open. Settles: R1-F10. Gates: Q.5/S112. Run by: PR.2/S02. Command: in the `test` job log, `pytest src/vaultspec_a2a/api/tests/test_engine_edge_bounds_agreement.py -rs` shows 5 SKIPPED.

### p21-store-census | medium | Count legacy lease, r1 digest and repair rows on real desktop stores

P21. Status: open. Settles: R1-F4, R3-F22 and R3-F4 (owner-run, O8). Gates: DL.6/S24 (r1 branch), E.1/S52 (`_legacy_lease_id`), S.5/S74 (repair enum). Run by: PR.3/S03. Command: on each real desktop home run the R1-U4 lease query, the R3-F22 digest query and the R3-F4 repair-row query; expected 0, 0, 0.

### p22-dashboard-dirs | medium | Check whether the dashboard writes receipts or snapshots dirs

P22. Status: open. Settles: R7-F14 and D26 (owner-run, O8). Gates: Y.2/S96. Run by: PR.3/S03. Command: `rg -n "receipts|snapshots" <dashboard>/engine <dashboard>/frontend/src`.

### p23-zai-catalog-live | medium | Show the live Z.ai catalog failure with a credential

P23. Status: open. Settles: R5-F9 (credential-run). Gates: L.5/S80. Run by: PR.3/S03. Command: `uv run --no-sync pytest -m service src/vaultspec_a2a/providers/tests/test_zai_catalog_live.py --require-prerequisite=zai-credential -q`.

## Recommendations

Each costly decision below needs an ADR action before any dependent Step executes. The recommendation is the architect's; the ADR records the decision, and the owner accepts or declines it (O2).

- D1 (AD.3/S30): keep the accepted Postgres production backend, or retire it? Recommended: SQLite only; delete the Postgres code and the `server` extra; supersede `2026-03-10-postgres-dual-backend-adr` after acceptance; amend the stream-resumption S5 phrase "identical on both backends"; TPM replaces its Postgres verification line. Evidence: the binary excludes the Postgres drivers (`packaging/pyinstaller/vaultspec-a2a.spec:76-78`), application containers are retired by `2026-10-04-container-release-native-production-adr`, and no CI job provisions Postgres. Keeping it dormant leaves about 1,000 untested dialect lines under every new migration. Ties: R3-F12.
- D2 (AD.4/S31): which model stand-in survives, and how do fixture lanes leave the product? Recommended: the deterministic lane only, moved to `testing/lanes/` and armed through an inverted seam. Product code declares a `LaneRegistration` protocol, `register_lanes(registry)` and a `lane_plugins` setting (`VAULTSPEC_A2A_LANE_PLUGINS`), honoured only when `serve_in_process_lanes` is armed and the desktop profile is not; a failed import is a typed startup refusal. Rejected: wheel entry points (dangling metadata), a product-side conditional import of `testing`, test-only entry modules. Guard Q.5(h) closes the string-import bypass. Retire `2026-03-31-decoupled-mockllm-adr`; amend the integration-testing ADR so VidaiMock is no longer the certification replay. Evidence: `providers/deterministic_chat_model.py:46-66,243-301`; the worker inherits the gateway env (`control/worker_management.py:137,166`); the binary freezes from an editable install (`packaging/pyinstaller/vaultspec-a2a.spec:81-85`), so F.5/S83 lands before F.2/S85. Ties: R6-F3, R6-F4, R6-F15, R6-F19, R6-F24, R6-F25, R6-F26, X1.
- D3 (AD.5/S32): which unservable lanes stay? Recommended: retire OpenAI, Zhipu and Antigravity; keep Z.ai with a real catalog; keep Kimi, proof-bound, with an absolute launcher and restored per-run isolation. Amend `2026-08-02-provider-model-catalog-adr` and reconcile the capability-evidence ADR's "every external lane". Evidence: production `create` callers sit behind proof (`graph/_compiler_models.py:93,264`); Antigravity has no execution path (`providers/factory.py:149-160`) yet spawns `agy models` on every cold catalog; provider-binary-policy Constraints: "A capability the production path cannot reach is not kept in the code." This overrides the TC8 web-search directive for three lanes (O5). Ties: R5-F8, R5-F9, R5-F15, X3.
- D4 (AD.1/S04): what does `threads.last_sequence` mean, and who writes it? Recommended: the allocator's issued high-water mark, written at settle from `RunSequenceAllocator`; the worker counter is a worker-local ordering aid; stamp trace and span ids at allocation. Amend stream-resumption S1, S5 and S7 as contract event CE1. Evidence: S1 and S7 contradict each other (`.vault/adr/2026-10-01-stream-resumption-adr.md:69,81`); settle reads the emitter counter (`control/event_handlers.py:810-812`). Ties: R2-F1, R2-F18.
- D5 (AD.6/S33): where does SQL live? Recommended: accept `2026-03-28-database-layer-adr` with an amendment: one `database/` module per aggregate, no `control/repositories/`, reconciliation in `control/`, facade-only imports and a shared `_leases.py`. Fix the migration-framework ADR heading drift in D20. Ties: R3-F9, R3-F10, R3-F11, R3-F23.
- D6 (AD.7/S34): one read-model type, OpenAPI names, and the history clarification shape. Recommended: the Layer-1 dataclasses are the source, served through `TypeAdapter` with wire bounds as `Annotated` metadata; preserve OpenAPI component names where P18 shows it is possible, otherwise announce renames in CE2; the history clarification field takes the canonical `ClarificationRequest`. Amend core-layer-boundary; retire domain-logic-extraction in D20. Evidence: the mirrors have lost fields (`api/schemas/snapshots.py:198-224`) and `model_validate(asdict())` drops unknown fields (`api/routes/_gateway_read_endpoints.py:573-581`). Ties: R2-F14, R1-F11, R2-F3.
- D7 (AD.8/S35): should duplication enforcement block and widen, who owns each quality dimension, and how is R0902 handled? Recommended: the AST guard widened and blocking; JSCPD pinned in `package.json`, widened to every tier and blocking against an adjudicated baseline once W05 lands; ruff C901 owns cyclomatic, pylint owns shape, limits and nesting, and the radon `health --gate cyclomatic` duplicate goes; disable R0902 project-wide. Amend repository-tooling-hardening ("staged strict-quality enforcement"). Evidence: `dev/audit/duplication.py:60`; `pyproject.toml:545,555`; `dev/health/report.py:396-410` against `dev/toolchain.py:405-418`. Ties: R6-F18, R6-F32, R7-F13, R3-F19, R4-F24.
- D8 (owner action, no ADR): how do unapproved owning plans and proposed served-capability ADRs affect execution? Recommended: re-home correctness work under accepted authority now (FX.4/S13 under provider-binary-policy D2); at gate G-W04 move any finding still owned by an unapproved plan's Step to its named fallback Step (M.5/S62, C.6/S104, L.3/S79, E.4/S57), and let the owning plan re-scope its Step. Owner actions O1 and O2. Ties: R5-F21, X2, R2-F15, R4-F15, R4-F35, R1-F8.
- D9 (AD.2/S05): verdict subscriber enablement. Recommended: start the subscriber whenever an engine record is discoverable, and refuse document-gate topologies with a typed run-start reason otherwise. Amend adr-authoring-orchestration (Verdict subscriber, PW7 default) as CE1. Evidence: default off (`control/infra_config.py:694-702`), started only at `api/app.py:644`, and the respond route refuses document pauses (`control/permission_service.py:321-352`). Ties: R4-F12.
- D10 (AD.9/S36): task-queue fate. Recommended: retire the capability and drop `task_queue_entries`; supersede `2026-03-03-persistent-task-queue-schema-adr`. Evidence: `seed_task_queue` has zero production callers, and the amendment's planner-emitted rows do not exist. Ties: R3-F3.
- D11 (AD.10/S37): pause authority. Recommended: the checkpoint is the pause authority for every interrupt kind; durable permission rows become journal, audit and disclosure cache; the one recorder is the shipped `reconcile_clarification_pause`, generalized to `reconcile_run_pause`. Open point: does a permission park keep a `PERMISSION_REQUEST_CREATED` writer receipt or park under the current writer? Recommended: the current writer, with the respond path validating against the journal row; AD.10/S37 must cite the reworked receipt checks (`control/event_handlers.py:873-885`). Amend clarification-continuation; reconcile tool-permission-model so the TPM P06 grant table builds on it. Ties: R4-F2, R4-F1, R4-F4.
- D12 (AD.11/S38): what does the provider hear on park, and what may precede a gated call? Recommended: answer the lane's abandon outcome (ACP `cancelled`; Codex its abort decision, verified against the pinned app-server schema); raise the Codex interrupt on the idle-timeout path too; state that a supervised run gates every non-idempotent effect. Amend tool-permission-model. Served-lane proof obligation: a credential-run Step shows a live supervised Codex turn parking on an approval, the worker answering the abandon outcome, and the replayed turn completing with real model output on a binary inside `PROVEN_TURN_LANES[CODEX]`; the change may not ship before that passes; Claude's proof waits for PBP P02.S21. Fallback if TPM declines: C.8 and CV.5 in the remediation plan. Ties: R4-F10.
- D13 (AD.12/S39): introspection backend and ownership before credential. Recommended: psutil as the single backend, and confirm that one of our descendants listens on the port before any bearer is sent, which makes a proof-of-possession challenge unnecessary; P19 verifies it per OS. New ADR; retire the proposed process-and-workspace-management ADR in D20; amend the desktop-product-profile "Security, singleton, and discovery" section. Ties: R7-F3, R7-F1, R7-F2, R7-F4.
- D14 (AD.13/S40): accounting surface. Recommended: `cost_tracking` is the single accounting home with an additive run-history `usage` read (CE2); the `token_usage` channel stays for compaction; drop `estimated_cost` and `MoneyAmount` after freezing a copy into migration 0014. New ADR; owner O3. Ties: R3-F14, R2-F24.
- D15 (AD.14/S41): stream frame contract and cross-repo bounds verification. Recommended: `PROGRESS_CATALOG` is the single schema source and a generated frame JSON Schema is published (SCC W04.P09.S27, fallback E.4/S57); unify the live ISO-8601 heartbeat (`api/thread_stream.py:532-541`) on float epoch in E.2/S53 as a CE2 event after dashboard acknowledgement (O10), else keep it ISO as the one catalogued exception; keep both `type` and `event_type` keys; a2a asserts its own constants over `create_app().openapi()` and the dashboard owns the engine-side check. Amend a2a-edge-conformance R6. Ties: R1-F2, R1-F10, R1-F16.
- D16 (AD.15/S42): settings single source. Recommended: `Settings` derives from `InfraConfig` only, and domain fields are read only through `domain_config`. Amend infra-config Consequences. Evidence: `max_stream_connections` is read through both (`api/thread_stream.py:646`, `streaming/subscribers.py:386`) while `settings_override` mutates only `settings`. Ties: R7-F23.
- D17 (AD.16/S43): retire dead protocol branches. Recommended: delete the `custom` stream mode and the write-only `clarification_answers` channel (old checkpoints through the checkpoint-schema owner under strict serde); amend the event-aggregation custom-write clause and the clarification-answers-grounding rejected-option rationale, whose premise is false; mark worker-process sections 2.2 and 2.7 historical. Ties: R2-F16, R4-F19, R2-F22.
- D18 (AD.17/S44): journal semantics. Recommended: the recovery-deadline CHECK applies only to dispatchable rows (`result_status IN ('accepted_not_applied','queued')`); `permission_logs` is the single decision record (TPM P06.S16); decline R3-F17 and fold its three validators into `GraphActionReceipt.matches()`. Amend control-action-leases. Ties: R3-F18, R3-F17.

Routine choices, recorded in the owning Step's ledger note rather than an ADR:

- D19 (DL.13/S26, owner O11): fold-and-delete `database/admin.py`. `migrate` duplicates `vaultspec-a2a migrate` and skips the migration lock (`database/admin.py:70-74` against `database/migrate.py:93-96`): delete. `snapshot` and `restore` duplicate the dashboard-owned snapshot and rollback (`cli/service.py:20-23`, `desktop/migration.py:357-364`): delete, because folding would create a second snapshot authority. `clear` has no consumer: delete. `migrate --fix` (WAL truncate plus VACUUM, kept administrative by `database/session.py:70-80`) folds into `vaultspec-a2a migrate --compact`, run after `_apply_mutations` on the quiesced stores, which `migrate_stores` already guards with a zero-timeout `BEGIN IMMEDIATE` (`desktop/migration.py:191-213`); a blocked checkpoint is a failed stage `COMPACT`. If O11 is declined, keep the module but still delete its duplicate `migrate`.
- D20 (AD.18/S45): record curation pass through `vaultspec-curate`: reject or supersede decoupled-mockllm, process-and-workspace-management and domain-logic-extraction; accept observability-telemetry-integration with corrections; fix the database-migration-framework heading; settle ecosystem-artifact-lifecycle and service-lifecycle-architecture-container-api-boundary; correct the WebSocket wording in the event-aggregation, worker-process, service-lifecycle and orchestration-topology ADRs; change the `.mcp.json` UI servers through `vaultspec-core spec mcps`. The owner authorizes each acceptance.
- D21: contract events go out in two batches under the `2026-07-14-a2a-edge-conformance-adr` R6 lockstep discipline. CE1 at W02 close: run-start statuses and responses, clarification 409 and 503, respond 422s, the `last_sequence` correction, narrowed `eligible_providers`, the document-gate refusal, unpublished `/internal`, and the additive `migrate --compact`. CE2 at W05 close: frame bounds, the history clarification shape, snapshot names, typed `degraded_reasons`, the usage read, the frame schema and the settlement env rename (alias kept). Precedent: `2026-10-01-stream-resumption-dashboard-contract-event-reference`.
- D22 (DL.12/S29): drop the runtime `websockets` pin after P10 shows no direct runtime holder.
- D23 (L.1/S76): keep both selection digests and document why at both definitions; the checkpointed `model_assignment_digest` binds in-flight runs (`worker/graph_lifecycle.py:479,620,967`).
- D24 (H.8/S95): replace the process-global `git_workspace_mutex` with a per-canonical-path lock local to the provider.
- D25 (owner O6): delete branches `fix/desktop-private-state` and `fix/internal-http-body-limit`.
- D26 (Y.2/S96): delete `StateLayout.receipts_dir` and `snapshots_dir` only if P22 shows the dashboard never writes them.
- D27 (DL.8/S27, owner O4): relocate approved bundle `c0e019c2` to the owner-named evidence home and delete the four unapproved bundles.

## Round 4 - orchestrator residue and backlog

These entries come from the orchestrator-owned round-4 ledgers `tmp/codebase-briefing/stage4/RESIDUE.md` (sites agents found outside their assigned scope) and `tmp/codebase-briefing/stage4/BACKLOG.md` (items not yet assigned to a round). Both ledgers state line numbers are from the reporting branch; re-locate with `rg` before acting. Topics prefixed `r4-` come from RESIDUE; `bk-` from BACKLOG. Entries marked `recorded` are owner rulings or wire-behaviour notices to pass on, not open work items.

### r4-role-grammar-fifth-copy | high | A fifth role-id regex copy uses `.match` with trailing `$`, admitting a newline

Status: open. Type: duplication. `team/team_config.py:49,763,797` (line numbers from the reporting branch) validates role ids with `re.match(..., "$")`, which a trailing `\n` satisfies, unlike `thread.constants.ROLE_ID_PATTERN.fullmatch`. Fold onto the shared pattern with `fullmatch` so this identity-grammar copy cannot admit role ids the canonical grammar rejects. Related to the r1-f4-restated-bounds identifier-grammar cluster but a distinct site not in its evidence.

### r4-seed-transcript-cap | medium | Seed transcript length cap is restated with two different validator syntaxes

Status: open. Type: duplication. `domain_config.py:227` (`le=100`) and `ipc/schemas.py:192` (`max_length=100`) restate the same 100-item cap independently (line numbers from the reporting branch). Fold onto one shared bound constant so the two layers cannot drift. Not previously captured in the audit's bounds clusters (r1-f3, r1-f4).

### r4-catalog-lane-cap | medium | Provider catalog cache restates MAX_PROVIDER_LANES behind a circular import

Status: open. Type: duplication. `providers/_provider_catalog_cache.py:86` hardcodes `max_lanes=128`, restating `MAX_PROVIDER_LANES` because importing it today would be circular (line numbers from the reporting branch). Move the constant to a leaf module both can import, then fold the literal onto it.

### r4-gateway-schema-literals | medium | Gateway schema repeats several numeric bounds as literals

Status: open. Type: duplication. `api/schemas/gateway.py` restates title max 200 twice (`:182`, `:423`); team_preset bound 64 twice against 128 in `ipc/schemas.py:182`; feedback_batch_id 256 also in `ipc/schemas.py:201`; approval_request_id 256 against `MAX_REQUEST_ID_CHARS` 128; permission option id 64 duplicated between `streaming/sse_frames.py:379` and `api/schemas/gateway.py:834` (line numbers from the reporting branch). The approval_request_id/MAX_REQUEST_ID_CHARS mismatch is a real bound disagreement, not just a style duplicate. Fold onto shared bound constants in the bounds-consolidation Step (E.1/S52).

### r4-public-id-control-char-rule | medium | Public-id control-character validation is implemented twice with different rules

Status: open. Type: duplication. `provider_catalog_service._valid_public_id` uses `str.isprintable()` while the schema pattern uses `^[^\x00-\x1f\x7f]+$`; the two admit different character sets (file-local to the reporting branch). Fold onto one validator before either diverges further from the other.

### r4-max-tool-call-chars-test-import | low | A schema-integrity test will import a deleted module once bounds consolidation lands

Status: open - owned by the remediation schedule's later rounds (tied to r1-f3-permission-bounds, Step DL.3/S19). Type: test-integrity. `database/tests/test_schema_integrity.py:52,370-374` (line numbers from the reporting branch) asserts `MAX_TOOL_CALL_CHARS` of 128 by importing from `api/schemas/events.py`, which DL.3/S19 deletes; the test must switch its import to `thread.constants` before that Step lands or it breaks.

### r4-receipt-bound-raw | medium | A receipt-id bound and an ownership join are restated as raw literals in compatibility code

Status: open. Type: duplication. `database/compatibility.py:209` (line numbers from the reporting branch) spells the receipt-id bound as a raw `> 64` instead of `RECEIPT_ID_MAX_LENGTH`; `:217-224` restates the writer/journal ownership join that `database.thread_owned_by` already encodes. Fold both onto their named helpers.

### r4-degraded-reasons-residue | medium | Degraded-reason helpers and typing need to move/narrow outside the already-tracked ownership split

Status: open - decision pending (ties to r2-f11-degraded-reasons, Step M.4/S61; D17). Type: duplication. `thread/snapshots.py`'s `finalize_snapshot_replay_status` and `classify_transcript_availability` need to move to `control/` so the `CHECKPOINT_MISSING` append goes through `mark_degraded`; `ipc/schemas.py:369` and `database/thread_repository.py:892,919` type degraded reasons as `list[str]` and should narrow to `DegradedReason`; `worker/state_projection.py:774-791` passes `.value` instead of the enum (line numbers from the reporting branch). The `control/_permission_response_contract.py:62-65` and `control/team_service.py` sub-items in the same residue note are already tracked as r4-f25-options-decode and r4-f17-actionable-permissions and are not repeated here.

### r4-acp-test-peer-inline-params | medium | ACP permission-request and initialize-result params are hand-built inline across many test files

Status: open. Type: duplication. `session/request_permission` params are built inline at `test_acp_callback_ownership.py:321`, `test_acp_permission_option_ids.py:60,76`, `test_kimi_permission.py:70,225`, `test_project_confinement.py:115`; client-side request writes repeat in `test_kimi_handshake_live.py:50`, `test_acp_migration_surface.py:61,123,225,255`, `test_acp_authoring_bridge.py:160,182`, `test_launcher_confinement.py`, `test_acp_fs_read_limits.py:286`; `initialize` result literals repeat in `test_acp_model_selection.py:153-226`, `test_claude_binary_identity.py:372` (line numbers from the reporting branch). Distinct from r6-f23-acp-fixtures' evidence set; needs its own ACP test-peer helper.

### r4-catalog-test-support-residue | medium | Catalog test support has its own picker, an undeclared path constant and a repeated schema-version literal

Status: open. Type: duplication. `service_tests/test_provider_condition_live.py:127-190,244` keeps its own billable-lane picker by design; `schema_version: 1` is a repeated literal in `api/tests/test_run_selection_schema.py:22` and `providers/tests/test_factory.py:468`; the `/v1/provider-catalog` path has no production constant (line numbers from the reporting branch). Distinct sites from r6-f7-catalog-selection's evidence.

### r4-native-command-catalog-write-only | medium | The ACP native-command advertisement path has no reader, only a writer

Status: open (C11b). Type: dead-code. Production only writes `AcpNativeCommandCatalog` (`providers/_acp_protocol.py` ~:131, ~:503-528, ~:594-596; `providers/_acp_native_commands.py` et al.; `active_native_control_targets` registry - line numbers from the reporting branch). Candidate for deletion: `AcpNativeCommandCatalog`, `NativeCommandAvailability`, `NativeCommandDisposition` (`_acp_types.py`), `AcpSessionContext.native_command_catalogs`/`native_commands_for`, `MAX_NATIVE_COMMAND_NAME_LENGTH`, `MAX_SESSION_COMMAND_CATALOGS`, `--advertise-commands` (`testing/acp.py` ~:247, ~:388-395), `providers/tests/test_acp_command_advertisements.py`, and the catalog assertion in `providers/tests/test_resource_lifetimes.py` ~:86. Distinct from r4-f35-native-control's invocation-path evidence; sequence after H06/H07 merge (both touch `_acp_types.py`).

### r4-execution-state-projection-suppression-stale | low | A pylint suppression on ExecutionStateProjection is now unnecessary

Status: open (Y01). Type: doc-drift. `ExecutionStateProjection`'s `pylint: disable=too-many-instance-attributes` becomes unnecessary once D7's project-wide R0902 disable lands (file-local to the reporting branch); remove the stale per-class suppression when D7 is applied.

### r4-eviction-outside-armed-desktop | high | Worker-port eviction fires on a URL mismatch alone, contradicting the ADR's owner-authorized-desktop rule

Status: open - decision pending (ties to r7-f1-bearer-disclosure, Step FX.5/S15). Type: decision. `control/_worker_health.py:627-684` `_shared_worker_port_clear` (line numbers from the reporting branch) evicts whenever `gateway_url` mismatches, but the governing ADR restricts eviction to an owner-authorized desktop gateway. Options: (a) gate eviction on desktop-armed plus owner-authorized state before any URL-mismatch clear; (b) keep URL-mismatch eviction and amend the ADR to permit it. Recommended: (a), folded into FX.5/S15 alongside the bearer-disclosure fix.

### r4-oauth-token-channel-retired-consumer | medium | The oauth_token channel's only consumer, the headless container, is retired

Status: open - decision pending (provider-binary-policy D4). Type: decision. The `oauth_token` channel's consuming headless-container path was retired by the native-only remediation (file-local to the reporting branch). Options: (a) drop the channel and its plumbing now that no consumer remains; (b) keep it dormant for a future consumer. Recommended: (a), owner call.

### r4-compose-wording-pass3-residue | low | A further batch of ADRs still carries Compose-scoped wording

Status: open. Type: doc-drift. `2026-07-15-agent-harness-provisioning-adr:174`, `2026-10-04-workspace-root-authority-desktop-native-admission-adr`, `-desktop-workspace-boundary-adr`, `2026-08-05-served-capability-contract-adr`, `2026-07-17-kimi-provider-adr`, and `2026-07-17-tool-cores-adr` still name the retired Compose profile (line references from the reporting branch, document-local); `2026-07-24-codebase-health-adr` also overlaps `2026-07-19-codebase-health-adr`, a separate naming-collision worth resolving in the same pass. Distinct ADR set from the BACKLOG Pass-3 list (bk-compose-wording-pass3-adrs).

### r4-agent-id-run-id-bound-mismatch | high | Published-contract bound mismatches between agent_id, role grammar and RelayCall.run_id

Status: open - decision pending. Type: contract-drift. `agent_id`'s max length (128) exceeds the role grammar's 63-char bound though both describe the same published identifier contract; `RelayCall.run_id`'s 160-char bound exceeds the run-id grammar's bound too (file-local to the reporting branch). Options: (a) narrow the looser bound to match the grammar; (b) widen the grammar to match the looser bound and republish. Recommended: (a), since the grammar is the validating authority; fold into the bounds-consolidation Step (E.1/S52).

### r4-dispatch-id-bound-mismatch | medium | dispatch_id's declared bound disagrees with its design-draft bound

Status: open - decision pending. Type: contract-drift. `dispatch_id` is bounded at 128 in the shipped schema against 64 in the design draft (file-local to the reporting branch); unlike r4-agent-id-run-id-bound-mismatch this is pre-publication, lowering urgency. Options: (a) adopt the draft's 64; (b) adopt the shipped 128 and update the draft. Recommended: (a) before the draft is finalized.

### r4-codex-test-only-seams | medium | Codex app-server client carries test-only seams, a module lacks __all__, and packaging docs name a deleted check

Status: open. Type: dead-code. `_CodexAppServerClient._process`/`_reader_task`/`_stderr_task` (`providers/_codex_app_server_client.py` ~:166-181) exist only for tests; `_acp_model_state.py` lacks `__all__`, against the project's public-API-exposure convention; `packaging/README.md:83` names a lifecycle check that no longer exists (line numbers from the reporting branch). None of these sites appear in r3-f19-test-only-methods' evidence.

### r4-terminal-settlement-residue | medium | Terminal settlement is re-derived inline outside its three already-tracked copies

Status: open - decision pending (ties to r3-f7-terminal-settlement, Step A.2/S65). Type: duplication (A02). `control/terminal_settlement.py` ~:146-151 writes a repair value inline that belongs in `thread/repair_policy.py` (A03 must own `control/terminal_settlement.py`); `control/dispatch.py` ~:396 `_refuse_incompatible_authority` and ~:438 `_refuse_missing_project` partly repeat settlement; `recovery_authority.py` ~:227 duplicates a queue refusal (line numbers from the reporting branch). None of these files/lines appear in r3-f7's evidence. Recommended: route all three through `settle_terminal`.

### r4-resume-value-residue | medium | Resume-value helpers are duplicated outside the already-tracked codec split

Status: open - decision pending (ties to r4-f22-resume-codecs, Step C.5/S103). Type: duplication (C05). `control/verdict_subscriber.py` ~:129 `_verdict_resume_payload` duplicates `ApprovalVerdict.as_resume_value()`; `worker/state_projection.py` ~:96 `answered_request_id` duplicates the private `_named_request` in `thread/resume_values.py` (line numbers from the reporting branch). Recommended: fold the first at merge with C07; make `_named_request` public and migrate the second caller.

### r4-per-run-registries-residue | medium | Per-run registries exist beyond the already-tracked token/catalog-store pair

Status: open - decision pending (design call, lock-coupled; ties to r3-f25-run-registry, Step Y.1/S106). Type: duplication (Y04). `worker/_executor_state.py` ~:45-47 keeps three per-thread dicts plus ~:80 `RunControlRegistry._controls`; `worker/authoring_binding.py` ~:55 `_fetch_locks` is a fourth (line numbers from the reporting branch). None of these appear in r3-f25's evidence (`worker/token_store.py`, `worker/catalog_store.py`).

### r4-native-isolation-residue | medium | Native isolation residue: a thrice-copied refusal check and a second hard-coded permission bit

Status: open (H08). Type: duplication. `scripts/build_linux_isolation.py` repeats its `S_ISREG` plus nlink refusal three times (~:55, ~:82, ~:113); `desktop/_linux_resolver.py` ~:156, ~:213 hard-codes `0o022` a second time, separate from the `desktop/_linux_helper.py` site r7-f9-native-isolation already cites (line numbers from the reporting branch).

### r4-fixtures-docker-lookup-residue | medium | Docker-lookup is hand-rolled outside the already-tracked fixture resolver, and reserved_port is test-only

Status: open (X01). Type: duplication. `testing/ports.py` ~:90 `reserved_port` is now test-only; Docker lookup is hand-rolled again at `conftest.py` ~:266, `service_tests/test_telemetry_request_privacy.py` ~:68 and `dev/runner.py` ~:146 (line numbers from the reporting branch) - distinct sites from r6-f25-fixture-boundary-test's `service_tests/harness.py:98-105`.

### r4-vault-citations-in-docstrings | low | Code and test docstrings cite vault finding ids, against the code-stands-alone rule

Status: open (R01a/E10). Type: doc-drift. `streaming/tests/test_aggregator.py` ~:1274, ~:1345, ~:1475 cite finding F17; `control/tests/test_terminal_sequence_capture.py:1` cites F19 (line numbers from the reporting branch). Source must not cite the project's own development records; sweep the tree for `R\d-F\d+|\bF\d{2}\b|W\d\d\.P\d\d|ADR|\.vault` in comments and docstrings (Step E10) and strip every hit.

### r4-streaming-residue-hygiene | low | Streaming modules lack __all__, carry a stale pylint disable and a stale middleware docstring

Status: open (R01a). Type: dead-code. `streaming/transformer.py` and `streaming/buffering.py` lack `__all__`; the `pylint: disable` on `EventAggregator`/`EventEmitters` is obviated by the class split (R01d); `telemetry/middleware.py` ~:195 describes a removed WebSocket path (line numbers from the reporting branch).

### r4-stream-resumability-residue | medium | Sequence-seeding failure has no public unseedable signal, and two resumability sites carry stale text

Status: open - decision pending (ties to r2-f20-resumability, Step R.2/S56). Type: decision (R02). Whether a run whose sequence seeding failed should report `stream_resumable=False` needs a public "unseedable" query on `RunSequenceAllocator`, which does not exist today; S01e's `retained_high_water_mark` deep import now sits at `api/_stream_replay.py` ~:21; `streaming/fanout.py:1-21` and `streaming/tests/test_fanout.py:3` carry stale text (line numbers from the reporting branch). Options: (a) add the public query and report `False` on seeding failure; (b) leave `stream_resumable` computed independently of seeding outcome. Recommended: (a).

### r4-replay-digest-stale-comments | low | Two replay-digest comments may now be stale

Status: open (G02). Type: doc-drift. `api/routes/_gateway_run_start.py` ~:277-284 and `api/run_admission.py` ~:140 (`continues_run_id`) carry comments that may no longer match behavior (line numbers from the reporting branch, distinct lines from r3-f22-r1-digest's evidence). Verify and correct at the same pass as DL.6/S24.

### r4-auth-bypass-doc-drift | low | Docs and test comments will go stale once the test-only auth bypass is removed

Status: open - owned by the remediation schedule's later rounds (follows r1-f9-auth-bypass, Step DL.4/S20). Type: doc-drift (E06). `docs/api/modules.rst` ~:136-138, `docs/operations.rst` ~:200-201, a comment in `service_tests/test_pw7_acceptance.py` ~:153-155, and wording in `api/tests/test_progress_allowlist.py:11` describe the bypass (line numbers from the reporting branch); correct all four once DL.4/S20 lands.

### r4-marker-purity-residue | medium | pytest.fail-based prerequisite checks and mismarked "unit" tests extend the marker-purity problem

Status: open - decision pending (ties to r6-f12-marker-hooks and r6-f16-adhoc-skips, Steps FX.11/S16, K.5/S50, K.3/S48). Type: test-integrity (ts-markers). `claude-acp-adapter` availability is checked via `pytest.fail` at `test_acp_catalog_live.py` ~:33,91 and `test_acp_migration_surface.py` ~:203, plus `providers/tests/conftest.py` `installed_acp_adapter`; `test_discovery_unit.py`, `test_authoring_scope_binding.py`, `test_engine_discovery_security.py` and `test_client_reresolve.py` are marked `unit` but start loopback servers, a wrong purity claim; `_installed_vocabulary.py` conflates a missing install with shape drift (line numbers from the reporting branch). Extend `tests/test_prerequisite_rule.py` to catch all of these.

### r4-assignment-residue-hardcoded-strings | medium | Lane names and execution-mode sets are hardcoded or restated outside the tracked factory cluster

Status: open - decision pending (ties to r5-f7-factory-rules, Step L.2/S77). Type: duplication (assign). `conftest.py` ~:423 hardcodes `"antigravity-cli"`; `factory._admit_execution_mode` restates `{"node","binary"}` against `infra_config.py` ~:723; `gateway._modern_frozen_disclosure` and `_RunDispatchResult.frozen` are typed `Any` (line numbers from the reporting branch). Fold the hardcoded strings onto named constants and give the disclosure fields a real type.

### r4-hmac-compare-digest-nonascii-crash | high | hmac.compare_digest raises instead of returning False on a non-ASCII stored digest

Status: open. Type: contract-drift (assign). A stored digest containing non-ASCII bytes makes `hmac.compare_digest` raise instead of returning a safe `False` (file-local to the reporting branch), turning a security-boundary equality check into an unhandled exception path on malformed input. Validate or sanitize the stored digest before comparison, or catch and treat as non-match.

### r4-l07-cancelled | medium | Owner cancelled L07: OpenAI-compatible and Zhipu/Z.ai lanes stay

Status: recorded - owner informed (2026-10-07). Type: decision. The owner ruled "openai, z ai, agy are not dead lanes ... do not drop support for these"; the kept lane set is Codex, Claude, Z.ai, Kimi and Agy. Z.ai is Zhipu's brand. Neither the OpenAI-compatible lane nor Zhipu is retired, superseding the removal direction in r5-f8-unservable-lanes/D3 for those two lanes and the BACKLOG's "OpenAI-compatible hosted lane and Zhipu" removal-schedule note. tool-cores P02.S19-S21/P03.S18 stay with their owning plan.

### r4-cli-subprocess-runner-residue | medium | A CLI subprocess runner is hand-built across four test files beside testing.run_cli

Status: open (S08). Type: duplication. `cli/tests/test_cli_live.py` ~:136 `_run_cli`, `cli/tests/test_desktop_serve.py` ~:44 `_run_cli`, `tests/gateway_boot.py` ~:135, ~:521 (hand-built migrate argv; `_MIGRATE_MODULE` duplicates `utils.runtime_exec.CLI_MODULE`), `desktop_tests/test_ownership_prerequisites.py` ~:81, ~:123, ~:235 (`_CLI_MODULE`), and `api/tests/test_active_run_discovery_live.py` ~:77 (line numbers from the reporting branch) all re-implement the CLI subprocess runner. Fold onto `testing.run_cli`.

### r4-sqlite-only-residue-d1 | medium | SQLite-only residue sites beyond r3-f12-postgres's evidence, pending D1

Status: open - decision pending (D1). Type: dead-code. `.env.example` ~:176-190 still carries a Postgres block; `control/infra_config.py:61-96` `_synchronous_url`/`_SYNC_DRIVERNAMES` has no production consumer after `admin.py` is removed, only `database/tests/_backends.py` ~:100; `control/tests/test_storage_paths.py:202` and the remainder of `control/tests/test_sync_url_derivation.py` carry Postgres-era docstrings (line numbers from the reporting branch). Clean up once D1 accepts SQLite-only.

### r4-compaction-followup-decision | medium | migrate --compact does not reach the checkpoint store or custom dev database URLs

Status: open - decision pending (follows D19). Type: decision. The checkpoint store is not compacted by `migrate --compact`; a custom `VAULTSPEC_A2A_DATABASE_URL` dev store cannot be compacted at all (file-local to the reporting branch). Options: (a) extend `--compact` to the checkpoint store and support custom URLs; (b) document both as known gaps. Recommended: (a) for the checkpoint store at minimum, since it is part of the same durable state D19 already targets.

### r4-stategraph-inline-subprocess-probe | low | A StateGraph is built inline inside a subprocess probe string

Status: open - owned by the remediation schedule's later rounds (folds into r6-f11-stategraph-boundary, Step K.4/S49). Type: duplication (K10b). `streaming/tests/test_public_stream_ingest.py` ~:213-235 (line numbers from the reporting branch) constructs a `StateGraph` as inline source inside a subprocess probe string, a site not in r6-f11's evidence and a notably fragile pattern beyond ordinary duplication.

### r4-document-approval-request-literal | medium | The "document_approval_request" string is a repeated literal with no shared constant

Status: open (C07). Type: duplication. The literal `"document_approval_request"` recurs without a shared constant at `control/event_handlers.py` ~:829,844, `streaming/_interrupt_projection.py` ~:46,167, `thread/snapshots.py` ~:97,108,179, `control/projection.py` ~:333, `graph/nodes/phase_gate.py` ~:295, `control/verdict_subscriber.py` ~:160, and a private copy in `database/permission_repository.py` (line numbers from the reporting branch); `settle_verdict_dispatch_receipt` also filters pending rows in Python instead of SQL. `test_verdict_subscriber_live.py` ~:595 seeds gate rows under a non-proposal id, worth fixing in the same pass.

### r4-wire-behaviour-notices | medium | Wire-behaviour changes the dashboard must be told about

Status: recorded - owner informed. Type: contract-drift. Four behavior changes ship or are planned: the permission description cap moves from 512 to 4096; a plan-approval response with no valid options now reports `approval_status: null` instead of a fabricated value; undeclared `incompatible_execution_authority_*` strings are no longer emitted; `DispatchRequest.model_assignment` now carries `provider_id`, and accepted-action payloads persisted before that upgrade are refused as incompatible. These extend the bound work in r1-f3-permission-bounds and the Round-2/3 "Assignment" residue; recorded here for dashboard-lockstep tracking per the edge's mutual-reference discipline.

### bk-compose-era-comments-reword | low | Five Compose-era source comments need rewording to "registry-managed or externally attached"

Status: open. Type: doc-drift. `control/_worker_health.py:507`, `control/config.py:151,371`, `desktop/settlement.py:18`, `control/health.py:834` and `worker/app.py:526` (line numbers from the reporting branch) describe Compose-era lifecycle ownership that no longer applies; reword each to "registry-managed or externally attached."

### bk-compose-profile-legacy-label | medium | control/health.py serves profile="compose" for an unarmed gateway, a legacy label

Status: open - decision pending. Type: decision. `control/health.py:667` (line reference from the reporting branch) serves `profile="compose"` for an unarmed gateway; the label is a leftover from the retired Compose profile and renaming it is a wire change requiring dashboard lockstep. Options: (a) rename to a native-accurate label under the contract-event batching discipline; (b) keep the string and document it as a stable legacy value. Recommended: (a), batched with the next contract-event window.

### bk-upward-imports-layering | medium | Control and utils modules import upward across the layering boundary

Status: open - decision pending (D5 D-04; ties to D5 and r3-f9-repository-layering). Type: contract-drift. `control/health.py:516` and `control/admission.py:43` import `api.schemas.gateway_readiness`; `utils/logging.py:39,420` imports `control` (line numbers from the reporting branch). Both invert the intended dependency direction. Distinct sites from r3-f9's SQL-layering evidence. Recommended default: move the shared readiness shape to a leaf both api and control import, and give utils/logging a narrow control-free hook.

### bk-stop-service-bearer-pid-check | high | cli stop_service sends the attach bearer after only a pid-alive check

Status: open - decision pending (D13 desktop amendment; ties to r7-f1-bearer-disclosure). Type: contract-drift. `cli/service.py:285-305` (line numbers from the reporting branch) sends the attach bearer and capability to a process verified only by a pid-alive check, not the descendant-ownership proof D13 establishes elsewhere. Recommended default: gate the bearer send on the same descendant-ownership check D13 adopts for eviction, before any credential leaves the CLI.

### bk-auto-spawn-worker-bearer-disclosure | high | auto_spawn_worker=False sends the bearer to whatever answers on the port

Status: recorded - owner informed (explicitly out of scope per D13; record only). Type: contract-drift. `control/worker_management.py:331-348` (line numbers from the reporting branch) sends the IPC bearer to whatever process answers when `auto_spawn_worker=False`, without the descendant-ownership check D13 applies to the spawn-and-verify path. The orchestrator ledger marks this record-only and out of scope for the current remediation; no action is requested here beyond this audit entry.

### bk-compose-wording-pass3-adrs | low | A second batch of ADRs needs the Compose-scoped wording pass

Status: open. Type: doc-drift. `2026-07-19-codebase-health-adr.md:96`, `2026-10-01-provider-binary-policy-adr.md:146`, `2026-09-21-workspace-root-authority-compose-provider-boundary-adr` and the proposed `2026-09-22-service-lifecycle-architecture-container-api-boundary-adr` (line/document references from the reporting branch) still carry Compose-scoped wording. Distinct ADR set from r4-compose-wording-pass3-residue's RESIDUE-sourced list; both batches belong to the same reconciliation pass.

### bk-plan-pass3-corrections | low | The remediation plan itself needs a dedup-first restructure and several row corrections

Status: open. Type: doc-drift. The plan needs: the approval line; a dedup-first restructure; absorbed other-plan findings; and row corrections at W01.P02.S04 (linked-proposal wording), W04.P09.S42 (the settings ADR is an amendment, not a new record), H.2 (create_time), E.2 (heartbeat with no ISO fallback), and the writer-reported SP7/SP9/lane-delta/L.3/Z.1 gaps (identifiers as given in the reporting branch's plan). These are plan-document corrections rather than code findings; recorded here per the backlog's own instruction to append them.

### bk-redrive-actions-dead-return | medium | redrive_direct_control_actions and redrive_clarification_actions return values are now unused

Status: open. Type: dead-code. Both functions' return values are unused at their only caller, `api/app.py` (file-local to the reporting branch), so their summary return types may be dead weight. Fold the cleanup into the control-pipeline recovery-owner task.

### bk-thread-models-docstring-stale | low | thread/models.py docstring and openapi.json name a module that moved

Status: open. Type: doc-drift. `thread/models.py:24-25` and `openapi.json:2406` (line numbers from the reporting branch) name `api.schemas.enums`; fix the docstring, then regenerate `openapi.json` in the verification phase.

### bk-thread-constants-docstring-stale | low | thread/constants.py docstring names a module scheduled for deletion

Status: open. Type: doc-drift. `thread/constants.py:32` (line reference from the reporting branch) names `api/schemas/events`, which DL.3/S19 deletes; fix the docstring in the bounds merge or a follow-up, distinct from r1-f3-permission-bounds' bound-mismatch finding at an overlapping line range.

### bk-subscriber-manager-broadcast-dead-sequencedevent | low | SubscriberManager.broadcast still serves a gateway SequencedEvent with no remaining reader

Status: open - owned by the remediation schedule's later rounds (Step R.1/S55; ties to r2-f6-aggregator-split/r2-f9-aggregator-forwarders). Type: dead-code. `streaming/subscribers.py:598-650` (line numbers from the reporting branch) keeps `SubscriberManager.broadcast` serving a gateway `SequencedEvent`; delete it in the relay-split task. Site not previously cited in r2-f6/r2-f9's evidence.

### bk-permission-description-test-pending | low | A persisted-description test is expected to fail until the bounds Step lands

Status: open (ties to r1-f3-permission-bounds, Step E.1/S52). Type: test-integrity. `test_persisted_description_matches_what_the_stream_showed` (file-local to the reporting branch) fails today because the catalog cap is 512 and must equal `MAX_PERMISSION_DESCRIPTION_CHARS`; this is a known, tracked failure, not a hidden one, pending E.1/S52.

### bk-openapi-json-hand-edited | medium | openapi.json was hand-edited for one description instead of regenerated

Status: open. Type: contract-drift. `openapi.json` (file-local to the reporting branch) carries a hand-edited description rather than a regenerated one, risking silent drift from the real schema; regenerate it at the verification phase instead of hand-maintaining it.

### bk-dead-dev-code-symbols | low | Three dev-tooling symbols have no non-default or real caller

Status: open. Type: dead-code. `Target.findings_codes`, `advisory_result(findings=...)` and `dev/__main__.py:128` have no non-default user; `configured_script_imports` (`dev/audit/unreachable_code.py:447`) matches no real `procs.toml` script (line numbers from the reporting branch).

### v3-worker-flush-stranded-events | high | Events buffered during an in-flight cadence flush waited for another run's event

Status: fixed refactor/centralize@05bd5a02. Type: correctness (pre-existing; the scheduling code is identical on `main`). `worker/ipc.py` `_schedule_flush` treated the in-flight cadence flush as the pending one after it had already taken its snapshot, so an event appended during the post armed nothing; a run that parked right after such an event emitted nothing further and its `permission_request` sat in the worker buffer. Live evidence from a service store: a run's events 1-9 persisted at 18:32:37 and its `permission_request` at 18:34:50, released only when the next run's dispatch stirred the bridge. Fix: the finishing cadence flush arms the next one when events remain. Verification: `worker/tests/test_ipc_batch_bounds.py::test_an_event_buffered_during_a_cadence_post_is_delivered_unprompted` red (5s timeout) then green; `service_tests/test_permissions_resume.py` + `test_stream_followup.py` went from 3/8 passed in 746s to 6/8 passed in 222s.

### v3-assignment-agreement-workspace | low | The assignment-agreement service test sited its run outside the desktop workspace boundary

Status: fixed refactor/centralize@75ab6b14. Type: test-integrity. `service_tests/test_dispatch_assignment_agreement.py` sent `tmp_path` as the run workspace while the centralized harness seats a desktop app home whose boundary is `state.workspaces_root`; the catalog read answered 422. The run now uses the harness's own workspace; the test passes (47.8s).

### v3-gateway-history-read-hang | medium | A gateway run-history read hung for the full client timeout under concurrent service load

Status: open; owner: a dedicated investigation after the PV wave (not reproduced in isolation). Type: correctness-risk. In two of three paired runs (`test_permissions_resume.py::test_supervisor_plan_rejection_requires_revision_before_reapproval` then `test_stream_followup.py`), a `GET /v1/runs/{id}/history` never answered within the 300s client timeout, shortly after a gateway "Direct recovery pass failed; the owner will retry" with `sqlite3.OperationalError: database is locked` on `BEGIN IMMEDIATE`. A py-spy dump during a stall showed every gateway and worker thread idle (the wait is at the asyncio level, not a SQLite busy wait). `test_stream_followup.py` alone passes (32.4s).

### v3-pv29-pv40-live-confirmation | medium | PV29 and PV40 reproduce on the centralized tree

Status: open; owner PVB (PV29, PV40). Type: correctness. PV29: `test_supervisor_plan_rejection_requires_revision_before_reapproval` fails in isolation: after the rejection the run stays `input_required` with `approval_status='rejected'` and no fresh pending plan approval. PV40: every `permission_request_created` and `permission_response_applied` journal row in a live service store has `result_status='applied'` with `applied_at` NULL.

### v3-service-tier-environment | info | Service-tier skips and residual failures that are environmental

Status: recorded. Type: environment. Service tier on refactor/centralize@2cb4fdc3: 99 passed, 10 failed, 71 skipped. The 71 skips need a running `vaultspec serve` engine, an opted-in live provider selection, or a Z.ai credential (main skips the same). Four `providers/tests/test_harness_mcp_pinning.py` failures come from the host vaultspec-rag service owning the GPU (`gpu_owner: owned_elsewhere`); thirteen unit-tier vaultspec-rag failures come from the host service (0.5.3) against the unpinned client (0.6.0), and `main` fails them too (DECISIONS Q50).

### v5-openapi-doc-residue | low | Three published-description defects found while regenerating openapi.json

Status: open; owners PVC (403) and PVA (descriptions). Type: contract-drift. Permission-respond serves 403 for document-approval pauses (`control/permission_service.py`) but `openapi.json` does not declare it, on `main` either; the published `AgentSnapshot` description says "`model` carry the real enums" while the field is `model_name: str | None`; the published `ThreadStateSnapshot` description carries developer-facing implementation notes.

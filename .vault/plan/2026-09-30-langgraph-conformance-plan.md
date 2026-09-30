---
tags:
  - '#plan'
  - '#langgraph-conformance'
date: '2026-09-30'
tier: L2
related:
  - '[[2026-09-30-langgraph-conformance-audit]]'
  - '[[2026-07-15-graph-agent-framework-harness-adr]]'
  - '[[2026-03-03-phase-artifact-gates-adr]]'
  - '[[2026-07-14-adr-authoring-orchestration-adr]]'
  - '[[2026-03-04-worker-process-architecture-adr]]'
  - '[[2026-09-05-embedded-runtime-remediation-adr]]'
  - '[[2026-03-10-postgres-dual-backend-adr]]'
  - '[[2026-08-02-control-action-leases-adr]]'
  - '[[2026-03-03-plan-approval-interrupt-adr]]'
modified: '2026-09-30'
body_schema: body-v2
body_hash: 'sha256:0c83e65b514edfee47ba9c5643e2fd7046a6c700f9a10f89285d20f83e0c3fef'
---

# `langgraph-conformance` plan

Fix every finding of the LangGraph conformance review: the critical resume accumulation, the unused research findings, the deprecations and private APIs, the unbounded review and routing loops, and the lower routing, streaming, interrupt and persistence gaps.

## Description

Approved 2026-09-30. Basis: the user, in session on 2026-09-30, after the conformance review reported: "These are all serious issues and gaps and I want you to address them, one by one, iterating through the issues. Fix the deprecations, unlimited review echoes. Focus first on the deprecation and the high research findings miss. The lower fixes are absolutely in scope for this session", then "the new persistent agents are also in scope with their findings. Redelegate these to separate agents please."

The work fixes the findings recorded in `2026-09-30-langgraph-conformance-audit`, in the user's order: the deprecation and private-API items and the unused research findings first, the unbounded loops next, then everything else. The critical resume-accumulation defect is fixed first within its Phase because it breaks ordinary multi-approval turns.

Decision coverage. Each Step restores behaviour an accepted decision already requires, so no new ADR is needed:

- P01 restores the routing, gate and synthesis behaviour of `2026-03-03-phase-artifact-gates-adr`, `2026-07-14-adr-authoring-orchestration-adr` and `2026-07-15-graph-agent-framework-harness-adr`.
- P02 restores the interrupt and resume contract of `2026-03-03-plan-approval-interrupt-adr` and `2026-08-02-control-action-leases-adr`.
- P03 restores the streaming and recovery contract of `2026-03-04-worker-process-architecture-adr`, whose section 2.6 already names `astream`, and the checkpoint-first recovery of `2026-09-05-embedded-runtime-remediation-adr`; `durability="sync"` realises that recovery rather than changing it.
- P04 restores the dual-backend behaviour of `2026-03-10-postgres-dual-backend-adr`.
- P05 is reserved for the version and deprecation sweep's findings.
- P06 drafts amendments for the design-record drift the review found. Those amend accepted decisions and are presented for approval, not applied.

## Steps

### Phase `P01` - Graph routing, research synthesis and state hygiene

The compiled graphs route, gate and synthesise the way their decisions describe, every review and routing loop is bounded, and checkpointed state carries only plain values.

- [ ] `P01.S01` - Feed every research branch's findings into the synthesis model's input; `src/vaultspec_a2a/graph/nodes/worker.py, src/vaultspec_a2a/graph/_compiler_research.py`.
- [ ] `P01.S02` - Write plain strings instead of StrEnum members into checkpointed state and interrupt payloads; `src/vaultspec_a2a/graph/`.
- [ ] `P01.S03` - Drop the deprecated MessageGraph from the local stubs, route set_node_defaults through the typed builder, and name the compiled graph; `typings/langgraph/graph/, src/vaultspec_a2a/graph/compiler.py`.
- [ ] `P01.S04` - Budget the submit-refusal loop per phase and end a spent budget in a typed outcome; `src/vaultspec_a2a/graph/nodes/phase_gate.py, src/vaultspec_a2a/graph/_compiler_research.py`.
- [ ] `P01.S05` - Clear validation errors when a phase advances and bound FINISH-block reroutes to workers that can satisfy the gate; `src/vaultspec_a2a/graph/nodes/supervisor.py, src/vaultspec_a2a/graph/nodes/phase_gate.py, src/vaultspec_a2a/thread/state.py`.
- [ ] `P01.S06` - Route a blocked FINISH through the HARD gate and plan approval, send a rejected plan without a planner back to the supervisor, and bind plan and document verdicts to their request; `src/vaultspec_a2a/graph/nodes/supervisor.py, src/vaultspec_a2a/graph/nodes/phase_gate.py, src/vaultspec_a2a/graph/compiler.py`.
- [ ] `P01.S07` - Refresh the vault index before the supervisor evaluates its gate, and in the research topology; `src/vaultspec_a2a/graph/nodes/supervisor.py, src/vaultspec_a2a/graph/nodes/vault_reader.py, src/vaultspec_a2a/graph/_compiler_research.py`.
- [ ] `P01.S08` - Show the routing refusal on every supervisor re-ask and refuse ambiguous route replies; `src/vaultspec_a2a/graph/nodes/supervisor.py`.
- [ ] `P01.S09` - Reset the loop count on each turn; `src/vaultspec_a2a/worker/graph_lifecycle.py, src/vaultspec_a2a/thread/state.py`.
- [ ] `P01.S10` - Size the superstep backstop to the retry budget, give the submit nodes a transport retry policy, and pin the node config-injection contract with a test; `src/vaultspec_a2a/graph/compiler.py, src/vaultspec_a2a/graph/_compiler_research.py, src/vaultspec_a2a/graph/nodes/_config_contract.py`.

### Phase `P02` - Interrupts and resume

Every pause resumes exactly once with the answer it asked for, however many approvals a turn needs and however often a resume is delivered.

- [ ] `P02.S11` - Stop resume updates accumulating on the parked checkpoint so a second approval or a redelivered resume applies; `src/vaultspec_a2a/worker/executor.py, src/vaultspec_a2a/thread/state.py`.
- [ ] `P02.S12` - Refuse a resume unless the checkpoint is parked on the interrupt it answers; `src/vaultspec_a2a/worker/executor.py, src/vaultspec_a2a/worker/state_projection.py`.
- [ ] `P02.S13` - Re-park instead of raising when a gate receives a stale or invalid answer; `src/vaultspec_a2a/graph/nodes/clarification.py, src/vaultspec_a2a/thread/clarification.py, src/vaultspec_a2a/graph/nodes/worker.py`.
- [ ] `P02.S14` - Key permission answers by request id with one interrupt per node execution, and refuse answers that name no request; `src/vaultspec_a2a/graph/nodes/worker.py, src/vaultspec_a2a/thread/state.py`.
- [ ] `P02.S15` - Resume by interrupt id when several interrupts are pending and let the permission service hold one request per interrupt; `src/vaultspec_a2a/worker/executor.py, src/vaultspec_a2a/control/permission_service.py`.

### Phase `P03` - Execution and streaming

Ingest runs on LangGraph's public stream API with durable checkpoints, drains and cancels truthfully, and sees interrupts and receipts as they happen.

- [ ] `P03.S16` - Propagate cancellation out of ingest and keep a requested drain for runs opened afterwards; `src/vaultspec_a2a/streaming/ingest.py, src/vaultspec_a2a/worker/executor.py`.
- [ ] `P03.S17` - Run ingest and resume with synchronous checkpoint durability; `src/vaultspec_a2a/streaming/ingest.py`.
- [ ] `P03.S18` - Move ingest to LangGraph's public stream modes, dropping the private runtime seat, detecting interrupts in-stream, and firing the application receipt from the first durable checkpoint; `src/vaultspec_a2a/streaming/, src/vaultspec_a2a/worker/_dispatch_receipts.py`.
- [ ] `P03.S19` - Key node boundaries, tool calls, nostream filtering and custom events on the identities LangGraph documents; `src/vaultspec_a2a/streaming/transformer.py`.

### Phase `P04` - Persistence

Both checkpoint backends behave as the dual-backend decision describes, set themselves up safely, and prune only what they understand.

- [ ] `P04.S20` - Give each run its own saver on the shared Postgres pool and prove concurrent use; `src/vaultspec_a2a/database/checkpoints.py, src/vaultspec_a2a/worker/graph_lifecycle.py`.
- [ ] `P04.S21` - Serialize Postgres saver setup across processes; `src/vaultspec_a2a/database/checkpoints.py`.
- [ ] `P04.S22` - Make the Windows selector bridge answer synchronous calls locally, clone on with_allowlist, and release its thread and pool on a failed start; `src/vaultspec_a2a/database/checkpoints.py`.
- [ ] `P04.S23` - Mark the desktop SQLite saver set up after schema validation; `src/vaultspec_a2a/database/checkpoints.py`.
- [ ] `P04.S24` - Guard settled-history pruning on saver support and schema version, and import the checkpoint channel names; `src/vaultspec_a2a/database/checkpoint_retention.py, src/vaultspec_a2a/thread/checkpoint_evidence.py, src/vaultspec_a2a/thread/snapshots.py`.
- [ ] `P04.S25` - Derive history depth from the tuple already read and report parent ids truthfully after a prune; `src/vaultspec_a2a/control/snapshot.py, src/vaultspec_a2a/control/thread_state_service.py, src/vaultspec_a2a/thread/snapshots.py`.
- [ ] `P04.S26` - Enable strict checkpoint deserialization on both savers; `src/vaultspec_a2a/database/checkpoints.py`.
- [ ] `P04.S27` - Retire the SQLite-only checkpoint backfill or run it on both backends; `src/vaultspec_a2a/database/migrations/__init__.py, src/vaultspec_a2a/api/app.py`.

### Phase `P05` - Version and deprecation sweep

No deprecated LangGraph-family API is called from the repository, and the locked versions are current or knowingly held.

- [x] `P05.S29` - Bump vaultspec-core to 0.3.2 and vaultspec-rag to 0.5.3 with no upper bound, and apply the framework's migrations and builtin upgrade; `pyproject.toml, uv.lock, .vaultspec/, prek.toml`.
- [x] `P05.S30` - Launch the vaultspec-core and vaultspec-rag MCP servers as their new releases serve them: renamed core server, declared new core tools and their egress, rag read-only surface and root pinning; `src/vaultspec_a2a/providers/_harness_mcp_registry.py`.

### Phase `P06` - Design records

The decisions that describe the graph match the graph, through amendments presented for approval.

- [ ] `P06.S28` - Draft amendments for the design-record drift the review found and present them for approval; `.vault/adr/`.

## Parallelization

P01, P02, P03 and P04 run in parallel, each owned by one executor in its own git worktree. File ownership is disjoint by Phase except `src/vaultspec_a2a/graph/nodes/worker.py` (P01 owns the prompt builder, P02 the permission callback), `src/vaultspec_a2a/thread/state.py` (P01 owns routing fields, P02 the receipt channels) and `src/vaultspec_a2a/worker/executor.py` (P02 owns resume, P03 drain and ingest); those are merged by the orchestrator. Executors commit one Step per commit and do not edit `.vault/`; the orchestrator logs, closes Steps and merges. P04.S26 (strict msgpack) runs after P01.S02 and P04.S22 are merged. P05 and P06 run after the sweep reports and the fix Phases merge.

## Verification

- Every new test fails on the code before its Step and passes after, against real graphs, real checkpointers and real subprocesses.
- Two approvals in one worker turn and a redelivered resume both complete through the real `Executor`.
- A research run's synthesis input carries every branch's findings.
- A refusing submitter, a blocked FINISH and a rejected plan each end in a bounded, typed outcome rather than `GraphRecursionError`.
- No production import from `langgraph._internal` remains except where a Step records why, and a deprecation-warning sweep over the graph, streaming and worker suites reports none from the repo's call sites.
- The full unit gate with Postgres and `just ci` pass, and a final integrated review passes.

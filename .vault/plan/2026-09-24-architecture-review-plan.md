---
tags:
  - '#plan'
  - '#architecture-review'
date: '2026-09-24'
tier: L2
related:
  - '[[2026-07-15-graph-agent-framework-harness-adr]]'
  - '[[2026-03-03-phase-artifact-gates-adr]]'
  - '[[2026-03-03-plan-approval-interrupt-adr]]'
  - '[[2026-03-03-blackboard-content-mounting-adr]]'
  - '[[2026-03-04-worker-process-architecture-adr]]'
  - '[[2026-08-02-control-action-leases-adr]]'
  - '[[2026-08-05-served-capability-contract-state-truthfulness-adr]]'
  - '[[2026-07-14-a2a-edge-conformance-adr]]'
  - '[[2026-02-25-llm-context-provider-abstraction-adr]]'
  - '[[2026-08-02-llm-context-provider-abstraction-acp-v1-client-wire-adr]]'
  - '[[2026-07-15-agent-harness-provisioning-adr]]'
  - '[[2026-07-17-tool-cores-adr]]'
  - '[[2026-08-03-current-project-binding-adr]]'
  - '[[2026-07-19-observability-lanes-adr]]'
  - '[[2026-03-20-service-lifecycle-architecture-adr]]'
modified: '2026-10-08'
body_schema: body-v2
body_hash: 'sha256:439b0ff701837460afa758c78867c86e34081c6d21185d8fa5fc017ea2d58507'
---

# `architecture-review` plan

Upgrade the LangGraph family, enroll the graph layer in LangGraph 1.2 primitives, and fix the major findings of the architecture review.

## Description

Approved 2026-09-24. Basis: the user's instruction in the review session of 2026-09-24 to bump the LangGraph dependencies to the latest version, enroll the codebase in the newer LangGraph features, and then enumerate and fix all of the major architectural bugs and issues identified, using subagents where appropriate with the orchestrator as principal coder.

Scope is the high and medium defect findings of `2026-09-24-architecture-review-audit`, measured against `2026-09-24-architecture-review-research`, plus the upgrade and enrollment. Each Step restores an accepted decision or closes a defect within it; no Step makes a new costly decision. Governing decisions by Phase: `P01` and `P02` by `2026-07-15-graph-agent-framework-harness-adr`, `2026-03-03-phase-artifact-gates-adr`, `2026-03-03-plan-approval-interrupt-adr`, `2026-03-03-blackboard-content-mounting-adr` (P01.S04 restores its section 2.1), and `2026-03-04-worker-process-architecture-adr`; `P03` by `2026-08-02-control-action-leases-adr` (P03.S15 restores its breaker rule), `2026-08-05-served-capability-contract-state-truthfulness-adr`, and `2026-07-14-a2a-edge-conformance-adr` R6; `P04` by `2026-02-25-llm-context-provider-abstraction-adr`, `2026-08-02-llm-context-provider-abstraction-acp-v1-client-wire-adr`, `2026-07-15-agent-harness-provisioning-adr`, `2026-07-17-tool-cores-adr`, and `2026-08-03-current-project-binding-adr`; `P05` by `2026-07-19-observability-lanes-adr`.

Coverage assessment: the dependency bump stays inside the LangGraph 1.x major and is a routine update within settled constraints, so no ADR is added for it. The following audit items are decisions, not defects, and are out of scope until the user decides them: A2A protocol capability (`no-a2a-protocol`, which would reverse the 2026-07-15 amendment to `2026-02-26-protocol-ecosystem-bridge-adr`), the busy-run continuation and multitask model beyond the typed refusal of P03.S14, persisted compaction and context-window policy, the default Claude binary and provider-session resumption policy beyond the single-resolver consistency of P04.S26, a unified durable permission model and decision log, and a durable per-run event log. `DeltaChannel` is not adopted: it is beta and its write-chain dependency conflicts with the pruning of P01.S08.

Several findings are also owned by open Steps of other plans, chiefly `2026-09-05-embedded-runtime-remediation-plan` (W02.P04.S16-S18, W02.P05.S23-S24, W04.P09.S46) and `2026-08-02-llm-context-provider-abstraction-plan`. This plan lands the defect fix; an owning Step is closed only when its own full scope is met, and the ledger records any partial landing.

`P06` was added 2026-10-01 on the user's continuation request for the remaining issues after the plan merged. It takes only the open findings of the execution and plan-close review that restore an accepted decision without making a new one: P06.S33 restores the retry rule of `2026-08-02-control-action-leases-adr`, P06.S37 and P06.S38 its lease and breaker rules, P06.S34, P06.S39 and P06.S42 fall under `2026-03-04-worker-process-architecture-adr`, and P06.S35, P06.S36, P06.S40, P06.S41 and P06.S43 under the provider decisions listed for `P04`. Findings that need a decision stay with the user: the continuation model, persisting before terminal fan-out, the Claude permission posture, the provider-binary policy and durable stream resumption.

## Steps

### Phase `P01` - LangGraph 1.2 upgrade and feature enrollment

The LangGraph family runs at its latest release and the graph layer uses the 1.2 node, channel, runtime, and drain primitives instead of hand-built equivalents.

- [x] `P01.S01` - Bump the LangGraph family, langchain-core, langchain-openai, langsmith, and langgraph-sdk to their latest releases and raise the declared floors to the APIs the code uses; `pyproject.toml, uv.lock`.
- [x] `P01.S02` - Widen the typed graph builder to the LangGraph 1.2 node options and declare destinations on every Command-returning node; `src/vaultspec_a2a/graph/compiler.py, src/vaultspec_a2a/graph/nodes/`.
- [x] `P01.S03` - Put model-calling nodes under node-level TimeoutPolicy and jittered RetryPolicy defaults and reconcile the graph-wide step timeout and stall watchdog with them; `src/vaultspec_a2a/graph/_compiler_retry.py, src/vaultspec_a2a/graph/compiler.py, src/vaultspec_a2a/streaming/ingest.py`.
- [x] `P01.S04` - Stop checkpointing mounted vault content by recomputing it per invocation instead of carrying it in a tracked channel; `src/vaultspec_a2a/graph/nodes/vault_reader.py, src/vaultspec_a2a/thread/state.py, src/vaultspec_a2a/graph/nodes/worker.py`.
- [x] `P01.S05` - Carry run identity in a typed LangGraph Runtime context passed on ingest and resume; `src/vaultspec_a2a/graph/, src/vaultspec_a2a/worker/graph_lifecycle.py, src/vaultspec_a2a/worker/executor.py`.
- [x] `P01.S06` - Drain in-flight runs at a superstep boundary with RunControl on worker shutdown so a restart resumes a checkpoint instead of a torn node; `src/vaultspec_a2a/worker/executor.py, src/vaultspec_a2a/streaming/ingest.py, src/vaultspec_a2a/worker/app.py`.
- [x] `P01.S07` - Drop langsmith nostream-tagged model events from the relayed stream; `src/vaultspec_a2a/streaming/transformer.py`.
- [x] `P01.S08` - Prune superseded checkpoints of settled runs while keeping each run's latest checkpoint; `src/vaultspec_a2a/database/checkpoints.py, src/vaultspec_a2a/control/event_handlers.py`.

### Phase `P02` - graph-layer defects

Graph routing, human-in-the-loop resume, crash recovery, and per-run isolation behave as the accepted gate, interrupt, and worker decisions require.

- [x] `P02.S09` - Route blocked HARD phase gates and unparseable supervisor output back to the supervisor under a bounded re-ask counter; `src/vaultspec_a2a/graph/nodes/supervisor.py, src/vaultspec_a2a/graph/compiler.py`.
- [x] `P02.S10` - Honour each preset recursion limit on served runs and bound document review loops per phase, with a working pipeline_loop early exit; `src/vaultspec_a2a/worker/executor.py, src/vaultspec_a2a/thread/executable_graph.py, src/vaultspec_a2a/team/team_config.py, src/vaultspec_a2a/graph/_compiler_research.py, src/vaultspec_a2a/graph/_compiler_topologies.py, src/vaultspec_a2a/graph/nodes/phase_gate.py`.
- [x] `P02.S11` - Bind a tool-permission approval to a fingerprint of the exact tool call and re-park when a replayed turn asks for a different call; `src/vaultspec_a2a/graph/nodes/worker.py, src/vaultspec_a2a/control/permission_dispatch.py, src/vaultspec_a2a/control/permission_service.py`.
- [x] `P02.S12` - Resume an interrupted run from its checkpoint through receipt evidence instead of replaying its input; `src/vaultspec_a2a/worker/state_projection.py, src/vaultspec_a2a/worker/executor.py`.
- [x] `P02.S13` - Give each invocation its own model instances and move rule loading and engine discovery off the worker event loop; `src/vaultspec_a2a/worker/graph_lifecycle.py, src/vaultspec_a2a/worker/executor.py, src/vaultspec_a2a/worker/_authoring_close.py, src/vaultspec_a2a/graph/nodes/worker.py, src/vaultspec_a2a/graph/nodes/supervisor.py, src/vaultspec_a2a/graph/_compiler_research.py, src/vaultspec_a2a/authoring/client.py`.

### Phase `P03` - run, session, and edge robustness

Busy runs, worker backpressure, event streams, checkpoint storage, the event bridge, and container shutdown fail typed and bounded instead of wedging.

- [x] `P03.S14` - Refuse a follow-up on a busy run with a typed conflict that installs no writer; `src/vaultspec_a2a/thread/message_policy.py, src/vaultspec_a2a/control/message_service.py, src/vaultspec_a2a/worker/app.py`.
- [x] `P03.S15` - Split worker refusals by reason and feed the circuit breaker only transport failures and server errors, with a single half-open probe; `src/vaultspec_a2a/control/dispatch.py, src/vaultspec_a2a/control/circuit_breaker.py, src/vaultspec_a2a/worker/app.py`.
- [x] `P03.S16` - Scope the stream database session to the handler so an open stream holds no connection or read transaction; `src/vaultspec_a2a/api/routes/_gateway_read_endpoints.py, src/vaultspec_a2a/api/thread_stream.py`.
- [x] `P03.S17` - Subscribe before reading run status, lead each stream with a snapshot frame, keep the run sequence in the frame body without an SSE id until the stream can resume, and signal backpressure drops; `src/vaultspec_a2a/api/thread_stream.py, src/vaultspec_a2a/streaming/`.
- [x] `P03.S18` - Back the Postgres checkpointer with a sized connection pool; `src/vaultspec_a2a/database/checkpoints.py`.
- [x] `P03.S19` - Bound, serialize, and split worker event batches and protect terminal events from eviction; `src/vaultspec_a2a/worker/ipc.py, src/vaultspec_a2a/worker/state_projection.py`.
- [x] `P03.S20` - Start containers through the owned serve entry with a stop grace period longer than the shutdown budget; `service/docker/prod.Dockerfile, service/docker-compose.prod.yml`.

### Phase `P04` - provider lane security and fidelity

Provider launchers, the Claude and Codex permission posture, native tool scope, credentials, and the ACP wire are confined and faithful on every served lane.

- [x] `P04.S21` - Resolve provider launchers to absolute paths from the service trusted PATH or the capsule, never the agent PATH or working directory; `src/vaultspec_a2a/providers/_factory_commands.py, src/vaultspec_a2a/providers/cli_resolution.py, src/vaultspec_a2a/providers/_subprocess.py`.
- [x] `P04.S22` - Pin the Claude lane permission posture: no ambient setting sources, persona-derived disallowed tools, dontAsk on autonomous runs verified against the reported mode, and allow-once for always options; `src/vaultspec_a2a/providers/_acp_session.py, src/vaultspec_a2a/providers/acp_chat_model.py, src/vaultspec_a2a/graph/nodes/worker.py`.
- [x] `P04.S23` - Scope native read tools to the workspace, stop pre-approving project-addressable rag tools, and scan Codex tool arguments for foreign projects; `src/vaultspec_a2a/providers/_native_read_tools.py, src/vaultspec_a2a/providers/_codex_permission.py, src/vaultspec_a2a/graph/nodes/worker.py`.
- [x] `P04.S24` - Fail closed when a permission callback names an option that was not offered; `src/vaultspec_a2a/providers/_acp_rpc_handlers.py`.
- [x] `P04.S25` - Write refreshed Codex credentials back to their source home under a lock; `src/vaultspec_a2a/providers/_codex_config_home.py`.
- [x] `P04.S26` - Use one Claude binary resolver for catalog discovery and execution and record the adapter and CLI identity each run used; `src/vaultspec_a2a/providers/factory.py, src/vaultspec_a2a/providers/acp_chat_model.py, src/vaultspec_a2a/providers/_acp_session.py`.
- [x] `P04.S27` - Render ACP prompts with roles, speaker names, and tool results through the renderer the Codex lane shares; `src/vaultspec_a2a/providers/acp_chat_model.py, src/vaultspec_a2a/providers/_codex_protocol.py`.
- [x] `P04.S28` - Retain a redacted ACP stderr tail, attach it to provider errors, and log provider session ids per turn; `src/vaultspec_a2a/providers/acp_chat_model.py, src/vaultspec_a2a/providers/_acp_session.py, src/vaultspec_a2a/providers/codex_chat_model.py`.
- [x] `P04.S29` - Pin the harness MCP launch interpreter to the project Python; `src/vaultspec_a2a/providers/_harness_mcp_registry.py`.

### Phase `P05` - context and observability

Transcripts carry real event times, logs are loss-free and correlated, and token accounting keeps what providers report.

- [x] `P05.S30` - Stamp message creation times when messages are produced and project an unknown time instead of the read time; `src/vaultspec_a2a/thread/snapshots.py, src/vaultspec_a2a/graph/nodes/worker.py, src/vaultspec_a2a/graph/nodes/clarification.py, src/vaultspec_a2a/worker/graph_lifecycle.py, src/vaultspec_a2a/api/schemas/snapshots.py, openapi.json`.
- [x] `P05.S31` - Make the JSON log formatter loss-free, UTC, schema-versioned, and redacting, with a context-variable correlation scope; `src/vaultspec_a2a/utils/logging.py, src/vaultspec_a2a/worker/executor.py`.
- [x] `P05.S32` - Keep cache-read, cache-write, and reasoning token counts through turn usage into cost tracking; `src/vaultspec_a2a/graph/nodes/worker.py, src/vaultspec_a2a/thread/models.py, src/vaultspec_a2a/thread/state.py, src/vaultspec_a2a/graph/protocols.py, src/vaultspec_a2a/worker/cost_port.py, src/vaultspec_a2a/database/models.py, src/vaultspec_a2a/database/migrations/versions/`.

### Phase `P06` - residual findings

Close the decision-free findings the plan-close review and its re-review left open, each restoring the accepted decision the finding names.

- [x] `P06.S33` - Retain accepted work on capacity and transport-unreachable refusals instead of marking the dispatch failed; `src/vaultspec_a2a/thread/dispatch_policy.py, src/vaultspec_a2a/control/direct_control_recovery.py`.
- [x] `P06.S34` - Make the worker event client outlast the gateway's worst-case terminal confirmation; `src/vaultspec_a2a/worker/ipc.py`.
- [x] `P06.S35` - Give each parallel research branch its own model instance so no two branches share one provider session; `src/vaultspec_a2a/graph/_compiler_research.py`.
- [x] `P06.S36` - Approve a native floor tool at the autonomous rung only when its path arguments lie inside the bound project; `src/vaultspec_a2a/providers/_acp_rpc_handlers.py, src/vaultspec_a2a/providers/tests/test_kimi_permission.py`.
- [x] `P06.S37` - Scope the breaker's half-open probe to the dispatch that reserved it; `src/vaultspec_a2a/control/circuit_breaker.py`.
- [x] `P06.S38` - State and test the recovery lease rule for a busy worker and re-cover the definite-versus-ambiguous release rule on a surviving verb; `src/vaultspec_a2a/control/direct_control_recovery.py, src/vaultspec_a2a/control/tests/test_direct_control_leases.py`.
- [x] `P06.S39` - Continue a redelivered first ingest that stopped at the input checkpoint instead of refusing it; `src/vaultspec_a2a/thread/checkpoint_evidence.py`.
- [x] `P06.S40` - Attach the stderr tail to the turn-idle deadline error; `src/vaultspec_a2a/providers/acp_chat_model.py`.
- [x] `P06.S41` - Advertise modes from the ACP simulator and refuse an autonomous session whose lane advertises none; `src/vaultspec_a2a/graph/tests/acp_simulator.py, src/vaultspec_a2a/providers/_acp_session.py`.
- [x] `P06.S42` - Reserve shutdown budget for the prune wait and key pending prunes to the app that waits on them; `src/vaultspec_a2a/lifecycle/shutdown.py, src/vaultspec_a2a/control/event_handlers.py, src/vaultspec_a2a/api/app.py`.
- [x] `P06.S43` - Escape setext-style role headings in rendered message content; `src/vaultspec_a2a/providers/_prompt_render.py`.
- [x] `P06.S44` - Probe the container's own hostname in the Compose healthchecks; `service/docker-compose.dev.yml, service/docker-compose.integration.yml, service/docker-compose.prod.yml`.
- [x] `P06.S45` - Reconcile finding statuses that later Steps closed; `.vault/audit/2026-09-24-architecture-review-audit.md, .vault/audit/2026-09-30-langgraph-conformance-audit.md`.
- [x] `P06.S46` - Write absolute Claude permission rule paths with the CLI's absolute anchor so deny and scope rules match the paths they name; `src/vaultspec_a2a/providers/_claude_tool_policy.py`.
- [x] `P06.S47` - Answer a permission response on a busy or saturated run with the same typed status the follow-up verb serves instead of 500 or 502; `src/vaultspec_a2a/control/permission_dispatch.py, src/vaultspec_a2a/api/routes/_gateway_action_endpoints.py`.
- [ ] `P06.S48` - Remove the dead state the residual fixes left behind and flush the replay recorder on every relay transport, re-scoped to HTTP only - 2026-10-06-codebase-remediation-plan's round-1 dead-internal deletes the internal WebSocket relay; `src/vaultspec_a2a/api/internal.py, src/vaultspec_a2a/control/circuit_breaker.py, src/vaultspec_a2a/control/message_service.py, src/vaultspec_a2a/control/_permission_response_contract.py, src/vaultspec_a2a/graph/_compiler_research.py`.
- [x] `P06.S49` - Escape a role heading formed by a whole underlined paragraph and deliver a re-raised signal without awaiting the finalisation reads; `src/vaultspec_a2a/providers/_prompt_render.py, src/vaultspec_a2a/streaming/ingest.py`.
- [x] `P06.S50` - Bring the unused-symbol and unconsumed-export gates back to zero; `src/vaultspec_a2a/`.
- [x] `P06.S51` - Mark an INGEST control action applied when its dispatch proves application, recording it as the thread's last applied action in the same settlement as the follow-up branch does; `src/vaultspec_a2a/control/_event_application.py, src/vaultspec_a2a/control/repair_transitions.py, src/vaultspec_a2a/control/tests/`.

## Parallelization

`P01` runs first and alone, because P01.S01 changes the lock every other Step builds on and P01 reshapes the graph builder that P02 edits. After P01.S01 lands, `P03` and `P04` run in parallel with `P01`/`P02`, each in an isolated worktree owned by one executor: `P03` owns `src/vaultspec_a2a/api/`, `src/vaultspec_a2a/streaming/` (except `transformer.py`, which P01.S07 owns), `src/vaultspec_a2a/control/`, `src/vaultspec_a2a/thread/message_policy.py`, `src/vaultspec_a2a/worker/app.py`, `src/vaultspec_a2a/worker/ipc.py`, the Postgres saver in `src/vaultspec_a2a/database/checkpoints.py`, and `service/`; `P04` owns `src/vaultspec_a2a/providers/` and `src/vaultspec_a2a/workspace/environment.py`. The orchestrator owns `P01`, `P02`, and `P05`, every edit to `src/vaultspec_a2a/graph/nodes/worker.py` (P04.S22 and P04.S23 hand their worker-side wiring to the orchestrator), all `.vault/` records, ledger rows, Step closure, and integration merges. Executors commit code only on their worktree branches; the orchestrator merges each branch, reruns the gates on the merged tree, and closes the Steps.

`P06` runs three executors in isolated worktrees on disjoint ownership. The control executor owns P06.S33, P06.S37 and P06.S38 (`src/vaultspec_a2a/thread/dispatch_policy.py`, `src/vaultspec_a2a/control/circuit_breaker.py`, `src/vaultspec_a2a/control/direct_control_recovery.py` and their tests). The worker executor owns P06.S34, P06.S39 and P06.S42 (`src/vaultspec_a2a/worker/ipc.py`, the checkpoint-evidence reader, `src/vaultspec_a2a/lifecycle/shutdown.py`, the prune scheduling in `src/vaultspec_a2a/control/event_handlers.py`, and `src/vaultspec_a2a/api/app.py`). The provider executor owns P06.S36, P06.S40, P06.S41 and P06.S43 (`src/vaultspec_a2a/providers/` and `src/vaultspec_a2a/graph/tests/acp_simulator.py`). The provider executor also takes P06.S46. The orchestrator owns P06.S35, P06.S44 and P06.S45, every `.vault/` record, and the integration merges.

## Verification

- `just check-python`, `just check-type`, and `just check-shell` pass on the integrated tree.
- `just test-unit` passes in full on the integrated tree, with `UV_PYTHON` pinned to the project Python.
- Each Step lands with a test that fails on the pre-fix code and passes after it, driving the real component (a compiled graph, the FastAPI app with real uvicorn and SQLite, a real subprocess), with no mocks or monkeypatching.
- The locked `langgraph` resolves to the latest release and `pyproject.toml` floors admit no version below the APIs the code imports.
- An integrated review against this plan and its governing decisions passes, and its findings are appended to `2026-09-24-architecture-review-audit`.

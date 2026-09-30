---
tags:
  - '#audit'
  - '#langgraph-conformance'
date: '2026-09-30'
modified: '2026-09-30'
body_schema: 'body-v2'
body_hash: 'sha256:f2a96b72fd54c1bf719552e6815dbfdcfc255b09143ed56b3a8f354f54f10d25'
related:
  - "[[2026-09-24-architecture-review-audit]]"
  - "[[2026-09-24-architecture-review-research]]"
---

# `langgraph-conformance` audit: `LangGraph conformance review`

## Scope

A read-only review of how the service uses LangGraph 1.2.12 and langgraph-checkpoint 4.2, run as five parallel reviews on 2026-09-30 after the architecture-review plan closed: version currency and deprecations, graph construction and topology, interrupts and resume, execution and streaming, and persistence. Each review checked the code against the official LangGraph documentation, the installed library source, and the accepted decisions that describe how the graph was meant to be set up, and proved its claims with real graphs over real checkpointers (probe scripts, not tests). The shipped presets were compiled through the production compiler; persistence was exercised against a live PostgreSQL 16.

## Findings

### research-findings-never-reach-synthesis | high | the research fan-out's findings are stored but never shown to the synthesis model

Researcher branches write only `research_findings` (`src/vaultspec_a2a/graph/nodes/diverge.py:319-333`), and the synthesis node is a plain worker whose prompt is built from persona, rules, anchoring, mounted context, feedback and `messages` (`src/vaultspec_a2a/graph/nodes/worker.py:127-182`). The only production reader of `research_findings` is the submitter's web-URL disclosure check (`src/vaultspec_a2a/authoring/submitter.py:468-500`). The synthesist persona says the findings "have been joined into your context" (`src/vaultspec_a2a/team/presets/agents/vaultspec-synthesist.toml:15-18`) and `2026-07-14-adr-authoring-orchestration-adr` says a join point feeds synthesis. A two-branch run carried both branches' claims in its checkpoint and neither in the synthesis model's input; `src/vaultspec_a2a/graph/tests/test_research_adr.py:266-316` asserts accumulation only.

### unbounded-submit-refusal-loop | medium | a conformance refusal loops writer, review and submit until the recursion limit

`ProposalRevisionRequiredError` routes the submit node back to the writer without spending the review budget (`src/vaultspec_a2a/graph/nodes/phase_gate.py:189-200`), and `review_revisions` resets only on a successful submit (`phase_gate.py:210`). A refusing submitter on `vaultspec-adr-research-mock` produced 16 submit attempts, 16 synthesis turns and 16 `validation_errors` before `GraphRecursionError`, although the router promises a human backstop (`src/vaultspec_a2a/graph/_compiler_research.py:336-341`).

### finish-gates-livelock-to-recursion-limit | medium | a blocked FINISH reroutes forever

`validation_errors` clears only on an explicit `[]` write (`src/vaultspec_a2a/thread/state.py:98-105`) that no production node makes, so a non-empty list blocks FINISH permanently (`src/vaultspec_a2a/graph/nodes/supervisor.py:152-168`); the audit reroute falls back to `workers[0]` (`supervisor.py:101-111,170-188`), which in the shipped star preset cannot satisfy it; both paths reset `supervisor_reasks`, so the re-ask budget never applies. Scripted star runs ended in `GraphRecursionError`.

### finish-reroute-bypasses-hard-gate-and-plan-approval | medium | a blocked FINISH skips the HARD phase gate and plan approval

The blocked-FINISH branch returns early (`src/vaultspec_a2a/graph/nodes/supervisor.py:385-403`), before `_phase_gate_decision` and `_plan_approval_decision` (`:405-418`), contrary to `2026-03-03-phase-artifact-gates-adr` sections 2.2 and 5. A scripted run with no plan reran the exec worker; one with an unapproved plan ran exec with no `plan_approval` interrupt. Star topology only.

### plan-rejection-routes-to-exec-worker | medium | a rejected plan is sent to the coder when the team has no planner

`_select_revision_worker` falls back to `workers[0]` (`src/vaultspec_a2a/graph/nodes/supervisor.py:93-111,521-539`); on `mock-supervisor-human-in-loop` a `rejected` verdict ran the coder.

### hard-gate-reads-stale-vault-index | medium | the supervisor gates on the index from before the worker ran

`vault_index` is refreshed only by the mount node before each worker (`src/vaultspec_a2a/graph/nodes/vault_reader.py:208-230`, wired at `src/vaultspec_a2a/graph/_compiler_topologies.py:219-222`); a plan written by the planner was refused as missing at the next supervisor decision, contrary to the refresh `2026-07-14-adr-authoring-orchestration-adr` requires.

### stale-validation-errors-leak-across-phases | medium | a gate's revision notes stay "active" in every later phase

Notes appended at `src/vaultspec_a2a/graph/nodes/phase_gate.py:284` are never cleared, so anchoring shows them to later workers as active errors (`src/vaultspec_a2a/context/anchoring.py:69-73`); after a research gate requested changes then approved, the ADR author still saw "fix sources".

### enum-members-in-checkpointed-state | medium | nodes write StrEnum members into checkpointed state that a future LangGraph will refuse to load

`PipelinePhase` and `ApprovalStatus` members are written to `pipeline_phase`, `gate_phase`, `review_revisions` keys and interrupt payloads (`src/vaultspec_a2a/graph/compiler.py:238-246`, `src/vaultspec_a2a/graph/nodes/supervisor.py:114-125,517,534,650`, `src/vaultspec_a2a/graph/_compiler_research.py:613-671`, `src/vaultspec_a2a/graph/nodes/phase_gate.py:196-263`). Each load logs "Deserializing unregistered type ... will be blocked in a future version" (`langgraph/checkpoint/serde/jsonplus.py:575-585`), so under strict msgpack a parked run would not hydrate. The persistence review's serde probe used a preset that writes none of these fields and saw no warning.

### blind-supervisor-reask-without-feature | low | the supervisor re-ask repeats the same prompt when no feature is active

The refusal reason reaches the model only through anchoring, which is empty without an active feature (`src/vaultspec_a2a/context/anchoring.py:45-47,62-64`), contrary to `src/vaultspec_a2a/domain_config.py:120-129`.

### ambiguous-supervisor-reply-is-not-refused | low | a reply naming two routes takes the longest match

`_parse_route` (`src/vaultspec_a2a/graph/nodes/supervisor.py:128-138`) routes "The reviewer approved; FINISH" to reviewer and "Do not send to planner; coder next" to planner.

### loop-count-not-reset-per-turn | low | a follow-up turn inherits the previous turn's loop count

`loop_count` (`src/vaultspec_a2a/thread/state.py:225`) is never reset in the per-turn input (`src/vaultspec_a2a/worker/graph_lifecycle.py:936-947`); the comment at `state.py:216-221` is stale against `_loop_route`.

### superstep-backstop-truncates-retries | low | a node retry gets about 30 seconds after a long first attempt

Each attempt gets `run_timeout` equal to the step budget with up to three attempts (`src/vaultspec_a2a/graph/_compiler_retry.py:230-237`), while the Pregel `step_timeout` is budget plus 30 s over the whole retry loop (`src/vaultspec_a2a/graph/compiler.py:958,1037`; `langgraph/pregel/_runner.py:450-487`).

### phase-submit-has-no-retry-policy | low | an engine transport blip fails a run after its human gates passed

The idempotent submit nodes are added without a `retry_policy` (`src/vaultspec_a2a/graph/_compiler_research.py:610-662`).

### compiled-graph-unnamed | low | the compiled graph is named "LangGraph"

`compile()` is called without `name` (`src/vaultspec_a2a/graph/compiler.py:171-176`).

### message-graph-deprecation-in-local-stub | low | the local type stubs re-export the deprecated MessageGraph

`typings/langgraph/graph/__init__.pyi:4` and `typings/langgraph/graph/message.pyi:20-21`; no production code uses it; `StateGraph` over an `add_messages` schema replaces it.

### set-node-defaults-bypasses-typed-builder | low | set_node_defaults skips the typed builder protocol

`src/vaultspec_a2a/graph/compiler.py:958` versus the protocol at `compiler.py:90-119`.

### config-annotation-workaround | low | node config injection depends on a private LangGraph table

`src/vaultspec_a2a/graph/nodes/_config_contract.py` rewrites annotations to match `langgraph/_internal/_runnable.py:168-176,348-358`.

### research-adr-has-no-mount-or-index-refresh | low | the research topology never refreshes the vault index

`src/vaultspec_a2a/graph/_compiler_research.py:479-604` builds no mount nodes, unlike the other topologies (`src/vaultspec_a2a/graph/compiler.py:547-551`).

### cancellation-swallowed-as-failure | medium | cancelling an ingest reports the run FAILED and logs a provider error

`src/vaultspec_a2a/streaming/ingest.py:483` catches `BaseException` without re-raising `CancelledError`, so a task cancel returns `failed` through `_report_provider_failure` (`ingest.py:521-539`) with an ERROR log and an `error` frame. The worker lifespan cancels dispatches when the drain budget ends (`src/vaultspec_a2a/worker/app.py:262-269,379-381`); under plain asyncio cancellation the settle would persist a FAILED terminal for a run the drain contract says is redelivered, and outer timeouts around ingest return silently.

### drain-not-sticky | medium | a run opened after drain was requested is never drained

`Executor.drain` (`src/vaultspec_a2a/worker/executor.py:764-766`) drains the controls that exist at that moment and records no state; `_open_run_control` (`executor.py:745-749`) gives later dispatches an undrained control. A pre-drained `RunControl` stops a run before its first node and leaves it resumable.

### private-runtime-seat | medium | shutdown drain depends on LangGraph's private runtime config key

`src/vaultspec_a2a/streaming/ingest.py:15,167-190` seats `Runtime(control=...)` under `langgraph._internal._constants.CONFIG_KEY_RUNTIME`, which `langgraph/constants.py:44-57` marks private, because `astream_events` v2 drops `control` (`langgraph/pregel/main.py:3743-3780`). The public `astream(..., control=...)` path drains correctly (probe).

### interrupt-detection-post-stream-only | medium | an interrupted run can settle COMPLETED if the post-run state read fails

The interrupted outcome comes only from a post-stream `aget_state` that returns `None` on timeout (`src/vaultspec_a2a/streaming/_interrupt_projection.py:52-91`), after which the outcome stays COMPLETED (`src/vaultspec_a2a/streaming/ingest.py:224-229,491-494`); the stream already carried a root `__interrupt__` chunk that the transformer drops. The `GraphInterrupt` branch at `ingest.py:641-648` is dead.

### receipt-trigger-precedes-checkpoint | medium | the early dispatch application receipt can never fire

`on_graph_started` fires on the root `on_chain_start` (`src/vaultspec_a2a/streaming/ingest.py:463-468`), before any checkpoint exists, and `emit_dispatch_application_receipt` returns silently without one (`src/vaultspec_a2a/worker/_dispatch_receipts.py:31-39`); the receipt reaches the gateway only at settle.

### durability-default-async | medium | checkpoint-first recovery runs on the default async durability

Neither ingest nor resume passes `durability` (`src/vaultspec_a2a/streaming/ingest.py:445-452`), so it is `"async"` (`langgraph/pregel/main.py:2602-2603`), which the durability-mode documentation says may lose a checkpoint on a crash; redelivery pre-flight and the embedded-runtime checkpoint-first authority assume the last completed superstep is durable. Raised by both the streaming and persistence reviews.

### streaming-api-choice | low | ingest uses astream_events v2 rather than the documented stream modes

v2 is unchanged in 1.2 but the documentation directs application code to `astream` stream modes (or the beta v3 events); staying on v2 is what forces the private runtime seat and leaves the gaps below.

### node-boundary-identity | low | any chain event carrying langgraph_node is taken for the node itself

`src/vaultspec_a2a/streaming/transformer.py:429-481,595-598`; a nested runnable produced duplicate statuses and a false plan update, and a subgraph's inner node was reported as a top-level agent. Latent: no production node nests runnables or subgraphs today.

### tool-call-identity-split | low | one tool call is tracked under two identities

Streamed tool-call chunks are keyed by the provider call id and tool events by the LangChain run id (`src/vaultspec_a2a/streaming/transformer.py:157-186,578-589`), leaving a PENDING duplicate.

### nostream-filter-layer | low | the nostream filter is hand-written rather than the documented exclude_tags

`src/vaultspec_a2a/streaming/transformer.py:558-564` versus `astream_events(..., exclude_tags=[TAG_NOSTREAM])`.

### custom-writer-dropped | low | get_stream_writer output is discarded and the custom-event branch has no producer

`src/vaultspec_a2a/streaming/transformer.py:408-426,590-594`; `_translate_custom_event` would fail on non-dict data.

### postgres-pool-serialized-by-saver-lock | medium | one saver uses one pooled connection at a time

`AsyncPostgresSaver._cursor` holds `self.lock` around every statement even over a pool (`langgraph/checkpoint/postgres/aio.py:374`), and one saver serves the process (`src/vaultspec_a2a/database/checkpoints.py:44-83,399-403`), so twelve concurrent writes peaked at one checked-out connection; the comments at `checkpoints.py:32-36,55-59` and `src/vaultspec_a2a/database/tests/test_checkpoint_pool.py:119-148` claim concurrency the test does not prove.

### concurrent-postgres-setup-race | low | two processes running setup on a fresh database collide

Reproduced 12 of 12 (`UniqueViolation` on `pg_type_typname_nsp_index`); gateway and worker both call `setup()` (`src/vaultspec_a2a/api/app.py:725`, `src/vaultspec_a2a/worker/app.py:206`). Shipped start ordering avoids it; scaled workers or a saver migration would not.

### selector-bridge-sync-calls-block-caller-loop | low | the Windows bridge blocks the caller's loop on get_next_version

`src/vaultspec_a2a/database/checkpoints.py:207-213,283-285` forwards the pure per-channel `get_next_version` across threads (137 us versus 1 us, stalls up to 490 ms under load).

### selector-bridge-contract-gaps | low | the bridge mutates itself in with_allowlist and leaks on a failed start

`with_allowlist` swaps the inner saver and returns itself (`src/vaultspec_a2a/database/checkpoints.py:315-324`) instead of a clone, `start()`/`setup()` run outside the `try` (`checkpoints.py:387-397`), and unsupported methods are proxied.

### sqlite-armed-setup-not-suppressed | low | skipping setup on desktop boot does not stop the SQLite saver running its DDL

`AsyncSqliteSaver` runs `setup()` on first use (`langgraph/checkpoint/sqlite/aio.py:360,452,530,583`) despite `src/vaultspec_a2a/database/checkpoints.py:352-357` skipping it.

### direct-sql-retention-unversioned | low | settled-history pruning trusts saver classes, not schema versions

`src/vaultspec_a2a/database/checkpoint_retention.py:89-128` recognises savers by `isinstance`, never checks `checkpoint_migrations`, never prefers an implemented `aprune`, and has no `DeltaChannel` guard (`langgraph/checkpoint/base/__init__.py:387-414`).

### raw-internal-channel-names | low | checkpoint evidence matches LangGraph's private channel names as literals

`src/vaultspec_a2a/thread/checkpoint_evidence.py:117,121`, `src/vaultspec_a2a/thread/snapshots.py:688`, `src/vaultspec_a2a/database/migrations/__init__.py:70`.

### history-depth-and-parent-after-prune | low | the history-depth read costs a second full read and misreports after pruning

`src/vaultspec_a2a/control/snapshot.py:293-302`, `src/vaultspec_a2a/control/thread_state_service.py:298-307`, `src/vaultspec_a2a/thread/snapshots.py:598-609`, `src/vaultspec_a2a/control/projection.py:368,374`.

### checkpoint-serde-strict-ready | low | strict msgpack would work but is not enabled

A real preset run round-trips with zero serde warnings under `LANGGRAPH_STRICT_MSGPACK=true` on all three savers; strict mode is off (`langgraph/checkpoint/serde/_msgpack.py:12-16`). Depends on `selector-bridge-contract-gaps` and `enum-members-in-checkpointed-state`.

### sqlite-only-checkpoint-backfill | low | the boot-time checkpoint backfill runs on SQLite only

`src/vaultspec_a2a/api/app.py:321-322`, `src/vaultspec_a2a/database/migrations/__init__.py:73-113`.

### langgraph-design-record-drift | low | several decision records describe the graph differently from the code

`2026-02-26-event-aggregation-server-side-replay-adr` section 2 and `2026-03-04-worker-process-architecture-adr` section 2.6 name `astream`; `2026-02-27-team-composition-topology-adr` section 2.2 passes `recursion_limit` to `compile()` and allows a null step timeout; `2026-03-03-blackboard-content-mounting-adr` specifies a `mounted_context` field the code replaced; `2026-03-03-phase-artifact-gates-adr` names `workers[0]` as the reroute target and its 2026-07-15 amendment is unimplemented for star; `2026-03-10-postgres-dual-backend-adr` sections 3.3 and 4.2 describe a single-connection saver; the worker-process ADR calls the gateway checkpointer read-only. Three graph records are still `proposed`. The research record's `langsmith:nostream` wording is stale; the tag is `nostream`.

### resume-update-accumulates | critical | a second resume on the same checkpoint fails the run and wedges its state

The resume dispatch sends `Command(resume=..., update={graph_action_receipts, active_graph_action_receipt, agent_descriptors, graph_definition_digest, model_assignment_digest})` (`src/vaultspec_a2a/worker/executor.py:698-715`), four of whose keys are last-value channels (`src/vaultspec_a2a/thread/state.py:228-235`). LangGraph stores `update` writes as pending writes on the interrupted checkpoint and accumulates them for the null task (`langgraph/pregel/_io.py:74-78`, `langgraph/pregel/_loop.py:422-431,932-944`), so any second resume landing on that checkpoint raises `InvalidUpdateError` for `active_graph_action_receipt`, persists the bad writes, and leaves `aget_state` raising on the thread for good. It happens when one worker turn needs a second tool approval, in the permission re-park loop, and when a resume is redelivered after the resumed turn died. It was reproduced through the real `Executor` on the gateway's run and on SQLite and in-memory savers; the same flow without `update=` completes. The documentation reserves `update` for node returns and names `Command(resume=...)` the only input pattern. The failure is reported as a provider failure (`src/vaultspec_a2a/streaming/ingest.py:521-539`).

### parallel-interrupt-resume | medium | the executor cannot resume while more than one interrupt is pending

`_handle_resume` always resumes with a plain value (`src/vaultspec_a2a/worker/executor.py:698-699`), which LangGraph refuses when several interrupts are pending (`langgraph/pregel/_loop.py:910-920`), and the permission service assumes one active request per thread (`src/vaultspec_a2a/control/permission_service.py:454-473,556-590`). Latent: the research fan-out never wires the permission callback (`src/vaultspec_a2a/graph/_compiler_research.py:236-315`), so supervised researchers fall to the autonomous rung instead of a human.

### repark-loop-positional | medium | the permission re-park loop breaks the documented interrupt rules

`src/vaultspec_a2a/graph/nodes/worker.py:765-772` calls `interrupt()` a number of times that depends on a replayed model turn, while resume values match strictly by position per task (`langgraph/types.py:1003-1018`) and the documentation forbids non-deterministic interrupt loops. Safety holds (an answer never reaches the wrong call); liveness does not (a reordered replay skips a valid answer and re-asks), and N approvals replay the turn N times.

### stale-resume-poisons-task | medium | a resume rejected inside a node fails the run for every later resume

A mismatched clarification answer raises `ValueError` (`src/vaultspec_a2a/thread/clarification.py:478-483`, via `src/vaultspec_a2a/graph/nodes/clarification.py:353-357`) and the mock lane raises on an unknown option (`src/vaultspec_a2a/graph/nodes/worker.py:773-779`) after `interrupt()` has recorded the value as the task's resume write, so the correct answer later replays the rejected one and fails the same way.

### unparked-resume-consumed | medium | a resume sent to a checkpoint that is not parked approves the next gate with no human

`_handle_resume` has no parked-check preflight, the plan and document gates do not bind a verdict to a request id (`src/vaultspec_a2a/graph/nodes/supervisor.py:500-508`, `src/vaultspec_a2a/graph/nodes/phase_gate.py:247-256`), and LangGraph hands the value to the first `interrupt()` of the next superstep (`langgraph/pregel/_algo.py:1320-1331`); a probe approved a plan that never parked.

### plan-approval-per-turn | medium | plan approval is requested before every exec turn, not once per session

`2026-03-03-plan-approval-interrupt-adr` sections 2.1 and 2.9 specify a persistent one-time approval; the code clears `approval_status` after each worker turn (`src/vaultspec_a2a/graph/nodes/worker.py:630-634`) and asks again (`src/vaultspec_a2a/graph/nodes/supervisor.py:298-311`). The ADR's resume shape and module paths are also stale.

### unbound-bare-answer | low | a permission answer naming no request is applied to whatever call is asking

`_answers_request` accepts a value with no request id (`src/vaultspec_a2a/graph/nodes/worker.py:716-726`), a compatibility path `2026-08-02-control-action-leases-adr` forbids.

## Recommendations

- Feed research findings to synthesis and bound every review and routing loop before the lower fixes, per the user's ordering.
- Replace the private runtime seat by moving ingest to the documented `astream` stream modes, which also removes the interrupt, receipt, node-identity, nostream and custom-writer gaps.
- Choose `durability="sync"` for ingest and resume; it realises the checkpoint-first recovery the embedded-runtime decision already requires.
- The design-record drift needs amendments to accepted decisions; they are proposed for approval rather than applied.

---
tags:
  - '#audit'
  - '#langgraph-conformance'
date: '2026-09-30'
modified: '2026-10-01'
body_schema: 'body-v2'
body_hash: 'sha256:db079956522b83d5c7ca2a6d95cb57140c1266374d7d2b7c986e013a5ca8dc75'
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

### vaultspec-framework-behind | high | the lock held vaultspec-core 0.2.2 and vaultspec-rag 0.4.25 while the framework moved five releases on

Fixed in P05.S29 and P05.S30. The `<0.3` cap never protected the core MCP lane: `uvx` resolves the latest release, whose executable was renamed to `vaultspec-core-mcp` in 0.2.4, so the registry's `vaultspec-mcp` launch only worked where `uvx` fell back to the project `.venv`'s 0.2.2 binary on PATH, and 0.3.2's read-only launch also serves `search` and `crossref`, which the exact-surface contract refused. Core now installs at 0.3.2 with its migrations (`trigger_split`, `commit_gate`) and builtin upgrade applied, rag at 0.5.3, both without an upper bound; the two open-world core tools are withheld on every lane (`src/vaultspec_a2a/providers/_harness_mcp_registry.py`, `harness_tool_is_withheld`), per the user's decision to serve but never permit them.

### rag-daemon-hosted-ranking-egress | medium | a rag daemon started with a hosted-ranking key sends search candidates off the host

Open. Since vaultspec-rag 0.4.34 a daemon holding `VAULTSPEC_RAG_TYPESAFE_API_KEY` sends candidates to a hosted API for every root it serves, while the registry declares the rag entry `network_egress: False`. The run's launch never supplies the key; the daemon is operator configuration the contract probe cannot see (`tools/list` passes either way). Recommendation: probe the daemon's reported hosted-ranking state before admitting the lane, or record that operator daemons must run without the key.

Decided 2026-10-01 by the user: an operator rule, documented in `docs/operations.rst` ("Semantic search server"); a2a cannot observe or enforce the daemon's ranking mode. Closed as operator configuration.

### rag-client-daemon-version-skew | low | an unpinned rag client and an older running daemon fail every search while the contract passes

Open. The 0.5.3 client requires the exact daemon release and a `readiness` field older daemons do not send; the registry deliberately leaves the rag requirement unpinned, so the next release reaches `uvx` while a running daemon stays behind, and `src/vaultspec_a2a/providers/_mcp_contract.py` verifies only `tools/list`.

### rag-extra-carries-unused-torch | low | the rag extra installs torch that the MCP client never uses

Open. `pyproject.toml` declares `rag = ["torch>=2.4", "vaultspec-rag[mcp]>=0.5.3"]`; the stdio client runs without torch on both releases, rag 0.5.3's own shipped spec dropped `[gpu]` from the MCP install, and hosting a daemon needs the `gpu` extra plus CUDA or MPS rather than torch alone.

### submitter-link-stripping-drift | low | the authoring submitter mirrors core's body-link stripping with regexes core has replaced

Fixed in P07.S38 with a port of core's reader, then replaced in P07.S48 under `2026-10-01-langgraph-conformance-core-runtime-dependency-adr`: vaultspec-core is a runtime dependency and the submitter runs core's own `check_body_links` over the proposal, so its notes are core's diagnostics word for word (`src/vaultspec_a2a/authoring/tests/test_core_body_links.py` checks a real on-disk vault with core's graph). Original finding: `src/vaultspec_a2a/authoring/submitter.py:94-106` reproduced core's link stripping, which 0.3.2 performs with a CommonMark-aware reader (`vaultspec_core/vaultcore/links.py`); edge-case documents may now be judged differently on each side.

### framework-advertises-hosted-search | low | the upgraded framework guidance tells agents to use hosted search this project withholds

Open. The 0.3.2 builtin rules, skills and personas direct agents to `vault search`, `vault adr crossref` and the MCP `search`/`crossref` tools. They do not reach a2a's own agent prompts (`src/vaultspec_a2a/context/rules.py` excludes `*.builtin.md`), but a developer session following them on this repository would send vault text to the hosted API if a key is configured.

Decided 2026-10-01 by the user: no repository rule overriding the builtin guidance; hosted `search` and `crossref` stay served but never permitted, as chosen earlier in the conformance work. Closed as accepted.

### retired-example-trigger | low | an example trigger with a retired event warns on every sync

Open. The `trigger_split` migration moved `.vaultspec/hooks/example-audit-on-create.yaml` to `.vaultspec/triggers/`; its `vault.document.created` event was retired in 0.2.4 and never fired. It is the user's policy source, so it is left for them to delete.

Deleted on 2026-10-01 at the user's request, and `vaultspec-core sync` re-run.

### legacy-empty-checkpoint-fixtures | low | test fixtures seed checkpoints with LangGraph's deprecated helper

Owned by P05.S32. 22 test files call `langgraph.checkpoint.base.empty_checkpoint`, which the library lists among "deprecated utilities used by past versions" and which writes checkpoint format 2 while the runtime writes format 4.

### langgraph-sync-durability-crashes-without-a-checkpointer | medium | synchronous durability kills a run whose graph has no checkpointer

Worked around in P03.S17; upstream defect in langgraph 1.2.12. `langgraph/pregel/main.py:2802-2804` says `durability` has no effect without a checkpointer, then `main.py:3461-3462` awaits `loop._put_checkpoint_fut`, which is only set when a checkpointer exists (`langgraph/pregel/_loop.py:1176-1202`), so the run dies with `AttributeError`. Ingest asks for sync durability only when the graph carries a real `BaseCheckpointSaver` (`src/vaultspec_a2a/streaming/ingest.py`, `_run_durability`). Recommendation: report upstream and drop the guard once fixed.

### custom-stream-writes-cannot-name-their-node | low | a node's own stream write is attributed to the run rather than the node

Open. LangGraph drops the writing node's segment from a custom write's namespace (`langgraph/pregel/main.py:3285-3296`), so `stream_mode="custom"` carries no node identity and a `get_stream_writer()` thought is attributed to the run's agent. No shipped node writes to the stream today; a fan-out whose branches both did would attribute both to the supervisor.

### tool-callback-ordering-is-no-longer-stream-serialised | low | tool frames and stream frames are ordered by real time rather than one queue

Recorded from P03.S18. Tool lifecycle now reaches the emitters from a callback handler concurrently with the stream consumer, so the order between a tool frame and a node-status frame follows real occurrence; each family stays internally ordered and the per-thread sequence stays monotonic. A consumer that assumed the old interleaving would not fail loudly.

### aggregator-test-doubles-still-outnumber-real-graphs | low | seven hand-written graph stubs re-declare the streaming protocol

Open. `src/vaultspec_a2a/streaming/tests/test_aggregator.py` implements the streaming protocol by hand seven times (plus two in `team/` and `worker/`) to force error branches; a shared real error-injecting graph fixture would carry them once and make a protocol change one edit rather than ten.

### star-topology-never-clears-validation-errors | medium | a star run's validation errors now end the run with a typed error rather than clearing

Open from P01.S05. The only production clear of `validation_errors` is the research topology's submit node (`src/vaultspec_a2a/graph/nodes/phase_gate.py`); in star and pipeline the channel is seeded at first ingest (`src/vaultspec_a2a/worker/graph_lifecycle.py`) and nothing writes `[]` again, so once non-empty it blocks FINISH until the new budget raises `SupervisorRoutingError`. Bounded now, but still terminal. Recommendation: decide who clears it in the non-document topologies - the exec worker's own return, or the gate on observing the artifact.

### finish-block-budget-outruns-a-small-recursion-limit | low | the blocked-FINISH budget needs about twelve supersteps to fire

Open from P01.S05. Each blocked FINISH costs three supersteps, so the default `supervisor_finish_block_limit` of 3 needs about twelve before its typed error; a star preset with `recursion_limit` at or below 12 gets `GraphRecursionError` instead. No shipped star preset is that low. Recommendation: validate the ratio at compile time or lower the default.

### strict-msgpack-degrades-rather-than-refusing | low | the enum finding overstated what strict mode does

Correction to `enum-members-in-checkpointed-state`. On langgraph-checkpoint 4.2 the strict path logs a blocked deserialization and yields the plain string (`langgraph/checkpoint/serde/jsonplus.py:598-608`), so the run resumes with a silently changed type rather than failing to hydrate. The fix in P01.S02 stands.

### blocked-finish-reason-is-dropped-when-the-reroute-needs-approval | low | one interleaving hides why FINISH was refused for a pass

Open from P01.S06. `_carrying_finish_block` (`src/vaultspec_a2a/graph/nodes/supervisor.py`) clears `routing_error` when the rerouted decision is a plan-approval request, because the approval branch is selected on `routing_error` being unset; the supervisor sees the refusal a pass later. Recommendation: discriminate that branch on the decision rather than on `routing_error`.

### repark-receipt-never-durable | medium | a resume that only re-parks never writes its receipt into the checkpoint

Open from P02.S11. A resumed run that suspends again does not advance the checkpoint, so its action receipt stays a pending write and `channel_values["active_graph_action_receipt"]` keeps the previous action's. `read_checkpoint_evidence` reads the receipt only from `channel_values`, so it reports the just-applied resume as a prior action, not incorporated; only the resume that completes the node advances the checkpoint. Recovery keyed on incorporation can therefore redeliver a resume that already applied; the P02.S12 preflight now refuses it rather than double-applying, so the symptom is a stuck recovery loop, not a duplicated answer. Recommendation: `_pending_evidence` in `src/vaultspec_a2a/thread/checkpoint_evidence.py` already reads `pending_writes` for interrupt and error; read the receipt channels there too.

### parallel-interrupt-disclosure-stale | medium | an answered parallel interrupt is still disclosed as pending

Open from P02.S15. After one of two fan-out interrupts is answered, `aget_state().interrupts` and every task's `interrupts` still list both, although the answered branch has run: the superstep holding them has not committed, so nothing clears the first. A reloading client re-renders a question already answered, and the resume preflight admits a redelivery of the answered request because it still reads as pending. Telling answered from pending needs the task's resume writes, which the snapshot does not expose. Recommendation: derive pending interrupts from the checkpoint's pending writes (`_task_projections` and the preflight in `src/vaultspec_a2a/worker/state_projection.py`) rather than from the snapshot.

### research-fan-out-has-no-human-permission-rung | medium | supervised researchers fall to the autonomous rung

Open, surfaced by P02.S15. `src/vaultspec_a2a/graph/_compiler_research.py` builds each researcher's model and composes only harness MCP servers; it never resolves the worker's effective model and never sets `permission_callback`. `src/vaultspec_a2a/providers/_acp_rpc_handlers.py` treats an absent callback as no human rung on any lane, so a supervised research run's branch tool calls are decided without a human. It is also why no parallel human gate arises in production today, though the fan-out is where two would. Recommendation: give each researcher the same permission rung a supervised worker gets, now that P02.S15 addresses one of several pending interrupts.

### interrupt-id-is-namespace-only | low | two interrupts in one task share one id

Open, surfaced by P02.S15. `Interrupt.from_ns` derives the id from the task namespace alone (`langgraph/types.py`), so every interrupt one task raises carries the same id; resume-by-id addresses a task, not a question. Harmless while each node execution raises at most one interrupt (P02.S14) and fan-out branches are separate tasks (P02.S15), and the asking-again gates re-park under the same id by design. Recommendation: never build question identity on the interrupt id; the request id stays the binding.

### provider-suite-fails-without-an-installed-adapter | low | ten provider tests fail in a checkout with no installed adapter

Open, surfaced by P02. `test_claude_permission_posture.py` (5), `test_capsule_acp_resolution.py` (2), `test_factory.py` (1) and `test_launcher_confinement.py` (2) under `src/vaultspec_a2a/providers/tests/` fail identically at the base commit in a fresh worktree with no `node_modules`: they need an installed adapter and node runtime. Not caused by P02. Recommendation: have these tests state the missing prerequisite in their failure, so a bare worktree's result is not misread.

### reparked-gate-reports-no-position | low | a gate asking again dropped out of the projected next nodes

Fixed in the P02.S13 integration correction. LangGraph leaves a task that already holds a resume write out of `StateSnapshot.next` (`langgraph/pregel/main.py`), so once the plan and document gates asked again on an unbound verdict, the execution-state projection reported no position and the research gate's semantic phase fell back from awaiting a decision to running. `_parked_next_nodes` in `src/vaultspec_a2a/worker/state_projection.py` now counts every task parked on an interrupt; `test_a_node_that_asks_again_is_still_the_next_node` fails without it.

### selector-bridge-sync-writes-deadlock | high | the Windows bridge's synchronous writes deadlocked its own selector loop

Fixed in P04.S22. `AsyncPostgresSaver.put` and `put_writes` marshal onto `self.loop` with `run_coroutine_threadsafe(...).result()` and carry no same-loop guard (`langgraph/checkpoint/postgres/aio.py`), and the bridge submitted those methods to that very loop, so each waited on the loop that had to run it; `get_tuple` and `delete_thread` carry the guard and refused instead (`InvalidStateError: Synchronous calls to AsyncPostgresSaver are only allowed from a different thread`, probed live). The bridge's synchronous surface now calls the inner async methods on its own loop; `src/vaultspec_a2a/database/tests/test_selector_bridge.py` hangs against the pre-S22 bridge.

### unreachable-checkpoint-history-degradations | low | two degraded reasons have no producer after the history read was removed

Owned by P07.S39. `DegradedReason.CHECKPOINT_HISTORY_TIMEOUT` and `CHECKPOINT_HISTORY_UNAVAILABLE` (`src/vaultspec_a2a/thread/enums.py`) were emitted only by the second history read that P04.S25 removed from `src/vaultspec_a2a/control/thread_state_service.py`; `CHECKPOINT_HISTORY_UNKNOWN` keeps a producer. Neither retired string appears in `openapi.json`, so retiring them is internal.

### pinned-postgres-retention-schema-version | low | retention stops pruning silently when the saver migrates further

Owned by P07.S39. `_POSTGRES_SCHEMA_VERSION` in `src/vaultspec_a2a/database/checkpoint_retention.py` refuses a store the saver has migrated past it with a warning and `False`, so settled history stops being pruned with no failure. The fail-safe direction is intended, but a saver upgrade must force a re-read of the DELETE statements rather than a bare constant bump.

### shared-lifetime-savers-must-not-be-closed | low | a sibling saver borrows a pool it does not own

Owned by P07.S39. `concurrent_checkpointer` and the selector bridge's `concurrent_sibling` and `with_allowlist` (`src/vaultspec_a2a/database/checkpoints.py`) return savers sharing the caller's pool, and for the bridge its thread and loop; closing one closes the store for all. Documented in each docstring but unenforced, the same hazard upstream `BaseCheckpointSaver.with_allowlist` carries; nothing closes a compiled graph's checkpointer today.

### persistence-probes-characterise-the-library | info | the persistence probes bypass the production entry points

Recorded from P04. The executor's pool and setup-race probes build a bare `AsyncPostgresSaver` and call `setup()` directly, bypassing `open_checkpointer`, `concurrent_checkpointer` and `setup_postgres_checkpointer`, so they still show the unguarded library behaviour after the fixes. The production paths are covered by `src/vaultspec_a2a/database/tests/test_checkpoint_setup_race.py` and `test_checkpoint_pool.py`.

### send-fan-out-branches-cannot-read-the-run-channels | medium | a Send branch is replayed with its dispatch payload, so no later state reaches it

Open, surfaced by P07.S33; needs a decision. Every research branch is a push task whose input is the state captured when the dispatch node emitted its `Send` (`src/vaultspec_a2a/graph/nodes/diverge.py`), and LangGraph rebuilds the task from its tasks channel on every resume without refreshing that payload (`langgraph/pregel/_algo.py`, `prepare_push_task_send`). A probe showed the run's `permission_answers` holding both answers while the resumed branch still read an empty map. `messages`, `vault_index`, `validation_errors` and `active_feature` are frozen the same way, so a branch that parks resumes against a stale view of the run. P07.S33 works around it for permissions by reading the task's own resume values. A pull fan-out (`Command(goto=[names])`) gives branches live channels and per-branch interrupt ids and was probed working, but the Send-based diverge stage is committed in `2026-07-14-adr-authoring-orchestration-adr`. Recommendation: decide between the two fan-out primitives in an amendment to that record.

### finish-block-superstep-arithmetic-was-overstated | info | the required recursion limit is three per blocked FINISH plus one

Correction to `finish-block-budget-outruns-a-small-recursion-limit`. Driving a real star graph with the recursion limit swept, the typed routing error first wins at a limit of 10 for the default budget of 3, and budgets of 1, 2, 4 and 5 need 4, 7, 13 and 16: the relation is `3 * limit + 1`, not about twelve. `src/vaultspec_a2a/graph/compiler.py` now carries that arithmetic, pinned by two tests at the boundary in both directions.

### only-one-shipped-preset-is-a-star | low | the star topology's gates and budgets ship almost untested against real presets

Open, surfaced by P07.S36; needs a decision. Of twenty presets under `src/vaultspec_a2a/team/presets/teams/`, only `mock-supervisor-human-in-loop.toml` declares a star topology, so every supervisor gate and budget is exercised only by synthetic teams built inside tests. `vaultspec-solo-coder.toml`, the preset closest to a production star run, is a pipeline with a recursion limit of 10, below the finish-block floor, so making it a star would trip the new compile-time refusal. Recommendation: decide whether a shipped star preset should exist and what its recursion limit is.

Decided 2026-10-01 by the user: no served star preset yet. Star stays a tested topology with only the mock preset until a lane has completed-turn proof for a supervisor role; the finish-block floor applies to whatever preset is added then. Closed as accepted.

### plan-approval-is-skipped-when-a-soft-phase-gate-warns | low | a warned exec route would reach its worker without plan approval

Owned by P07.S42; latent. `_evaluate_supervisor_response` returns the phase-gate decision before `_plan_approval_decision` runs (`src/vaultspec_a2a/graph/nodes/supervisor.py`), so a route that only warns at its phase gate never reaches the approval check. It cannot happen today because the one SOFT prerequisite targets the `adr` phase and only an `exec` route requests approval; adding a SOFT gate on the exec phase would make it live.

### retention-tests-duplicate-helpers | low | the merged retention guard tests copy a helper and a graph builder

Owned by P07.S39. `src/vaultspec_a2a/tests/test_structural_duplication.py` fails on the P04 merge: `_history` exists in both `src/vaultspec_a2a/database/tests/test_checkpoint_retention.py` and `test_checkpoint_retention_guards.py`, and `_delta_graph` and `_plain_graph` in the latter are one shape. The P04 validation ran the database suites but not the package-level structural tests, so the pushed head carries the failure until S39 lands.

### boot-proof-leaked-the-engine-seat | low | the boot proof failed whenever an earlier test had seated the gateway engine

Fixed in a P04.S27 correction. `test_boot_does_not_rewrite_legacy_checkpoint_rows` in `src/vaultspec_a2a/database/tests/test_boot_leaves_checkpoints_alone.py` disposed the engine boot seated but left the process-wide seat in `src/vaultspec_a2a/database/session.py` pointing at it, so `get_engine` refused it when the API suites ran first in one process. It now clears the seat before and after, as the redispatch tests do.

### postgres-proofs-need-the-declared-prerequisite | info | the real-Postgres tests are deselected unless the run declares the prerequisite

Recorded from P05.S32. Tests marked `requires_prerequisites("postgres")` run only when pytest is given `--require-prerequisite=postgres` (`src/vaultspec_a2a/conftest.py`); the `VAULTSPEC_A2A_TEST_POSTGRES_URL` variable alone satisfies the probe but not the declaration. The orchestrator's post-merge runs for P04 set the variable without the flag, so the pool and selector-bridge proofs were not exercised there; they pass with it after the S32 merge, and every later gate in this plan declares it.

### body-link-regex-diverges-from-core-reader | low | the submitter and core disagree on an inline code span delimited by two backticks

Open, blocking P07.S38; needs a dependency-strategy decision. `_INLINE_CODE_RE` in `src/vaultspec_a2a/authoring/submitter.py` matches single-backtick runs only, while vaultspec-core 0.3.2 reads code spans by backtick run length (`vaultspec_core/vaultcore/markdown.py`, `INLINE_CODE_RE` and `non_prose_spans`). On a real comparison against the installed core, a double-backtick span containing a literal backtick and a wiki-link is stripped whole by core but left partly exposed by the submitter, whose conformance notes then report a false `wiki-link in body text`. The faithful fixes are a runtime dependency on vaultspec-core (exact parity, but core becomes a production import rather than a tooling pin), a core CLI verb the submitter spawns (none exists today), or porting core's reader (no dependency, but the same drift relocated). Recommendation: decide the dependency strategy in an ADR before S38 changes code.

### rag-hosted-ranking-egress-is-unobservable | info | the rag lane cannot see whether its daemon ranks through the hosted API

Recorded from P07.S37, narrowing `rag-daemon-hosted-ranking-egress`. The installed vaultspec-rag 0.5.3 exposes the daemon's hosted-ranking state only through the daemon's own health endpoint; no served MCP tool or resource carries it, so admission cannot refuse an egressing daemon without reaching past the read-only surface this project allows itself. S37 made version skew fail closed through the client's own readiness verdict and recorded the egress limit at the rag launch spec in `src/vaultspec_a2a/providers/_harness_mcp_registry.py`. The egress finding stays open as operator configuration: a daemon serving this project must run without `VAULTSPEC_RAG_TYPESAFE_API_KEY`.

### aggregator-stub-count-corrected | info | the team and worker graph stubs the audit counted were not protocol re-declarations

Correction to `aggregator-test-doubles-still-outnumber-real-graphs`. Outside `src/vaultspec_a2a/streaming/tests/test_aggregator.py`, `src/vaultspec_a2a/team/tests/test_failure_scenario_preset.py` declares a structural Protocol it never instantiates, and `src/vaultspec_a2a/worker/tests/test_state_projection_timeout_knob.py` carries one stub with its own recorded justification (it controls a checkpoint read's latency). P07.S40 replaced the seven aggregator stubs with one real error-injecting graph and kept one documented stream-versus-state stub.

### codeql-reads-trusted-as-secret | high | CodeQL flagged launcher paths in the spawn logs as clear-text secrets

Fixed in commit `3ebff38`; false positive. CodeQL's clear-text logging query raised three high alerts on the spawn and termination log calls in `src/vaultspec_a2a/providers/_subprocess.py`. Reproduced locally with CodeQL 2.27.1: every source was a call to `resolve_trusted_executable` or `_trusted_search_directories` in `src/vaultspec_a2a/providers/cli_resolution.py`. The shared sensitive-name heuristic classifies any function whose name contains `trusted` as returning a secret, so the resolved launcher path flowed as a secret into the `command_executable` spawn metadata. The functions were renamed to `resolve_service_executable` and `_absolute_search_directories`, and the query now finds nothing. The logging path is unchanged, so a real secret routed into spawn metadata would still be caught. An allowlist rewrite of `_metadata_extra` also silenced the query, but only by hiding the flow, and was rejected.

### postgres-inlines-a-str-subclass-before-the-serializer-sees-it | low | a StrEnum channel value reaches the served store as a bare string while SQLite keeps its type

Open, surfaced by P04.S26; latent. `AsyncPostgresSaver.aput` writes `None`, `str`, `int`, `float` and `bool` channel values inline in the checkpoint row rather than through the serializer (`langgraph/checkpoint/postgres/aio.py`), so a `StrEnum` member is stored as a plain string on Postgres, while the SQLite saver serializes the whole checkpoint and keeps the constructor. Measured directly: the same value produced a strict-mode block on SQLite and nothing on Postgres. The two backends therefore round-trip `str`, `int`, `float` and `bool` subclasses differently, and strict mode cannot see such a value on the served backend. Latent because P01.S02 removed enum members from checkpointed state; `src/vaultspec_a2a/database/tests/test_checkpoint_strict_serde.py` uses a plain `Enum` and says why. Recommendation: keep checkpointed state free of scalar subclasses, which the strict-mode tests already pin for enums.

### execution-state-degradations-are-outside-the-declared-vocabulary | medium | two reasons a client receives are not members of the enumeration that declares them

Owned by P07.S43. The worker's execution-state projection emits `execution_state_projection_timeout` and `execution_state_projection_unavailable` (`src/vaultspec_a2a/worker/state_projection.py`), neither a `DegradedReason` member (`src/vaultspec_a2a/thread/enums.py`), and both reach the served `degraded_reasons` through `src/vaultspec_a2a/control/projection.py`. The containment guard in `src/vaultspec_a2a/api/tests/test_served_vocabulary_containment.py` sweeps only `degraded_reasons.append(...)` literals, so constructor keywords escape it. Declaring them keeps the wire strings unchanged.

### degraded-reason-unknown-has-no-producer | low | a declared reason nothing emits

Owned by P07.S43. `DegradedReason.UNKNOWN` has no producer and no reference anywhere in the package, and the class docstring's membership rule does not place it. Every other member has a producer.

### strict-msgpack-comment-overstates-the-refusal-in-the-compiler | low | a compiler comment says strict msgpack refuses a type it only degrades

Owned by P07.S44. The comment above `_ROLE_TO_PHASE` in `src/vaultspec_a2a/graph/compiler.py` repeats the claim `strict-msgpack-degrades-rather-than-refusing` corrected: strict mode logs, emits a blocked event and returns the raw constructor argument, so a run hydrates with a silently changed type rather than failing to.

### clarification-live-proof-waited-on-the-wrong-condition | low | the live clarification loop asserted the run's position after waiting only for its answers

Fixed under P07.S35 (commit `ea26f72`). `_wait_for_answered_clarification` in `src/vaultspec_a2a/api/tests/test_clarification_loop_live.py` returned once the answers were committed, a superstep before the position the caller asserted; the S35 preflight's extra checkpoint read shifted the interleaving enough to lose that race about one run in six. The wait now covers the condition asserted.

### pyjwt-pre-verification-recursion-advisory | medium | the lock held a PyJWT release with an unauthenticated recursion denial of service

Fixed in commit `3599038`. The dependency gate in `just ci` refused GHSA-42vr-xj54-vc7v on PyJWT 2.14.0, reached only through the `mcp[crypto]` extra; nothing in this project parses a JWT itself. The lock moved to 2.15.1 rather than recording an acceptance, and the gate passes.

### plain-value-proofs-used-the-system-temp-directory | low | two graph tests opened their stores outside the pytest temp root

Fixed as a P01.S02 correction (commit `d88d16b`). `src/vaultspec_a2a/graph/tests/test_checkpointed_value_types.py` used `tempfile.TemporaryDirectory()`, which the storage-anchor gate refuses; it failed `just ci` locally and the PR's Basic CI. The tests now take `tmp_path`. The per-package runs that validated S02 did not include the `dev/` harness where that gate lives.

## Plan-close review, 2026-09-30

An independent review of `518b768..e7b3887` failed the plan with one high and one medium finding and four lows. The high finding reopened P07.S34, which is fixed and closed again (`250408f`). The medium finding was resolved by correcting P01.S07's row rather than widening it. Three lows were fixed as corrections; the fourth does not reproduce and is recorded below.

### repark-receipt-never-reaches-the-gateway | high | a resume that only asks again never sent its application report

Fixed by reopening P07.S34 (commit `250408f`). `src/vaultspec_a2a/worker/_dispatch_receipts.py` decided whether a dispatch had landed from committed channel values alone. A resume that parks the turn again commits no superstep, so the reporter never sent its application report. The gateway records an action's application only on that report, so recovery later redelivered an answer the run had already consumed, and the resume preflight refused it: the stuck loop `repark-receipt-never-durable` describes. The reporter now reads the same checkpoint evidence the gateway verifies against, held writes included. `test_a_resume_that_only_asks_again_reports_its_application` drives the real executor and fails without the fix.

### research-topology-index-refresh-never-built | medium | P01.S07 claimed the research topology refresh it deliberately did not build

Resolved by correcting the Step. The supervisor refresh landed; the research topology was left without one on purpose, as S07's ledger note records: its documents are unapplied engine proposals and none of its gates reads `vault_index`. The Step row said otherwise and now matches what was done. `research-adr-has-no-mount-or-index-refresh` is closed as by design; the scope split is carried by the proposed amendment to `2026-07-14-adr-authoring-orchestration-adr`.

### document-gate-without-a-proposal-id-is-unanswerable | low | a gate with no committed proposal parked on a question nothing could answer

Fixed as a P02.S13 correction (commit `bea40ce`). The resume preflight admits only an answer naming a pending request, and a gate with no proposal id has none, so its fail-closed branch was unreachable. It now routes to revision without parking.

### ingest-still-classifies-baseexception-as-a-provider-failure | low | a process exit inside a run might settle it as failed

Does not reproduce as described. A graph node runs in its own task, and asyncio re-raises `SystemExit` and `KeyboardInterrupt` from a task straight out of the event loop rather than to the coroutine awaiting it, so the catch-all in `src/vaultspec_a2a/streaming/ingest.py` never receives them from a node. A probe that raised `SystemExit` inside a node took the event loop down without reaching ingest. They could reach it only if raised in the ingest task's own frames, which no code path does. Left unchanged; revisit if in-task callbacks ever raise them.

### aggregator-projection-seams-have-no-production-caller | low | two aggregator methods existed only for tests

Fixed as a P03.S18 correction (commit `ce82446`). Ingest now builds the run lifecycle handler and projects frames through its own methods, and the aggregator delegates to them, so the aggregator suite exercises the path a run uses.

### readiness-tool-docstring-claims-a-declared-tool | low | the contract probe described the rag readiness tool as declared

Fixed as a P07.S37 correction (commit `1d086f0`). The docstring now says the probe calls a served tool a run may not call, and why that is in bounds.

### stale-audit-entries-closed | info | several open entries were already fixed by later Steps

Recorded from the plan-close review. `blocked-finish-reason-is-dropped-when-the-reroute-needs-approval` and `star-topology-never-clears-validation-errors` were fixed by P07.S36. `plan-approval-is-skipped-when-a-soft-phase-gate-warns` was fixed by P07.S42. `finish-block-budget-outruns-a-small-recursion-limit` was superseded by the compile-time refusal of S36. `retention-tests-duplicate-helpers` was fixed by P07.S39. `repark-receipt-never-durable` is closed by S34 and its reopen above. Each earlier entry's opening status line stands as it was written; this entry closes them.

## Re-review of the plan-close fixes, 2026-09-30

An independent re-review of `150b0b9..b0f2bd3` passed. It confirmed the S34 reporter fires once per dispatch and never early, and fires on neither an incompatible nor a prior-action checkpoint; the gateway accepts every checkpoint id the reporter now sends. It confirmed the no-proposal gate branch is a backstop the submit ordering never reaches, and that the streaming refactor holds no per-run state. One medium and three lows followed, all resolved.

### unavailable-checkpoint-reads-as-receipt-not-due | medium | a failed checkpoint read was logged as a receipt not yet due

Fixed as a P07.S34 correction (commit `0804ef0`). `read_checkpoint_evidence` turns every read failure into an unavailable verdict, and the reporter logged it at debug as a checkpoint not yet carrying the dispatch, where the committed-values reporter had warned. The reporter now warns with the `dispatch_application_receipt_failed` action for an unavailable read. `test_an_unreadable_checkpoint_is_reported_as_a_failed_receipt` fails without it.

### failed-turn-resume-settles-ahead-of-its-terminal | low | an answer applied by a turn that then failed moved the finished run back to running

Fixed by P07.S45 (commit `400efd9`). Evidence-based reporting reports a resume whose turn failed after consuming the answer, and `commit_proven_application` in `src/vaultspec_a2a/control/_event_application.py` then moved the thread to RUNNING, an illegal transition once the FAILED terminal had landed. The reviewer traced it through source; `test_an_answer_applied_by_a_turn_that_then_failed_leaves_the_run_failed` executes it and reproduced the `InvalidTransitionError`. The permission still settles; a finished run keeps its status.

### gate-comment-overstates-the-resume-preflight | low | the no-proposal branch credited the preflight with a guarantee the verdict binding provides

Fixed as a P02.S13 correction (commit `e2b5e2d`). The preflight admits an answer naming no request; it is `verdict_answers_request` that refuses every unbound verdict, so a park could only end in the rejection the branch takes directly. The comment now says so. The same correction applies to `document-gate-without-a-proposal-id-is-unanswerable` above.

### baseexception-resolution-is-narrower-than-its-claim | low | the not-reproducing verdict holds for SystemExit and KeyboardInterrupt only

Correction to `ingest-still-classifies-baseexception-as-a-provider-failure`. Asyncio's task step re-raises `SystemExit` and `KeyboardInterrupt` out of the loop, so the verdict stands for those two, from sync and async nodes alike. Any other non-`Exception` `BaseException` subclass raised by a node does reach the catch-all in `src/vaultspec_a2a/streaming/ingest.py`, is classified as a provider failure and is swallowed; the reviewer probed it with a bare subclass. No such subclass exists in this package, LangGraph, langchain-core or anyio, so nothing exercises it today. Recommendation: if the catch-all is revisited, re-raise non-`Exception` exceptions after classification rather than returning FAILED.

Fixed in P07.S46. The catch-all still reports the run failed to its viewers and then re-raises any exception outside `Exception` (`src/vaultspec_a2a/streaming/ingest.py`); `test_a_signal_raised_by_a_node_is_reported_and_still_propagates` in `src/vaultspec_a2a/streaming/tests/test_aggregator.py` drives a real node raising a bare `BaseException` subclass and fails on the prior code.

### design-record-drift-amendments-applied | info | the ten drifted decision records are amended and two proposed records accepted

Closes `langgraph-design-record-drift` through P06.S28. The user approved the drafted amendments as recommended on 2026-09-30 ("approve the ADR amendments as recommended"). Each record gained an "Amendment - langgraph-conformance (2026-09-30)" section:

- `2026-02-26-event-aggregation-server-side-replay-adr`
- `2026-03-04-worker-process-architecture-adr`
- `2026-02-27-team-composition-topology-adr`
- `2026-03-03-blackboard-content-mounting-adr`
- `2026-03-03-contextual-anchoring-graph-lifecycle-adr`
- `2026-03-03-phase-artifact-gates-adr`
- `2026-03-03-plan-approval-interrupt-adr`
- `2026-03-10-postgres-dual-backend-adr`
- `2026-07-14-adr-authoring-orchestration-adr`
- `2026-02-26-orchestration-topology-pipeline-adr`

The drafts' later findings are folded in, among them strict serde and the borrowed-close refusal, the exec worker retiring validation errors, the compile-time finish budget and the frozen `Send` payload. Two further edits:

- `2026-03-03-persistent-task-queue-schema-adr` gained a note retiring its `mounted_context` example.
- `2026-09-24-architecture-review-research` now names the tag `nostream`.

The drafts recommended accepting two records, and both are now accepted:

- `2026-02-27-team-composition-topology-adr`
- `2026-02-26-orchestration-topology-pipeline-adr`

`2026-02-26-event-aggregation-server-side-replay-adr` is amended but stays `proposed`, because the drafts made no recommendation between accepting it and deprecating it in favour of `2026-07-14-a2a-edge-conformance-adr`; that choice is the user's.

The `workers[0]` withdrawal is recorded as an amendment, not a supersession, as recommended.

Two decisions stay open in `2026-07-14-adr-authoring-orchestration-adr`:
- a pull fan-out in place of `Send`;
- the submitter's dependency strategy for P07.S38.

Citations name files and symbols rather than line numbers, because the drafted lines had moved by the time the amendments were applied. TypeSafe crossref was not configured, so placement rests on the drafter's local discovery across the full ADR listing.

## Recommendations

- Feed research findings to synthesis and bound every review and routing loop before the lower fixes, per the user's ordering.
- Replace the private runtime seat by moving ingest to the documented `astream` stream modes, which also removes the interrupt, receipt, node-identity, nostream and custom-writer gaps.
- Choose `durability="sync"` for ingest and resume; it realises the checkpoint-first recovery the embedded-runtime decision already requires.
- The design-record drift needs amendments to accepted decisions; they are proposed for approval rather than applied.

### rule-frontmatter-misread-with-a-byte-order-mark | low | a rule file saved with a byte-order mark lost its roles and leaked its frontmatter

Fixed in P07.S49. The rules loader read rule frontmatter with its own line scanner, which required the first line to be exactly `---`; a rule saved as UTF-8 with a byte-order mark, as Windows editors commonly write it, was read as having no frontmatter, so a role-scoped turn dropped it and an unscoped compile put its YAML into the prompt as text. `src/vaultspec_a2a/context/rules.py` now reads rule frontmatter with core's `parse_frontmatter` and `split_frontmatter`; `test_a_rule_saved_with_a_byte_order_mark_keeps_its_frontmatter` fails on the prior scanner.

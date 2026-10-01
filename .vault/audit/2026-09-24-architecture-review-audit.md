---
tags:
  - '#audit'
  - '#architecture-review'
date: '2026-09-24'
modified: '2026-10-01'
body_schema: 'body-v2'
body_hash: 'sha256:5e130aa3c424788dd4027fbb9847ec7112345660c8073c0e50218c8d4e10b967'
related:
  - "[[2026-09-24-architecture-review-research]]"
  - "[[2026-07-15-graph-agent-framework-harness-adr]]"
  - "[[2026-07-15-agent-harness-provisioning-adr]]"
  - "[[2026-08-02-control-action-leases-adr]]"
  - "[[2026-08-02-llm-context-provider-abstraction-acp-v1-client-wire-adr]]"
  - "[[2026-07-19-observability-lanes-adr]]"
  - "[[2026-07-19-a2a-edge-conformance-adr]]"
---

# `architecture-review` audit: `architecture review against modern agent orchestration standards`

## Scope

Whole-system review on 2026-09-24 of `vaultspec-a2a` at `e516a7f` (source unchanged through `df81af2`) against the baseline in `2026-09-24-architecture-review-research`: the LangGraph graph layer, session, thread, and run management, tool use and permissions, context assembly and logging, provider CLI acquisition, and the service edge with its performance and A2A capability. Six read-only reviewers covered one area each; every high finding and a sample of the rest were re-verified against the code by the orchestrator, and several were probed against the locked environment (`langgraph@1.2.11`, `langgraph-checkpoint-sqlite@3.1.1`, `fastapi@0.141.1`, `@agentclientprotocol/claude-agent-acp@0.59.0`). Findings that restate an open plan Step name that Step rather than claiming novelty; an unqualified `W`-prefixed Step id belongs to `2026-09-05-embedded-runtime-remediation-plan`, and `P01.S01`, `P01.S02`, and `P02.S05` belong to `2026-08-02-llm-context-provider-abstraction-plan`. No live provider turn was run: this environment holds no provider credential, and the only repository secret wired to a workflow authenticates the `@claude` review action, not a test lane.

Provider acquisition, in short: the repository pins exactly one provider artifact, the Claude ACP adapter and its vendored native Claude binaries, through `package-lock.json` integrity hashes restored by `npm ci` under an exact Node version check. Every other CLI (Codex, Kimi, Antigravity) and, at execution time, the Claude binary itself are taken from whatever the host PATH resolves, with no version floor or recorded identity; Antigravity is discovery-only and never executes. Admission of a lane to service is separately gated by live completed-turn proof (`src/vaultspec_a2a/providers/lane_admission.py:167-205`), and only Codex is catalog-admitted today.

Sound foundations the findings do not diminish: the writer-fenced compare-and-set status election, transactional-outbox dispatch with stable dispatch ids and leases, and checkpoint-receipt-proven completion; LangGraph gate nodes that split idempotent commits from pure interrupts, a side-effect-aware retry predicate, and digest-keyed single-flight graph compilation; a closed, frozen harness MCP registry with `strictMcpConfig`, an exact-name deny-by-default autonomous permission rung, and a privilege-dropping Compose identity launcher; stderr-only rotated JSON log lanes, a versioned, allowlisted, byte-capped SSE frame contract, and W3C trace propagation from gateway to worker; a lock-pinned ACP adapter tree with Job Object and session-group process containment; and a loopback, constant-time-bearer edge with bounded bodies, bounded per-subscriber queues, and an OpenAPI artifact held byte-equal to the live app.

## Findings

### phase-gates-do-not-block | high | the HARD phase gates record an error but still route to the blocked worker

Status: fixed in P02.S09 (`src/vaultspec_a2a/graph/nodes/supervisor.py:539-620`, `_evaluate_supervisor_response`; `src/vaultspec_a2a/graph/compiler.py:954-977`, `_route_from_supervisor`): a blocked gate now returns `refused=True` and the compiler edge routes back to the supervisor on `supervisor_reasks` rather than following `next`. Original finding: diverges from accepted `2026-03-03-phase-artifact-gates-adr` ("HARD gate: block routing") and `2026-03-03-plan-approval-interrupt-adr`. `_phase_gate_decision` returns the blocked `next_route` unchanged with only `routing_error` set (`src/vaultspec_a2a/graph/nodes/supervisor.py:240-268`), and `_route_from_supervisor` follows `next` (`src/vaultspec_a2a/graph/compiler.py:774-792`). A scripted run with an empty vault index routes to `coder` (exec phase) regardless; plan approval never fires because it needs a plan to exist. The only test asserts `routing_error` is set, not where the run goes (`src/vaultspec_a2a/graph/tests/nodes/test_supervisor.py:286-295`). LangGraph places such guards in the edge or `Command` routing (research, langgraph section).

### permission-resume-replays-turn | high | approving a tool permission replays the whole agent turn and can bind to a different tool call

Status: partially fixed. P02.S11 binds an approval to a fingerprint of the exact tool call and re-parks on mismatch (`src/vaultspec_a2a/providers/_acp_rpc_handlers.py`), and P02.S14 of `2026-09-30-langgraph-conformance-plan` bounds the repark loop to at most one `interrupt()` per node execution (`src/vaultspec_a2a/graph/nodes/worker.py:834-925`, `_park_on`/`_permission_callback_for`; see `repark-loop-positional` in `2026-09-30-langgraph-conformance-audit`, closed by the same change). The residual turn-replay cost is the accepted per-call-provider-sessions trade-off reaffirmed by `2026-10-01-provider-binary-policy-adr` D5. Original finding: the permission callback raises `interrupt()` inside `model.ainvoke` (`src/vaultspec_a2a/graph/nodes/worker.py:178-188,653-681`); the CLI is denied and torn down (`src/vaultspec_a2a/providers/_acp_rpc_handlers.py:581-596`). On resume the node re-executes, a fresh CLI session regenerates the turn, and resume index 0 is consumed by whichever permission request arrives first; `_resolve_resume_option_id` only checks the option id exists in the new option set (`src/vaultspec_a2a/graph/nodes/worker.py:631-650`), and option ids are generic, so "allow" granted for tool A can apply to tool B. Pre-request side effects and the LLM turn are repeated. LangGraph requires side effects before `interrupt()` to be idempotent; `HumanInTheLoopMiddleware` pauses after tool calls are emitted and before they execute (research, langgraph section). The plan-approval ADR's revision moved plan approval out of the supervisor for this same reason; the permission path was not moved.

### launcher-path-hijack | high | a workspace-planted executable replaces the Claude provider launcher

Status: fixed in P04.S21 (`src/vaultspec_a2a/providers/cli_resolution.py:30-106`, `resolve_service_executable`/`_absolute_search_directories`): the launcher now resolves to an absolute path from a trusted search path rather than a bare name or the agent's PATH/working directory. Original finding: reproduced through production `spawn_acp_process`. The project-local Claude command is the bare name `node` (`src/vaultspec_a2a/providers/_factory_commands.py:317`), and `resolve_env_vars` prepends the workspace's `.venv/bin` (or `Scripts`) to the child PATH (`src/vaultspec_a2a/workspace/environment.py:165-175`); POSIX exec resolves the bare name against that PATH, as does the Compose launcher's `execvp` (`service/docker/provider_identity_launcher.c:100`), and Windows `cmd.exe` searches the working directory (the workspace) first (`src/vaultspec_a2a/providers/_subprocess.py:257-270`). A scratch workspace with `.venv/bin/node` printed its own marker instead of starting the adapter. Any cloned repository, or an agent in an earlier run, can plant it; it runs with the operator's identity and the run's injected secrets and bypasses every tool-permission check. The same vector reaches `#!/usr/bin/env node` shebangs and the `uvx` used for harness MCP servers.

### codex-auth-copy-no-writeback | high | Codex credentials are copied into a throwaway home and refreshed tokens are discarded

Status: fixed in P04.S25, further hardened in its reopen for an event-loop block (`codex-credential-writeback-blocks-the-event-loop` below). Original finding: Codex is the only catalog-admitted lane. `auth.json` is copied into a per-run home (`src/vaultspec_a2a/providers/_codex_config_home.py:359-371`) that is `rmtree`d afterwards (`:398-410`). When Codex rotates its refresh token mid-run the new token dies with the home and the operator's `~/.codex` keeps a spent token, which signs them out with `refresh_token_reused`; concurrent runs share one source file. OpenAI's CI guidance requires writing the refreshed file back and not sharing it across concurrent jobs. The keyring (`cli_auth_credentials_store=auto`) default may leave no `auth.json` to copy at all.

### followup-on-busy-run | high | a second message during a running turn strands the run in reconciling

Status: partially fixed in P03.S14: a busy run now installs no writer and refuses with a typed conflict (`followup-verb-has-no-reachable-success` below). The busy/parked/settled continuation model itself is now decided by `2026-10-01-run-continuation-adr`, implementation planned under feature `run-continuation` (`run-busy-refusal-contract` below). Original finding: verified by code trace, not reproduced end to end. RUNNING admits follow-ups (`src/vaultspec_a2a/thread/message_policy.py:26-48`) and accepting one installs it as the run writer (`src/vaultspec_a2a/control/message_service.py:262-283`). The worker refuses the busy thread with 429 (`src/vaultspec_a2a/worker/app.py:309-318`), the gateway schedules a retry, and the in-flight turn's completion and failure are then both refused as PRIOR_ACTION evidence (`src/vaultspec_a2a/thread/checkpoint_evidence.py:76-82`, `src/vaultspec_a2a/control/event_handlers.py:245-251,428-438`). A retry that lands after the first turn ends meets an END checkpoint and reports COMPLETED without running the message (`src/vaultspec_a2a/worker/state_projection.py:346-349`), which the gateway also refuses, so the run quarantines to RECONCILING at its deadline. The only live test asserts a stub worker received the dispatch (`src/vaultspec_a2a/api/tests/test_gateway_live.py:381-392`). Agent Server makes this a declared multitask strategy (research, agent-server section); open plan Steps W02.P04.S16-S18 of `2026-09-05-embedded-runtime-remediation-plan` own enqueue.

### crash-resume-reingests | high | worker recovery replays the graph input instead of resuming the checkpoint

Status: fixed in P02.S12; `drain-redelivery-reported-complete` below verifies the same `pre_flight_checkpoint` fix (`src/vaultspec_a2a/worker/state_projection.py`) against a real redelivery test. Original finding: the empty-pending-writes heuristic is already recorded in `2026-09-06-embedded-runtime-remediation-recovery-architecture-audit`, the duplicated input is new. The pre-flight treats empty pending writes as COMPLETED (`src/vaultspec_a2a/worker/state_projection.py:346-349`) and proceeds when the checkpoint read fails (`:327-340`); otherwise the redelivered INGEST re-sends the full input (`src/vaultspec_a2a/worker/graph_lifecycle.py:906-918`). A LangGraph 1.2.11 probe cancelled a two-node graph mid-node: `pending_writes=[]` with `next=('b',)`, and re-invoking with the input duplicated the user message and re-ran node a, where `ainvoke(None)` resumed cleanly. The receipt reducer also accepts a repeated `dispatch_id` (`src/vaultspec_a2a/thread/action_receipts.py:88-108`). LangGraph's durable-execution contract is resume-with-None (research, langgraph section).

### breaker-fed-by-backpressure | high | capacity and semantic refusals open the shared circuit breaker

Status: fixed in P03.S15 (`src/vaultspec_a2a/control/dispatch.py:197-299`, `_dispatch_response_or_raise`): a 429 now calls `circuit_breaker.record_refusal()` and settles the breaker healthy, and only a transport `httpx.HTTPError` or a 5xx server error calls `record_failure()`. Original finding: diverges from accepted `2026-08-02-control-action-leases-adr` ("worker saturation does not open the shared failure breaker"); open Steps W02.P05.S23/S24 and W02.P04.S18 cover it. Every 429 and every non-2xx, including 409, calls `record_failure()` (`src/vaultspec_a2a/control/dispatch.py:206-231`) against a 3-failure / 30 s breaker (`src/vaultspec_a2a/control/infra_config.py:764-771`) whose half-open state admits all traffic (`src/vaultspec_a2a/control/circuit_breaker.py:51-59`). Six simultaneous starts, or the follow-up retry loop above, can 503 every run's permission answers for 30 s.

### claude-settings-override-autonomy | high | operator and workspace Claude settings can override the autonomous deny-by-default rung

Status: fixed in P04.S22 (`src/vaultspec_a2a/providers/_acp_session.py:71-107,636-677`): `claude_session_options` now also pins `settingSources: []` and persona-derived `disallowedTools`, and the session verifies the reported permission mode against `AUTONOMOUS_PERMISSION_MODE`. The posture itself (`default`, not `dontAsk`) is an accepted deviation tracked by `claude-mode-default-not-dontask` below; the cross-lane policy consolidation is decided by `2026-10-01-tool-permission-model-adr`, implementation planned under feature `tool-permission-model`. Original finding: `claude_session_options` pins only `strictMcpConfig` and `allowedTools` (`src/vaultspec_a2a/providers/_acp_session.py:66-83`); the pinned adapter `@agentclientprotocol/claude-agent-acp@0.59.0` then defaults `settingSources` to user, project, and local (`node_modules/@agentclientprotocol/claude-agent-acp/dist/acp-agent.js:3751`) and resolves `permissionMode` from them, while the lane runs in the operator's own config home (`src/vaultspec_a2a/providers/_config_home_roots.py:4-7`). A user-level `acceptEdits` or `bypassPermissions` default auto-approves tools before the a2a rung is consulted, and project-level `.claude/settings*.json` in a user-selected repository loads allow rules and hooks. `AcpChatModel.set_mode` has no production caller and `currentModeId` is recorded but never checked. The Claude Agent SDK documents that auto-approved tools never reach `canUseTool` (research, permissions section).

### acp-client-enforcement-unreached | high | client-side fs, terminal, and .vault write enforcement never runs on served ACP lanes

Status: open; P02.S05 of `2026-08-02-llm-context-provider-abstraction-plan` ("prove supported-adapter fs/terminal over real stdio") is still open. The adapter defines `readTextFile`/`writeTextFile` wrappers (`acp-agent.js:3025-3031`) that nothing calls: the CLI's native Read, Write, Edit, and Bash act on disk directly. Persona `filesystem_write=false`/`terminal=false` only clear `clientCapabilities`, which the adapter ignores, so the confined handlers (`src/vaultspec_a2a/providers/_acp_rpc_handlers.py:63-291`) and the `.vault` deny are bypassed; the code comment at `src/vaultspec_a2a/providers/_acp_session.py:596-599` asserting the deny still applies is false for Claude and Z.ai. Existing tests call the handlers directly (`src/vaultspec_a2a/providers/tests/test_acp_vault_deny.py`).

### cross-project-guard-unreachable | high | the cross-project argument guard is unreachable for pre-approved tools

Status: partially fixed. P04.S23 added the Codex-side scan (`src/vaultspec_a2a/providers/_codex_permission.py:230-240`, `foreign_project_argument`), refusing a foreign `project_root` argument under Codex. The Claude/ACP side remains unreachable — autonomous composition still pre-approves `mcp__vaultspec-rag__*` via `allowedTools` with no path scoping (`src/vaultspec_a2a/providers/_acp_mcp.py:189-214`, `harness_allowed_tool_names`) — and is now decided by `2026-10-01-tool-permission-model-adr`, implementation planned under feature `tool-permission-model`. Original finding: the guard runs only inside `on_request_permission` (`src/vaultspec_a2a/providers/_acp_rpc_handlers.py:557-579`), but autonomous composition places `mcp__vaultspec-rag__*` in `allowedTools` (`src/vaultspec_a2a/graph/nodes/worker.py:767`), so those calls never raise a permission request; the Codex rung compares only `(server, tool)` (`src/vaultspec_a2a/providers/_codex_permission.py:213-229`) under `default_tools_approval_mode="auto"` (`src/vaultspec_a2a/providers/_codex_config_home.py:309`). A `project_root` argument naming another enrolled project is read in autonomous mode. `test_project_confinement.py:125-145` proves handler logic production does not execute.

### unscoped-native-reads | high | autonomous research roles hold unscoped host reads plus open web egress

Status: fixed in P04.S23 (`src/vaultspec_a2a/providers/_native_read_tools.py:245-325`, `native_read_floor_rules`/`workspace_scoped_tool_rule`): the native read floor now composes workspace-scoped rules instead of bare-name entries, withholding any floor tool whose rule grammar takes no path when the run has a workspace. Original finding: Bare `Read`, `Grep`, and `Glob` are allowlisted (`src/vaultspec_a2a/providers/_native_read_tools.py:43,278-288`); in default mode in-workspace reads are already auto-approved, so the bare entries only add out-of-workspace reads (operator credentials, `~/.ssh`; `/proc/<pid>/environ`, which holds the bridge bearer, unverified live). `WebFetch` is served under a blocklist posture (`src/vaultspec_a2a/providers/lane_admission.py:274-285`). Private-data read plus untrusted content plus an outbound channel is the OWASP LLM01/LLM06 exfiltration triad. Compose is mitigated by the identity launcher; desktop has no UID boundary.

### invented-message-timestamps | high | transcript timestamps are the read time, not the event time

Status: fixed in P05.S30 (stamps production time via `stamp_message_created_at`); see `message-timestamp-nullable-contract` below for the resulting nullable-timestamp contract on pre-upgrade history. Original finding: `extract_message_timestamp` falls back to `datetime.now(UTC)` (`src/vaultspec_a2a/thread/snapshots.py:739-761`) and nothing stamps `created_at` on produced messages, so the authoritative run history reports projection time as event time; committed evidence shows messages 8 µs apart and after their checkpoint.

### acp-prompt-flattening | high | ACP prompts drop roles, speaker attribution, and tool results

Status: fixed in P04.S27; see `prompt-render-role-headers-are-forgeable` below, which verifies the shared `src/vaultspec_a2a/providers/_prompt_render.py` renderer both lanes now use. Original finding: `_astream_session` renders every message as a bare text block and silently drops `ToolMessage` (`src/vaultspec_a2a/providers/acp_chat_model.py:469-475`), so system instructions, other agents' outputs, and the model's own prior turns arrive indistinguishable; Codex labels roles (`src/vaultspec_a2a/providers/_codex_protocol.py:39-62`), so the two transports disagree. This widens the injection surface noted in the permissions findings.

### acp-stderr-invisible | high | ACP CLI stderr is DEBUG-only and not retained on failure

Status: fixed in P04.S28 (`src/vaultspec_a2a/providers/acp_chat_model.py:771-796,953`): `_read_stderr_loop` now retains a redacted stderr tail attached to the early-exit error. The turn-idle deadline error's own tail is a residual tracked separately by `acp-turn-idle-error-lacks-stderr` below (owned by P06.S40, in progress). Original finding: breaks L2 of `2026-08-05-served-capability-contract-failure-observability-adr`. `_read_stderr_loop` logs each line at DEBUG, unredacted (`src/vaultspec_a2a/providers/acp_chat_model.py:898-921`), under an INFO default; an early exit reports only a line count. Codex already keeps a redacted 200-line tail (`src/vaultspec_a2a/providers/_codex_app_server_client.py:30-60`).

### no-a2a-protocol | high | the service is not A2A-protocol capable; the protocol was deliberately dropped

Status: open decision, not a defect. The 2026-07-15 amendment to `2026-02-26-protocol-ecosystem-bridge-adr` drops the Google (now Linux Foundation) A2A ambition and declares "a2a" a project label; declared transports are ACP and REST/SSE. The edge is the bearer-authenticated `/v1` REST+SSE contract of `2026-07-14-a2a-edge-conformance-adr` R6 (`src/vaultspec_a2a/api/routes/gateway.py:73`), with no Agent Card, JSON-RPC binding, `/.well-known` route, push-notification config, or `a2a-sdk` dependency. Most A2A concepts already have a counterpart: `ThreadStatus` maps one-to-one onto submitted/working/input-required/completed/canceled/failed (`src/vaultspec_a2a/thread/enums.py:45`), run-status and cancel map onto GetTask and CancelTask, clarification and permission pauses map onto input-required answered through the typed respond verbs, and the SSE frame catalog maps onto status and artifact update events. Absent are the Agent Card, a multi-task context, push notifications, file parts, `auth-required`, and snapshot-first resubscription. Because execution runs in the worker, `a2a-sdk`'s `DefaultRequestHandler` plus in-process `AgentExecutor` does not fit; a custom request handler over the existing control services does (research, a2a section).

### sse-pins-db-session | high | every open SSE stream holds a pooled database session and an open SQLite read transaction

Status: fixed in P03.S16 (`src/vaultspec_a2a/api/routes/_gateway_read_endpoints.py:378-390`): the stream route now depends on `get_db(scope="function")`, giving the connection back when the handler returns rather than holding it for the stream's life. Original finding: measured. `run_stream_endpoint` depends on `get_db` (`src/vaultspec_a2a/api/routes/_gateway_read_endpoints.py:376-379`); with FastAPI 0.141's default request-scoped yield teardown the session closes only after the stream ends (`src/vaultspec_a2a/database/session.py:426-450`), and the status read inside the stream builder autobegins a transaction. Three open streams gave `pool.checkedout()==3` and a busy `wal_checkpoint(TRUNCATE)`; fifteen exhausted the 5+10 pool and the sixteenth database-using request blocked. About fifteen attached viewers therefore stall run-start, status, cancel, and the `/internal/events` relay on the same engine, `max_stream_connections=256` is unreachable, and the WAL grows while any viewer is attached, the hazard `session.py:52-66` documents.

### unparseable-route-finishes | medium | unparseable supervisor output completes the run and skips the FINISH guards

Status: fixed in P02.S09 (`src/vaultspec_a2a/graph/nodes/supervisor.py:205-233`, `_parse_route`): an unparseable or ambiguous reply now returns a refusal that re-asks the supervisor instead of falling back to `FINISH`. Original finding: `_parse_route` substring-matches and falls back to `FINISH` (`src/vaultspec_a2a/graph/nodes/supervisor.py:125-135`); the unparseable branch returns before `_check_finish_blocked` (`:317-327`). Scripted: with active validation errors, explicit FINISH reroutes to `coder`, but garbled text writes a completion receipt.

### preset-recursion-limit-ignored | medium | the per-preset `recursion_limit` is ignored on served runs

Status: fixed in P02.S10 (`src/vaultspec_a2a/worker/executor.py:98-108`, `_recursion_limit`): the dispatch now takes `min(req.recursion_limit, definition.recursion_limit)`, so a served run is held to the preset's own budget. Original finding: Presets declare it (`src/vaultspec_a2a/team/team_config.py:504`), but served paths pass the global `graph_recursion_limit=100` (`src/vaultspec_a2a/domain_config.py:174`, `src/vaultspec_a2a/api/routes/_gateway_run_start.py:258`); only tests read the preset value.

### unbounded-review-loops | medium | review loops have no per-phase bound and the pipeline_loop early exit is dead

Status: fixed in P02.S10 (`src/vaultspec_a2a/graph/compiler.py:980-991`, `_loop_route`): a `max_loops` guard now forces `"FINISH"` once the counter reaches it, so the `pipeline_loop` early exit works. Original finding: `_doc_review_router` cycles (`src/vaultspec_a2a/graph/_compiler_research.py:336-342,648-676`) cost two LLM turns each and are bounded only by the global limit; `_loop_route` exits early only on `next=="FINISH"`, which no worker writes (`src/vaultspec_a2a/graph/compiler.py:795-807`). `RemainingSteps` and model/tool call-limit middleware are the standard bounds.

### checkpoint-growth | medium | checkpoint storage grows super-linearly with no retention

Status: partially fixed. P01.S08 prunes a settled run's superseded checkpoints while keeping its latest one (`src/vaultspec_a2a/database/checkpoints.py:384,569`, `prune_settled_checkpoints`; `src/vaultspec_a2a/control/event_handlers.py:642-698`, `_schedule_settled_history_prune`), but growth DURING a live run is still unbounded until settle, which `2026-10-01-run-continuation-adr`'s Consequences flag as a prerequisite a multi-turn run makes urgent; no context-window policy ADR yet exists. Original finding: The saver stores full channel values each super-step; measured 20 turns of 10 KB messages produced 22 checkpoints totalling 2.16 MB (about 10.5x the transcript). `mounted_context`, descriptors, and receipts ride every checkpoint, and `Send(name, state)` copies full state into each branch (`src/vaultspec_a2a/graph/nodes/diverge.py:123`). Nothing calls `adelete_thread` or prune (`src/vaultspec_a2a/database/checkpoints.py:196`). LangGraph 1.2 offers `DeltaChannel` and documented storage optimization; Agent Server offers TTLs.

### shared-model-instances | medium | concurrent runs of one preset share model instances that refuse concurrent use

Status: fixed in P02.S13 (`src/vaultspec_a2a/worker/graph_lifecycle.py:76-110`, `graph_cache_key`): the cache key now includes the run's `thread_id`, so concurrent runs of one preset no longer share model instances; see `graph-cache-per-run` below. Original finding: code reading only. The compiled-graph cache key has no run identity (`src/vaultspec_a2a/worker/graph_lifecycle.py:91-97`), so up to five concurrent runs share model objects; `AcpChatModel` raises a non-retryable `AcpSessionBusyError` on concurrent use (`src/vaultspec_a2a/providers/acp_chat_model.py:336-338`).

### blocking-io-on-loop | medium | synchronous file and HTTP I/O runs on the worker event loop

Status: fixed in P02.S13: `_build_worker_messages` (which builds the rule message) now runs via `asyncio.to_thread` (`src/vaultspec_a2a/graph/nodes/worker.py:1207-1220`), and `resolve_engine`/`resolve_engine_with_retry` are offloaded the same way (`src/vaultspec_a2a/worker/graph_lifecycle.py:785-885`, `src/vaultspec_a2a/worker/_authoring_close.py:45,54`, `src/vaultspec_a2a/authoring/client.py:206`). Original finding: diverges from `2026-03-03-blackboard-content-mounting-adr` §4. A new `RuleManager` per turn does synchronous glob and frontmatter reads (`src/vaultspec_a2a/graph/nodes/worker.py:109-112`, `src/vaultspec_a2a/context/rules.py:110-115`); `_build_feedback_reader` calls synchronous `resolve_engine()` (`httpx.get`, 3 s timeout) on the loop (`src/vaultspec_a2a/worker/graph_lifecycle.py:850`) while its sibling at `:774` uses `to_thread`.

### no-cli-version-identity | medium | no system CLI has a version floor, pin, or recorded identity

Status: open; decided by `2026-10-01-provider-binary-policy-adr` (D2: a lane proof now carries its admitted version range), implementation planned under feature `provider-binary-policy`. Original finding: Resolution checks presence only (`src/vaultspec_a2a/providers/cli_resolution.py:19-37`); `LaneProof` records a test id but no binary version (`src/vaultspec_a2a/providers/lane_admission.py:167-205`); the adapter's `agentInfo` and Codex's `userAgent` are discarded; CI installs `@openai/codex` unpinned (`.github/workflows/test.yml:223`); the native Claude installer auto-updates. "Proven lane" admission therefore does not bind to the binary that was proven.

### claude-binary-split | medium | discovery and execution run different Claude binaries, chosen by PATH

Status: partially fixed in P04.S26, which unified discovery and execution onto one resolver (see `capsule-claude-binary-still-overridden-by-path` below, which stays open for the capsule authority gap). The residual capsule-authority and version-range gaps are decided by `2026-10-01-provider-binary-policy-adr` (D1/D2), implementation planned under feature `provider-binary-policy`. Original finding: Execution sets `CLAUDE_CODE_EXECUTABLE` to the PATH `claude` (`src/vaultspec_a2a/providers/acp_chat_model.py:359-366`); catalog discovery does not (`src/vaultspec_a2a/providers/factory.py:200-224`), so the adapter falls back to its lock-vendored binary. On this host they are 2.1.281 and 2.1.207. In the desktop profile a PATH `claude` overrides the "immutable" capsule.

### oauth-token-setting-unwired | medium | the `CLAUDE_CODE_OAUTH_TOKEN` setting never reaches the child

Status: open; decided by `2026-10-01-provider-binary-policy-adr` D4 (a declared `claude_auth_channel` setting wires the token only under an explicit headless channel), implementation planned under feature `provider-binary-policy`. Original finding: The setting exists (`src/vaultspec_a2a/control/infra_config.py:508`) but no production code reads it; `.env` loads into settings, not `os.environ`, and `VAULTSPEC_*` is scrubbed from children (`src/vaultspec_a2a/workspace/environment.py:159`). `.env.example` tells operators the Claude lane authenticates with it, and the test prerequisite counts it as a credential, so the probe passes while the production child is unauthenticated.

### windows-shell-spawn | medium | Windows provider spawns go through a `cmd.exe` shell

Status: open; unverified on a real Windows host. The default Windows path is `create_subprocess_shell(list2cmdline(...))` (`src/vaultspec_a2a/providers/_subprocess.py:257-270`) for Claude `node`, Codex `.cmd`, Kimi, and the catalogs; `list2cmdline` leaves `&` and `%` unescaped, the BatBadBut class.

### capsule-integrity-and-node-skew | medium | bundled-runtime integrity is unchecked and Node pins disagree

Status: open. Capsule validation checks file existence only (`src/vaultspec_a2a/desktop/profile.py:313-335`) and the manifest carries no digests by design; `.node-version` is 26.8.1 (checked only at init), the Docker image uses floating `node:22-slim` (`service/docker/prod.Dockerfile:16,119`), and the desktop-profile ADR says the capsule ships Node 22. There is no runtime `node --version` probe.

### kimi-provisioning-drift | medium | Kimi code, settings, and CI target different products and versions

Status: open; contained because the lane is unadmitted. Code and settings target "Kimi Code 0.28.1" with `~/.kimi-code` (`src/vaultspec_a2a/providers/_factory_commands.py:98`), CI installs `kimi-cli==1.49.0` (`.github/workflows/test.yml:224`), and the pin constant and Git-Bash readiness check promised by `2026-07-17-kimi-provider-adr` do not exist.

### compose-provisions-no-lane | medium | the Compose worker image provisions no admitted provider lane

Status: open. The prod worker image carries Node 22, the vendored Claude binary, and the retired Gemini CLI (`service/docker/prod.Dockerfile:96-98`) but no `codex`; the worker environment has no provider credentials (`service/docker-compose.prod.yml:57-85`) and the agent user's HOME is `/nonexistent`; base images use floating tags.

### orphan-detection-generation | medium | orphaned runs are not bound to the worker generation that ran them

Status: open. `control_actions.worker_generation` carries the writer generation, not the worker process generation (`src/vaultspec_a2a/control/thread_service.py:441`); the watchdog restarts the worker without reconciling its runs (`src/vaultspec_a2a/control/worker_management.py:715-760`); only gateway startup demotes to RECONCILING (`src/vaultspec_a2a/control/recovery_authority.py:86`), so an orphan waits for the 90 s lease expiry. Conversely a gateway restart demotes runs a surviving standalone worker still executes.

### leaseless-redispatch | medium | a second, lease-less recovery path survives beside the coordinator

Status: open; W02.P03.S11 owns it. `redispatch_reconciling_threads` (`src/vaultspec_a2a/control/dispatch.py:414-521`) re-dispatches up to 100 runs at startup without a lease (`src/vaultspec_a2a/api/app.py:661-670`), contrary to the state-truthfulness amendment's single-coordinator rule.

### stream-resumption | medium | event streams cannot resume and can miss the terminal frame

Status: open; decided by `2026-10-01-stream-resumption-adr` (durable per-run event sequence and bounded replay), implementation planned under feature `stream-resumption`. Original finding: SSE frames carry no `id:` (`src/vaultspec_a2a/streaming/sse_frames.py:505-507`), there is no `Last-Event-ID` handling or replay buffer, and run status is read before the subscription is attached (`src/vaultspec_a2a/api/thread_stream.py:150,229-237`), so a terminal event relayed in between leaves a stream that heartbeats forever. The per-thread sequence lives in worker memory and resets on restart (`src/vaultspec_a2a/streaming/emitters.py:148-200`). Agent Server and A2A both define a resumable or snapshot-first subscription (research, streaming section).

### content-derived-idempotency | medium | follow-up idempotency keys are derived from message content

Status: fixed in P01.S03 of `2026-10-01-run-continuation-plan`: the messages verb requires a client-supplied `Idempotency-Key` and answers 422 without one; the content-derived default is deleted (`src/vaultspec_a2a/thread/idempotency.py`). Earlier status: open; decided by `2026-10-01-run-continuation-adr` (content-derived keys are retired for the messages verb in favour of a required client-supplied idempotency key), implementation planned under feature `run-continuation`. Original finding: The default key hashes thread, agent, and content (`src/vaultspec_a2a/thread/idempotency.py:29-33`), so a second identical "continue" in one run silently returns `dispatched=False` (`src/vaultspec_a2a/control/message_service.py:92-98`). A2A deduplicates on a client-supplied `messageId`.

### postgres-checkpointer-single-connection | medium | the Postgres checkpointer runs on one connection with no pool or reconnect

Status: fixed in P03.S18 (`src/vaultspec_a2a/database/checkpoints.py:104-149`): the Postgres checkpointer is now backed by a sized `AsyncConnectionPool`. Original finding: `from_conn_string` opens a single psycopg `AsyncConnection` (`src/vaultspec_a2a/database/checkpoints.py:318-322`), serializing every run's checkpoint writes and disabling checkpointing until restart if the connection drops. The saver accepts an `AsyncConnectionPool`.

### permission-fallback-fails-open | medium | an unoffered permission option id falls back to the first offered option

Status: fixed in P04.S24 (`src/vaultspec_a2a/providers/_acp_rpc_handlers.py:630-650`): an answer naming an option that was never offered is now refused rather than substituted. Original finding: probe-confirmed. On an id mismatch the handler substitutes the first offered option (`src/vaultspec_a2a/providers/_acp_rpc_handlers.py:626-634`); the adapter orders options `allow_always`, `allow`, `reject`, so an autonomous rejection whose reject option lacks an id resolves to `allow_always`, contradicting `_denial_option_id` (`:385-394`).

### always-allow-persisted-by-cli | medium | a supervised "always allow" is persisted by the CLI outside a2a's control

Status: open; decided by `2026-10-01-tool-permission-model-adr` (a new a2a-owned `permission_rules` table replaces the suppressed CLI "always" option with a scoped, expiring, attributed grant), implementation planned under feature `tool-permission-model`. Original finding: destination unverified live. The interrupt forwards every option including `allow_always` (`src/vaultspec_a2a/graph/nodes/worker.py:674-681`) and the adapter returns SDK suggestions as `updatedPermissions`, whose destinations include local and project settings. Combined with the settings-source finding, a rule written this way can widen later autonomous runs. ACP assigns remembering "always" to the client.

### tool-decision-audit | medium | permission decisions are only partially and anonymously audited

Status: open; decided by `2026-10-01-tool-permission-model-adr` (one attributed `permission_logs` sink for every decision on every lane), implementation planned under feature `tool-permission-model`. Original finding: `permission_logs` is written only for human responses, with `agent_id=None` and no responder identity (`src/vaultspec_a2a/control/permission_service.py:834-845`, `src/vaultspec_a2a/database/models.py:526-535`); autonomous approvals and denials, Codex decisions, cross-project refusals, and terminal creation reach only process logs.

### dead-require-approval-for | medium | `require_approval_for` is parsed but never enforced

Status: open; decided by `2026-10-01-tool-permission-model-adr` (`require_approval_for` gets a reader and the provider CLI's own tool-rule vocabulary), implementation planned under feature `tool-permission-model`. Original finding: Declared at `src/vaultspec_a2a/team/team_config.py:275-292` with no reader; `vaultspec-coder.toml` sets it to `["fs.writeTextFile"]`, advertising a gate that does not exist, the same zero-caller defect class the clarification rule names.

### child-env-denylist | medium | provider child environments are built by denylist

Status: open. `resolve_env_vars` scrubs known names (`src/vaultspec_a2a/workspace/environment.py:101-161`) but passes `GITHUB_TOKEN`, `GH_TOKEN`, `NPM_TOKEN`, cloud credentials, `SSH_AUTH_SOCK`, and `KUBECONFIG`; terminal children accept agent-chosen env overrides unfiltered (`src/vaultspec_a2a/providers/_acp_rpc_terminal_handlers.py:146-182`); the authoring bridge tokens sit in the CLI's environment (`src/vaultspec_a2a/providers/acp_chat_model.py:410-423`) and so reach every Bash child.

### unpinned-harness-mcp | medium | harness MCP servers are fetched at runtime without version pins

Status: partially fixed. P04.S29 pins the launch interpreter to the project Python (`src/vaultspec_a2a/providers/_harness_mcp_registry.py:185`, `--python`); the package version is deliberately left unpinned, and the resulting client/daemon skew is now made fail-closed by P07.S37 of `2026-09-30-langgraph-conformance-plan` (see that audit's `rag-client-daemon-version-skew`, fixed). Original finding: reproduced. The registry launches `uvx --from vaultspec-rag[mcp]` and `vaultspec-core` with neither a package version nor a `--python` pin (`src/vaultspec_a2a/providers/_harness_mcp_registry.py`), and the contract check verifies tool names, not code (`src/vaultspec_a2a/providers/_mcp_contract.py:330`). Because `uvx` takes the host's default interpreter, a host whose default Python is older than 3.13 cannot resolve `vaultspec-rag` at all: on this environment's image (default 3.11) seventeen unit tests that compose the server fail with a bare resolution error, and all seventeen pass with `UV_PYTHON=3.13`. Desktop disables runtime acquisition.

### provider-transcripts-unlinked | medium | provider-native session ids and transcripts are neither recorded nor linked

Status: open; decided by `2026-10-01-provider-binary-policy-adr` D3 (every run records the provider-native session id alongside its runtime identity), implementation planned under feature `provider-binary-policy`. Original finding: The ACP `sessionId` is read (`src/vaultspec_a2a/providers/_acp_session.py:632`) but never logged or persisted; each turn writes a fresh Claude transcript into the operator's `~/.claude/projects` under their retention policy. Codex runs `ephemeral: true` in a deleted per-run home, so no rollout survives.

### compaction-view-only | medium | context compaction is a local view with a rough estimator and misfires

Status: open; no ADR governs compaction. `should_compact` fires at 80% of one global 120k budget (`src/vaultspec_a2a/domain_config.py:120`) but `compact_context` acts only above 100% while the debug log reports `compacted=True`; tool-call arguments are not counted; the kept suffix can start with an orphan `ToolMessage`; rules, anchoring, and up to 20k mounted tokens are outside the budget; the "summary" is a fixed placeholder; and `add_messages` without `RemoveMessage` means checkpointed history only grows (`src/vaultspec_a2a/thread/state.py:221`).

### prompt-order-vs-cache | medium | dynamic context precedes history, defeating prefix caching

Status: open; size unmeasured because ACP reports no usage. Anchoring, mounted documents, and feedback are placed before the history (`src/vaultspec_a2a/graph/nodes/worker.py:141-160`).

### token-accounting-gaps | medium | cache and reasoning token counts are dropped; ACP lanes report none

Status: fixed in P05.S32 (`src/vaultspec_a2a/graph/nodes/worker.py:655-657,704-706`, `src/vaultspec_a2a/database/models.py:843-845`): cache-read, cache-write, and reasoning token counts now flow from turn usage into cost tracking. Original finding: Codex maps cache-read, cache-creation, and reasoning tokens (`src/vaultspec_a2a/providers/_codex_protocol.py:295-315`) but `_turn_token_usage` keeps only input/output/total (`src/vaultspec_a2a/graph/nodes/worker.py:518-535`) and `cost_tracking` has no columns for them (`src/vaultspec_a2a/database/models.py:821-850`).

### json-log-formatter | medium | the JSON log formatter loses records and carries no schema, zone, or redaction

Status: fixed in P05.S31 (`src/vaultspec_a2a/utils/logging.py:198-199,258-362`): the formatter now carries a schema field and UTC millisecond timestamps, redacts credential-shaped values, and serializes with `default=_json_default` so a non-JSON extra no longer drops the record. Original finding: latent for current call sites. `json.dumps(log_data)` has no `default=` (`src/vaultspec_a2a/utils/logging.py:212`), so a non-JSON extra drops the record; timestamps are zone-less local time (`:196`); there is no schema version, pid, service, or sequence field, and no central redaction filter (a probe logged an API-key-shaped extra verbatim).

### correlation-stops-at-provider | medium | correlation ids do not reach provider logs or LangSmith runs

Status: fixed in P05.S31: a `log_context` ContextVar scope now carries `thread_id`/`dispatch_id` to every log call within it (`src/vaultspec_a2a/utils/logging.py:204-220`, `src/vaultspec_a2a/worker/executor.py:473`), and the graph `RunnableConfig` now carries `run_name`, `tags`, and `metadata` (`src/vaultspec_a2a/worker/executor.py:85-95`). Original finding: There is no ContextVar log context; `runtime_log_extra` omits `thread_id` and `dispatch_id` (`src/vaultspec_a2a/providers/_acp_auth.py:49-87`); the graph `RunnableConfig` carries no `run_id`, `tags`, or `metadata` (`src/vaultspec_a2a/worker/executor.py:515-518`); no `TRACEPARENT` reaches CLI children.

### no-durable-event-log | medium | there is no GenAI span model and no durable per-run event log

Status: open; decided by `2026-10-01-stream-resumption-adr` (S5: an append-only `run_events` table), implementation planned under feature `stream-resumption`. Original finding: No `gen_ai.*` span or attribute exists; the event sequence is in worker memory; the relay drops by design; and the acceptance evidence bundle carries `last_sequence: 0` with no events. The durable records are the checkpoint plus the permission, control-action, recovery, and cost tables.

### mounted-content-checkpointed | medium | mounted vault content is persisted in every checkpoint

Status: fixed in P01.S04 (`src/vaultspec_a2a/graph/nodes/vault_reader.py:240-245`, `src/vaultspec_a2a/graph/nodes/worker.py:1200`): `mount_node` now returns only `vault_index`, and mounted content is recomputed per invocation as a local variable, never a checkpointed channel. Original finding: diverges from `2026-03-03-blackboard-content-mounting-adr` §2.1 ("never persisted as content"). `mount_node` returns up to 20k tokens as a channel value (`src/vaultspec_a2a/graph/nodes/vault_reader.py:224-263`) that LangGraph checkpoints each super-step; `aprune` is defined but never called (`src/vaultspec_a2a/database/checkpoints.py:196`).

### terminal-frame-race | medium | a viewer attaching in a narrow window never receives the terminal frame

Status: fixed in P03.S17 (`src/vaultspec_a2a/api/thread_stream.py:244-262`): the stream now subscribes before reading durable status, closing the window this finding described. The relay fan-out and `clear_thread_state` timing noted below remain an external-plan concern (W04.P09.S27 of `2026-08-05-served-capability-contract-plan` and W04.P09.S46). Original finding: ordering confirmed in code, timing not reproduced; R6 gap owned by W04.P09.S27 of `2026-08-05-served-capability-contract-plan` and W04.P09.S46. The stream reads durable status (`src/vaultspec_a2a/api/thread_stream.py:229`) before it subscribes (`:113,150`); the relay fans out before it persists (`src/vaultspec_a2a/api/internal.py:206,219`); terminal acceptance awaits a checkpoint read of up to 10 s (`src/vaultspec_a2a/control/event_handlers.py:639`); and `clear_thread_state` then unsubscribes late attachers (`src/vaultspec_a2a/streaming/subscribers.py:155`). Related to `stream-resumption` above.

### backpressure-invisible | medium | subscriber queue overflow is silent to the consumer

Status: fixed in P03.S17 (`src/vaultspec_a2a/api/thread_stream.py:118-135,190-205`): a bounded `progress_dropped` resynchronization frame now signals backpressure drops to the consumer. Original finding: Drop-oldest only logs (`src/vaultspec_a2a/streaming/fanout.py:120-137`); `progress_dropped` is emitted only for oversized frames (`src/vaultspec_a2a/streaming/sse_frames.py:530-549`); R6 requires a bounded resynchronization indication.

### container-bypasses-serve-path | medium | the container entrypoint bypasses the owned serve path and its graceful shutdown

Status: fixed in P03.S20 (`service/docker/prod.Dockerfile:82,103,148`, `service/docker-compose.prod.yml:19,67`): both stages now run through the owned serve entry (`vaultspec-a2a serve` / `python -m vaultspec_a2a.worker`) with `stop_grace_period` set; see `compose-gateway-binds-loopback` below for a reopened residual on the gateway bind host. Original finding: measured. `service/docker/prod.Dockerfile:93,132` run `uvicorn --factory` directly, so `timeout_graceful_shutdown` (`src/vaultspec_a2a/api/app.py:797`) is never applied; with one open stream the server had not exited 8 s after `should_exit`, and Docker's default 10 s stop then SIGKILLs before the lifespan drains admission, closes the database, and flushes telemetry. No compose file sets `stop_grace_period`.

### ipc-bridge-wedge | medium | the worker-to-gateway event bridge can wedge, reorder, and duplicate

Status: fixed in P03.S19 (`src/vaultspec_a2a/worker/ipc.py:74,302,317,459,471,518,542`): batches now split and are bounded, a failed batch is re-queued, and terminal events are protected from eviction. The IPC client timeout residual stays open, owned by P06.S34, in progress (`ipc-client-timeout-shorter-than-terminal-confirmation` below). Original finding: not reproduced. `flush_events` posts the whole buffer, up to 10,000 events (`src/vaultspec_a2a/worker/ipc.py:198,318`), the gateway rejects batches over 4 MiB (`src/vaultspec_a2a/api/internal.py:407`), and the worker re-queues without splitting (`src/vaultspec_a2a/worker/ipc.py:339`), so a post-outage backlog can 413 forever; worker drop-oldest does not protect terminal events; the deferred and immediate terminal flushes (`src/vaultspec_a2a/worker/state_projection.py:496`) share no lock; and the 10 s client timeout (`src/vaultspec_a2a/worker/ipc.py:75`) is shorter than the gateway's worst-case terminal confirmation.

### blocking-engine-discovery | medium | engine discovery blocks the worker event loop after every authoring run

Status: fixed in P02.S13: `resolve_engine()`/`resolve_engine_with_retry` are now offloaded via `asyncio.to_thread` at every call site, including the one already handled (`src/vaultspec_a2a/worker/_authoring_close.py:45,54`, `src/vaultspec_a2a/worker/graph_lifecycle.py:785-885`, `src/vaultspec_a2a/authoring/client.py:206`). Original finding: `src/vaultspec_a2a/worker/_authoring_close.py:45` calls synchronous `resolve_engine()` (file reads plus `httpx.get(timeout=3.0)` per candidate, `src/vaultspec_a2a/authoring/discovery.py:253`), and `src/vaultspec_a2a/authoring/client.py:203` calls the bearer resolver synchronously on a 401, on the loop that also carries up to five runs, the heartbeat, and `/dispatch`. The hazard is acknowledged and handled elsewhere (`src/vaultspec_a2a/worker/authoring_binding.py:70-74`).

### nostream-tag-ignored | low | supervisor routing tokens leak to clients because `TAG_NOSTREAM` is ignored under `astream_events` v2

Status: fixed in P01.S07/P03.S18-19: ingest now runs on LangGraph's public stream modes rather than `astream_events` v2 (`src/vaultspec_a2a/streaming/ingest.py:549`), and the `nostream` tag is honoured by the stream layer itself rather than filtered by hand in the transformer (`src/vaultspec_a2a/streaming/transformer.py:188-190`). Original finding: Scripted: three tagged `on_chat_model_stream` events under v2 versus none under `stream_mode="messages"`; the transformer does no tag filtering (`src/vaultspec_a2a/streaming/transformer.py:530-555`).

### validation-errors-never-cleared | low | `validation_errors` accumulates for the life of a run

Status: fixed by P01.S05 and P01.S06 of `2026-09-30-langgraph-conformance-plan` (`src/vaultspec_a2a/graph/nodes/worker.py:741-776`, `src/vaultspec_a2a/graph/nodes/phase_gate.py:332-348`): the exec worker and the document gates now write the channel's own `[]` clear signal when a phase advances or a gate approves. Original finding: The reducer clears only on an explicit empty list (`src/vaultspec_a2a/thread/state.py:98-105`); producers only append; anchoring shows them as active in every later prompt (`src/vaultspec_a2a/context/anchoring.py:69-73`), leaking research revision notes into ADR and plan phases.

### langgraph-12-primitives-unused | low | node timeouts, error handlers, and destinations are hidden by the typed builder

Status: fixed in P01.S02/P01.S03 and P01.S10 of `2026-09-30-langgraph-conformance-plan`: `_TypedBuilder` now also types `error_handler`, `destinations`, and `timeout` (`src/vaultspec_a2a/graph/compiler.py:92-180`), `destinations` are declared on `Command`-returning nodes (`compiler.py:674`), node timeouts are applied via `TimeoutPolicy` (`compiler.py:1095`), and retries carry `jitter=True` (`src/vaultspec_a2a/graph/_compiler_retry.py:161-195`). Original finding: `_TypedBuilder` narrows `add_node` to `metadata` and `retry_policy` (`src/vaultspec_a2a/graph/compiler.py:85-111`), hiding `timeout=`, `error_handler=`, `destinations=`, `defer=`, and `cache_policy=` present in 1.2.11; a hand-written stall watchdog backs up `step_timeout` (`src/vaultspec_a2a/streaming/ingest.py:42-155`); throttling retries have no jitter (`src/vaultspec_a2a/graph/_compiler_retry.py:143-150`); `Command`-returning nodes declare no destinations, so `get_graph()` draws them to `__end__`.

### no-runtime-context | low | run identity lives in checkpointed state and closures instead of Runtime context

Status: fixed in P01.S05 (`src/vaultspec_a2a/graph/run_context.py:23-37`, `RunContext`; `src/vaultspec_a2a/graph/compiler.py:1090`, `context_schema=RunContext`): run identity is now carried in a typed Runtime context passed on ingest and resume. Original finding: medium refactor because providers bind the workspace at construction. `thread_id` and `workspace_root` are state fields (`src/vaultspec_a2a/thread/state.py:333,338`), workspace and autonomy are closure-bound (hence part of the graph cache key), and `_config_contract.py` works around config injection under postponed annotations, which `context_schema` avoids.

### checkpoint-serde-unhardened | low | checkpoints use permissive msgpack with no encryption

Status: partially fixed in P04.S26 of `2026-09-30-langgraph-conformance-plan`, which configures strict msgpack on each saver (`src/vaultspec_a2a/database/checkpoints.py`); `EncryptedSerializer` remains unconfigured and no Step owns it. Original finding: Default `JsonPlusSerializer`; neither strict msgpack nor `EncryptedSerializer` is configured although state is JSON-only by design and transcripts carry workspace code.

### dead-task-queue-tool | low | `mark_task_complete` is never offered to a real model

Status: open. It has no `bind_tools` call or MCP exposure and only the deterministic test model emits it (`src/vaultspec_a2a/graph/nodes/worker.py:321-357`).

### dependency-floors | low | declared LangGraph floors are far below the APIs the code uses

Status: fixed in P01.S01 (`pyproject.toml:27-29,66`): floors now read `langgraph>=1.2.12,<2`, `langgraph-checkpoint>=4.2.0,<5`, `langgraph-checkpoint-sqlite>=3.1.1,<4`, and `langgraph-checkpoint-postgres>=3.1.2,<4`. Original finding: `pyproject.toml` declares `langgraph>=0.2.16` and checkpoint savers `>=2.0.0`, while the code relies on 1.x injection and checkpoint 4.x APIs (`src/vaultspec_a2a/database/checkpoints.py:183-256`). An unlocked install can resolve an incompatible stack.

### coarse-acquisition-errors | low | acquisition failures collapse into one untyped message

Status: open. Readiness returns "not installed or resolvable" for every failure (`src/vaultspec_a2a/providers/provider_readiness.py:115-131`); the catalog drops `data.details` (`src/vaultspec_a2a/providers/acp_catalog.py:81-102`), so this host's `Claude Code process exited with code 1` surfaced as a bare `-32603 provider error`; `auth_hint()` is Claude-specific even on Kimi (`src/vaultspec_a2a/providers/_acp_auth.py:95-100`).

### antigravity-discovery-only | low | the Antigravity lane is discovery-only with a loose binary lookup

Status: open. It is absent from the supported-execution set (`src/vaultspec_a2a/providers/factory.py:131-142`); lookup is `ANTIGRAVITY_CLI_PATH` accepted on `is_file()`, then `which(agy)`, then hard-coded installer paths (`src/vaultspec_a2a/providers/antigravity_cli.py:31-65`); `ANTIGRAVITY_CLI_HOME` is documented as a login home but used only to find the binary.

### stale-provisioning-docs | low | provisioning docstrings, test resolver, and install hints are stale

Status: partially fixed. The two module docstrings now describe the current run-workspace-projection design (`src/vaultspec_a2a/providers/_codex_config_home.py:1-10`, `src/vaultspec_a2a/providers/_config_home_roots.py:1-7`); the conftest `_on_path` reimplementation and the stale `npm install -g @anthropic-ai/claude-code` hint are unchanged (`src/vaultspec_a2a/conftest.py:98,351`). Original finding: `_codex_config_home.py:7-10` and `_config_home_roots.py:5-7` describe retired workspace projections; the conftest `_on_path` reimplements resolution and accepts `.cmd` on POSIX (`src/vaultspec_a2a/conftest.py:98`); its hint recommends the deprecated `npm install -g @anthropic-ai/claude-code` (`:338`).

### sqlite-shared-checkpoint-file | low | the SQLite checkpoint store defaults to the application database file

Status: open; W02.P04.S15 owns it. Pragmas are correct (WAL, `busy_timeout` 5000 ms, `BEGIN IMMEDIATE`, `src/vaultspec_a2a/database/session.py:82-136`), but the checkpoint DSN defaults to the application file (`src/vaultspec_a2a/control/config.py:450`), putting three writers in two processes on one lock.

### unfenced-status-writers | low | three thread-status writers still bypass the fenced election

Status: open; W02.P03.S82 owns it. `update_thread_status` is called at `src/vaultspec_a2a/control/_event_application.py:249`, `src/vaultspec_a2a/control/verdict_subscriber.py:156`, and `src/vaultspec_a2a/control/repair_transitions.py:52`, against state-truthfulness rule T6.

### lost-failed-event | low | a relay-dropped FAILED event is not recoverable from the checkpoint

Status: open; W02.P03.S14 owns it. The worker relay is a lossy 10k in-memory buffer with three retries (`src/vaultspec_a2a/worker/ipc.py:197-210,304-340`); completion is recoverable from the checkpoint but FAILED is not (`src/vaultspec_a2a/control/recovery_authority.py:227-228`), so such a run waits for its deadline.

### single-run-threads | low | a thread holds exactly one run, with no context grouping or fork

Status: open; decided by `2026-10-01-run-continuation-adr` (a settled run's continuation is a new run carrying an optional `continues_run_id`, a single-parent lineage link rather than a multi-run context grouping), implementation planned under feature `run-continuation`. Original finding: informational. Terminal states only archive (`src/vaultspec_a2a/thread/transitions.py:77-80`) and follow-ups after completion get 409. A2A groups tasks under a `contextId`; Agent Server threads hold many runs and fork from checkpoints.

### per-call-provider-sessions | low | provider sessions last one model call, which is sound for recovery but costly

Status: accepted trade-off, recorded for visibility. ACP spawns a process and `session/new` per call (`src/vaultspec_a2a/providers/acp_chat_model.py:540-565,830-845`); Codex starts an ephemeral app-server thread per call (`src/vaultspec_a2a/providers/codex_chat_model.py:539-550`). The checkpoint is therefore the only transcript, which makes recovery and forking provider-agnostic, at the cost of re-sending the full transcript, spawn latency, and lost provider-native context on every call. The `session/load` path (`src/vaultspec_a2a/providers/_acp_session.py:621-623`) has no production caller.

### terminal-allowlist-not-boundary | low | the terminal allowlist is bypassable and output caps are unenforced

Status: latent (no served persona enables `terminal`); P01.S02 owns it. The allowlist admits shells and interpreters and matches `Path(command).stem`, so `./python.evil` and `bash -c` payloads pass (probe-confirmed); `outputByteLimit` is ignored, `truncated` is always false, and terminals have no count or lifetime cap (`src/vaultspec_a2a/providers/_acp_rpc_terminal_handlers.py:47-417`).

### read-cap-bypass | low | `fs/read_text_file` accepts `limit=-1` and reads the whole file

Status: latent; P01.S01 of the ACP v1 client-wire plan owns it. `min(-1, cap)` then `read(-1)` returns everything (probe: 5,000,000 characters); the cap counts characters not bytes, `line` is ignored, and `sessionId` is not checked (`src/vaultspec_a2a/providers/_acp_rpc_handlers.py:175-205,644-684`).

### worker-stderr-truncated | low | the autospawned worker's stderr file is truncated on every respawn

Status: open. `open("wb")` on a per-port path (`src/vaultspec_a2a/control/worker_management.py:160`, `src/vaultspec_a2a/control/_worker_health.py:245-247`) wipes the previous generation's pre-logging boot traceback.

### rule-cache-and-double-load | low | the rule cache never hits and Claude lanes likely load project rules twice

Status: open; double load unverified against the pinned adapter. A new `RuleManager` per call defeats its mtime cache (`src/vaultspec_a2a/graph/nodes/worker.py:109`); with default `settingSources` the adapter also loads project `CLAUDE.md` and `.claude/rules`.

### machine-path-in-evidence | low | a committed acceptance artifact carries a local Windows user path

Status: open. `execution-evidence.json` under `src/vaultspec_a2a/acceptance/tests/artifacts/runs/` records `workspace_root` under a named user's `AppData\Local\Temp`, against the machine-specific-files rule.

### sync-preflight-io | low | run-start and readiness do synchronous filesystem work inline

Status: open. Workspace resolution, preset TOML loading, and `verify_harness` run inline (`src/vaultspec_a2a/api/routes/_gateway_run_start.py:187-208`, `src/vaultspec_a2a/api/routes/gateway.py:626-656`); presets-list already offloads.

### telemetry-middleware-shape | low | the telemetry middleware wraps SSE and ends spans at header time

Status: open. `TelemetryMiddleware` is a `BaseHTTPMiddleware` (`src/vaultspec_a2a/telemetry/middleware.py:78`), adding a hop per streamed chunk and never measuring stream duration; the body-limit middleware is correctly pure ASGI.

### beyond-loopback-hardening | low | the edge is hardened for loopback only

Status: open; acceptable under the loopback contract, blocking for any networked or A2A use. Compose publishes the gateway and Jaeger on all interfaces (`service/docker-compose.prod.yml:21`); unauthenticated `/health` discloses the pid and worker state (`src/vaultspec_a2a/api/app.py:907`); there is no Host/Origin validation (which MCP requires of local HTTP servers) and no rate limiting; `/internal/*` shares the public listener; `mcp_host=0.0.0.0` (`src/vaultspec_a2a/control/infra_config.py:647`) is dead configuration.

### contract-fidelity | low | the published contract under-describes streams, errors, and health

Status: open. OpenAPI documents the stream as `application/json` with an empty schema and omits the SSE frame catalog; errors are bare `{"detail"}` rather than typed codes or RFC 9457 problem details; unarmed `/health` returns 200 even when degraded.

## Recommendations

Defect fixes that restore an accepted decision or close a security hole, each small and local:

- Make blocked phase gates route back to the supervisor and send unparseable supervisor output back instead of to FINISH, with tests asserting the next hop (`phase-gates-do-not-block`, `unparseable-route-finishes`).
- Resolve provider launchers to absolute paths from the service's trusted PATH or the capsule at classification time, never from the agent's PATH or working directory; set `NoDefaultCurrentDirectoryInExePath` on Windows; add a planted-`.venv/bin/node` regression test (`launcher-path-hijack`).
- Pin the Claude lane's posture: `settingSources: []`, persona-derived `disallowedTools`, `dontAsk` on autonomous runs with a refusal when `currentModeId` differs, and a per-run configuration directory (`claude-settings-override-autonomy`, `acp-client-enforcement-unreached`, `always-allow-persisted-by-cli`).
- Fall back to a reject option or a cancelled outcome, never the first offered option (`permission-fallback-fails-open`).
- Scope native reads to the workspace and deny home and `/proc`; serve the WebFetch allowlist posture; stop pre-approving rag tools until the rag server confines itself to its launch root (`unscoped-native-reads`, `cross-project-guard-unreachable`).
- Bind a permission approval to a fingerprint of the exact tool call and re-park on mismatch (`permission-resume-replays-turn`).
- Scope the stream route's database session to the function and add a `checkedout()==0` test (`sse-pins-db-session`).
- Refuse follow-ups on a busy run with a typed 409 and stop feeding the circuit breaker with backpressure and semantic refusals; allow one half-open probe (`followup-on-busy-run`, `breaker-fed-by-backpressure`).
- Stop discarding refreshed Codex credentials: a persistent a2a-owned Codex home or a locked write-back, with explicit keyring detection (`codex-auth-copy-no-writeback`).
- Stamp message timestamps at production time and project unknown rather than now (`invented-message-timestamps`); render ACP prompts with roles and tool results through one shared renderer (`acp-prompt-flattening`); keep a redacted ACP stderr tail (`acp-stderr-invisible`).
- Point the container at the owned serve entry and set `stop_grace_period` (`container-bypasses-serve-path`); offload `resolve_engine` and rule loading to threads (`blocking-engine-discovery`, `blocking-io-on-loop`).

Hardening that needs no new decision: the worker resume path through receipt-based checkpoint evidence and `ainvoke(None)` with a SIGKILL test (`crash-resume-reingests`); a pooled Postgres checkpointer (`postgres-checkpointer-single-connection`); a separate SQLite checkpoint file (`sqlite-shared-checkpoint-file`); per-invocation model instances (`shared-model-instances`); preset recursion limits and per-phase revision caps (`preset-recursion-limit-ignored`, `unbounded-review-loops`); bounded, locked, split-on-413 IPC batches that protect terminal events (`ipc-bridge-wedge`); snapshot-after-subscribe streams with `id:` sequences and a backpressure sentinel (`terminal-frame-race`, `backpressure-invisible`, `stream-resumption`); JSON formatter hardening with a ContextVar correlation context (`json-log-formatter`, `correlation-stops-at-provider`); raised LangGraph dependency floors (`dependency-floors`); pinned Codex in CI with `npm audit signatures`, aligned Node pins, and removal of the retired Gemini image stage (`no-cli-version-identity`, `capsule-integrity-and-node-skew`, `compose-provisions-no-lane`).

Decisions a follow-on ADR must make; this audit does not make them:

- Whether the service becomes A2A-protocol capable, reversing the 2026-07-15 amendment to `2026-02-26-protocol-ecosystem-bridge-adr`, and if so: optional adapter extra or first-class edge, `contextId` as a multi-run thread or a single run, the Agent Card's skill source under the served-profile rule, and the carrier for workspace and actor tokens (`no-a2a-protocol`, `single-run-threads`). A cross-repository edge change is a contract event under `2026-07-14-a2a-edge-conformance-adr` R6.
- The multitask and continuation model for input on a busy or finished run: Agent Server's same-thread `enqueue`/`interrupt`/`rollback`/`reject`, Codex's steer, or A2A's new task in the same context (`followup-on-busy-run`, `single-run-threads`).
- Context-window policy: persisted summarization sized per lane model profile, pair-preserving trimming, budgeting of rules and mounted content, and stable-prefix prompt order; no ADR governs compaction today (`compaction-view-only`, `prompt-order-vs-cache`, `mounted-content-checkpointed`).
- Provider binary and credential policy: default to the lock-vendored Claude binary or the host one, version ranges attached to lane proofs, recorded binary identity in run evidence, and whether provider-native sessions are resumed or remain per call (`claude-binary-split`, `no-cli-version-identity`, `per-call-provider-sessions`, `oauth-token-setting-unwired`).
- A unified, durable tool-permission model across lanes: one policy input (including `require_approval_for`), an a2a-owned "always" rule table with scope and expiry, and an attributed decision log (`tool-decision-audit`, `dead-require-approval-for`, `always-allow-persisted-by-cli`).
- A durable per-run JSONL event log and GenAI span model: schema, retention, content-capture posture, and its relation to checkpoint history (`no-durable-event-log`, `provider-transcripts-unlinked`, `token-accounting-gaps`).

## Execution and plan-close review, 2026-09-30

Findings raised while executing `2026-09-24-architecture-review-plan` and by its plan-close review. The review failed the plan on one critical and two high findings; P01.S08, P03.S14, P03.S17, P03.S19, P03.S20, P04.S23, P04.S25 and P04.S27 were reopened and fixed, and the remainder are recorded here with their owner.

### compose-gateway-binds-loopback | critical | the gateway container bound 127.0.0.1 after P03.S20 moved it to the serve entry

Status: fixed in the P03.S20 reopen. The serve entry binds `settings.host`, whose default is loopback (`src/vaultspec_a2a/control/infra_config.py`, `host`), and only the worker stage set its bind host, so every Compose variant published a dead port and refused the worker's relay while the in-container healthcheck passed. The gateway stage now sets `VAULTSPEC_A2A_HOST=0.0.0.0` (`service/docker/prod.Dockerfile`), and `src/vaultspec_a2a/control/tests/test_deployment_names.py` holds every served stage (with inherited ENV) and every Compose file to a non-loopback bind; the new test fails on the prior Dockerfile. Residual: the Compose healthchecks still probe `localhost` from inside the container, so they would not catch a regression on their own; probing the container's own hostname would. Residual fixed in P06.S44: every gateway and worker healthcheck in `service/docker-compose.dev.yml`, `service/docker-compose.integration.yml` and `service/docker-compose.prod.yml` probes `socket.gethostname()`, held by `test_every_served_healthcheck_probes_the_container_by_its_own_hostname`; not yet run under Docker in this environment.

### grep-pre-approved-host-wide | high | P04.S23 left Grep pre-approved by bare name, readable anywhere on the host

Status: fixed in the P04.S23 reopen; supersedes `grep-unscoped-read`, whose stated mitigation was wrong because a bare allowlist entry never reaches the permission rung. `native_read_floor_rules` (`src/vaultspec_a2a/providers/_native_read_tools.py`) withholds any floor tool whose rule grammar takes no path when the run has a workspace, so the floor composes `Read(<ws>/**)` and `Glob(<ws>/**)` only. The session's working directory is the workspace (`src/vaultspec_a2a/providers/_acp_session.py`, `setup_session`), where the CLI's own posture lets a read-only built-in proceed; an out-of-workspace Grep is raised to the rung, whose prose title does not match any allowlisted name, so an autonomous run refuses it. Residual: that in-workspace Grep proceeds unprompted rests on the pinned CLI's working-directory posture and has no live proof yet; if it does not, Grep degrades to refused rather than to host-wide.

### followup-verb-has-no-reachable-success | high | after P03.S14 the messages verb refuses in every lifecycle state while the contract advertised 202

Status: fixed in the P03.S14 reopen (contract half); absorbs `followup-continuation-seam-unreachable`. The route now states on the edge that no run state admits a follow-up and that its 202 is not currently served (`src/vaultspec_a2a/api/routes/_gateway_action_endpoints.py`, `run_message_endpoint`), backed by `test_every_lifecycle_status_resolves_to_a_typed_answer`. The 409 `code` is narrowed from the whole failure vocabulary to `RunMessageRefusalCode` (`src/vaultspec_a2a/api/schemas/gateway.py`), so `openapi.json` names only the five codes the refusal carries. The continuation model itself remains the user's decision; the verb stays published so a caller learns the refusal by code.

### run-busy-refusal-contract | medium | the follow-up verb's refusal changed shape on the dashboard edge

Status: open, cross-repository; updates the execution finding of the same name. `/v1/runs/{run_id}/messages` refuses with `409 {"detail": {"code", "message"}}` where `code` is `RunMessageRefusalCode` (`input_required`, `terminal`, `conflict`, `incompatible_state`, `run_busy`) instead of a string `detail`, and its 202 is documented as not served. The dashboard must be told as a contract event.

### message-timestamp-nullable-contract | low | a replayed message's timestamp may now be null on the dashboard edge

Status: open, cross-repository; from P05.S30. `MessageSnapshot.timestamp` is `datetime | None` in `openapi.json`: messages are stamped with their production time (`src/vaultspec_a2a/thread/snapshots.py`, `stamp_message_created_at`) when a run's input is accepted, a worker turn finishes and a clarification is answered, and a message recorded before that reports no time rather than the snapshot's read time. The dashboard must render a null time; only pre-upgrade history carries one.

### prompt-render-role-headers-are-forgeable | medium | message content could reproduce the renderer's role headings

Status: fixed in the P04.S27 reopen. A content line that reads as a role heading (any depth, any case) is escaped rather than removed, and a speaker name is held to one line (`src/vaultspec_a2a/providers/_prompt_render.py`, `_defused`, `speaker_label`), so a tool result or another agent's output cannot open a system section. `src/vaultspec_a2a/providers/tests/test_prompt_render.py` drives forged headings through both lanes' rendering.

### codex-credential-writeback-blocks-the-event-loop | medium | the Codex write-back held a polled file lock on the worker loop

Status: fixed in the P04.S25 reopen. The config-home cleanup, which carries the write-back, runs through `asyncio.to_thread` (`src/vaultspec_a2a/providers/codex_chat_model.py`), and credential bytes that do not decode as UTF-8 are reported and never published over the operator's login (`src/vaultspec_a2a/providers/_codex_auth.py`, `write_back_refreshed_credential`), covered by `test_bytes_that_are_not_a_login_are_never_written_back`.

### sse-id-without-resumption | medium | P03.S17 put a restartable in-memory sequence in the SSE id field

Status: fixed in the P03.S17 reopen. No frame carries an SSE `id` (`src/vaultspec_a2a/streaming/sse_frames.py`, `_encode`): the sequence restarts with the worker and nothing buffers frames for a `Last-Event-ID`, so an id promised a resumption the stream does not offer and invited deduplication that would drop a restarted worker's events. The sequence stays in the body. A resumable stream needs a durable sequence and a replay buffer, which the `stream-resumption` finding still owns.

### settled-prune-on-the-relay-critical-path | medium | P01.S08's prune ran inside the terminal relay request

Status: fixed in the P01.S08 reopen. The prune is scheduled as a tracked background task (`src/vaultspec_a2a/control/event_handlers.py`, `_schedule_settled_history_prune`), the gateway lifespan waits for pending prunes before the checkpointer closes (`src/vaultspec_a2a/api/app.py`, `settle_pending_checkpoint_prunes`), and a failed or cancelled SQLite prune rolls back on the saver's shared connection (`src/vaultspec_a2a/database/checkpoint_retention.py`, `_prune_sqlite`). `test_a_failed_sqlite_prune_leaves_nothing_for_the_next_write_to_commit` uses a real trigger; the prior code lost every superseded write there.

### requeued-ipc-batch-drops-terminal-events | medium | P03.S19 protected terminals on append but not on re-queue

Status: fixed in the P03.S19 reopen. A failed batch goes back ahead of events that arrived while it was in flight and the cap is restored by the same outcome-preserving eviction a full buffer uses (`src/vaultspec_a2a/worker/ipc.py`, `_requeue_failed_batch`, `_pop_evictable_event`); the drop log counts lost outcomes. `test_a_refused_batch_keeps_its_outcome_when_the_buffer_refilled` holds and refuses a real batch; the prior slice dropped the terminal.

### step-id-carried-forward-in-a-test-docstring | medium | test docstrings cited plan Step ids

Status: fixed. The five Step-id prefixes in `src/vaultspec_a2a/control/tests/test_active_project_identity.py` were replaced by the invariant each test states.

### drained-settle-leaves-the-failure-stash-behind | low | the drain path returned before draining the failure stashes

Status: fixed. `_settle_run` drains both stashes before the `INGEST_DRAINED` return (`src/vaultspec_a2a/worker/_dispatch_settlement.py`).

### seated-runtime-also-shadows-the-saver-store | low | the drain workaround's seated runtime replaced the graph's store

Status: fixed; refines `langgraph-v2-drops-run-control`. The seated runtime carries the graph's own store (`src/vaultspec_a2a/streaming/ingest.py`, `_config_carrying_control`), and `test_shutdown_drain_stops_the_run_between_nodes_without_settling_it` now compiles its graph with a store that a node writes through; without the fix the node sees no store.

### langgraph-v2-drops-run-control | medium | astream_events v1/v2 does not forward the control keyword to the Pregel loop

Status: worked around in P01.S06; upstream defect. LangGraph 1.2.12 `astream_events` forwards `control` only for `version="v3"`, so a `RunControl` passed to a v2 stream never reaches the loop. The worker seats `Runtime(control=..., store=...)` under LangGraph's private `CONFIG_KEY_RUNTIME` key (`src/vaultspec_a2a/streaming/ingest.py`, `_config_carrying_control`); a rename of that key fails at import, and `src/vaultspec_a2a/worker/tests/test_executor_drain.py` detects a drain that stops working. Recommendation: report upstream and drop the workaround once v2 forwards `control`, or move ingest to the v3 event API.

### drain-redelivery-reported-complete | high | a run drained at shutdown was reported completed when its action was delivered again

Status: fixed in P02.S12. A drained run leaves a checkpoint with no pending writes, which the ingest preflight read as "ran to END"; the preflight now reads the action receipts the checkpoint carries and continues a part-way run with `None` input (`src/vaultspec_a2a/worker/state_projection.py`, `pre_flight_checkpoint`), driven by `src/vaultspec_a2a/worker/tests/test_executor_redelivery.py`.

### capsule-claude-binary-still-overridden-by-path | medium | under the desktop capsule a PATH claude is still the one a served turn runs

Status: open; partially fixes `claude-binary-split`, which stays open. `pin_claude_executable` (`src/vaultspec_a2a/providers/cli_resolution.py`) resolves the CLI from the service PATH with no capsule branch, unlike the capsule's Node and adapter resolution in `src/vaultspec_a2a/providers/_factory_commands.py`. P04.S26 unified discovery and execution, not capsule authority. Recommendation: the provider-binary follow-on ADR named in the recommendations above decides capsule-vendored versus host binary per profile.

### half-open-probe-token-is-not-owner-scoped | low | any dispatch's settlement releases another dispatch's half-open probe

Status: fixed in P06.S37: `pre_dispatch` returns a `DispatchAdmission` and `release_probe` clears the probe only for its owner (`src/vaultspec_a2a/control/circuit_breaker.py`). Original finding: the breaker's single probe flag (`src/vaultspec_a2a/control/circuit_breaker.py`, `pre_dispatch`, `release_probe`) is cleared by every settlement path without checking who reserved it, so a dispatch in flight across an open-to-half-open transition can admit a second probe. The window needs a request outliving the 30 s recovery timeout. Recommendation: hand `pre_dispatch` a probe token and release only the owner's.

### run-busy-not-in-the-recovery-lease-release-set | low | a worker 409 now retains the action lease where it used to release it

Status: fixed in P06.S38 by stating the rule: retention is right, because the worker is executing that run. `DEFINITE_NON_DELIVERY` in `src/vaultspec_a2a/control/action_lease.py` is the one statement of the release set, and `test_a_busy_worker_keeps_the_action_claim_for_the_run_it_is_running` meets the worker's real `run_busy`. Original finding: `_settle_delivery_failure` released the lease only for circuit-open, at-capacity and rejected (`src/vaultspec_a2a/control/direct_control_recovery.py`), and the worker's busy 409 is now `RUN_BUSY`, so recovery holds the lease until expiry. Holding it is arguably right, since the worker is executing that run, but the change is unstated and untested. Recommendation: state and test the intent, or add `RUN_BUSY` to the release set.

### deleted-follow-up-dispatch-coverage | low | P03.S14 removed the only tests of the definite-versus-ambiguous lease rule

Status: fixed in P06.S38: `test_definite_resume_failure_releases_and_ambiguous_failure_retains` re-expresses the rule on the permission verb. Original finding: the replaced message-path tests in `src/vaultspec_a2a/control/tests/test_direct_control_leases.py` were the only ones asserting that a definite failure releases the claim and an ambiguous one retains it with its recorded recovery condition, machinery the cancel, permission and recovery verbs still use. Recommendation: re-express the rule against the cancel or permission-respond verb.

### settled-prune-early-receipt-window | low | a turn admitted during the settled-history prune could lose its first application receipt

Status: accepted risk from P01.S08, currently unreachable. The prune runs after the durable terminal write, now in the background; a turn admitted between that write and the prune whose worker had checkpointed past its first superstep could see the checkpoint pinned by its on-start receipt deleted, with the settle-time receipt still applying it. No run state admits a follow-up today, so nothing can be admitted in that window. A tighter bound would prune only ids older than the proven terminal checkpoint.

### permission-repeat-call-same-task | low | the same tool call asked twice in one task shares one permission request id

Status: open from P02.S11. The request id is derived from the task's checkpoint namespace and the exact call (`src/vaultspec_a2a/graph/nodes/worker.py`, `_permission_request_id`), so two identical asks in one task name one request. Before S11 every permission interrupt of a task shared one id, so this narrows an existing collision. A per-task ordinal would separate them only if the provider's ask order is stable across replay.

### input-checkpoint-crash-window | low | a crash between the input checkpoint and the first superstep refuses the redelivered first ingest

Status: fixed in P06.S39: `read_checkpoint_evidence` (`src/vaultspec_a2a/thread/checkpoint_evidence.py`) folds an input checkpoint's staged `__start__` writes through the receipt reducers, so the crash window reads as pending and the worker continues with `None` input, delivering the input once; gateway recovery shares the reader. An earlier action's input checkpoint now reads as a prior action rather than incompatible. Original finding: LangGraph's step -1 input checkpoint holds the input before any channel carries the action receipt, so receipt evidence reads it as incompatible and the preflight refuses the redelivery, failing closed rather than delivering the input twice. Recognising `metadata.source == "input"` in `read_checkpoint_evidence`, which gateway recovery shares, would let it continue.

### at-capacity-marks-failed | medium | a capacity refusal still marks the dispatch failed

Status: fixed in P06.S33, with transport-unreachable, which the same ruling covers: both carry `should_mark_failed=False` (`src/vaultspec_a2a/thread/dispatch_policy.py`), the permission verb reads its status from the typed failure (`src/vaultspec_a2a/control/permission_dispatch.py`, `permission_dispatch_error`), and `test_a_saturated_worker_leaves_the_parked_run_answerable` drives the worker's own 429. Original finding: `FailureType.AT_CAPACITY` carried `should_mark_failed=True` in `src/vaultspec_a2a/thread/dispatch_policy.py` (`_POLICY`), which the control-action-leases recovery amendment's "capacity retains accepted work" rule argues against.

### ipc-client-timeout-shorter-than-terminal-confirmation | medium | the worker's event client gives up before the gateway can confirm a terminal

Status: fixed in P06.S34: `event_client_timeout()` (`src/vaultspec_a2a/worker/ipc.py`) derives the client budget from the gateway's checkpoint-read bound plus a named allowance, so raising one raises the other; `test_a_terminal_held_for_the_whole_confirmation_is_posted_once` holds a real terminal POST for the whole bound. Original finding: the worker's 10 s client timeout (`src/vaultspec_a2a/worker/ipc.py`) is shorter than the gateway's worst-case terminal confirmation, a durable write plus a checkpoint read bounded at 10 s, so a slow store makes the worker re-post a terminal the gateway is accepting.

### terminal-fanout-before-persist | low | a stream learns of a terminal before it is durable, closed only to one heartbeat

Status: open decision from P03.S17. The stream re-reads durable status on each heartbeat and closes on a terminal, bounding the race to one idle beat. Persisting before fan-out in `src/vaultspec_a2a/api/internal.py` would close it at the cost of delaying every relayed frame by a database write; that latency trade-off is the user's.

Decided 2026-10-01 by the user: keep the one-heartbeat bound. Closed as an accepted risk; durable stream resumption is decided separately under the `stream-resumption` feature.

### parallel-researchers-share-one-model | medium | the research fan-out's parallel branches share one provider model instance

Status: fixed in P06.S35, after reproduction: three branches over real ACP models failed with `AcpSessionBusyError` on the second branch, so any research fan-out wider than one thread failed on a real lane. The researcher role is now resolved once per branch (`src/vaultspec_a2a/graph/_compiler_research.py`, `_resolve_research_adr_models`), and `src/vaultspec_a2a/graph/tests/test_research_branch_models.py` drives three branches to the join. Original finding: every researcher branch calls the one model resolved at compile time (`src/vaultspec_a2a/graph/_compiler_research.py`, `_make_research_producer`) and those branches run in one superstep, while `AcpChatModel` refuses concurrent use; `with_mcp_servers` copies share the original's transport. A per-branch model from the provider factory would separate them and belongs with the provider-lane work.

### graph-cache-per-run | low | each run now compiles its own graph

Status: accepted trade-off of P02.S13. The graph cache is keyed on the run's thread as well as its compilation identity, so a worker compiles once per run; the LRU bound still caps the entries held.

### claude-mode-default-not-dontask | medium | the unattended Claude lane pins default, not the planned dontAsk

Status: accepted deviation from P04.S22, for the user. The pinned CLI maps `dontAsk` to "deny if not pre-approved" without raising `session/request_permission`, which would take the permission rung and the cross-project guard out of the path. `default` still overrides an operator's ambient `acceptEdits` or `bypassPermissions` while every uncovered call reaches the rung (`src/vaultspec_a2a/providers/_claude_tool_policy.py`, `AUTONOMOUS_PERMISSION_MODE`). Moving the posture into the CLI is a decision for the unified permission model.

### acp-turn-idle-error-lacks-stderr | low | the turn-idle deadline error carries only a stderr line count

Status: fixed in P06.S40: one redacted tail reader serves both errors (`src/vaultspec_a2a/providers/acp_chat_model.py`, `_redacted_stderr_tail`). Original finding: the ACP early-exit error carried the child's stderr tail; the turn-idle deadline error still reports only how many lines it saw.

### acp-simulator-advertises-no-modes | low | an autonomous session warns rather than refuses when a lane advertises no modes

Status: fixed in P06.S41: the simulator advertises the pinned adapter's modes and takes `--omit-modes`, and an unattended session against a modeless lane is refused (`src/vaultspec_a2a/providers/_acp_session.py`, `_pin_autonomous_permission_mode`). Original finding: the pinned adapter always advertises modes, but the in-repo simulator (`src/vaultspec_a2a/graph/tests/acp_simulator.py`) does not, so tightening the warning to a refusal needs a `modes` block in the simulator first.

### fix-re-review | low | the re-review of the plan-close fixes passes

Status: recorded. An independent re-review of the fixes above verified that each closes the finding it names, including the shutdown ordering of the prune wait inside the checkpointer's scope and the seated runtime's merge with the run's own context, and found no critical or high finding. Its findings follow.

### requeue-redrive-never-armed | medium | a backlog re-queued by the cadence flush itself was never driven again

Status: fixed; raised as low by the re-review and elevated here. A batch the cadence flush failed is re-queued inside that flush's own task, and the scheduler counted the still-running task as the pending flush, so after a second failed flush the backlog waited for an event a finished run never sends. `_schedule_flush` now treats the calling flush task as finishing (`src/vaultspec_a2a/worker/ipc.py`), and `test_a_backlog_the_cadence_flush_failed_is_driven_again` fails on the prior code. Residual: a direct flush that fails while a cadence flush is pending retries at the cadence rather than the redrive delay; nothing is lost.

### forged-heading-escape-rewrites-mounted-vault-headings | medium | the heading escape rewrote legitimate headings in mounted documents

Status: fixed. Only a depth-one heading naming a role is escaped now (`src/vaultspec_a2a/providers/_prompt_render.py`, `_FORGED_ROLE_HEADING`), so an audit entry or a transcript section in a mounted document reaches the model as written; `test_a_mounted_document_keeps_its_own_deeper_headings` fails on the prior pattern. Residual: a setext-style heading (a role word underlined with `=`) is not escaped; fencing each message body would make the boundary structural rather than lexical. Residual fixed in P06.S43: the `=` underline under a role line is escaped, and that pass runs first because escaping a hash would otherwise leave a paragraph its underline promotes back to a heading (`src/vaultspec_a2a/providers/_prompt_render.py`, `_FORGED_SETEXT_ROLE_HEADING`).

### kimi-rung-approves-bare-grep-host-wide | medium | the autonomous rung still approves a native read floor tool by bare name

Status: fixed in P06.S36: a floor tool is approved at the rung only when its path arguments, read from `rawInput` and `locations`, all lie inside the bound project (`src/vaultspec_a2a/providers/_project_scope.py`, `path_arguments_in_project`), on both lanes; `test_kimi_permission.py` refuses host, `..` and pathless calls. Original finding: the rung unioned the lane's native floor into its approvals (`src/vaultspec_a2a/providers/_acp_rpc_handlers.py`, `_autonomous_option_id`), and a kimi title reduces to exactly `Grep`, so an autonomous kimi Grep of any host path is approved; `foreign_project_argument` scans only project-root keys, not `path`. Kimi is not a proven turn lane, so no served profile reaches it today. The Claude floor has the same shape and is inert only because the pinned adapter titles its calls in prose. Recommendation: approve a floor tool at the rung only when the call's own path arguments lie inside the bound project, and re-point `src/vaultspec_a2a/providers/tests/test_kimi_permission.py` at the refusal, before any kimi lane is admitted.

### stale-comment-says-grep-composes-bare | low | a comment still described the removed Grep composition

Status: fixed (`src/vaultspec_a2a/providers/_claude_tool_policy.py`, `CLAUDE_PATH_RULE_TOOLS`).

### refusal-code-import-guard-cannot-fail | low | an import-time check compared a set with itself

Status: fixed; the guard was removed (`src/vaultspec_a2a/api/schemas/gateway.py`, `RunMessageRefusalCode`).

### prune-wait-has-two-uncovered-shutdown-edges | low | a spent shutdown budget or a cross-loop task can leave the prune wait ineffective

Status: fixed in P06.S42: `finish_before` takes a `minimum` the prune phase keeps when the shared budget is spent, and pending prunes live in a `CheckpointPruneRegistry` seated on each app (`src/vaultspec_a2a/control/event_handlers.py`, `src/vaultspec_a2a/api/app.py`). Residual: `_settlement_tasks` is still process-wide state that no shutdown phase waits for, and the cross-loop edge is narrowed to an app relaying on a loop other than its lifespan's, which no production path does. Original finding: when the shared shutdown budget was spent, `finish_before` closed the prune wait without running it (`src/vaultspec_a2a/lifecycle/shutdown.py`), so an in-flight prune can outlive the checkpointer; and `_prune_tasks` is module state shared by every app instance in a process (`src/vaultspec_a2a/control/event_handlers.py`), as `_settlement_tasks` already is. Recommendation: give the prune phase a reserve and key the pending set to the app whose lifespan waits on it.

### claude-rule-paths-anchor-at-the-working-directory | medium | absolute deny and scope rules are written in the CLI's working-directory-relative form

Status: fixed in P06.S46: one renderer, `claude_rule_path` in `src/vaultspec_a2a/providers/_claude_tool_policy.py`, writes the `//` absolute anchor for the deny and scope rules and normalises a Windows drive to `//c/...`; `src/vaultspec_a2a/providers/tests/test_claude_rule_anchor.py` proves it on the real CLI against a scripted loopback endpoint, where the old single-slash spelling grants and denies nothing. Original finding: raised by the tool-permission-model research and confirmed against the current Claude Code permissions reference, which states that a single leading slash anchors a session rule at the primary working directory and that `//path` is the absolute form. `CLAUDE_DENIED_READ_PATHS` (`src/vaultspec_a2a/providers/_claude_tool_policy.py`) writes `/proc/**`, so the deny covers `<workspace>/proc` rather than the process table, and `workspace_scoped_tool_rule` writes `Read(<absolute workspace>/**)`, which resolves under the working directory and matches nothing. The home-relative denies are unaffected. Exposure is bounded: an out-of-workspace read still reaches the permission rung, which an autonomous run refuses, so this is a lost defence layer rather than an open read. Whether the pinned CLI shares the documented grammar is to be proven at the fix.

### finding-statuses-reconciled | info | P06.S45 reconciled the original Findings section's statuses against the Steps and ADRs that closed, partially closed, or now govern them

Status: recorded. 32 findings in the original Findings section (above "## Execution and plan-close review, 2026-09-30") are now `fixed`, each citing the closing Step and the current code it verified against: `phase-gates-do-not-block`, `launcher-path-hijack`, `codex-auth-copy-no-writeback`, `crash-resume-reingests`, `breaker-fed-by-backpressure`, `claude-settings-override-autonomy`, `unscoped-native-reads`, `invented-message-timestamps`, `acp-prompt-flattening`, `acp-stderr-invisible`, `sse-pins-db-session`, `unparseable-route-finishes`, `preset-recursion-limit-ignored`, `unbounded-review-loops`, `shared-model-instances`, `blocking-io-on-loop`, `postgres-checkpointer-single-connection`, `permission-fallback-fails-open`, `token-accounting-gaps`, `json-log-formatter`, `correlation-stops-at-provider`, `mounted-content-checkpointed`, `terminal-frame-race`, `backpressure-invisible`, `container-bypasses-serve-path`, `ipc-bridge-wedge`, `blocking-engine-discovery`, `nostream-tag-ignored`, `validation-errors-never-cleared`, `langgraph-12-primitives-unused`, `no-runtime-context`, `dependency-floors`. Two of these (`validation-errors-never-cleared`, `langgraph-12-primitives-unused`) landed only once a Step of the later `2026-09-30-langgraph-conformance-plan` ran and are cited by plan name to disambiguate the shared `P01.Sxx` numbering. 8 are `partially fixed`, each keeping the unresolved half open with its owner: `permission-resume-replays-turn` (owner: accepted per-call-session trade-off), `followup-on-busy-run` (owner: `2026-10-01-run-continuation-adr`), `cross-project-guard-unreachable` (owner: `2026-10-01-tool-permission-model-adr`), `checkpoint-growth` (owner: undecided context-window policy), `claude-binary-split` (owner: `2026-10-01-provider-binary-policy-adr`), `unpinned-harness-mcp` (owner: deliberately unpinned, skew made fail-closed by the conformance plan), `checkpoint-serde-unhardened` (owner: unowned `EncryptedSerializer` gap), `stale-provisioning-docs` (owner: unowned `conftest.py` residual). 10 are reworded `open; decided by <stem>` for the four 2026-10-01 follow-on ADRs now governing them: `no-cli-version-identity`, `oauth-token-setting-unwired`, `provider-transcripts-unlinked` (provider-binary-policy); `stream-resumption`, `no-durable-event-log` (stream-resumption); `content-derived-idempotency`, `single-run-threads` (run-continuation); `always-allow-persisted-by-cli`, `tool-decision-audit`, `dead-require-approval-for` (tool-permission-model). The remaining original findings were re-verified against current code and left `open` unchanged because no Step or accepted decision closes them (`no-a2a-protocol`, `windows-shell-spawn`, `capsule-integrity-and-node-skew`, `kimi-provisioning-drift`, `compose-provisions-no-lane`, `orphan-detection-generation`, `leaseless-redispatch`, `child-env-denylist`, `compaction-view-only`, `prompt-order-vs-cache`, `dead-task-queue-tool`, `coarse-acquisition-errors`, `antigravity-discovery-only`, `sqlite-shared-checkpoint-file`, `unfenced-status-writers`, `lost-failed-event`, `per-call-provider-sessions`, `terminal-allowlist-not-boundary`, `read-cap-bypass`, `acp-client-enforcement-unreached`, `worker-stderr-truncated`, `rule-cache-and-double-load`, `machine-path-in-evidence`, `sync-preflight-io`, `telemetry-middleware-shape`, `beyond-loopback-hardening`, `contract-fidelity`); several of these (`windows-shell-spawn`, `capsule-integrity-and-node-skew`, `compose-provisions-no-lane`, `child-env-denylist`, `orphan-detection-generation`, `worker-stderr-truncated`, `rule-cache-and-double-load`, `dead-task-queue-tool`, `coarse-acquisition-errors`, `telemetry-middleware-shape`, `beyond-loopback-hardening`, `contract-fidelity`, `compaction-view-only`, `prompt-order-vs-cache`) were confirmed unchanged in current code (grep-verified) rather than left on trust. No findings in the later "Execution and plan-close review", "Re-review", or langgraph-upgrade sections were touched: they already carry Step-cited, current status. One record-code disagreement surfaced: the comment at `src/vaultspec_a2a/providers/_acp_session.py:720-722` still asserts the `.vault` deny policy blocks Claude/Z.ai fs writes, which `acp-client-enforcement-unreached` already correctly records as false and still open; no change needed there, only noted here as the one place a stale in-code comment and the audit's open status agree.

### permission-respond-busy-answers-500 | low | a permission answer to a busy run is served as an internal error

Status: fixed in P06.S47: one mapping in `src/vaultspec_a2a/api/routes/_gateway_action_endpoints.py`, `_refused_dispatch`, serves both verbs; permission respond now answers a busy run with a typed 409, capacity with 503 and an incompatible state with a typed 409, a dashboard contract event recorded in the ledger. Originally raised by the P06.S33 executor. A worker `run_busy` refusal gives the permission verb no error status, and the route answers `result.error_status_code or 500` (`src/vaultspec_a2a/api/routes/_gateway_action_endpoints.py`), so a client is told the gateway failed when the run is merely busy. A capacity refusal on the same verb is a 502 while the follow-up verb serves 503 for it. The two verbs should serve one typed vocabulary for the same dispatch outcome.

### dispatch-failure-policy-mostly-discarded | info | six of seven callers discard the failure policy pair

Recorded from P06.S33. After the capacity fix the permission service is the only consumer of the `FailureAction` that `evaluate_dispatch_failure` returns; the other call sites bind it as `_policy`. Simplifying the return is optional cleanup with no behavioural effect.

### mcp-tool-path-argument-unscoped | medium | an allowlisted MCP tool's path argument is not measured against the bound project

Status: open, owned by P02.S04 of `2026-10-01-tool-permission-model-plan` (widen the project scan to path-valued arguments); raised by the P06.S36 executor. The rung's project scan reads only project-root keys, and the new path scan runs only on the native-floor branch, so an allowlisted MCP tool called with an absolute out-of-project `path` and no project root is approved. A blanket path check would refuse legitimate calls, because `path` on an MCP tool is not always a filesystem path, so the scan needs the tool's declared argument semantics.

### claude-path-rule-tools-include-unconsulted-names | low | the path-rule tool set names tools whose path rules the CLI no longer consults

Status: open, owned by P07.S21 of `2026-10-01-tool-permission-model-plan`. Per the current Claude Code permissions reference, path rules for `Write`, `NotebookEdit` and `MultiEdit` are accepted but never consulted, with `Edit(...)` the replacement, and a `Glob` path rule is consulted only from the `--allowedTools` flag; `CLAUDE_PATH_RULE_TOOLS` still lists `Write`, `NotebookEdit` and `Cd`, and the floor composes `Glob(<ws>/**)` through the adapter's options namespace, whose routing is unverified. Latent: no caller renders a write tool into a rule today.

### acp-simulator-has-no-config-option-verb | low | the simulator cannot exercise the permission-mode pin round trip

Recorded from P06.S41. The simulator advertises modes but does not implement `session/set_config_option`, so it simulates only a lane already in the unattended mode; the pin round trip stays covered by the echo-context tests in `src/vaultspec_a2a/providers/tests/test_claude_permission_posture.py`.

### model-stack-warmup-timing-under-parallel-load | low | the loop-responsiveness test failed once under parallel load

Recorded during P06.S46 verification. `test_compiling_a_graph_keeps_the_loop_serving` in `src/vaultspec_a2a/providers/tests/test_model_stack_warmup.py` failed in a three-worker run of the provider suite and passed five of five alone. It measures event-loop latency during graph compilation, so CPU contention from sibling test workers reaches its threshold. Not a root cause yet: the next full gate either reproduces it, which makes it a defect in the bound or in the offload, or does not.

### settlement-tasks-outlive-their-app | low | settlement callbacks are process-wide state no shutdown phase waits for

Recorded from P06.S42. `_settlement_tasks` in `src/vaultspec_a2a/control/event_handlers.py` is still module state shared by every app in a process, the shape the prune set just lost, and no lifespan phase waits for it, so a desktop settlement callback can outlive the app that started it.

### event-client-budget-delays-health-probe | info | the derived client budget also lengthens the worker's startup probe

Recorded from P06.S34. The derived budget governs every request the worker's event client makes, so a hung gateway now delays the worker's startup health probe and a heartbeat by 15 s rather than 10 s; the heartbeat interval is 30 s and shutdown stays bounded by its own deadline.

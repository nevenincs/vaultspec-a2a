---
tags:
  - '#audit'
  - '#architecture-review'
date: '2026-09-24'
modified: '2026-09-24'
body_schema: 'body-v2'
body_hash: 'sha256:62e7a395cfa2732acd448777043e33bab0e049f03574d9ab1dfc9afb45670b38'
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

Status: open; diverges from accepted `2026-03-03-phase-artifact-gates-adr` ("HARD gate: block routing") and `2026-03-03-plan-approval-interrupt-adr`. `_phase_gate_decision` returns the blocked `next_route` unchanged with only `routing_error` set (`src/vaultspec_a2a/graph/nodes/supervisor.py:240-268`), and `_route_from_supervisor` follows `next` (`src/vaultspec_a2a/graph/compiler.py:774-792`). A scripted run with an empty vault index routes to `coder` (exec phase) regardless; plan approval never fires because it needs a plan to exist. The only test asserts `routing_error` is set, not where the run goes (`src/vaultspec_a2a/graph/tests/nodes/test_supervisor.py:286-295`). LangGraph places such guards in the edge or `Command` routing (research, langgraph section).

### permission-resume-replays-turn | high | approving a tool permission replays the whole agent turn and can bind to a different tool call

Status: open. The permission callback raises `interrupt()` inside `model.ainvoke` (`src/vaultspec_a2a/graph/nodes/worker.py:178-188,653-681`); the CLI is denied and torn down (`src/vaultspec_a2a/providers/_acp_rpc_handlers.py:581-596`). On resume the node re-executes, a fresh CLI session regenerates the turn, and resume index 0 is consumed by whichever permission request arrives first; `_resolve_resume_option_id` only checks the option id exists in the new option set (`src/vaultspec_a2a/graph/nodes/worker.py:631-650`), and option ids are generic, so "allow" granted for tool A can apply to tool B. Pre-request side effects and the LLM turn are repeated. LangGraph requires side effects before `interrupt()` to be idempotent; `HumanInTheLoopMiddleware` pauses after tool calls are emitted and before they execute (research, langgraph section). The plan-approval ADR's revision moved plan approval out of the supervisor for this same reason; the permission path was not moved.

### launcher-path-hijack | high | a workspace-planted executable replaces the Claude provider launcher

Status: open; reproduced through production `spawn_acp_process`. The project-local Claude command is the bare name `node` (`src/vaultspec_a2a/providers/_factory_commands.py:317`), and `resolve_env_vars` prepends the workspace's `.venv/bin` (or `Scripts`) to the child PATH (`src/vaultspec_a2a/workspace/environment.py:165-175`); POSIX exec resolves the bare name against that PATH, as does the Compose launcher's `execvp` (`service/docker/provider_identity_launcher.c:100`), and Windows `cmd.exe` searches the working directory (the workspace) first (`src/vaultspec_a2a/providers/_subprocess.py:257-270`). A scratch workspace with `.venv/bin/node` printed its own marker instead of starting the adapter. Any cloned repository, or an agent in an earlier run, can plant it; it runs with the operator's identity and the run's injected secrets and bypasses every tool-permission check. The same vector reaches `#!/usr/bin/env node` shebangs and the `uvx` used for harness MCP servers.

### codex-auth-copy-no-writeback | high | Codex credentials are copied into a throwaway home and refreshed tokens are discarded

Status: open; Codex is the only catalog-admitted lane. `auth.json` is copied into a per-run home (`src/vaultspec_a2a/providers/_codex_config_home.py:359-371`) that is `rmtree`d afterwards (`:398-410`). When Codex rotates its refresh token mid-run the new token dies with the home and the operator's `~/.codex` keeps a spent token, which signs them out with `refresh_token_reused`; concurrent runs share one source file. OpenAI's CI guidance requires writing the refreshed file back and not sharing it across concurrent jobs. The keyring (`cli_auth_credentials_store=auto`) default may leave no `auth.json` to copy at all.

### followup-on-busy-run | high | a second message during a running turn strands the run in reconciling

Status: open; verified by code trace, not reproduced end to end. RUNNING admits follow-ups (`src/vaultspec_a2a/thread/message_policy.py:26-48`) and accepting one installs it as the run writer (`src/vaultspec_a2a/control/message_service.py:262-283`). The worker refuses the busy thread with 429 (`src/vaultspec_a2a/worker/app.py:309-318`), the gateway schedules a retry, and the in-flight turn's completion and failure are then both refused as PRIOR_ACTION evidence (`src/vaultspec_a2a/thread/checkpoint_evidence.py:76-82`, `src/vaultspec_a2a/control/event_handlers.py:245-251,428-438`). A retry that lands after the first turn ends meets an END checkpoint and reports COMPLETED without running the message (`src/vaultspec_a2a/worker/state_projection.py:346-349`), which the gateway also refuses, so the run quarantines to RECONCILING at its deadline. The only live test asserts a stub worker received the dispatch (`src/vaultspec_a2a/api/tests/test_gateway_live.py:381-392`). Agent Server makes this a declared multitask strategy (research, agent-server section); open plan Steps W02.P04.S16-S18 of `2026-09-05-embedded-runtime-remediation-plan` own enqueue.

### crash-resume-reingests | high | worker recovery replays the graph input instead of resuming the checkpoint

Status: open; the empty-pending-writes heuristic is already recorded in `2026-09-06-embedded-runtime-remediation-recovery-architecture-audit`, the duplicated input is new. The pre-flight treats empty pending writes as COMPLETED (`src/vaultspec_a2a/worker/state_projection.py:346-349`) and proceeds when the checkpoint read fails (`:327-340`); otherwise the redelivered INGEST re-sends the full input (`src/vaultspec_a2a/worker/graph_lifecycle.py:906-918`). A LangGraph 1.2.11 probe cancelled a two-node graph mid-node: `pending_writes=[]` with `next=('b',)`, and re-invoking with the input duplicated the user message and re-ran node a, where `ainvoke(None)` resumed cleanly. The receipt reducer also accepts a repeated `dispatch_id` (`src/vaultspec_a2a/thread/action_receipts.py:88-108`). LangGraph's durable-execution contract is resume-with-None (research, langgraph section).

### breaker-fed-by-backpressure | high | capacity and semantic refusals open the shared circuit breaker

Status: open; diverges from accepted `2026-08-02-control-action-leases-adr` ("worker saturation does not open the shared failure breaker"); open Steps W02.P05.S23/S24 and W02.P04.S18 cover it. Every 429 and every non-2xx, including 409, calls `record_failure()` (`src/vaultspec_a2a/control/dispatch.py:206-231`) against a 3-failure / 30 s breaker (`src/vaultspec_a2a/control/infra_config.py:764-771`) whose half-open state admits all traffic (`src/vaultspec_a2a/control/circuit_breaker.py:51-59`). Six simultaneous starts, or the follow-up retry loop above, can 503 every run's permission answers for 30 s.

### claude-settings-override-autonomy | high | operator and workspace Claude settings can override the autonomous deny-by-default rung

Status: open. `claude_session_options` pins only `strictMcpConfig` and `allowedTools` (`src/vaultspec_a2a/providers/_acp_session.py:66-83`); the pinned adapter `@agentclientprotocol/claude-agent-acp@0.59.0` then defaults `settingSources` to user, project, and local (`node_modules/@agentclientprotocol/claude-agent-acp/dist/acp-agent.js:3751`) and resolves `permissionMode` from them, while the lane runs in the operator's own config home (`src/vaultspec_a2a/providers/_config_home_roots.py:4-7`). A user-level `acceptEdits` or `bypassPermissions` default auto-approves tools before the a2a rung is consulted, and project-level `.claude/settings*.json` in a user-selected repository loads allow rules and hooks. `AcpChatModel.set_mode` has no production caller and `currentModeId` is recorded but never checked. The Claude Agent SDK documents that auto-approved tools never reach `canUseTool` (research, permissions section).

### acp-client-enforcement-unreached | high | client-side fs, terminal, and .vault write enforcement never runs on served ACP lanes

Status: open; P02.S05 of `2026-08-02-llm-context-provider-abstraction-plan` ("prove supported-adapter fs/terminal over real stdio") is still open. The adapter defines `readTextFile`/`writeTextFile` wrappers (`acp-agent.js:3025-3031`) that nothing calls: the CLI's native Read, Write, Edit, and Bash act on disk directly. Persona `filesystem_write=false`/`terminal=false` only clear `clientCapabilities`, which the adapter ignores, so the confined handlers (`src/vaultspec_a2a/providers/_acp_rpc_handlers.py:63-291`) and the `.vault` deny are bypassed; the code comment at `src/vaultspec_a2a/providers/_acp_session.py:596-599` asserting the deny still applies is false for Claude and Z.ai. Existing tests call the handlers directly (`src/vaultspec_a2a/providers/tests/test_acp_vault_deny.py`).

### cross-project-guard-unreachable | high | the cross-project argument guard is unreachable for pre-approved tools

Status: open. The guard runs only inside `on_request_permission` (`src/vaultspec_a2a/providers/_acp_rpc_handlers.py:557-579`), but autonomous composition places `mcp__vaultspec-rag__*` in `allowedTools` (`src/vaultspec_a2a/graph/nodes/worker.py:767`), so those calls never raise a permission request; the Codex rung compares only `(server, tool)` (`src/vaultspec_a2a/providers/_codex_permission.py:213-229`) under `default_tools_approval_mode="auto"` (`src/vaultspec_a2a/providers/_codex_config_home.py:309`). A `project_root` argument naming another enrolled project is read in autonomous mode. `test_project_confinement.py:125-145` proves handler logic production does not execute.

### unscoped-native-reads | high | autonomous research roles hold unscoped host reads plus open web egress

Status: open. Bare `Read`, `Grep`, and `Glob` are allowlisted (`src/vaultspec_a2a/providers/_native_read_tools.py:43,278-288`); in default mode in-workspace reads are already auto-approved, so the bare entries only add out-of-workspace reads (operator credentials, `~/.ssh`; `/proc/<pid>/environ`, which holds the bridge bearer, unverified live). `WebFetch` is served under a blocklist posture (`src/vaultspec_a2a/providers/lane_admission.py:274-285`). Private-data read plus untrusted content plus an outbound channel is the OWASP LLM01/LLM06 exfiltration triad. Compose is mitigated by the identity launcher; desktop has no UID boundary.

### invented-message-timestamps | high | transcript timestamps are the read time, not the event time

Status: open. `extract_message_timestamp` falls back to `datetime.now(UTC)` (`src/vaultspec_a2a/thread/snapshots.py:739-761`) and nothing stamps `created_at` on produced messages, so the authoritative run history reports projection time as event time; committed evidence shows messages 8 µs apart and after their checkpoint.

### acp-prompt-flattening | high | ACP prompts drop roles, speaker attribution, and tool results

Status: open. `_astream_session` renders every message as a bare text block and silently drops `ToolMessage` (`src/vaultspec_a2a/providers/acp_chat_model.py:469-475`), so system instructions, other agents' outputs, and the model's own prior turns arrive indistinguishable; Codex labels roles (`src/vaultspec_a2a/providers/_codex_protocol.py:39-62`), so the two transports disagree. This widens the injection surface noted in the permissions findings.

### acp-stderr-invisible | high | ACP CLI stderr is DEBUG-only and not retained on failure

Status: open; breaks L2 of `2026-08-05-served-capability-contract-failure-observability-adr`. `_read_stderr_loop` logs each line at DEBUG, unredacted (`src/vaultspec_a2a/providers/acp_chat_model.py:898-921`), under an INFO default; an early exit reports only a line count. Codex already keeps a redacted 200-line tail (`src/vaultspec_a2a/providers/_codex_app_server_client.py:30-60`).

### no-a2a-protocol | high | the service is not A2A-protocol capable; the protocol was deliberately dropped

Status: open decision, not a defect. The 2026-07-15 amendment to `2026-02-26-protocol-ecosystem-bridge-adr` drops the Google (now Linux Foundation) A2A ambition and declares "a2a" a project label; declared transports are ACP and REST/SSE. The edge is the bearer-authenticated `/v1` REST+SSE contract of `2026-07-14-a2a-edge-conformance-adr` R6 (`src/vaultspec_a2a/api/routes/gateway.py:73`), with no Agent Card, JSON-RPC binding, `/.well-known` route, push-notification config, or `a2a-sdk` dependency. Most A2A concepts already have a counterpart: `ThreadStatus` maps one-to-one onto submitted/working/input-required/completed/canceled/failed (`src/vaultspec_a2a/thread/enums.py:45`), run-status and cancel map onto GetTask and CancelTask, clarification and permission pauses map onto input-required answered through the typed respond verbs, and the SSE frame catalog maps onto status and artifact update events. Absent are the Agent Card, a multi-task context, push notifications, file parts, `auth-required`, and snapshot-first resubscription. Because execution runs in the worker, `a2a-sdk`'s `DefaultRequestHandler` plus in-process `AgentExecutor` does not fit; a custom request handler over the existing control services does (research, a2a section).

### sse-pins-db-session | high | every open SSE stream holds a pooled database session and an open SQLite read transaction

Status: open; measured. `run_stream_endpoint` depends on `get_db` (`src/vaultspec_a2a/api/routes/_gateway_read_endpoints.py:376-379`); with FastAPI 0.141's default request-scoped yield teardown the session closes only after the stream ends (`src/vaultspec_a2a/database/session.py:426-450`), and the status read inside the stream builder autobegins a transaction. Three open streams gave `pool.checkedout()==3` and a busy `wal_checkpoint(TRUNCATE)`; fifteen exhausted the 5+10 pool and the sixteenth database-using request blocked. About fifteen attached viewers therefore stall run-start, status, cancel, and the `/internal/events` relay on the same engine, `max_stream_connections=256` is unreachable, and the WAL grows while any viewer is attached, the hazard `session.py:52-66` documents.

### unparseable-route-finishes | medium | unparseable supervisor output completes the run and skips the FINISH guards

Status: open. `_parse_route` substring-matches and falls back to `FINISH` (`src/vaultspec_a2a/graph/nodes/supervisor.py:125-135`); the unparseable branch returns before `_check_finish_blocked` (`:317-327`). Scripted: with active validation errors, explicit FINISH reroutes to `coder`, but garbled text writes a completion receipt.

### preset-recursion-limit-ignored | medium | the per-preset `recursion_limit` is ignored on served runs

Status: open. Presets declare it (`src/vaultspec_a2a/team/team_config.py:504`), but served paths pass the global `graph_recursion_limit=100` (`src/vaultspec_a2a/domain_config.py:174`, `src/vaultspec_a2a/api/routes/_gateway_run_start.py:258`); only tests read the preset value.

### unbounded-review-loops | medium | review loops have no per-phase bound and the pipeline_loop early exit is dead

Status: open. `_doc_review_router` cycles (`src/vaultspec_a2a/graph/_compiler_research.py:336-342,648-676`) cost two LLM turns each and are bounded only by the global limit; `_loop_route` exits early only on `next=="FINISH"`, which no worker writes (`src/vaultspec_a2a/graph/compiler.py:795-807`). `RemainingSteps` and model/tool call-limit middleware are the standard bounds.

### checkpoint-growth | medium | checkpoint storage grows super-linearly with no retention

Status: open. The saver stores full channel values each super-step; measured 20 turns of 10 KB messages produced 22 checkpoints totalling 2.16 MB (about 10.5x the transcript). `mounted_context`, descriptors, and receipts ride every checkpoint, and `Send(name, state)` copies full state into each branch (`src/vaultspec_a2a/graph/nodes/diverge.py:123`). Nothing calls `adelete_thread` or prune (`src/vaultspec_a2a/database/checkpoints.py:196`). LangGraph 1.2 offers `DeltaChannel` and documented storage optimization; Agent Server offers TTLs.

### shared-model-instances | medium | concurrent runs of one preset share model instances that refuse concurrent use

Status: open; code reading only. The compiled-graph cache key has no run identity (`src/vaultspec_a2a/worker/graph_lifecycle.py:91-97`), so up to five concurrent runs share model objects; `AcpChatModel` raises a non-retryable `AcpSessionBusyError` on concurrent use (`src/vaultspec_a2a/providers/acp_chat_model.py:336-338`).

### blocking-io-on-loop | medium | synchronous file and HTTP I/O runs on the worker event loop

Status: open; diverges from `2026-03-03-blackboard-content-mounting-adr` §4. A new `RuleManager` per turn does synchronous glob and frontmatter reads (`src/vaultspec_a2a/graph/nodes/worker.py:109-112`, `src/vaultspec_a2a/context/rules.py:110-115`); `_build_feedback_reader` calls synchronous `resolve_engine()` (`httpx.get`, 3 s timeout) on the loop (`src/vaultspec_a2a/worker/graph_lifecycle.py:850`) while its sibling at `:774` uses `to_thread`.

### no-cli-version-identity | medium | no system CLI has a version floor, pin, or recorded identity

Status: open. Resolution checks presence only (`src/vaultspec_a2a/providers/cli_resolution.py:19-37`); `LaneProof` records a test id but no binary version (`src/vaultspec_a2a/providers/lane_admission.py:167-205`); the adapter's `agentInfo` and Codex's `userAgent` are discarded; CI installs `@openai/codex` unpinned (`.github/workflows/test.yml:223`); the native Claude installer auto-updates. "Proven lane" admission therefore does not bind to the binary that was proven.

### claude-binary-split | medium | discovery and execution run different Claude binaries, chosen by PATH

Status: open. Execution sets `CLAUDE_CODE_EXECUTABLE` to the PATH `claude` (`src/vaultspec_a2a/providers/acp_chat_model.py:359-366`); catalog discovery does not (`src/vaultspec_a2a/providers/factory.py:200-224`), so the adapter falls back to its lock-vendored binary. On this host they are 2.1.281 and 2.1.207. In the desktop profile a PATH `claude` overrides the "immutable" capsule.

### oauth-token-setting-unwired | medium | the `CLAUDE_CODE_OAUTH_TOKEN` setting never reaches the child

Status: open. The setting exists (`src/vaultspec_a2a/control/infra_config.py:508`) but no production code reads it; `.env` loads into settings, not `os.environ`, and `VAULTSPEC_*` is scrubbed from children (`src/vaultspec_a2a/workspace/environment.py:159`). `.env.example` tells operators the Claude lane authenticates with it, and the test prerequisite counts it as a credential, so the probe passes while the production child is unauthenticated.

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

Status: open. SSE frames carry no `id:` (`src/vaultspec_a2a/streaming/sse_frames.py:505-507`), there is no `Last-Event-ID` handling or replay buffer, and run status is read before the subscription is attached (`src/vaultspec_a2a/api/thread_stream.py:150,229-237`), so a terminal event relayed in between leaves a stream that heartbeats forever. The per-thread sequence lives in worker memory and resets on restart (`src/vaultspec_a2a/streaming/emitters.py:148-200`). Agent Server and A2A both define a resumable or snapshot-first subscription (research, streaming section).

### content-derived-idempotency | medium | follow-up idempotency keys are derived from message content

Status: open. The default key hashes thread, agent, and content (`src/vaultspec_a2a/thread/idempotency.py:29-33`), so a second identical "continue" in one run silently returns `dispatched=False` (`src/vaultspec_a2a/control/message_service.py:92-98`). A2A deduplicates on a client-supplied `messageId`.

### postgres-checkpointer-single-connection | medium | the Postgres checkpointer runs on one connection with no pool or reconnect

Status: open. `from_conn_string` opens a single psycopg `AsyncConnection` (`src/vaultspec_a2a/database/checkpoints.py:318-322`), serializing every run's checkpoint writes and disabling checkpointing until restart if the connection drops. The saver accepts an `AsyncConnectionPool`.

### permission-fallback-fails-open | medium | an unoffered permission option id falls back to the first offered option

Status: open; probe-confirmed. On an id mismatch the handler substitutes the first offered option (`src/vaultspec_a2a/providers/_acp_rpc_handlers.py:626-634`); the adapter orders options `allow_always`, `allow`, `reject`, so an autonomous rejection whose reject option lacks an id resolves to `allow_always`, contradicting `_denial_option_id` (`:385-394`).

### always-allow-persisted-by-cli | medium | a supervised "always allow" is persisted by the CLI outside a2a's control

Status: open; destination unverified live. The interrupt forwards every option including `allow_always` (`src/vaultspec_a2a/graph/nodes/worker.py:674-681`) and the adapter returns SDK suggestions as `updatedPermissions`, whose destinations include local and project settings. Combined with the settings-source finding, a rule written this way can widen later autonomous runs. ACP assigns remembering "always" to the client.

### tool-decision-audit | medium | permission decisions are only partially and anonymously audited

Status: open. `permission_logs` is written only for human responses, with `agent_id=None` and no responder identity (`src/vaultspec_a2a/control/permission_service.py:834-845`, `src/vaultspec_a2a/database/models.py:526-535`); autonomous approvals and denials, Codex decisions, cross-project refusals, and terminal creation reach only process logs.

### dead-require-approval-for | medium | `require_approval_for` is parsed but never enforced

Status: open. Declared at `src/vaultspec_a2a/team/team_config.py:275-292` with no reader; `vaultspec-coder.toml` sets it to `["fs.writeTextFile"]`, advertising a gate that does not exist, the same zero-caller defect class the clarification rule names.

### child-env-denylist | medium | provider child environments are built by denylist

Status: open. `resolve_env_vars` scrubs known names (`src/vaultspec_a2a/workspace/environment.py:101-161`) but passes `GITHUB_TOKEN`, `GH_TOKEN`, `NPM_TOKEN`, cloud credentials, `SSH_AUTH_SOCK`, and `KUBECONFIG`; terminal children accept agent-chosen env overrides unfiltered (`src/vaultspec_a2a/providers/_acp_rpc_terminal_handlers.py:146-182`); the authoring bridge tokens sit in the CLI's environment (`src/vaultspec_a2a/providers/acp_chat_model.py:410-423`) and so reach every Bash child.

### unpinned-harness-mcp | medium | harness MCP servers are fetched at runtime without version pins

Status: open; reproduced. The registry launches `uvx --from vaultspec-rag[mcp]` and `vaultspec-core` with neither a package version nor a `--python` pin (`src/vaultspec_a2a/providers/_harness_mcp_registry.py`), and the contract check verifies tool names, not code (`src/vaultspec_a2a/providers/_mcp_contract.py:330`). Because `uvx` takes the host's default interpreter, a host whose default Python is older than 3.13 cannot resolve `vaultspec-rag` at all: on this environment's image (default 3.11) seventeen unit tests that compose the server fail with a bare resolution error, and all seventeen pass with `UV_PYTHON=3.13`. Desktop disables runtime acquisition.

### provider-transcripts-unlinked | medium | provider-native session ids and transcripts are neither recorded nor linked

Status: open. The ACP `sessionId` is read (`src/vaultspec_a2a/providers/_acp_session.py:632`) but never logged or persisted; each turn writes a fresh Claude transcript into the operator's `~/.claude/projects` under their retention policy. Codex runs `ephemeral: true` in a deleted per-run home, so no rollout survives.

### compaction-view-only | medium | context compaction is a local view with a rough estimator and misfires

Status: open; no ADR governs compaction. `should_compact` fires at 80% of one global 120k budget (`src/vaultspec_a2a/domain_config.py:120`) but `compact_context` acts only above 100% while the debug log reports `compacted=True`; tool-call arguments are not counted; the kept suffix can start with an orphan `ToolMessage`; rules, anchoring, and up to 20k mounted tokens are outside the budget; the "summary" is a fixed placeholder; and `add_messages` without `RemoveMessage` means checkpointed history only grows (`src/vaultspec_a2a/thread/state.py:221`).

### prompt-order-vs-cache | medium | dynamic context precedes history, defeating prefix caching

Status: open; size unmeasured because ACP reports no usage. Anchoring, mounted documents, and feedback are placed before the history (`src/vaultspec_a2a/graph/nodes/worker.py:141-160`).

### token-accounting-gaps | medium | cache and reasoning token counts are dropped; ACP lanes report none

Status: open. Codex maps cache-read, cache-creation, and reasoning tokens (`src/vaultspec_a2a/providers/_codex_protocol.py:295-315`) but `_turn_token_usage` keeps only input/output/total (`src/vaultspec_a2a/graph/nodes/worker.py:518-535`) and `cost_tracking` has no columns for them (`src/vaultspec_a2a/database/models.py:821-850`).

### json-log-formatter | medium | the JSON log formatter loses records and carries no schema, zone, or redaction

Status: open, latent for current call sites. `json.dumps(log_data)` has no `default=` (`src/vaultspec_a2a/utils/logging.py:212`), so a non-JSON extra drops the record; timestamps are zone-less local time (`:196`); there is no schema version, pid, service, or sequence field, and no central redaction filter (a probe logged an API-key-shaped extra verbatim).

### correlation-stops-at-provider | medium | correlation ids do not reach provider logs or LangSmith runs

Status: open. There is no ContextVar log context; `runtime_log_extra` omits `thread_id` and `dispatch_id` (`src/vaultspec_a2a/providers/_acp_auth.py:49-87`); the graph `RunnableConfig` carries no `run_id`, `tags`, or `metadata` (`src/vaultspec_a2a/worker/executor.py:515-518`); no `TRACEPARENT` reaches CLI children.

### no-durable-event-log | medium | there is no GenAI span model and no durable per-run event log

Status: open. No `gen_ai.*` span or attribute exists; the event sequence is in worker memory; the relay drops by design; and the acceptance evidence bundle carries `last_sequence: 0` with no events. The durable records are the checkpoint plus the permission, control-action, recovery, and cost tables.

### mounted-content-checkpointed | medium | mounted vault content is persisted in every checkpoint

Status: open; diverges from `2026-03-03-blackboard-content-mounting-adr` §2.1 ("never persisted as content"). `mount_node` returns up to 20k tokens as a channel value (`src/vaultspec_a2a/graph/nodes/vault_reader.py:224-263`) that LangGraph checkpoints each super-step; `aprune` is defined but never called (`src/vaultspec_a2a/database/checkpoints.py:196`).

### terminal-frame-race | medium | a viewer attaching in a narrow window never receives the terminal frame

Status: open; ordering confirmed in code, timing not reproduced; R6 gap owned by W04.P09.S27 of `2026-08-05-served-capability-contract-plan` and W04.P09.S46. The stream reads durable status (`src/vaultspec_a2a/api/thread_stream.py:229`) before it subscribes (`:113,150`); the relay fans out before it persists (`src/vaultspec_a2a/api/internal.py:206,219`); terminal acceptance awaits a checkpoint read of up to 10 s (`src/vaultspec_a2a/control/event_handlers.py:639`); and `clear_thread_state` then unsubscribes late attachers (`src/vaultspec_a2a/streaming/subscribers.py:155`). Related to `stream-resumption` above.

### backpressure-invisible | medium | subscriber queue overflow is silent to the consumer

Status: open. Drop-oldest only logs (`src/vaultspec_a2a/streaming/fanout.py:120-137`); `progress_dropped` is emitted only for oversized frames (`src/vaultspec_a2a/streaming/sse_frames.py:530-549`); R6 requires a bounded resynchronization indication.

### container-bypasses-serve-path | medium | the container entrypoint bypasses the owned serve path and its graceful shutdown

Status: open; measured. `service/docker/prod.Dockerfile:93,132` run `uvicorn --factory` directly, so `timeout_graceful_shutdown` (`src/vaultspec_a2a/api/app.py:797`) is never applied; with one open stream the server had not exited 8 s after `should_exit`, and Docker's default 10 s stop then SIGKILLs before the lifespan drains admission, closes the database, and flushes telemetry. No compose file sets `stop_grace_period`.

### ipc-bridge-wedge | medium | the worker-to-gateway event bridge can wedge, reorder, and duplicate

Status: open; not reproduced. `flush_events` posts the whole buffer, up to 10,000 events (`src/vaultspec_a2a/worker/ipc.py:198,318`), the gateway rejects batches over 4 MiB (`src/vaultspec_a2a/api/internal.py:407`), and the worker re-queues without splitting (`src/vaultspec_a2a/worker/ipc.py:339`), so a post-outage backlog can 413 forever; worker drop-oldest does not protect terminal events; the deferred and immediate terminal flushes (`src/vaultspec_a2a/worker/state_projection.py:496`) share no lock; and the 10 s client timeout (`src/vaultspec_a2a/worker/ipc.py:75`) is shorter than the gateway's worst-case terminal confirmation.

### blocking-engine-discovery | medium | engine discovery blocks the worker event loop after every authoring run

Status: open. `src/vaultspec_a2a/worker/_authoring_close.py:45` calls synchronous `resolve_engine()` (file reads plus `httpx.get(timeout=3.0)` per candidate, `src/vaultspec_a2a/authoring/discovery.py:253`), and `src/vaultspec_a2a/authoring/client.py:203` calls the bearer resolver synchronously on a 401, on the loop that also carries up to five runs, the heartbeat, and `/dispatch`. The hazard is acknowledged and handled elsewhere (`src/vaultspec_a2a/worker/authoring_binding.py:70-74`).

### nostream-tag-ignored | low | supervisor routing tokens leak to clients because `TAG_NOSTREAM` is ignored under `astream_events` v2

Status: open. Scripted: three tagged `on_chat_model_stream` events under v2 versus none under `stream_mode="messages"`; the transformer does no tag filtering (`src/vaultspec_a2a/streaming/transformer.py:530-555`).

### validation-errors-never-cleared | low | `validation_errors` accumulates for the life of a run

Status: open. The reducer clears only on an explicit empty list (`src/vaultspec_a2a/thread/state.py:98-105`); producers only append; anchoring shows them as active in every later prompt (`src/vaultspec_a2a/context/anchoring.py:69-73`), leaking research revision notes into ADR and plan phases.

### langgraph-12-primitives-unused | low | node timeouts, error handlers, and destinations are hidden by the typed builder

Status: open. `_TypedBuilder` narrows `add_node` to `metadata` and `retry_policy` (`src/vaultspec_a2a/graph/compiler.py:85-111`), hiding `timeout=`, `error_handler=`, `destinations=`, `defer=`, and `cache_policy=` present in 1.2.11; a hand-written stall watchdog backs up `step_timeout` (`src/vaultspec_a2a/streaming/ingest.py:42-155`); throttling retries have no jitter (`src/vaultspec_a2a/graph/_compiler_retry.py:143-150`); `Command`-returning nodes declare no destinations, so `get_graph()` draws them to `__end__`.

### no-runtime-context | low | run identity lives in checkpointed state and closures instead of Runtime context

Status: open; medium refactor because providers bind the workspace at construction. `thread_id` and `workspace_root` are state fields (`src/vaultspec_a2a/thread/state.py:333,338`), workspace and autonomy are closure-bound (hence part of the graph cache key), and `_config_contract.py` works around config injection under postponed annotations, which `context_schema` avoids.

### checkpoint-serde-unhardened | low | checkpoints use permissive msgpack with no encryption

Status: open. Default `JsonPlusSerializer`; neither strict msgpack nor `EncryptedSerializer` is configured although state is JSON-only by design and transcripts carry workspace code.

### dead-task-queue-tool | low | `mark_task_complete` is never offered to a real model

Status: open. It has no `bind_tools` call or MCP exposure and only the deterministic test model emits it (`src/vaultspec_a2a/graph/nodes/worker.py:321-357`).

### dependency-floors | low | declared LangGraph floors are far below the APIs the code uses

Status: open. `pyproject.toml` declares `langgraph>=0.2.16` and checkpoint savers `>=2.0.0`, while the code relies on 1.x injection and checkpoint 4.x APIs (`src/vaultspec_a2a/database/checkpoints.py:183-256`). An unlocked install can resolve an incompatible stack.

### coarse-acquisition-errors | low | acquisition failures collapse into one untyped message

Status: open. Readiness returns "not installed or resolvable" for every failure (`src/vaultspec_a2a/providers/provider_readiness.py:115-131`); the catalog drops `data.details` (`src/vaultspec_a2a/providers/acp_catalog.py:81-102`), so this host's `Claude Code process exited with code 1` surfaced as a bare `-32603 provider error`; `auth_hint()` is Claude-specific even on Kimi (`src/vaultspec_a2a/providers/_acp_auth.py:95-100`).

### antigravity-discovery-only | low | the Antigravity lane is discovery-only with a loose binary lookup

Status: open. It is absent from the supported-execution set (`src/vaultspec_a2a/providers/factory.py:131-142`); lookup is `ANTIGRAVITY_CLI_PATH` accepted on `is_file()`, then `which(agy)`, then hard-coded installer paths (`src/vaultspec_a2a/providers/antigravity_cli.py:31-65`); `ANTIGRAVITY_CLI_HOME` is documented as a login home but used only to find the binary.

### stale-provisioning-docs | low | provisioning docstrings, test resolver, and install hints are stale

Status: open. `_codex_config_home.py:7-10` and `_config_home_roots.py:5-7` describe retired workspace projections; the conftest `_on_path` reimplements resolution and accepts `.cmd` on POSIX (`src/vaultspec_a2a/conftest.py:98`); its hint recommends the deprecated `npm install -g @anthropic-ai/claude-code` (`:338`).

### sqlite-shared-checkpoint-file | low | the SQLite checkpoint store defaults to the application database file

Status: open; W02.P04.S15 owns it. Pragmas are correct (WAL, `busy_timeout` 5000 ms, `BEGIN IMMEDIATE`, `src/vaultspec_a2a/database/session.py:82-136`), but the checkpoint DSN defaults to the application file (`src/vaultspec_a2a/control/config.py:450`), putting three writers in two processes on one lock.

### unfenced-status-writers | low | three thread-status writers still bypass the fenced election

Status: open; W02.P03.S82 owns it. `update_thread_status` is called at `src/vaultspec_a2a/control/_event_application.py:249`, `src/vaultspec_a2a/control/verdict_subscriber.py:156`, and `src/vaultspec_a2a/control/repair_transitions.py:52`, against state-truthfulness rule T6.

### lost-failed-event | low | a relay-dropped FAILED event is not recoverable from the checkpoint

Status: open; W02.P03.S14 owns it. The worker relay is a lossy 10k in-memory buffer with three retries (`src/vaultspec_a2a/worker/ipc.py:197-210,304-340`); completion is recoverable from the checkpoint but FAILED is not (`src/vaultspec_a2a/control/recovery_authority.py:227-228`), so such a run waits for its deadline.

### single-run-threads | low | a thread holds exactly one run, with no context grouping or fork

Status: open, informational. Terminal states only archive (`src/vaultspec_a2a/thread/transitions.py:77-80`) and follow-ups after completion get 409. A2A groups tasks under a `contextId`; Agent Server threads hold many runs and fork from checkpoints.

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

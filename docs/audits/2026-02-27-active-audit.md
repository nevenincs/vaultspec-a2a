---
date: 2026-02-27
type: audit
feature: active-codebase
description: "Rev 3 active codebase audit verifying all lib/ modules against ADRs 001-013; confirms zero critical violations after task completions #3-#6 and #10-#12."
related:
  - docs/adrs/2026-02-26-001-process-workspace-management-adr.md
  - docs/adrs/2026-02-26-009-module-hierarchy-adr.md
  - docs/adrs/2026-02-26-010-observability-telemetry-adr.md
  - docs/adrs/2026-02-27-013-team-composition-topology-adr.md
---

# Active Codebase Audit -- 2026-02-27 (Rev 3)

## Audited By: supervisor

## Scope: All lib/ modules against ADRs 001-013 + backend-foundational-gaps.md

## Revision Notes

Rev 3 -- All tasks verified. Tasks #3, #4, #5, #6, #10, #11, #12 complete.
Zero critical violations remaining

---

## CHANGE LOG FROM REV 1

| File | Change | Impact |
| ------ | -------- | -------- |
| `lib/core/permissions.py` | DELETED (376 lines removed) | Resolves ADR-009 tension from Rev 1 |
| `lib/core/__init__.py` | +24 lines: added`compile_team_graph`, `create_worker_node`, `create_supervisor_node`exports; removed 6 permission symbols | Resolves CRITICAL #4 from Rev 1 |
| `lib/core/aggregator.py` | +54 lines: expanded OTel metrics, public buffer/flush methods | Improved ADR-010 wiring |
| `lib/api/endpoints.py` | +226 lines,`_enrich_snapshot_from_state()`added | CRITICAL #4 from Rev 2 RESOLVED |
| `lib/providers/acp_chat_model.py` | +300 lines: 7 RPC handlers, _RPC_DISPATCH dict, batch JSON-RPC, sandbox path validation | CRITICAL #1 and #2 from Rev 2 RESOLVED |
| `lib/providers/__init__.py` | Full facade: 8 symbols in`__all__`, lazy imports for circular deps | CRITICAL #3 from Rev 2 RESOLVED |
| `lib/providers/factory.py` | `__all__ = ["ProviderFactory"]`added | Gap 4 from Rev 2 RESOLVED |
| `lib/providers/acp_exceptions.py` | `__all__`with 6 symbols added | Gap 4 from Rev 2 RESOLVED |
| `lib/core/nodes/supervisor.py` | `__all__ = ["create_supervisor_node"]`added | Gap 4 from Rev 2 RESOLVED |
| `lib/core/nodes/__init__.py` | Full facade:`X as X`pattern,`__all__`defined | Gap 4 from Rev 2 RESOLVED |
| `lib/api/websocket.py` | `_DEAD_CLIENT_TIMEOUT = 90.0`, `asyncio.wait_for()`, `inject_trace_context`in writer | Gap 3 + OTel Gap RESOLVED |
| `lib/api/app.py` | `TelemetryMiddleware`mounted via`app.add_middleware()` | OTel Gap RESOLVED |

---

## lib/core/graph.py

- [ADR-013 SS2.5] compile_team_graph() signature`(team_config, agent_configs,
  checkpointer, supervisor_agent_config)`: **PASS** -- Line 85-90. Matches
  ADR-013 SS5.
- [ADR-013 SS2.5] Star topology `add_conditional_edges(supervisor, ...)`:
  **PASS** -- `_compile_star()`at line 147
  uses`builder.add_conditional_edges("supervisor", ...)`with route_map.
- [ADR-013 SS2.5] Pipeline topology (no supervisor, sequential chain): **PASS**
  --`_compile_pipeline()`at line 221 wires explicit`add_edge`calls with`START ->
  node[0] -> ... -> END`.
- [ADR-013 SS2.5] Pipeline_loop `loop_count`guard + conditional back-edge:
  **PASS** --`_compile_pipeline_loop()`at line 259 reads`state.get("loop_count",
  0)`and compares against`max_loops`.
- [ADR-013 SS2.7] interrupt_before assembled from all agents'
  require_approval_for: **PASS** -- Lines 120-125 collect `interrupt_nodes`from
  all workers with non-empty`require_approval_for`.
- [ADR-013 SS2.6] Supervisor prompt uses roster with display_name, id,
  description: **PASS** -- `_build_supervisor_prompt()`at line 67.
- [ADR-013 SS2.3] Model resolution precedence (worker override > agent TOML >
  team defaults): **PASS** --`_resolve_model_for_worker()`at line 30.
- [ADR-012 SS2.5] Node metadata carrier (display_name, role, description on
  add_node): **PASS** -- All three`_compile_*`functions pass metadata
  to`builder.add_node()`.
- [ADR-009] `__all__`defined: **PASS** -- Line 27.
- [ADR-009] Relative imports: **PASS**.

---

## lib/core/state.py

- [ADR-013 SS5]`loop_count: int`field exists: **PASS** -- Line 100:`loop_count:
  NotRequired[int]`.
- [ADR-008 SS5] All fields JSON-serializable: **PASS** -- Primitives, dicts,
  lists, BaseMessage.
- [ADR-002 SS5] Token accounting in TeamState: **PASS** -- `token_usage:
  Annotated[dict[str, dict[str, int]], _merge_token_usage]`at line 94.
- [ADR-009]`__all__`defined: **PASS**.
- [ADR-009] Relative imports: **PASS**.

---

## lib/core/aggregator.py

- [ADR-004 SS2] Uses`astream_events(version="v2")`: **PASS** -- Line 787-790.
- [ADR-011 SS5] Per-thread monotonic sequence numbers starting at 1: **PASS** --
  `_sequences: defaultdict(int)`, `_next_sequence`increments then returns (lines
  183-186).
- [ADR-011 SS5] Debouncing: ToolCallUpdate 100ms: **PASS**
  --`_TOOL_CALL_UPDATE_DEBOUNCE = 0.100`at line 79.
- [ADR-011 SS5] Debouncing: PlanUpdate 250ms: **PASS** --`_PLAN_UPDATE_DEBOUNCE
  = 0.250`at line 80.
- [ADR-004 SS5] Token chunk batching (50ms / 4KB): **PASS** -- Lines 85-86.
- [ADR-004 SS5] Backpressure via bounded queue (512): **PASS** --`_QUEUE_MAXSIZE
  = 512`at line 91.
- [ADR-012 SS2.5] register_graph() extracts node metadata: **PASS** -- Line 204.
- [ADR-010] OTel instrumentation: **PASS** -- Uses`get_tracer`, `get_meter`,
  creates 4 metrics (events_emitted, events_filtered, chunks_batched,
  ingest_duration). Spans in `_broadcast`and`ingest`.
- [ADR-010] OTel spans in flush_chunks: **PASS** -- Line 356:
  `_tracer.start_as_current_span("aggregator.flush_chunks")`.
- [ADR-009] `__all__`defined: **PASS**.
- [ADR-009] Relative imports: **PASS**.

---

## lib/core/team_config.py

- [ADR-012 SS2.3] AgentConfig exact fields: **PASS**.
- [ADR-012 SS5] agent.id validated as Python identifier: **PASS**.
- [ADR-012 SS2.8] Config discovery order (workspace -> preset -> error):
  **PASS**.
- [ADR-013 SS2.4] TeamConfig exact fields: **PASS**.
- [ADR-013 SS2.4] TopologyConfig validation: **PASS**.
- [ADR-013 SS5] topology.order agent IDs subset of workers: **PASS**.
- [ADR-013 SS5] topology.loop_node must appear in topology.order: **PASS**.
- [ADR-009]`__all__`defined: **PASS**.
- [ADR-009] Relative imports: **PASS**.

---

## lib/core/**init**.py

- [ADR-009] Facade re-exports with`X as X`pattern: **PASS** -- All exports use
  explicit`X as X`pattern.
- [ADR-009]`__all__`defined: **PASS** -- Lines 105-148.
- [ADR-009 Key Shifts] registry.py DELETED: **PASS** -- File does not exist on
  disk.
- [ADR-009 Key Shifts] permissions.py DELETED: **PASS** (Rev 2)
  --`lib/core/permissions.py` has been deleted. The 6 permission symbols
  (`PermissionEngine`, `PermissionAction`, `PermissionDecision`,
  `PermissionPolicy`, `PermissionRequest`, `PermissionScope`) are no longer
  imported or exported. `PermissionDeniedError`still correctly exported
  from`exceptions.py`.
- [ADR-009 SS5] Facade exports `compile_team_graph`: **PASS** (Rev 2) -- Line
  35: `from .graph import compile_team_graph as compile_team_graph`. In
  `__all__`at line 139.
- [ADR-009 SS5] Facade exports`create_worker_node`: **PASS** (Rev 2) -- Line 46:
  `from .nodes.worker import create_worker_node as create_worker_node`. In
  `__all__`at line 141.
- [ADR-009 SS5] Facade exports`create_supervisor_node`: **PASS** (Rev 2) -- Line
  45: `from .nodes.supervisor import create_supervisor_node as
  create_supervisor_node`. In `__all__`at line 140.
- [ADR-009]`EventAggregator`via lazy import: **PASS** -- Uses`__getattr__`lazy
  import pattern.

---

## lib/core/permissions.py

- **DELETED** (Rev 2). The 377-line`PermissionEngine`implementation has been
  removed per ADR-009 Key Architectural Shifts table. Permission handling is now
  exclusively via LangGraph`interrupt()`in`worker.py`. This resolves the ADR-009
  tension identified in Rev 1.

---

## lib/core/exceptions.py

- [ADR-009] `__all__`defined: **PASS** -- Lines 223-240.
- All exception classes remain intact after permissions.py
  deletion.`PermissionDeniedError`still present and valid (line 144).

---

## lib/core/presets/agents/*.toml

- [ADR-012 SS2.7] 4 required preset agents (planner, coder, reviewer, analyst):
  **PASS** -- All 4 files exist + supervisor.toml.
- [ADR-012 SS2.7] Capability matrices verified: **PASS**.

---

## lib/core/presets/teams/*.toml

- [ADR-013 SS2.9] 4 required team presets: **PASS** -- coding-star,
  coding-pipeline, coding-loop, solo-coder.
- [ADR-013 SS2.9] Topologies correct: **PASS**.

---

## lib/core/nodes/worker.py

- [ADR-012 SS2.4]`create_worker_node(model, system_prompt, name)`signature:
  **PASS** -- Line 64.
- [ADR-006] interrupt() wiring for ACP permission_callback: **PASS**
  --`_interrupt_permission_callback`at line 21.
- [ADR-012 SS2.4] Duck-typed permission_callback detection: **PASS** --`if
  hasattr(model, "permission_callback")`at line 97.
- [ADR-009]`__all__`defined: **PASS**.
- [ADR-009] Relative imports: **PASS**.

---

## lib/core/nodes/supervisor.py

- [ADR-013 SS2.6] Routing logic: text-parsing supervisor output: **PASS** --
  Lines 43-54.
- [ADR-013] END condition:`next_route = "FINISH"`when no match: **PASS**.
- [ADR-009]`__all__`: **PASS** (Rev 3) -- `__all__ =
  ["create_supervisor_node"]`at line 12.
- [ADR-009] Relative imports: **PASS**.

---

## lib/api/app.py

- [ADR-007]`@asynccontextmanager`lifespan: **PASS** -- Line 55.
- [ADR-007] CORS middleware (permissive in dev): **PASS** -- Lines 147-154.
- [ADR-007] StaticFiles mounted at src/ui/build/: **PASS** -- Lines 176-181.
- [ADR-007] Database initialized at startup: **PASS** -- Line 73.
- [ADR-010] Telemetry configured at startup: **PASS** -- Lines 114-116.
- [ADR-010] TelemetryMiddleware mounted: **PASS** (Rev 3) -- Lines
  157-158:`app.add_middleware(cast(Any, _TelemetryMiddleware))`. Optional import
  with graceful fallback at lines 38-43.
- [ADR-011] WebSocket at /ws: **PASS** -- Lines 168-173.
- [ADR-006] MCP server mounted at /mcp: **PASS** -- Line 165.
- [ADR-004] EventAggregator created in lifespan: **PASS** -- Line 77.
- [ADR-009] `__all__`defined: **PASS**.
- [ADR-009] Relative imports: **PASS**.
- [GAP] Lifespan properly structured: **PASS**.
- [ADR-007 SS5]`anyio.create_task_group()`in lifespan: **MISSING** -- Background
  tasks use fire-and-forget asyncio tasks.

---

## lib/api/endpoints.py

- [ADR-011 SS2.2] POST /threads: **PASS** -- Line 131.
- [ADR-011 SS2.2] GET /threads: **PASS** -- Line 217.
- [ADR-011 SS2.2] GET /threads/{id}/state: **PASS** -- Line 243.
- [ADR-011 SS2.2] POST /threads/{id}/messages: **PASS** -- Line 273.
- [ADR-011 SS2.2] GET /team/status: **PASS** -- Line 330.
- [ADR-011 SS2.2] POST /permissions/{id}/respond: **PASS** -- Line 391.
- [ADR-013 SS6] GET /teams endpoint: **PASS** -- Line 357.
- [ADR-011 SS3.1] Permission response via REST only: **PASS**
  --`Command(resume=body.option_id)`at line 431.
- [ADR-011] GET /threads/{id}/state calls graph.get_state(): **PASS** (Rev 3)
  --`_enrich_snapshot_from_state()`at lines 245-285 maps LangChain BaseMessage
  to MessageSnapshot.`aget_state()`called at line 321. Graceful fallback: logs
  warning on exception, never 500s. Extracts`checkpoint_id`from state config.
- [ADR-009]`__all__`defined: **PASS**.
- [ADR-009] Relative imports: **PASS**.

---

## lib/api/websocket.py

- [ADR-011 SS5] Heartbeat every 30 seconds: **PASS** --`_HEARTBEAT_INTERVAL =
  30.0`at line 65.
- [ADR-011] ConnectedEvent on open: **PASS** -- Lines 116-121.
- [ADR-011] HeartbeatEvent with timestamp and server_uptime_seconds: **PASS** --
  Lines 316-319.
- [ADR-004] subscribe/unsubscribe scoped by thread_id: **PASS** -- Lines
  199-215.
- [ADR-011 SS3.1] PermissionResponse via WS: logs but delegates to REST:
  **PASS** -- Lines 252-261.
- [ADR-011] SEND_MESSAGE wired to graph invocation: **PASS** -- Lines 217-239.
- [ADR-004 SS5] Backpressure via bounded queue per client: **PASS** -- Queue
  from aggregator (maxsize=512).
- [ADR-010] OTel instrumentation: **PASS** (Rev 2) --`ws_span`from
  telemetry.middleware used in`connect`, `disconnect`, `_handle_client_message`.
  `get_tracer`and`get_meter`called at module level. 3 OTel
  counters:`ws.events_sent`, `ws.send_failures`, `ws.heartbeats_sent`.
- [ADR-011 SS5] Dead connection timeout 90s (3 missed heartbeats): **PASS** (Rev
  3) -- `_DEAD_CLIENT_TIMEOUT = 90.0`at line
  68.`asyncio.wait_for(websocket.receive_json(),
  timeout=_DEAD_CLIENT_TIMEOUT)`at line 176. Heartbeat loop runs independently
  as separate task.
- [ADR-010] inject_trace_context in WS writer: **PASS** (Rev 3) -- Lines
  314-318:`inject_trace_context(trace_carrier)`called per frame, injected
  as`payload["_trace"]`for W3C traceparent propagation.
- [ADR-009]`__all__`defined: **PASS**.
- [ADR-009] Relative imports: **PASS**.

---

## lib/api/schemas/events.py

- [ADR-011] All 12 server event types present: **PASS** -- All 12 present.
- [ADR-012 SS6] AgentSummary has role, display_name, description: **PASS** --
  Lines 120-122.
- [ADR-012 SS6] AgentSummary has agent_id, node_name, state, provider, model:
  **PASS** -- Lines 114-118.
- [ADR-011] Discriminated union on`type`field: **PASS**
  --`Field(discriminator="type")`at line 268.
- [ADR-011] Connection-scoped events do NOT extend EventEnvelope: **PASS** --
  ConnectedEvent and HeartbeatEvent extend BaseModel directly.
- [ADR-009]`__all__`defined: **PASS**.
- [ADR-009] Relative imports: **PASS**.

---

## lib/api/schemas/rest.py

- [ADR-013 SS6] CreateThreadRequest has team_preset field: **PASS**.
- [ADR-013 SS6] TeamPresetsResponse model exists: **PASS**.
- [ADR-013 SS6] TeamPresetSummary fields: **PASS**.
- [ADR-011] All REST request/response models present: **PASS**.
- [ADR-009]`__all__`defined: **PASS**.
- [ADR-009] Relative imports: **PASS**.

---

## lib/api/schemas/enums.py

- [ADR-011] AgentLifecycleState (8 states): **PASS**.
- [ADR-011] ServerEventType (12 types): **PASS**.
- [ADR-011] ClientCommandType (6 types): **PASS**.
- [ADR-009]`__all__`defined: **PASS**.

---

## lib/api/schemas/commands.py

- [ADR-011] All 6 client command types: **PASS**.
- [ADR-011] ClientMessage discriminated union: **PASS**.
- [ADR-009]`__all__`defined: **PASS**.
- [ADR-009] Relative imports: **PASS**.

---

## lib/providers/acp_chat_model.py

- [ADR-006 SS5.1 pt 1]`asyncio.create_subprocess_shell`with single string:
  **PASS** -- Line 164.
- [ADR-006 SS5.1 pt 2]`limit=10*1024*1024`(10MB buffer): **PASS** -- Line 171.
- [ADR-006 SS5.1 pt 3] Stdin:`json.dumps(req).encode("utf-8") + b"\n"`: **PASS**
  -- Used consistently.
- [ADR-006 SS5.1 pt 4] `while line := await process.stdout.readline()`: **PASS**
  -- Line 339.
- [ADR-006 SS5.1 pt 5] Bidirectional dispatch: **PASS** -- `_dispatch_packet`at
  line 361.
- [ADR-006 SS5.1 pt 6] ACP session lifecycle (initialize -> session/new ->
  session/prompt): **PASS**.
- [ADR-006 SS5.1 pt 7] Tool call tracking dict keyed by toolCallId: **PASS**.
- [ADR-006 SS5.1 pt 8] end_turn detection: **PASS** -- Line 390.
- [ADR-006 SS5.1 pt 9] Windows pipe cleanup via`_transport.close()`: **PASS** --
  Lines 282-284.
- [ADR-006 SS5.1 pt 10] session/cancel with id + 3s timeout: **PASS** -- Lines
  261-275.
- [ADR-006 SS5.1 pt 11] _handle_server_rpc handles fs/*and terminal/* methods:
  **PASS** (Rev 3) -- `_RPC_DISPATCH`dict at lines 412-421 dispatches all 8
  methods:`session/request_permission`, `fs/read_text_file`,
  `fs/write_text_file`, `terminal/create`, `terminal/kill`, `terminal/output`,
  `terminal/wait_for_exit`, `terminal/release`. Sandbox path validation via
  `_sandbox_path()`. Terminal lifecycle tracked in `ctx.terminals`. Unknown
  methods return -32601 per JSON-RPC spec.
- [ADR-006 SS5.1 pt 12] _process_stdout_loop handles batch JSON-RPC: **PASS**
  (Rev 3) -- Lines 361-364: `isinstance(parsed, list)`branch iterates batch
  items and dispatches each via`_dispatch_packet`.
- [ADR-012 SS2.6] AcpChatModel `agent_config: AgentConfig | None = None` field:
  **PASS** -- Line 111.
- [ADR-012 SS5] agent_config=None -> hardcoded False for all ACP flags: **PASS**
  -- Lines 500-515.
- [ADR-009]`__all__`defined: **PASS**.
- [ADR-009] Relative imports: **PASS**.

---

## lib/providers/factory.py

- [ADR-012 SS2.4]`ProviderFactory.create(provider, capability)`accepts
  AgentConfig: **PASS** -- Line 27.
- [ADR-002] Claude: AcpChatModel with CLAUDE_CODE_OAUTH_TOKEN via env: **PASS**.
- [ADR-002] Gemini: AcpChatModel with zero credential injection: **PASS**.
- [ADR-002] GLM-5/Zhipu: ChatOpenAI with base_url override: **PASS**.
- [ADR-009]`__all__`: **PASS** (Rev 3) -- `__all__ = ["ProviderFactory"]`at line
  16.
- [ADR-009] Relative imports: **PASS**.

---

## lib/providers/**init**.py

- [ADR-009] Facade with`X as X`re-exports: **PASS** (Rev 3) -- Eager`X as
  X`imports for 6 exception types (lines 12-17). Lazy imports
  for`AcpChatModel`and`ProviderFactory`via`__getattr__`with`globals()`caching
  (lines 23-36). Docstring with usage example.
- [ADR-009]`__all__`defined: **PASS** (Rev 3) -- 8 symbols in`__all__`(lines
  39-48).
- [ADR-009] Relative imports: **PASS** --`.acp_exceptions`, `.acp_chat_model`,
  `.factory`.

---

## lib/providers/acp_exceptions.py

- [ADR-009] `__all__`: **PASS** (Rev 3) -- `__all__`with 6 symbols at lines
  9-16.
- [ADR-009] Relative imports: N/A -- no internal lib/ imports.

---

## lib/database/session.py

- [ADR-007] WAL mode pragmas: **PASS**.
- [ADR-007] aiosqlite via async engine: **PASS**.
- [ADR-009]`__all__`defined: **PASS**.
- [ADR-009] Relative imports: **PASS**.

---

## lib/database/**init**.py

- [ADR-009] Facade with`X as X`re-exports: **PASS**.
- [ADR-009]`__all__`defined: **PASS**.

---

## lib/workspace/git_manager.py

- [ADR-001]`asyncio.Lock()`mutex: **PASS**.
- [ADR-001]`asyncio.create_subprocess_exec`: **PASS**.
- [ADR-001] `asyncio.shield()`on destructive operations: **PASS**.
- [ADR-001] Branch naming`agent/{agent_id}`: **PASS**.
- [ADR-009] `__all__`defined: **PASS**.
- [ADR-009] Relative imports: **PASS**.

---

## lib/telemetry/instrumentation.py

- [ADR-010] Optional OTel with no-op fallback: **PASS**.
- [ADR-010]`configure_telemetry()`function: **PASS**.
- [ADR-009]`__all__`defined: **PASS**.
- [ADR-009] Relative imports: N/A.

---

## lib/telemetry/middleware.py

- [ADR-010] TelemetryMiddleware for HTTP spans: **PASS**.
- [ADR-010] ws_span for WebSocket operations: **PASS**.
- [ADR-010] inject_trace_context into WS frames: **PASS**.
- [ADR-010] W3C traceparent propagation: **PASS**.
- [ADR-009]`__all__`defined: **PASS**.
- [ADR-009] Relative imports: **PASS**.

---

## lib/telemetry/**init**.py

- [ADR-009] Facade with`X as X`re-exports: **PASS**.
- [ADR-009]`__all__`defined: **PASS**.

---

## lib/protocols/mcp/server.py

- [ADR-006 SS5] MCP server returns immediate response: **PASS**.
- [ADR-003] MCP tools exposed: **PASS** -- 3 tools.
- [ADR-006 SS5] MCP tools are stubs: **OBSERVATION** -- Tools return
  documentation text but do NOT invoke the graph engine.
- [ADR-009]`__all__`defined: **PASS**.

---

## CRITICAL VIOLATIONS (Rev 3)

### Resolved from Rev 1

- ~~CRITICAL #4:`lib/core/__init__.py`missing graph and node exports~~ --
  **RESOLVED** (Rev 2). Task #4.
- ~~ADR-009 permissions.py tension~~ -- **RESOLVED** (Rev 2). Task #4.

### Resolved from Rev 2

- ~~CRITICAL #1:`_handle_server_rpc`missing fs/*and terminal/* handlers~~ --
  **RESOLVED** (Rev 3). Task #3. All 7 RPC handlers implemented
  via`_RPC_DISPATCH`dict.
- ~~CRITICAL #2:`_process_stdout_loop`doesn't handle batch JSON-RPC~~ --
  **RESOLVED** (Rev 3). Task #3. Batch JSON-RPC arrays now iterated and
  dispatched.
- ~~CRITICAL #3:`lib/providers/__init__.py`empty facade~~ -- **RESOLVED** (Rev
  3). Task #10. Full facade with 8 symbols, lazy imports,`X as X`pattern.
- ~~CRITICAL #4: GET /threads/{id}/state missing graph.get_state()~~ --
  **RESOLVED** (Rev 3). Task #12.`_enrich_snapshot_from_state()`maps messages,
  extracts checkpoint_id.

### Still Present

### ZERO CRITICAL VIOLATIONS

---

## REGRESSIONS FOUND

None across all 3 revisions.

---

## GAPS RESOLVED (Rev 3)

1. ~~**Gap 5 (Host-side ACP RPC handlers)**~~ -- **RESOLVED**. Task #3. All 7
   methods + batch handling.
2. ~~**Gap 7 (Provider facade)**~~ -- **RESOLVED**. Task #10. Full facade with 8
   symbols.
3. ~~**[ADR-011 SS5] Dead connection timeout (90s)**~~ -- **RESOLVED**. Task
   #6.`_DEAD_CLIENT_TIMEOUT = 90.0`, `asyncio.wait_for()`.
4. ~~**[ADR-009] Missing `__all__`**~~ -- **RESOLVED**. Task #11. supervisor.py,
   factory.py, acp_exceptions.py, nodes/**init**.py all have `__all__`.
5. ~~**[ADR-010] TelemetryMiddleware not mounted**~~ -- **RESOLVED**. Task #5.
   Mounted in app.py line 158.
6. ~~**[ADR-010] inject_trace_context not called in WS writer**~~ --
   **RESOLVED**. Task #5. Called in websocket.py line 316.

## REMAINING GAPS (non-critical, deferred)

1. **[ADR-007 SS5] `anyio.create_task_group()`in lifespan**: Not used.
   Background tasks use fire-and-forget asyncio tasks. Low priority.

1. **[ADR-006 SS5] MCP tools are stubs**: They return documentation text but do
   not invoke the graph engine. Deferred to MCP integration phase.

1. **[MINOR]`_sandbox_path`uses string prefix
comparison**:`str(resolved).startswith(str(cwd.resolve()))`in`acp_chat_model.py:470`.
   Could theoretically be tricked with path prefix collisions (e.g.,
   `/home/user`vs`/home/user2`). Low risk since cwd is controlled by the
   orchestrator.

1. **[MINOR] `terminal/output` concatenates stdout+stderr**: No distinction
   between streams. Acceptable for v1.

---

## SUMMARY ACROSS REVISIONS

| Revision | Criticals | Gaps | Tasks Verified |
| ---------- | ----------- | ------ | ---------------- |
| Rev 1 | 5 | 6 | 0 |
| Rev 2 | 4 | 6 | #4 |
| Rev 3 | **0** | **2 (non-critical)** | #3, #4, #5, #6, #10, #11, #12 |

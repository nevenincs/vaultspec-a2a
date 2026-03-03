---
date: 2026-02-27
type: audit
feature: protocol-compliance-gaps
description: 'LangGraph, A2A SDK, ACP protocol, and ADR compliance audit identifying critical gaps including loop_count never incremented and WebSocket permission_response not rejected.'
related:
  - docs/adrs/2026-02-26-003-protocol-bridging-translation-adr.md
  - docs/adrs/2026-02-26-011-frontend-backend-contract-adr.md
  - docs/adrs/2026-02-27-013-team-composition-topology-adr.md
---

# Protocol Compliance & Gaps Audit -- 2026-02-27

## Auditor: auditor-2

## Scope: LangGraph compliance, A2A SDK compliance, ACP protocol compliance, ADR

compliance, Gaps

---

## CRITICAL COMPLIANCE GAPS

### [COMP-001] loop_count is NEVER incremented -- pipeline_loop max_loops guard

is dead code

**Standard:** ADR-013 section 2.5 ("incremented by loop_node, forced to FINISH
when loop_count >= max_loops")
**Expected:** The loop_node (or a wrapper around it) increments
`TeamState.loop_count`on each iteration.
**Actual:**`_loop_router`in`lib/core/graph.py:307`reads`state.get("loop_count",
0)`and compares against`max_loops`, but **no node in the entire codebase ever
writes `loop_count + 1`back to state**. Worker nodes only return`{"messages":
[response]}`. The `create_worker_node`function
at`lib/core/nodes/worker.py:92-102`returns`{"messages": [response]}`with
no`loop_count`key.
**Impact:** **CRITICAL.** In any`pipeline_loop`topology, the loop will run
indefinitely (until token exhaustion or other failure), completely ignoring
the`max_loops`configuration. The guard at`graph.py:308`is unreachable dead code.
**Fix:** The loop_node must return`{"loop_count": current_loop_count + 1,
"messages": [...]}`. Either create a specialized `create_loop_worker_node`or
wrap the worker_node for`pipeline_loop`topologies to increment`loop_count`on
each pass.

### [COMP-002] permission_response WS commands NOT explicitly rejected server-side

**Standard:** ADR-011 section 3.1 ("permission responses via REST only"), Gap 2
in backend-foundational-gaps.md ("permission_response MUST go via REST only --
reject if received over WS")
**Expected:** When a`ClientCommandType.PERMISSION_RESPONSE`command arrives over
WebSocket, the server should reject it with an error response and NOT process
it.
**Actual:** In`lib/api/websocket.py:268-277`, the `PERMISSION_RESPONSE`case
simply logs the event and adds a comment "Permission responses are preferably
handled via REST (ADR-011 section 3.1) for guaranteed delivery" -- but it does
NOT reject the command. It silently accepts and ignores it, with no error sent
back to the client.
**Impact:** **HIGH.** The frontend could send permission responses over
WebSocket, which may appear to succeed from the client perspective but would be
silently dropped. The protocol specification requires explicit rejection, not
silent acceptance. A malformed client could believe it responded to a permission
request when it did not.
**Fix:** Send an error event back to the client when`PERMISSION_RESPONSE`
arrives via WebSocket, e.g.:

```python
case ClientCommandType.PERMISSION_RESPONSE:
    await websocket.send_json({
        "type": "error",
        "code": "WS_PERMISSION_REJECTED",
        "message": "Permission responses must use REST POST /permissions/{id}/respond"
    })
```

### [COMP-003] ACP initialize response validation is incomplete vs TOAD

**Standard:** ADR-006 section 5.1 point 6, TOAD `agent.py:635-661`
**Expected:** After `initialize`, store `agentCapabilities`and
check`loadSession`before attempting`session/load`. Also store `authMethods`.
**Actual:** In `lib/providers/acp_chat_model.py:706-711`, the implementation
stores `agentCapabilities`and`authMethods`but does NOT validate
the`protocolVersion`in the response (TOAD asserts`response is not None`and
stores all fields). However, the`loadSession` check IS correctly done at line
718 (`self._agent_capabilities.get("loadSession")`).
**Impact:** MEDIUM. If the server returns an incompatible protocol version, the
client will continue with potentially incompatible behavior.

---

## ADR-006 section 5.1 COMPLIANCE MATRIX

| #   | Pattern                                                        | Line in acp_chat_model.py | Status   | Notes                                                                                                                                                                                                                                             |
| --- | -------------------------------------------------------------- | ------------------------- | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | `create_subprocess_shell(command_str)`                         | line 166-174              | **PASS** | Uses`asyncio.create_subprocess_shell(shell_command, ...)`with single string                                                                                                                                                                       |
| 2   | `limit=10*1024*1024`on stdout/stderr                           | line 173                  | **PASS** | `limit=10 * 1024 * 1024`                                                                                                                                                                                                                          |
| 3   | Stdin:`json.dumps(req).encode("utf-8") + b"\n"`                | lines 704, 725, 754, 282  | **PASS** | Consistently uses`json.dumps(req).encode("utf-8") + b"\n"`                                                                                                                                                                                        |
| 4   | Stdout:`while line := await process.stdout.readline()`         | line 348                  | **PASS** | Uses walrus operator readline loop                                                                                                                                                                                                                |
| 5   | Bidirectional dispatch: responses vs notifications             | lines 374-394             | **PASS** | `_dispatch_packet`checks for`result`/`error`(response) vs`method`with`id`(server RPC) vs`method`without`id`(notification)                                                                                                                         |
| 6   | Session lifecycle: initialize -> session/new -> session/prompt | lines 194-196             | **PASS** | `_initialize_session`->`_setup_session`->`_setup_prompt`                                                                                                                                                                                          |
| 7   | Tool call tracking dict keyed by`toolCallId`                   | line 647                  | **PASS** | `self._tool_calls[tid] = dict(update)`                                                                                                                                                                                                            |
| 8   | `end_turn`detection from session/prompt response               | line 403                  | **PASS** | `result.get("stopReason") == "end_turn"`triggers`ctx.prompt_done.set()`                                                                                                                                                                           |
| 9   | Windows pipe cleanup via`_transport.close()`                   | lines 291-293             | **PASS** | `transport = getattr(ctx.process, "_transport", None); if transport is not None: transport.close()`                                                                                                                                               |
| 10  | `session/cancel`proper JSON-RPC with 3s timeout                | lines 268-284             | **PASS** | Sends with`rpc_id`, awaits `ctx.response_futures[rpc_id]`with`timeout=3.0`                                                                                                                                                                        |
| 11  | `_handle_server_rpc`handles all 7 fs/terminal methods          | lines 412-421             | **PASS** | Dispatch table covers:`session/request_permission`, `fs/read_text_file`, `fs/write_text_file`, `terminal/create`, `terminal/kill`, `terminal/output`, `terminal/wait_for_exit`, `terminal/release`(8 methods total, 7 fs/terminal + 1 permission) |
| 12  | `_process_stdout_loop`handles batch JSON-RPC (list)            | lines 361-366             | **PASS** | `if isinstance(parsed, list): for item in parsed: ...`                                                                                                                                                                                            |

---

## LANGGRAPH COMPLIANCE ISSUES

### [LG-001] loop_count never incremented (see COMP-001)

**File:**`lib/core/graph.py:305-310`, `lib/core/nodes/worker.py:92-102`
**Standard:** ADR-013 section 2.5 ("`loop_count`incremented by loop_node")
**Actual:** Worker node returns only`{"messages": [response]}`. No code path
writes `loop_count`.
**Impact:** CRITICAL. Pipeline_loop topology runs forever, ignoring max_loops.

### [LG-002] astream_events version="v2" correctly used

**File:** `lib/core/aggregator.py:787-791`
**Standard:** ADR-004 (use `astream_events(version="v2")`)
**Actual:** `graph.astream_events(graph_input, config, version="v2")`-- CORRECT.
**Status:** PASS

### [LG-003] add_sequence not used directly -- correct workaround

**File:**`lib/core/graph.py:253-256, 296-300`
**Standard:** ADR-013 section 2.5 references `add_sequence`but the LangGraph API
signature at`state.py:889`shows`add_sequence`expects callables and
calls`add_node`internally.
**Actual:** The implementation correctly uses manual`add_edge`chains instead
of`add_sequence`because nodes are pre-registered with metadata via`add_node`.
The comment at line 229 explains this: "Uses explicit add_edge calls (not
add_sequence) because nodes are added with metadata via add_node first."
**Status:** PASS -- correct engineering decision.

### [LG-004] interrupt() correctly used from langgraph.types

**File:** `lib/core/nodes/worker.py:8` (`from langgraph.types import interrupt`)
**Standard:** LangGraph interrupt API
**Actual:** Correctly imports from `langgraph.types`and
calls`interrupt()`in`_interrupt_permission_callback`at line 47.
**Status:** PASS

### [LG-005] Supervisor routing via text parsing is fragile

**File:**`lib/core/nodes/supervisor.py:45-56`
**Standard:** ADR-013 section 2.5 star spec (supervisor returns `{"next":
agent_id}`)
**Actual:** The supervisor invokes the LLM with a text prompt asking it to
respond with a worker name, then parses the text output with exact match /
substring fallback. This is fragile -- the LLM may wrap the name in quotes, add
punctuation, or include explanation text that contains a worker name as a
substring.
**Impact:** MEDIUM. Could cause routing failures or incorrect routing if the LLM
response format is unexpected. The ADR-013 section 2.5 star code example assumes
`state["next"]`is cleanly set. LangGraph's official`create_react_agent`pattern
uses structured output (function calling) to avoid text parsing.
**Status:** ADVISORY -- works but fragile.

### [LG-006] TeamState`messages`uses`add_messages`reducer -- correct

**File:**`lib/core/state.py:80`
**Standard:** LangGraph pattern for message accumulation
**Actual:** `messages: Annotated[list[BaseMessage], add_messages]`-- CORRECT.
The`add_messages`reducer handles deduplication and proper message append
semantics, including on interrupt resume.
**Status:** PASS

### [LG-007] TeamState`loop_count`is last-write-wins (no reducer) -- correct design

**File:**`lib/core/state.py:100`
**Standard:** ADR-013 section 5 ("plain last-write-wins int")
**Actual:** `loop_count: NotRequired[int]`with no`Annotated`reducer -- this is
correct last-write-wins semantics for LangGraph.
**Status:** PASS (but the value is never written -- see COMP-001)

### [LG-008] on_chain_stream event not handled in aggregator

**File:**`lib/core/aggregator.py:96-110`
**Standard:** LangGraph v2 emits `on_chain_stream`for structured output
**Actual:** The`_PASSTHROUGH_EVENTS`and`_NODE_BOUNDARY_EVENTS`sets do not
include`on_chain_stream`. This event is silently filtered out (logged as debug
"Filtered LangGraph event").
**Impact:** LOW. Structured output streaming from chains will not appear in the
frontend. This may become relevant if agents produce structured output.
**Status:** GAP -- not blocking but should be addressed for completeness.

---

## A2A SDK GAPS

### [A2A-001] No subscriber cleanup on disconnect with backpressure

**Standard:** A2A `event_queue.py`uses bounded queues
with`close()`and`clear_events()`for cleanup.`InMemoryQueueManager`uses async
locks for all operations.
**Actual:**
Our`EventAggregator.remove_subscriber()`at`aggregator.py:263-266`simply pops the
queue and subscriptions dicts. It does NOT drain or close the queue. If a
subscriber disconnects while events are pending, those events are simply
garbage-collected.
**Impact:** LOW. No resource leak since Python GC handles it, but it differs
from A2A's explicit close pattern which ensures orderly shutdown.
**Status:** GAP

### [A2A-002] No tap/child queue pattern for late-joining subscribers

**Standard:** A2A`InMemoryQueueManager.tap()`creates child queues that receive
all future events from a parent queue. This enables multiple consumers of the
same event stream.
**Actual:** Our`EventAggregator`does not implement a tap/child pattern. Each
subscriber gets its own independent queue. If a subscriber connects mid-stream,
it only receives events from that point forward.
**Impact:** LOW for v1. The REST`/threads/{id}/state`endpoint handles
reconnection replay.
**Status:** GAP

### [A2A-003] Backpressure: queue.put() blocks instead of oldest-message-drop

**Standard:** Backend-foundational-gaps.md section 2 specifies "Backpressure via
bounded queue per client (oldest-message-drop on overflow)"
**Actual:**`EventAggregator._broadcast()`at`aggregator.py:307`uses`await
queue.put(event)`which blocks when the queue is full (maxsize=512). The comment
says "Uses`await queue.put()`(never`put_nowait`) to propagate backpressure".
**Impact:** MEDIUM. A slow subscriber will block ALL broadcasts (since
`_broadcast`iterates sequentially). This means one slow client can stall event
delivery to all other clients. The spec says oldest-message-drop; the
implementation does blocking wait instead.
**Fix:** Use`put_nowait()`with exception handling that drops the oldest
message:`try: queue.put_nowait(event) except asyncio.QueueFull:
queue.get_nowait(); queue.put_nowait(event)`.

---

## ACP PROTOCOL DEVIATIONS (vs TOAD reference)

### [ACP-001] Missing `session/update`handling for`user_message_chunk`

**Standard:** TOAD `agent.py:236-239`handles`user_message_chunk`session updates
**Actual:**`_handle_session_update`at`acp_chat_model.py:626-643`does not
handle`user_message_chunk`. Only handles: `agent_message_chunk`,
`agent_thought_chunk`, `tool_call`, `tool_call_update`, `current_mode_update`.
**Impact:** LOW. User message chunks are echoes of what the host sent; ignoring
them is acceptable.

### [ACP-002] Missing `plan`session update handling

**Standard:** TOAD`agent.py:260-261`handles`{"sessionUpdate": "plan", "entries":
entries}`
**Actual:** `_handle_session_update`does not handle`plan`updates.
**Impact:** MEDIUM. Plan entries from ACP agents will be silently dropped. The
frontend has a`PlanUpdateEvent`schema type but it will never be emitted from ACP
agent sessions.

### [ACP-003] Missing`available_commands_update`session update handling

**Standard:** TOAD`agent.py:290-294`handles`available_commands_update`
**Actual:** Not handled in `_handle_session_update`.
**Impact:** LOW. Available commands are informational for UI purposes.

### [ACP-004] Missing `tool_call_update`synthetic entry creation for unknown toolCallId

**Standard:** TOAD`agent.py:277-288`creates a synthetic`tool_call`entry when
a`tool_call_update`arrives for an unknown`toolCallId`.
**Actual:** `_on_tool_call_update`at`acp_chat_model.py:663-670`silently ignores
updates for unknown tool call IDs (only updates if`tid in self._tool_calls`).
**Impact:** MEDIUM. If an ACP agent sends a `tool_call_update`before its
corresponding`tool_call`(which TOAD documents as a real scenario), the update
will be lost.

### [ACP-005] fs/read_text_file missing`line`and`limit`parameters

| **Standard:** TOAD`agent.py:349-370`supports optional`line: int |
None`and`limit: int | None`parameters for partial file reads. |
**Actual:**`_on_fs_read_text_file`at`acp_chat_model.py:474-487`only
reads`params["path"]`and returns the full file content. No`line`/`limit`support.
**Impact:** MEDIUM. Agents requesting partial file reads will receive the entire
file, wasting tokens and potentially exceeding context limits.

### [ACP-006] terminal/output response structure differs from TOAD

**Standard:** TOAD`agent.py:439-445`returns`{"output": str, "truncated":
bool}`and optionally`{"exitStatus": {"exitCode": int}}`if the process has
exited.
**Actual:**`_on_terminal_output`at`acp_chat_model.py:553-585`returns`{"output":
combined, "truncated": False}`but never includes`exitStatus`even when the
process has finished.
**Impact:** LOW. Agents won't know a terminal has exited until they
call`terminal/wait_for_exit`.

### [ACP-007] terminal/wait_for_exit response missing `signal`field

**Standard:** TOAD`agent.py:467-468`returns`{"exitCode": return_code, "signal":
signal}`.
**Actual:**
`_on_terminal_wait_for_exit`at`acp_chat_model.py:608-612`returns`{"exitCode":
process.returncode}`but no`signal`field.
**Impact:** LOW. ACP protocol specifies the field but agents may tolerate its
absence.

### [ACP-008] terminal/create does not support`env`parameter correctly

**Standard:** TOAD`agent.py:396-398`maps`env`list of`{name, value}`dicts to a
flat env dict.
**Actual:**`_on_terminal_create`at`acp_chat_model.py:505-533`ignores
the`env`parameter entirely. It spawns the process with no env override.
**Impact:** MEDIUM. Agents that pass environment variables to terminal commands
will have those variables silently ignored.

### [ACP-009] No`clientInfo.title`field in initialize request

**Standard:** TOAD`protocol.py:24-27`defines`Implementation`with`name`, `title`,
and `version`fields. TOAD`agent.py:649`sends`title: toad.TITLE`.
**Actual:** `_initialize_session`at`acp_chat_model.py:701`sends`"clientInfo":
{"name": "vaultspec", "version": "1.0.0"}`without`title`.
**Impact:** LOW. Field is optional per the TypedDict.

### Total ACP deviations vs TOAD: 9

---

## ADR COMPLIANCE DETAILS

### ADR-001: Process & Workspace Management

| Clause                                    | Status       | Notes                                                        |
| ----------------------------------------- | ------------ | ------------------------------------------------------------ |
| Managed CLI subprocesses via AcpChatModel | PASS         | Correctly implemented                                        |
| Zero PTY / Zero Batch                     | PASS         | `create_subprocess_shell`with piped stdin/stdout/stderr      |
| Workspace isolation (worktrees)           | PASS         | `lib/workspace/git_manager.py`exists                         |
| Global Git Mutex                          | NOT VERIFIED | `git_manager.py`exists but not read in detail for this audit |

### ADR-004: Event Aggregation & State Replay

| Clause                                   | Status      | Notes                                                                                     |
| ---------------------------------------- | ----------- | ----------------------------------------------------------------------------------------- |
| Sequence numbers monotonic per thread_id | PASS        | `aggregator.py:183-186`uses`defaultdict(int)`incremented atomically                       |
| Fan-out to subscribed clients only       | PASS        | `_broadcast`checks`thread_id in client_subs`at`aggregator.py:306`                         |
| Backpressure bounded queue per client    | **PARTIAL** | Queue is bounded (maxsize=512) but uses blocking put instead of oldest-drop (see A2A-003) |
| State replay via REST                    | PASS        | `GET /threads/{id}/state`at`endpoints.py:288-333`calls`graph.aget_state()`                |

### ADR-006: Protocol Ecosystem & Bridge Strategy

| Clause                                       | Status         | Notes                                                      |
| -------------------------------------------- | -------------- | ---------------------------------------------------------- |
| All 12 AcpChatModel subprocess patterns      | **11/12 PASS** | Only missing fs/read_text_file line/limit params (ACP-005) |
| session/cancel as proper RPC with 3s timeout | PASS           | `acp_chat_model.py:268-284`                                |
| Host-side RPC handlers (7 methods)           | PASS           | 8 handlers registered in dispatch table                    |

### ADR-007: Tech Stack & Deployment

| Clause                                            | Status   | Notes                                                                                                                                                                                     |
| ------------------------------------------------- | -------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| ProactorEventLoop on Windows                      | PASS     | Default on Python 3.13/Windows, no special config needed                                                                                                                                  |
| No uvloop                                         | PASS     | Not imported anywhere                                                                                                                                                                     |
| AsyncSqliteSaver from langgraph-checkpoint-sqlite | PASS     | Imported in`graph.py:16`                                                                                                                                                                  |
| WAL mode: PRAGMA journal_mode=WAL                 | PASS     | `session.py:51`sets WAL on every connection                                                                                                                                               |
| CORS middleware                                   | PASS     | `app.py:147-154`adds CORSMiddleware in dev mode                                                                                                                                           |
| anyio.create_task_group() in lifespan             | **FAIL** | ADR-007 section 5 specifies`anyio.create_task_group()`but`app.py`uses plain lifespan context manager with no task group. Background tasks are created with`asyncio.create_task()`instead. |

### ADR-009: Facade Pattern & Module Hierarchy

| Sub-module                    | `__all__` | `X as X`                       | Relative imports | Status                                                                                              |
| ----------------------------- | --------- | ------------------------------ | ---------------- | --------------------------------------------------------------------------------------------------- |
| `lib/api/__init__.py`         | PASS      | PASS                           | PASS             | CLEAN                                                                                               |
| `lib/api/schemas/__init__.py` | PASS      | PASS                           | PASS             | CLEAN                                                                                               |
| `lib/core/__init__.py`        | PASS      | Uses lazy`__getattr__`for some | PASS             | CLEAN                                                                                               |
| `lib/core/nodes/__init__.py`  | PASS      | PASS                           | PASS             | CLEAN                                                                                               |
| `lib/providers/__init__.py`   | PASS      | Uses lazy`__getattr__`for some | PASS             | CLEAN                                                                                               |
| `lib/database/__init__.py`    | PASS      | PASS                           | PASS             | CLEAN                                                                                               |
| `lib/telemetry/__init__.py`   | PASS      | PASS                           | PASS             | CLEAN                                                                                               |
| `lib/workspace/__init__.py`   | PASS      | PASS                           | PASS             | CLEAN                                                                                               |
| `lib/utils/__init__.py`       | PASS      | **FAIL**                       | PASS             | Missing`X as X`pattern -- uses bare`from .enums import AgentState, Environment, LogLevel, Provider` |
| `lib/core/registry.py`        | DELETED   | N/A                            | N/A              | CLEAN (per ADR-009)                                                                                 |
| `lib/core/permissions.py`     | DELETED   | N/A                            | N/A              | CLEAN (per ADR-009)                                                                                 |

### ADR-010: Observability & Telemetry

| Clause                       | Status | Notes                                                              |
| ---------------------------- | ------ | ------------------------------------------------------------------ |
| OpenTelemetry from day one   | PASS   | `lib/telemetry/instrumentation.py`exists with TracerProvider setup |
| FastAPI auto-instrumentation | PASS   | `TelemetryMiddleware`in`app.py:158`                                |
| LangSmith tracing            | PASS   | Referenced in telemetry config                                     |
| Trace ID in WebSocket frames | PASS   | `websocket.py:315-318`injects`_trace`dict                          |

### ADR-011: Frontend-Backend Wire Contract

| Clause                                      | Status         | Notes                                               |
| ------------------------------------------- | -------------- | --------------------------------------------------- |
| 12 ServerEvent types                        | PASS           | All defined in`schemas/events.py`                   |
| 6 ClientCommand types                       | PASS           | All defined in`schemas/commands.py`                 |
| 6 REST endpoints                            | PASS + 1 extra | 6 ADR-011 routes +`GET /teams`(ADR-013)             |
| Permission response REST-only enforcement   | **FAIL**       | See COMP-002 -- WS permission_response not rejected |
| Sequence monotonic per thread               | PASS           | `aggregator.py:183-186`                             |
| HeartbeatEvent every 30s                    | PASS           | `websocket.py:340`uses`_HEARTBEAT_INTERVAL = 30.0`  |
| Reconnection protocol (snapshot + sequence) | PASS           | `GET /threads/{id}/state`returns`last_sequence`     |

### ADR-012: Agent Definition Schema

| Clause                                                      | Status | Notes                                                            |
| ----------------------------------------------------------- | ------ | ---------------------------------------------------------------- |
| AgentConfig Pydantic model                                  | PASS   | `lib/core/team_config.py`                                        |
| TOML loading via tomllib                                    | PASS   | `from_toml()`uses`tomllib.load()`                                |
| Preset agents in`lib/core/presets/agents/`                  | PASS   | Directory exists                                                 |
| ACP capability binding (agent_config -> clientCapabilities) | PASS   | `acp_chat_model.py:682-699`reads from`agent_config.capabilities` |
| Config discovery order (workspace -> preset -> error)       | PASS   | `load_agent_config()`in`team_config.py`                          |

### ADR-013: Team Composition & Topology

| Clause                                              | Status            | Notes                     |
| --------------------------------------------------- | ----------------- | ------------------------- |
| TeamConfig Pydantic model                           | PASS              | `lib/core/team_config.py` |
| 3 topology types (star, pipeline, pipeline_loop)    | PASS              | All three in`graph.py`    |
| loop_count field in TeamState                       | PASS (declared)   | `state.py:100`            |
| loop_count incremented by loop_node                 | **CRITICAL FAIL** | See COMP-001              |
| Supervisor prompt enhancement with agent roster     | PASS              | `graph.py:67-82`          |
| interrupt_before assembly                           | PASS              | `graph.py:120-125`        |
| Model resolution precedence (worker > agent > team) | PASS              | `graph.py:30-53`          |
| CreateThreadRequest gains team_preset               | PASS              | In`schemas/rest.py`       |
| GET /teams endpoint                                 | PASS              | `endpoints.py:425-451`    |

---

## UNIMPLEMENTED FEATURES

### [UNIMP-001] Dead letter queue for failed events (ADR-011 section 6)

**Standard:** ADR-011 section 6 mentions schema evolution and implies a dead
letter queue for failed events.
**Actual:** No dead letter queue exists. Failed events are logged and dropped.
**Impact:** LOW for v1.

### [UNIMP-002] MCP tools are stubs

**Standard:** ADR-006 section 2 (MCP server exposing team/create, team/status
tools)
**Actual:**`lib/protocols/mcp/server.py`exists (imported in`app.py:31`) and
mounted at `/mcp`, but the actual tool implementations are not audited in this
pass. Based on the import and mount pattern, it appears to be wired but
functionality level is unclear.
**Impact:** UNKNOWN without further investigation.

### [UNIMP-003] Workspace isolation not enforced per-agent

**Standard:** ADR-001 section 2 (dual-mode workspace, worktree per agent)
**Actual:** AcpChatModel accepts a `cwd`parameter and uses it for sandboxing,
but the graph compilation does NOT assign per-agent working directories. All
agents in a team would share the same`cwd` unless explicitly set per
AcpChatModel instance.
**Impact:** MEDIUM for multi-agent concurrent editing scenarios
(`.git/index`corruption risk per ADR-001).

### [UNIMP-004] anyio.create_task_group() not used in lifespan

**Standard:** ADR-007 section 5 ("Long-running background tasks ... must be
carefully tied to FastAPI's @asynccontextmanager lifespan events
using`anyio.create_task_group()`")
**Actual:** `app.py`uses plain`asynccontextmanager`with`yield`and no task group.
Background tasks spawned via`asyncio.create_task()`in endpoints.
**Impact:** LOW. The current approach works but task lifecycle is not
structurally tied to lifespan shutdown. Orphaned tasks could theoretically run
after shutdown begins.

### [UNIMP-005] LangSmith LANGCHAIN_TRACING_V2 not explicitly wired

**Standard:** ADR-010 mandates LangSmith tracing integration
**Actual:** The telemetry module exists and is configured, but there is no
explicit`LANGCHAIN_TRACING_V2=true` environment variable setup in the lifespan
or config. LangSmith tracing would only work if the user sets the env var
manually.
**Impact:** LOW. LangSmith works via env vars natively; the app just doesn't set
them.

---

## CLEAN (passed all checks)

The following areas passed all compliance checks:

- **AcpChatModel subprocess patterns** (11/12 pass, only missing fs line/limit
  params)
- **Wire contract schema completeness** (51 Pydantic types, all 12 events, all 6
  commands)
- **Sequence number management** (monotonic per thread, atomically incremented)
  | - **Session lifecycle ordering** (initialize -> session/new | load ->
  session/prompt) |
- **Windows pipe cleanup** (\_transport.close() pattern)
- **session/cancel as proper RPC** (with 3-second timeout)
- **Batch JSON-RPC handling** (array dispatch in \_process_stdout_loop)
- **Facade pattern compliance** (all sub-modules except lib/utils have correct
  **all** and X as X)
- **Registry and permissions deletion** (ADR-009 mandate fulfilled)
- **CORS middleware** (present in dev mode)
- **WAL mode** (set on every SQLite connection)
- **Heartbeat protocol** (30-second interval)
- **Agent config TOML loading** (discovery order, validation)
- **Three topology types** (star, pipeline, pipeline_loop compilation)
- **OTel instrumentation** (tracers and meters in aggregator and websocket)

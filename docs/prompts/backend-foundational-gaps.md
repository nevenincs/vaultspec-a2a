# Backend Foundational Layer — Implementation Delegation Prompt

## Context

You are implementing the foundational backend infrastructure for the A2A agent
orchestration system. The provider layer (AcpChatModel), LangGraph core (graph
compilation, interrupt/resume), and wire contract schemas (51 Pydantic types) are
already implemented and tested. What's missing is the **serving infrastructure**
that connects these foundations to the frontend.

## Mandatory Pre-Reading

Before writing ANY code, you MUST read and internalize these documents IN ORDER:

### Binding ADRs (read ALL, cover-to-cover)

```
docs/adrs/004-event-aggregation-server-side-replay.md   — Event aggregator, WebSocket, replay
docs/adrs/006-protocol-ecosystem-bridge.md               — ACP protocol, host-side RPCs
docs/adrs/007-tech-stack-deployment.md                   — FastAPI, SQLite WAL, deployment
docs/adrs/008-orchestration-topology-pipeline.md         — LangGraph topology, astream_events
docs/adrs/009-approved-module-hierarchy.md               — Facade pattern, __all__, relative imports
docs/adrs/010-observability-telemetry-integration.md     — OTel, LangSmith (MANDATORY from day one — see Gap 9)
docs/adrs/011-frontend-backend-contract.md               — Wire protocol, 12 events, 6 commands, 6 REST routes
```

### Distilled Docs (read ALL referenced sections)

**NOTE:** Architecture, Process, and Protocols distilled docs are DEPRECATED.
Their gap resolutions reference obsolete A2A/ACP patterns. Only Agents and
Control Surface distilled docs remain current. Read the deprecated ones for
historical context only — ADRs override them where they conflict.

```
docs/distilled/2026-25-02-architecture-distilled.md      — DEPRECATED. Section 3-5 for historical context only
docs/distilled/2026-25-02-protocols-distilled.md         — DEPRECATED. Section 6-7 for historical context only
docs/distilled/2026-25-02-process-distilled.md           — DEPRECATED. Section 1.1 for historical context only
docs/distilled/2026-25-02-agents-distilled.md            — CURRENT. Section 2: Claude/Gemini ACP capabilities
docs/distilled/2026-25-02-control-surface-distilled.md   — CURRENT. Section 2.3: WS integration, terminal streaming
docs/distilled/2026-25-02-control-surface-gaps-research.md — CURRENT. Section 3: Server-side replay
```

### Reference Implementations (read the specific files cited per gap)

```
knowledge/repositories/toad/src/toad/acp/agent.py        — Lines 348-468: Host-side RPC handlers (fs/*, terminal/*)
knowledge/repositories/toad/src/toad/acp/protocol.py     — TypedDict definitions for terminal/fs types
knowledge/repositories/toad/src/toad/db.py               — SQLite session persistence pattern
knowledge/repositories/a2a-python/src/a2a/server/apps/jsonrpc/fastapi_app.py  — FastAPI app pattern
knowledge/repositories/a2a-python/src/a2a/server/apps/rest/fastapi_app.py     — REST endpoint pattern
knowledge/repositories/a2a-python/src/a2a/server/events/event_queue.py        — EventQueue subscriber pattern
knowledge/repositories/a2a-python/src/a2a/server/events/in_memory_queue_manager.py — Multi-subscriber fan-out
knowledge/repositories/langgraph/libs/checkpoint-sqlite/langgraph/checkpoint/sqlite/aio.py — AsyncSqliteSaver bootstrap
```

### Existing Codebase (read before modifying)

```
lib/api/schemas/          — All 6 modules: enums, base, events, commands, rest, snapshots (51 types)
lib/api/__init__.py       — Existing facade (well-done, use as pattern)
lib/api/endpoints.py      — Current stub: router = "router_placeholder"
lib/core/graph.py         — compile_team_graph()
lib/core/state.py         — TeamState TypedDict
lib/core/nodes/worker.py  — Worker node with interrupt() permission wiring
lib/core/nodes/supervisor.py — Supervisor node with text-parsing routing
lib/core/registry.py      — Empty stub, TO BE DELETED per ADR-009
lib/core/permissions.py   — Empty stub, TO BE DELETED per ADR-009
lib/core/__init__.py      — Current exports (incomplete, references stubs to remove)
lib/providers/acp_chat_model.py — 642 lines, full ACP lifecycle
lib/providers/__init__.py — Empty (facade violation)
lib/providers/factory.py  — ProviderFactory.create()
lib/database/__init__.py  — Empty
lib/core/config.py        — Settings with database_url field
```

---

## Implementation Gaps (9 items, ordered by dependency)

### Gap 1: FastAPI Application Entry Point + Lifespan

**Create:** `lib/api/app.py`
**Modify:** `lib/api/__init__.py`, `lib/api/endpoints.py`

Requirements:
- FastAPI application factory using `@asynccontextmanager` lifespan (NOT deprecated `on_event`)
- Lifespan must: initialize AsyncSqliteSaver, compile team graph, start event aggregator, mount static SPA
- Static SPA files served from `src/ui/build/` with fallback to `index.html` (adapter-static SPA mode)
- Mount REST router at `/api/` prefix
- Mount WebSocket at `/ws`
- Single Uvicorn process (no workers — Windows ProactorEventLoop)

**References:** ADR-007 §3, ADR-004 §2, ADR-009 §3

**Constraints:**
- No `uvloop` (Windows incompatible)
- `ProactorEventLoop` is default on Python 3.13/Windows — no special config needed
- Consider adding a `pyproject.toml` script entry or `__main__.py` for launch

---

### Gap 2: WebSocket Multiplexer

**Create:** `lib/api/websocket.py`
**Modify:** `lib/api/app.py` (mount route)

Requirements:
- Single multiplexed WebSocket per browser client
- Parse incoming JSON via `ClientMessage` discriminated union (6 types in `schemas/commands.py`)
- `subscribe` command scopes events to a `thread_id`; `unsubscribe` removes
- Fan-out `ServerEvent` messages to subscribed clients
- Send `ConnectedEvent` with `client_id` on connection
- Send `HeartbeatEvent` every 30 seconds
- Backpressure via bounded queue per client (oldest-message-drop on overflow)
- Sequence numbers monotonic per `thread_id`

**References:** ADR-004 §3, ADR-011 §4

**Constraints:**
- `permission_response` MUST go via REST only (reject if received over WS)
- All agent events carry `agent_id` for client-side routing
- Use existing Pydantic schemas for serialization — `ServerEvent.model_dump_json()`

---

### Gap 3: Event Aggregator (astream_events → ServerEvent)

**Create:** `lib/core/aggregator.py` (filename per ADR-009 hierarchy)
**Modify:** `lib/core/__init__.py` (export)

Requirements:
- Consumes `graph.astream_events(version="v2")` output
- Maps LangGraph event kinds to the 12 `ServerEvent` Pydantic types:
  - `on_chat_model_stream` → `MessageChunkEvent`
  - `on_tool_start` → `ToolCallStartEvent`
  - `on_tool_end` → `ToolCallUpdateEvent(status=completed)`
  - Custom metadata for `ThoughtChunkEvent`, `PermissionRequestEvent`
  - `interrupt` events → `PermissionRequestEvent`
- Assigns monotonic sequence numbers per `thread_id`
- Fans out to subscribed WebSocket clients via the multiplexer
- Runs as a long-lived `asyncio.Task` per graph invocation

**References:** ADR-004 §2, ADR-008 §4, ADR-011 §3

**Constraints:**
- `astream_events` version MUST be `"v2"` (not v1)
- Must handle both streaming chunks AND interrupt events
- Aggregator is the ONLY source of truth for event sequencing

---

### Gap 4: REST Endpoint Wiring (6 Routes)

**Modify:** `lib/api/endpoints.py` — replace stub entirely

Six endpoints per ADR-011 §5:

| Route | Method | Request Schema | Response Schema |
|-------|--------|---------------|-----------------|
| `/api/threads` | POST | `CreateThreadRequest` | `{"thread_id": str}` |
| `/api/threads` | GET | — | `ThreadListResponse` |
| `/api/threads/{id}/state` | GET | — | `ThreadStateSnapshot` |
| `/api/threads/{id}/messages` | POST | `SendMessageRequest` | `{"status": "ok"}` |
| `/api/team/status` | GET | — | `TeamStatusResponse` |
| `/api/permissions/{id}/respond` | POST | `PermissionResponseRequest` | `{"status": "ok"}` |

**References:** ADR-011 §5, ADR-004 §4

**Constraints:**
- `POST /api/permissions/{id}/respond` is the ONLY way to respond to permissions (path per ADR-011)
- `GET /api/threads/{id}/state` must call `graph.get_state({"configurable": {"thread_id": id}})` for reconnection snapshot
- `POST /api/threads` must invoke `graph.ainvoke()` or `graph.astream()` with new `thread_id`
- All endpoints validate against existing Pydantic schemas in `schemas/rest.py` and `schemas/snapshots.py`

---

### Gap 5: Host-side ACP RPC Handlers

**Modify:** `lib/providers/acp_chat_model.py`

Requirements:
- Change `_initialize_session()`: set `fs.readTextFile: True`, `fs.writeTextFile: True`, `terminal: True`
- Expand `_handle_server_rpc()` to dispatch 7 new methods:
  - `fs/read_text_file` — read file contents, return as string
  - `fs/write_text_file` — write string to file path
  - `terminal/create` — spawn async subprocess, return terminal_id
  - `terminal/kill` — kill subprocess by terminal_id
  - `terminal/output` — read stdout/stderr buffer for terminal_id
  - `terminal/wait_for_exit` — await subprocess completion, return exit code
  - `terminal/release` — cleanup terminal resources
- Fix `_cleanup_session()`: change `session/cancel` from notification to RPC with 3-second timeout
- Fix `_process_stdout_loop`: handle batch JSON-RPC (list of dicts, not just single dict)

**References:** ADR-006 §5.1, Toad `agent.py` lines 348-468, Toad `protocol.py`

**Constraints:**
- File system operations MUST be sandboxed to the agent's `cwd`
- Terminal processes tracked per-session, cleaned up on session teardown
- ADR-001 §3: Global git mutex for workspace safety — file writes must respect this
- Follow Toad's patterns faithfully — it is the canonical ACP host implementation

---

### Gap 6: Database Layer

**Create:** `lib/database/connection.py`, `lib/database/sessions.py`
**Modify:** `lib/database/__init__.py`

Requirements:
- `aiosqlite` connection factory with `PRAGMA journal_mode=WAL` on every connection
- Session persistence: thread metadata, timestamps, team configs
- Simple `CREATE TABLE IF NOT EXISTS` migrations (no Alembic for v1)
- This layer is for APPLICATION data only — LangGraph manages its own checkpointer tables

**References:** ADR-007 §4, ADR-009 §3

**Constraints:**
- Do NOT duplicate LangGraph's checkpointer schema
- `aiosqlite` already in deps via `langgraph-checkpoint-sqlite`
- `lib/core/config.py` already has `database_url` field (default: `"sqlite:///vaultspec.db"`)
- WAL mode is mandatory per ADR-007

---

### Gap 7: Provider Facade

**Modify:** `lib/providers/__init__.py`, add `__all__` to sub-modules that lack it

Requirements:
- Export: `AcpChatModel`, `ProviderFactory`, `AcpError`, `AcpErrorCode`, `AcpPromptError`
- Use `X as X` re-export pattern (ruff F401 compliance)
- Relative imports only
- Fix `factory.py` missing `Any` import from `typing`

**References:** ADR-009 §2, use `lib/api/schemas/__init__.py` as the pattern

---

### Gap 8: Core Facade Cleanup (Delete Registry + Permissions per ADR-009)

**Delete:** `lib/core/registry.py`, `lib/core/permissions.py`
**Modify:** `lib/core/__init__.py`, `lib/core/nodes/__init__.py`

ADR-009 "Key Architectural Shifts" table mandates:
- `registry.py` → DELETE. LangGraph checkpointer replaces agent state tracking.
- `permissions.py` → DELETE. LangGraph `interrupt()` in worker node replaces PermissionEngine.

Requirements:
- DELETE `lib/core/registry.py` and `lib/core/permissions.py`
- Remove any imports/exports of `Registry` or `PermissionEngine` from `lib/core/__init__.py`
- Export `compile_team_graph`, `create_worker_node`, `create_supervisor_node` from `lib/core/`
- `lib/core/nodes/__init__.py`: add proper exports with `__all__`
- Add `__all__` to `lib/core/graph.py`, `lib/core/state.py`, `lib/core/config.py`, `lib/core/exceptions.py`

**References:** ADR-009 §2 (facade mandate), ADR-009 §Key Architectural Shifts (deletion mandate)

**Constraints:**
- Target: `from lib.core import compile_team_graph` must work
- Target: `from lib.core.nodes import create_worker_node, create_supervisor_node` must work
- Agent lifecycle tracking (if needed later) belongs in the Event Aggregator, not a standalone Registry

---

### Gap 9: Telemetry Foundation (OTel + LangSmith)

**Create:** `lib/telemetry/instrumentation.py`, `lib/telemetry/tracing.py`
**Modify:** `lib/telemetry/__init__.py`, `pyproject.toml`

ADR-010 mandates OpenTelemetry from day one — this is NOT deferred.

Requirements:
- Add `opentelemetry-api`, `opentelemetry-sdk`, `opentelemetry-instrumentation-fastapi`, `opentelemetry-exporter-otlp` to `pyproject.toml` dependencies
- `instrumentation.py`: TracerProvider setup, OTLP exporter configuration, FastAPI auto-instrumentation
- `tracing.py`: Manual span helpers for graph invocations, ACP subprocess calls, WebSocket events
- Trace ID injection into WebSocket event frames (per ADR-010)
- LangSmith tracing integration for LangGraph/LangChain callbacks
- Facade in `lib/telemetry/__init__.py` with proper `__all__` and re-exports

**References:** ADR-010 (entire document), ADR-009 §3 (module hierarchy)

**Constraints:**
- OTel setup must be called from the FastAPI lifespan (Gap 1) — `TracerProvider` initialized at startup, shut down at teardown
- LangSmith tracing via `LANGCHAIN_TRACING_V2=true` env var + `langsmith` SDK (already in deps via langchain)
- Must not block the event loop — use `BatchSpanProcessor` (not `SimpleSpanProcessor`)
- Exporter endpoint configurable via `lib/core/config.py` Settings

---

## Implementation Order (Dependency-Aware)

```
Phase A (No dependencies, can be parallel):
  Gap 7: Provider facade                     — pure wiring
  Gap 8: Core facade cleanup (delete + fix)  — delete stubs, fix exports

Phase B (Depends on Phase A):
  Gap 6: Database layer                      — foundation for session persistence
  Gap 5: Host-side ACP RPC handlers          — unblocks agent tool execution
  Gap 9: Telemetry foundation                — OTel + LangSmith setup

Phase C (Depends on Phase B):
  Gap 1: FastAPI app entry point             — needs DB + graph + telemetry init
  Gap 3: Event Aggregator                    — needs graph, schemas

Phase D (Depends on Phase C):
  Gap 2: WebSocket multiplexer              — needs app + aggregator
  Gap 4: REST endpoints                     — needs app + DB + graph
```

## Validation Criteria

After implementation, the following must be true:
1. `uvicorn lib.api.app:create_app --factory` starts without errors
2. `GET /api/threads` returns `{"threads": []}`
3. `POST /api/threads` creates a thread and returns `{"thread_id": "..."}`
4. WebSocket connects at `/ws`, receives `ConnectedEvent`, then `HeartbeatEvent` every 30s
5. `subscribe` command on WS scopes events to a thread
6. Agent tool calls (fs/read, terminal/create) are handled, not rejected with -32601
7. `from lib.core import compile_team_graph` works
8. `from lib.providers import AcpChatModel, ProviderFactory` works
9. `lib/core/registry.py` and `lib/core/permissions.py` are DELETED
10. `from lib.telemetry import setup_tracing` works, TracerProvider initializes
11. All existing tests still pass (`pytest lib/`)

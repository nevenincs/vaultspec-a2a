---
date: 2026-02-27
type: audit
feature: implementation-alignment
description: 'Cross-reference of all completed and in-progress lib/ modules against ADRs 001-011 and the ten-item gap analysis, identifying coverage gaps, stub files, and missing integration wiring.'
related:
  - docs/adrs/2026-02-26-001-process-workspace-management-adr.md
  - docs/adrs/2026-02-25-002-llm-context-provider-abstraction-adr.md
  - docs/adrs/2026-02-26-004-event-aggregation-replay-adr.md
  - docs/adrs/2026-02-26-009-module-hierarchy-adr.md
  - docs/adrs/2026-02-26-011-frontend-backend-contract-adr.md
---

# Implementation Alignment Audit — 2026-02-27

Audited by: researcher
Scope: `lib/` codebase as of 2026-02-27, cross-referenced against ADR-001
through ADR-011 and
`docs/architecture/2026-25-02-gap-analysis-audit.md`.

---

## 1. Inventory of Actual Files

All work is in the single `main`worktree (no git worktrees in use yet).

| Module                             | Files                                                                     | Status   |
| ---------------------------------- | ------------------------------------------------------------------------- | -------- |
| `lib/core/exceptions.py`           | 11 exception classes, error taxonomy                                      | COMPLETE |
| `lib/core/state.py`                | `TeamState`TypedDict, 3 reducers                                          | COMPLETE |
| `lib/core/context.py`              | `compact_context`, `estimate_tokens`, `prepare_handoff`, `should_compact` | COMPLETE |
| `lib/core/models.py`               | `ArtifactRef`, `PlanEntry`, `TokenUsageEntry`dataclasses                  | COMPLETE |
| `lib/core/aggregator.py`           | `EventAggregator`with debounce, chunking, LangGraph ingest                | COMPLETE |
| `lib/core/registry.py`             | `Registry`class — **stub only (2 lines)**                                 | STUB     |
| `lib/core/permissions.py`          | `PermissionEngine`class — **stub only (2 lines)**                         | STUB     |
| `lib/core/graph.py`                | (not audited — pre-existing)                                              | EXISTING |
| `lib/core/nodes/worker.py`         | (not audited — pre-existing)                                              | EXISTING |
| `lib/core/nodes/supervisor.py`     | (not audited — pre-existing)                                              | EXISTING |
| `lib/api/schemas/`                 | 51 Pydantic types, 6 modules + facade                                     | COMPLETE |
| `lib/api/websocket.py`             | `ConnectionManager`, heartbeat, command dispatch                          | COMPLETE |
| `lib/api/endpoints.py`             | **Stub only (`router_placeholder`string)**                                | STUB     |
| `lib/database/models.py`           | 4 SQLAlchemy models: Thread, Artifact, PermissionLog, CostTracking        | COMPLETE |
| `lib/database/session.py`          | WAL mode, engine factory, session factory,`get_db`DI                      | COMPLETE |
| `lib/database/crud.py`             | Full CRUD for all 4 models, pagination, aggregation                       | COMPLETE |
| `lib/database/__init__.py`         | Facade re-exporting all 28 symbols                                        | COMPLETE |
| `lib/database/migrations/`         | Directory exists,`__init__.py`only — **no migration tooling**             | STUB     |
| `lib/workspace/git_manager.py`     | `GitManager`, mutex, create/remove/list/merge worktrees                   | COMPLETE |
| `lib/workspace/environment.py`     | `resolve_venv`, `resolve_env_vars`                                        | COMPLETE |
| `lib/telemetry/instrumentation.py` | `configure_telemetry`, `get_tracer`, `get_meter`, `TelemetryConfig`       | COMPLETE |
| `lib/telemetry/middleware.py`      | `TelemetryMiddleware`, `ws_span`, `inject_trace_context`                  | COMPLETE |
| `lib/providers/acp_chat_model.py`  | `AcpChatModel`BaseChatModel (pre-existing)                                | EXISTING |
| `lib/providers/factory.py`         | Provider factory (pre-existing)                                           | EXISTING |
| `lib/providers/probes/`            | Claude/Gemini/OpenAI/Zhipu health probes                                  | EXISTING |

---

## 2. Findings Table: ADR Cross-Reference

### ADR-001: Process and Workspace Management

| Requirement                                           | Status      | Notes                                                            |
| ----------------------------------------------------- | ----------- | ---------------------------------------------------------------- |
| Global`asyncio.Lock()`mutex for git operations        | COVERED     | `_git_mutex`in`git_manager.py:28`                                |
| `asyncio.create_subprocess_exec`for git (not shell)   | COVERED     | `_run_git`uses`create_subprocess_exec`                           |
| `asyncio.shield()`on destructive git operations       | COVERED     | `create_worktree`, `remove_worktree`, `merge_worktree`all shield |
| Branch naming`agent/{agent_id}`                       | COVERED     | `git_manager.py:123`                                             |
| Worktree directory under`agent/`relative to repo root | COVERED     | `git_manager.py:124`                                             |
| Preserve forensic state — no auto-cleanup on failure  | COVERED     | `remove_worktree` is manual-only, documented                     |
| Agent Registry (`id→port→health`)                     | **MISSING** | `lib/core/registry.py`is a 2-line stub                           |
| Process Manager (Windows subprocess lifecycle)        | **MISSING** | No process spawning/health check implementation                  |
| Port allocation for agent processes                   | **MISSING** | No port range or conflict resolution                             |
| Windows Job Objects (zombie prevention)               | **MISSING** | Not addressed anywhere                                           |

**ADR-001 verdict: PARTIAL** — Git worktree lifecycle is complete. Process
management and Agent Registry are entirely absent.

---

### ADR-002: LLM Context & Provider Abstraction

| Requirement                                         | Status      | Notes                                                            |
| --------------------------------------------------- | ----------- | ---------------------------------------------------------------- |
| `compact_context`at 80% token ceiling               | COVERED     | `context.py:52`uses 0.8 threshold                                |
| Preserve first system message and recent N messages | COVERED     | `context.py:77-108`                                              |
| `prepare_handoff`strips internal reasoning          | COVERED     | `context.py:115-136`                                             |
| Token accounting in`TeamState`                      | COVERED     | `token_usage`field with additive merge reducer                   |
| Never log`CLAUDE_CODE_OAUTH_TOKEN`                  | COVERED     | Explicitly excluded in telemetry, workspace                      |
| Model selection (which model for which role)        | **MISSING** | `factory.py`exists but model routing logic not audited/specified |
| Prompt templates per agent role                     | **MISSING** | No system prompt templates anywhere in`lib/`                     |
| Retry/backoff for LLM API errors                    | **MISSING** | Exception taxonomy exists but no retry loop                      |

**ADR-002 verdict: PARTIAL** — Context management is solid. Prompt engineering,
model selection logic, and retry are unaddressed.

---

### ADR-003: Protocol Bridging and Translation

| Requirement                                                                               | Status      | Notes                                         |
| ----------------------------------------------------------------------------------------- | ----------- | --------------------------------------------- |
| MCP state mapping (6 states: idle, working, input_required, completed, failed, cancelled) | COVERED     | `AgentLifecycleState`in`api/schemas/enums.py` |
| `AgentLifecycleState`(wire) vs internal`AgentState`separation                             | COVERED     | Two distinct enums                            |
| MCP Server exposing orchestrator as tool surface                                          | **MISSING** | `lib/protocols/mcp/`has only`__init__.py`stub |
| A2A protocol abandoned per ADR-006                                                        | COVERED     | No A2A code present                           |
| ACP bridging via`AcpChatModel`                                                            | COVERED     | Pre-existing provider implementation          |

**ADR-003 verdict: PARTIAL** — Wire protocol mapping is complete. MCP Server
(Task 10) is not yet implemented.

---

### ADR-004: Event Aggregation and State Replay

| Requirement                                            | Status      | Notes                                            |
| ------------------------------------------------------ | ----------- | ------------------------------------------------ |
| `EventAggregator`as central bus                        | COVERED     | `lib/core/aggregator.py`— full implementation    |
| `astream_events(version="v2")`ingestion                | COVERED     | `aggregator.py:632-656`                          |
| Event filtering (node boundary filter)                 | COVERED     | `_PASSTHROUGH_EVENTS`+`_NODE_BOUNDARY_EVENTS`    |
| Per-thread monotonic sequence numbers                  | COVERED     | `_next_sequence`+`_sequences`dict                |
| Debouncing: ToolCallUpdate 100ms, PlanUpdate 250ms     | COVERED     | Constants at`aggregator.py:49-50`                |
| Token chunk batching (50ms / 4KB)                      | COVERED     | `_buffer_message_chunk`                          |
| Backpressure via bounded queue (512)                   | COVERED     | `_QUEUE_MAXSIZE = 512`                           |
| State replay via`graph.get_state()` REST endpoint      | **MISSING** | REST endpoints are a stub (`endpoints.py`)       |
| `WebSocket ConnectionManager`with heartbeat            | COVERED     | `lib/api/websocket.py`complete                   |
| Client subscription management (subscribe/unsubscribe) | COVERED     | `ConnectionManager`delegates to`EventAggregator` |

**ADR-004 verdict: MOSTLY COVERED** — Core aggregator complete. State replay
REST endpoint is the only gap (blocked on Task 5).

---

### ADR-005: Frontend Rendering Stack

| Requirement                                           | Status      | Notes                                                                                  |
| ----------------------------------------------------- | ----------- | -------------------------------------------------------------------------------------- |
| React 5 SPA with adapter-static                       | COVERED     | Per memory:`src/ui/` scaffolded, 0 errors                                              |
| shadcn-React components                               | COVERED     | 21 component sets installed                                                            |
| Tailwind CSS v4                                       | COVERED     | Configured                                                                             |
| TypeScript types from Pydantic schemas                | PARTIAL     | 473 manually-written TS types exist; openapi-typescript generation pipeline not set up |
| Mock WebSocket adapter (`src/ui/src/lib/api/mock.ts`) | **MISSING** | ADR-011 §2.5 fixture/mock strategy not implemented                                     |
| `src/ui/tests/fixtures/`recorded WS sessions          | **MISSING** | No Playwright fixture recordings                                                       |

**ADR-005 verdict: PARTIAL** — SPA scaffolded. Type generation pipeline and mock
adapter are missing.

---

### ADR-006: Protocol Ecosystem Bridge

| Requirement                                                              | Status      | Notes                                                                                     |
| ------------------------------------------------------------------------ | ----------- | ----------------------------------------------------------------------------------------- |
| LangGraph as core internal engine                                        | COVERED     | Architecture of`lib/core/`                                                                |
| MCP for external tool boundary                                           | PARTIAL     | Consuming tools via LangChain MCP adapters is possible; exposing as MCP server is Task 10 |
| `AcpChatModel`for CLI subprocess bridge                                  | COVERED     | Pre-existing                                                                              |
| Claude subprocess:`node.exe <dist/index.js>`NOT .CMD shim                | COVERED     | Per existing`acp_chat_model.py`                                                           |
| Gemini subprocess:`create_subprocess_shell("gemini --experimental-acp")` | COVERED     | Per existing`acp_chat_model.py`                                                           |
| `limit=10*1024*1024`for ACP stream buffer                                | COVERED     | Pre-existing                                                                              |
| Stdin write with`\n`delimiter                                            | COVERED     | Pre-existing                                                                              |
| Walrus operator`while line := await readline()`                          | COVERED     | Pre-existing                                                                              |
| Bidirectional dispatch (responses vs notifications)                      | COVERED     | Pre-existing                                                                              |
| ACP session lifecycle (initialize → session/new → session/prompt)        | COVERED     | Pre-existing                                                                              |
| Tool call tracking dict keyed by`toolCallId`                             | COVERED     | Pre-existing                                                                              |
| `end_turn`detection from`session/prompt`response                         | COVERED     | Pre-existing                                                                              |
| Windows pipe cleanup via`_transport.close()`                             | COVERED     | Pre-existing                                                                              |
| MCP timeout → immediate "Task Started" response                          | **MISSING** | Not in Task 10 scope definition                                                           |

**ADR-006 verdict: MOSTLY COVERED** — All 9 AcpChatModel patterns present. MCP
server async-task response pattern is unspecified.

---

### ADR-007: Tech Stack and Deployment

| Requirement                                                    | Status      | Notes                                                      |
| -------------------------------------------------------------- | ----------- | ---------------------------------------------------------- |
| FastAPI + Uvicorn                                              | COVERED     | pyproject.toml deps                                        |
| SQLite WAL mode via aiosqlite                                  | COVERED     | `session.py:50`PRAGMA WAL                                  |
| Foreign keys ON pragma                                         | COVERED     | `session.py:51`                                            |
| React static SPA served by FastAPI`StaticFiles`                | **MISSING** | No FastAPI`app.py`with`StaticFiles`mount                   |
| `@asynccontextmanager`lifespan with`anyio.create_task_group()` | **MISSING** | No app lifespan implementation                             |
| CORS configuration for dev                                     | **MISSING** | Not tracked in any task                                    |
| Cache-Control headers for static asset serving                 | **MISSING** | ADR-007 §5 pitfall — not addressed                         |
| Connection pool / write batching for Event Aggregator          | PARTIAL     | Aggregator debounces writes; no explicit DB write batching |

**ADR-007 verdict: PARTIAL** — Persistence layer correct. FastAPI application
wiring (app.py, lifespan, StaticFiles, CORS) is completely absent and UNTRACKED.

---

### ADR-008: Orchestration Topology / Pipeline

| Requirement                                                       | Status  | Notes                           |
| ----------------------------------------------------------------- | ------- | ------------------------------- |
| LangGraph state JSON-serializable (no Pydantic/datetime in state) | COVERED | `TeamState`uses primitives only |
| SQLite checkpoint via`langgraph-checkpoint-sqlite`                | COVERED | In`pyproject.toml`deps          |
| `asyncio.create_subprocess_exec`for git (not shell)               | COVERED | `git_manager.py`                |
| Non-blocking async for all I/O                                    | COVERED | All modules async               |

### ADR-008 verdict: COVERED

---

### ADR-009: Approved Module Hierarchy

| Requirement                                | Status  | Notes                                                         |
| ------------------------------------------ | ------- | ------------------------------------------------------------- |
| `__all__`in all public modules             | COVERED | All audited modules have`__all__`                             |
| `X as X`re-exports in`__init__.py`facades  | COVERED | `lib/database/__init__.py`, `lib/telemetry/__init__.py`, etc. |
| Relative imports only within `lib/`        | COVERED | Enforced by ruff TID252                                       |
| Consumer imports from sub-module root only | COVERED | Pattern followed                                              |
| `lib/workspace/`module                     | COVERED | Facade`__init__.py`present                                    |
| `lib/database/`module                      | COVERED | Complete facade                                               |
| `lib/protocols/`— a2a/, mcp/, adapter/     | PARTIAL | Directories exist;`a2a/`, `mcp/`, `adapter/`are empty stubs   |

**ADR-009 verdict: MOSTLY COVERED** — Structural patterns enforced. Protocol
sub-modules are empty stubs.

---

### ADR-010: Observability and Telemetry

| Requirement                                                             | Status      | Notes                                                  |
| ----------------------------------------------------------------------- | ----------- | ------------------------------------------------------ |
| `configure_telemetry()`at FastAPI lifespan                              | PARTIAL     | Function exists; no lifespan to call it from           |
| `TelemetryMiddleware`for HTTP spans                                     | COVERED     | `middleware.py`                                        |
| W3C traceparent propagation                                             | COVERED     | `middleware.py:109`                                    |
| `ws_span()`for WebSocket operations                                     | COVERED     | `middleware.py:145-187`                                |
| `inject_trace_context()`into WS frames                                  | COVERED     | `middleware.py:190-217`                                |
| Custom spans for graph execution / tool calls                           | **MISSING** | Aggregator does not add OTel spans to LangGraph events |
| Meter for token usage / turn duration / active threads / WS connections | **MISSING** | No OTel metrics anywhere in aggregator or WS layer     |
| LangSmith project/tag binding (thread_id, agent_id)                     | **MISSING** | No`langsmith.py`module; LangSmith is env-var only      |
| OTel spans integrated into`ConnectionManager`                           | **MISSING** | WS manager does not call`ws_span()`                    |

**ADR-010 verdict: PARTIAL** — Infrastructure in place. Instrumentation not yet
wired into the aggregator, WS manager, or graph execution layer.

---

### ADR-011: Frontend-Backend Wire Contract

| Requirement                                          | Status      | Notes                                                                       |
| ---------------------------------------------------- | ----------- | --------------------------------------------------------------------------- |
| All 12 server event types                            | COVERED     | `lib/api/schemas/events.py`                                                 |
| All 6 client command types                           | COVERED     | `lib/api/schemas/commands.py`                                               |
| `AgentLifecycleState`(8 states)                      | COVERED     | `lib/api/schemas/enums.py`                                                  |
| Sequence numbers starting at 1                       | COVERED     | `_next_sequence`increments before first use                                 |
| `ConnectedEvent`on open with active_threads          | COVERED     | `websocket.py:70-75`                                                        |
| `HeartbeatEvent`every 30 seconds                     | COVERED     | `websocket.py:233-258`                                                      |
| REST endpoints (6 routes)                            | **MISSING** | `endpoints.py`is a placeholder string                                       |
| `ThreadStateSnapshot` for state replay               | COVERED     | Schema defined; no REST endpoint to serve it                                |
| Permission responses via REST only                   | PARTIAL     | WS handler logs the command but doesn't route to REST — missing enforcement |
| Dead connection timeout at 90s (3 missed heartbeats) | **MISSING** | Client-side; no server-side enforcement                                     |
| Reconnection protocol (§2.3, 7 steps)                | **MISSING** | Client-side only; no server snapshot endpoint                               |
| TypeScript type generation (`openapi-typescript`)    | **MISSING** | Manual types exist; generation pipeline UNTRACKED                           |
| `src/ui/src/lib/api/mock.ts`WS mock adapter          | **MISSING** | UNTRACKED                                                                   |
| Schema fixture builder functions                     | PARTIAL     | Test file has some; not a formal builder module                             |

**ADR-011 verdict: PARTIAL** — Wire contract schemas complete. REST endpoints
and TypeScript generation pipeline absent.

---

## 3. Findings Table: Gap Analysis Cross-Reference

| Gap #  | Gap Description                | Resolution Status | Notes                                                                                                                             |
| ------ | ------------------------------ | ----------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| Gap 1  | No provider adapter interface  | PARTIAL           | `AcpChatModel`covers Claude/Gemini. No formal`AgentAdapter`protocol class. OpenAI/Zhipu have probes but no full adapter.          |
| Gap 2  | LLM integration layer missing  | PARTIAL           | Token accounting in`TeamState`, context compaction in `context.py`. No prompt templates, no retry loop, no model selection logic. |
| Gap 3  | Process manager underspecified | **MISSING**       | No process manager anywhere. `Registry`is a 2-line stub. No port allocation, health check endpoint, or Windows Job Objects.       |
| Gap 4  | Event aggregator reliability   | COVERED           | `EventAggregator`complete with debounce, chunking, backpressure.                                                                  |
| Gap 5  | Permission flow granularity    | PARTIAL           | `PermissionEngine`is a 2-line stub. Schemas exist. REST endpoint to submit response is absent.                                    |
| Gap 6  | Error recovery strategy        | COVERED           | Exception taxonomy with`severity`+`RecoveryAction`complete.                                                                       |
| Gap 7  | State persistence schema       | COVERED           | 4 SQLAlchemy models + CRUD + WAL session.                                                                                         |
| Gap 8  | Testing strategy absent        | PARTIAL           | Tests exist per module. No integration tests, no recorded WS fixtures, no CI config.                                              |
| Gap 9  | Context window management      | COVERED           | `compact_context`, `should_compact`, `prepare_handoff`all implemented.                                                            |
| Gap 10 | Merge conflict strategy        | COVERED           | `GitManager`with mutex,`has_conflicts`, `merge_worktree`, `MergeStrategy`enum.                                                    |

---

## 4. "Must Build Custom" Checklist (Gap Analysis §Code Reuse Assessment)

| Item                                                    | Status      | Module                            | Notes                                                               |
| ------------------------------------------------------- | ----------- | --------------------------------- | ------------------------------------------------------------------- |
| Process Manager (Windows subprocess lifecycle)          | **MISSING** | none                              | CRITICAL — no task currently covers this                            |
| Event Aggregator (multi-SSE fan-in, WS fan-out)         | COVERED     | `lib/core/aggregator.py`          |                                                                     |
| Provider Adapter layer (per-provider CLI wrappers)      | PARTIAL     | `lib/providers/acp_chat_model.py` | Claude + Gemini. No formal`AgentAdapter`protocol.                   |
| LLM Client abstraction (tool-calling translation)       | PARTIAL     | `lib/providers/factory.py`        | Factory exists; abstraction incomplete                              |
| Permission Manager (runtime policy engine)              | **STUB**    | `lib/core/permissions.py`         | 2 lines                                                             |
| Scoped MCP Tool Server (per-agent filesystem isolation) | **MISSING** | none                              | Task 10 is MCP server but path isolation not in scope               |
| WebSocket Connection Manager (channel multiplexing)     | COVERED     | `lib/api/websocket.py`            |                                                                     |
| Workspace Manager (git worktree lifecycle)              | COVERED     | `lib/workspace/git_manager.py`    |                                                                     |
| Message Router (user→correct agent routing)             | **MISSING** | none                              | SEND_MESSAGE command handler is a log stub in`websocket.py:166-172` |
| Agent Registry (id→port→health mapping)                 | **STUB**    | `lib/core/registry.py`            | 2 lines                                                             |

---

## 5. Untracked Requirements (No Task Covers These)

These items have no assigned task and are not blocked by pending tasks:

### CRITICAL — Blocking Integration

| Item                                                                                          | ADR Reference            | Severity |
| --------------------------------------------------------------------------------------------- | ------------------------ | -------- |
| FastAPI`app.py`— lifespan, middleware stack, CORS, static file serving                        | ADR-007 §5, ADR-010 §2   | CRITICAL |
| `anyio.create_task_group()` lifespan wiring (EventAggregator, DB init, telemetry)             | ADR-007 §5               | CRITICAL |
| REST endpoint implementation (`/threads`, `/threads/{id}/state`, `/permissions/{id}/respond`) | ADR-011 §2.2             | CRITICAL |
| Message routing: `SEND_MESSAGE`WebSocket command → graph invocation                           | ADR-004, ADR-011         | CRITICAL |
| Permission response routing: WS`PERMISSION_RESPONSE`→ REST → LangGraph`Command(resume=...)`   | ADR-006 §2, ADR-011 §3.1 | CRITICAL |

### HIGH — ADR Constraints Unaddressed

| Item                                                                             | ADR Reference     | Severity |
| -------------------------------------------------------------------------------- | ----------------- | -------- |
| Process Manager: Windows subprocess lifecycle, port allocation, health checks    | ADR-001 §5, Gap 3 | HIGH     |
| Agent Registry: id→port→health state machine                                     | ADR-001, Gap 1    | HIGH     |
| `PermissionEngine`implementation (granularity, timeout, escalation, persistence) | Gap 5             | HIGH     |
| OTel spans wired into aggregator event processing and WS connection lifecycle    | ADR-010 §5        | HIGH     |
| CORS middleware for React dev server (port 5173)                                 | ADR-007           | HIGH     |
| `StaticFiles`mount for serving React build                                       | ADR-007 §2.4      | HIGH     |

### MEDIUM — Quality and Tooling

| Item                                                                         | ADR Reference     | Severity |
| ---------------------------------------------------------------------------- | ----------------- | -------- |
| TypeScript type generation via`openapi-typescript`pipeline                   | ADR-011 §2.4      | MEDIUM   |
| `src/ui/src/lib/api/mock.ts`WS mock adapter for frontend dev                 | ADR-011 §2.5      | MEDIUM   |
| Database migration tooling (currently no`alembic`or custom migration runner) | ADR-007, Gap 7    | MEDIUM   |
| Prompt templates per agent role (system prompts)                             | ADR-002, Gap 2    | MEDIUM   |
| LLM API retry/backoff logic                                                  | ADR-002, Gap 2    | MEDIUM   |
| Scoped MCP tool server filesystem path validation/isolation                  | ADR-006 §5, Gap 5 | MEDIUM   |
| `session/cancel`timeout enforcement (3s per ADR-006 §5.1.6)                  | ADR-006 §5.1      | MEDIUM   |
| Client dead timeout enforcement (90s server-side disconnect)                 | ADR-011 §5        | MEDIUM   |
| Cache-Control headers for static asset serving                               | ADR-007 §5        | LOW      |
| `openapi-typescript`CI validation step                                       | ADR-011 §2.4      | LOW      |

---

## 6. Recommended New Tasks

The following new tasks should be created to close the untracked gaps:

### New Task A: Implement FastAPI Application Entry Point

### Priority: CRITICAL — blocks all integration

Build`lib/app.py`or`lib/api/app.py`:

- `@asynccontextmanager`lifespan with`anyio.create_task_group()`
- Startup order: `init_db()`→`configure_telemetry()`→`EventAggregator`start
  →`ConnectionManager`bind -`TelemetryMiddleware`added to app -`CORSMiddleware`for`http://localhost:5173`in dev -`StaticFiles`mount for`src/ui/build/`(or`src/ui/.React-kit/output/client/`)
- WebSocket endpoint at `/ws`wired to`ConnectionManager`
- HTTP 90-second dead client enforcement via WS `close`

### New Task B: Implement REST API Endpoints (Task 5 amendment)

### Priority: CRITICAL — REST endpoints are a string placeholder

Task 5 exists but the scope must explicitly cover:

- `POST /threads`→`create_thread`CRUD + emit`AgentStatusEvent(submitted)`
- `GET /threads`→ paginated`list_threads`
- `GET /threads/{id}/state`→`graph.get_state(config)`for reconnection protocol -`POST /threads/{id}/messages`→ enqueue into graph invocation -`GET /team/status`→`Registry.get_all()`
- `POST
/permissions/{id}/respond`→`PermissionResponseRequest`→`Command(resume=option_id)`
- Wire `SEND_MESSAGE`WebSocket command to same graph invocation path

### New Task C: Implement Agent Registry and Process Manager

### Priority: HIGH

Implement`lib/core/registry.py`:

- `agent_id → {state, port, pid, health_url}`mapping
- State machine: init → ready → running → draining → stopped → error
- Stale entry detection + cleanup

Implement`lib/core/process_manager.py`:

- Windows subprocess lifecycle using `asyncio.create_subprocess_exec`
- Port allocation from configurable range with conflict detection
- Health check loop with timeout/retry per ADR-001
- Windows Job Object integration for zombie prevention
- Graceful drain with force-kill timeout

### New Task D: Implement PermissionEngine

### Priority: HIGH — prerequisite for Task 6

Task 6 scope exists but `lib/core/permissions.py`must be implemented:

- Per-tool-type granularity vs per-call (configurable)
- In-memory pending request queue (keyed by`request_id`)
- Per-request timeout (configurable, default 5 minutes)
- Escalation: timeout → auto-deny with `ErrorEvent`
- Persistence: `allow_always`decisions stored in`permission_logs` DB table
- Dangerous tool list (always require approval regardless of prior grants)

### New Task E: Wire OTel Instrumentation into Runtime Components

### Priority: HIGH — ADR-010 compliance

`lib/core/aggregator.py`: Add `ws_span()`around`ingest()`and`_broadcast()`
`lib/api/websocket.py`: Add `ws_span()`around`connect()`, `listen()`,
`_handle_client_message()`
`lib/telemetry/instrumentation.py`: Add `get_meter()`usage for token count, WS
connection count, active threads
Add OTel span propagation from incoming WS frame`_trace`field

### New Task F: TypeScript Type Generation Pipeline

### Priority: MEDIUM

- Register all Pydantic schemas on FastAPI endpoints (needed for OpenAPI export)
- Document`npx openapi-typescript http://localhost:8000/openapi.json`command
- Add CI step validating generated types match current spec
- Implement`src/ui/src/lib/api/mock.ts`WS mock adapter

---

## 7. Priority Ranking of Missing Items

| Priority | Item                                                                           | Blocking                           |
| -------- | ------------------------------------------------------------------------------ | ---------------------------------- |
| 1        | FastAPI app entry point (lifespan, middleware, CORS, StaticFiles, WS endpoint) | Everything                         |
| 2        | REST endpoints (6 routes per ADR-011 §2.2)                                     | Reconnection protocol, permissions |
| 3        | Message routing (SEND_MESSAGE → graph invocation)                              | E2E functionality                  |
| 4        | Permission response pipeline (WS/REST → Command(resume=))                      | Human-in-the-loop                  |
| 5        | PermissionEngine implementation                                                | Task 6                             |
| 6        | Agent Registry state machine                                                   | Process management                 |
| 7        | Process Manager (Windows subprocess lifecycle)                                 | Multi-agent execution              |
| 8        | OTel wiring into aggregator and WS manager                                     | ADR-010 §5 compliance              |
| 9        | TypeScript type generation pipeline                                            | Frontend-backend sync              |
| 10       | Database migration tooling                                                     | Schema evolution                   |
| 11       | CORS + Cache-Control + StaticFiles config                                      | Deployment                         |
| 12       | Prompt templates per agent role                                                | Agent quality                      |
| 13       | LLM retry/backoff                                                              | Reliability                        |

---

## 8. Summary

### What is solid

- Wire protocol schemas (ADR-011) — complete and consistent
- Event aggregation (ADR-004) — thorough implementation with debounce, chunking,
  backpressure
- Database layer (ADR-007) — correct WAL configuration, typed models, CRUD
- Git workspace management (ADR-001) — mutex, shield, conflict detection
- Context window management (ADR-002) — compact, estimate, handoff
- Error taxonomy (Gap 6) — severity + recovery action on all exception classes
- Telemetry infrastructure (ADR-010) — optional SDK, no-op fallback, WS helpers

### What is missing or stubbed

-`lib/api/endpoints.py`— placeholder string, zero implementation -`lib/core/registry.py`— 2-line stub -`lib/core/permissions.py`— 2-line stub -`lib/protocols/mcp/`, `a2a/`, `adapter/` — empty directories

- No FastAPI application (`app.py`) — no lifespan, no CORS, no StaticFiles, no
  WS route
- No message routing from WS `SEND_MESSAGE`command to graph invocation
- No permission response pipeline from WS/REST to`Command(resume=)`
- OTel instrumentation is installed but not wired into any live code path
- TypeScript type generation pipeline is untracked

**The single most critical gap:** There is no FastAPI `app.py`. Without it, the
entire system cannot run. No single task currently owns this file.

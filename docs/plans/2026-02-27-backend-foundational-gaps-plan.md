# Backend Foundational Gaps Implementation Plan

**Date:** 2026-02-27
**Type:** Implementation Plan
**Status:** Proposed

## References

| Document | Path | Role |
|---|---|---|
| ADR-001 | `docs/adrs/001-process-and-workspace-management.md` | Git mutex, workspace isolation |
| ADR-002 | `docs/adrs/002-llm-context-provider-abstraction.md` | Provider architecture, context management |
| ADR-003 | `docs/adrs/003-protocol-bridging-translation.md` | MCP state mapping, interrupt routing |
| ADR-004 | `docs/adrs/004-event-aggregation-server-side-replay.md` | Aggregator, WebSocket, replay |
| ADR-006 | `docs/adrs/006-protocol-ecosystem-bridge.md` | ACP subprocess patterns, MCP boundary |
| ADR-007 | `docs/adrs/007-tech-stack-deployment.md` | FastAPI, SQLite WAL, static SPA delivery |
| ADR-008 | `docs/adrs/008-orchestration-topology-pipeline.md` | LangGraph topology, async mandate |
| ADR-009 | `docs/adrs/009-approved-module-hierarchy.md` | Module structure, facade pattern, `__all__` |
| ADR-010 | `docs/adrs/010-observability-telemetry-integration.md` | OTel from day one, LangSmith |
| ADR-011 | `docs/adrs/011-frontend-backend-contract.md` | Wire protocol, 12 events, 6 commands, 6 REST routes |
| ADR-012 | `docs/adrs/012-agent-definition-schema.md` | TOML agent config, ACP capability binding |
| ADR-013 | `docs/adrs/013-team-composition-topology.md` | TOML team config, 3 topologies |
| Audit | `docs/audits/2026-02-27-implementation-alignment-audit.md` | Current state, gap cross-reference |
| Research: Backend Gaps | `docs/research/2026-02-27-backend-gaps-research.md` | Aggregator, SQLite, workspace patterns |
| Research: Model Matrix | `docs/research/2026-02-27-model-capability-matrix.md` | Provider capabilities, role-model mapping |
| Prompt | `docs/prompts/backend-foundational-gaps.md` | Gap definitions, phased ordering |

---

## Executive Summary

This plan addresses the nine foundational backend gaps identified in the
implementation prompt, cross-referenced against the implementation alignment
audit of 2026-02-27 and all thirteen binding ADRs. The provider layer
(`AcpChatModel`), LangGraph core (graph compilation, interrupt/resume), wire
contract schemas (51 Pydantic types), database layer (SQLAlchemy models, CRUD,
WAL session), event aggregator, WebSocket multiplexer, workspace management, and
telemetry infrastructure are all implemented. What remains is the **serving
infrastructure** that connects these foundations into a runnable system, plus
facade and cleanup work mandated by ADR-009.

The audit's single most critical finding is: **there is no FastAPI `app.py`**.
Without it, the system cannot start. This plan structures nine implementation
gaps across four dependency-ordered phases, incorporating the audit's six
recommended new tasks (A through F) and all untracked requirements.

Additionally, ADR-012 and ADR-013 (published 2026-02-27) introduce TOML-based
agent definition and team composition schemas that refactor `compile_team_graph()`
and the supervisor prompt. These are sequenced after the foundational serving
layer is operational.

---

## Pre-Reading Requirements

Implementers MUST read the following documents cover-to-cover before beginning
work. These documents are binding and override any ad-hoc patterns found in the
codebase.

### Binding ADRs (all thirteen)

```
docs/adrs/001-process-and-workspace-management.md
docs/adrs/002-llm-context-provider-abstraction.md
docs/adrs/003-protocol-bridging-translation.md
docs/adrs/004-event-aggregation-server-side-replay.md
docs/adrs/005-frontend-rendering-stack.md
docs/adrs/006-protocol-ecosystem-bridge.md
docs/adrs/007-tech-stack-deployment.md
docs/adrs/008-orchestration-topology-pipeline.md
docs/adrs/009-approved-module-hierarchy.md
docs/adrs/010-observability-telemetry-integration.md
docs/adrs/011-frontend-backend-contract.md
docs/adrs/012-agent-definition-schema.md
docs/adrs/013-team-composition-topology.md
```

### Audit and Research

```
docs/audits/2026-02-27-implementation-alignment-audit.md
docs/research/2026-02-27-backend-gaps-research.md
docs/research/2026-02-27-model-capability-matrix.md
```

### Reference Implementations (read specific files cited per gap)

```
knowledge/repositories/toad/src/toad/acp/agent.py           -- Lines 348-468: Host-side RPC handlers
knowledge/repositories/toad/src/toad/acp/protocol.py        -- TypedDict definitions for terminal/fs types
knowledge/repositories/a2a-python/src/a2a/server/apps/jsonrpc/fastapi_app.py
knowledge/repositories/a2a-python/src/a2a/server/events/event_queue.py
knowledge/repositories/langgraph/libs/checkpoint-sqlite/langgraph/checkpoint/sqlite/aio.py
```

---

## Current State Summary

Source: Implementation Alignment Audit 2026-02-27.

### Fully Implemented (No Work Required)

| Component | Module | ADR Coverage |
|---|---|---|
| Wire contract schemas | `lib/api/schemas/` (51 Pydantic types, 6 modules) | ADR-011 COMPLETE |
| Event aggregator | `lib/core/aggregator.py` | ADR-004 COMPLETE |
| WebSocket connection manager | `lib/api/websocket.py` | ADR-004 COMPLETE |
| Database models + CRUD | `lib/database/models.py`, `crud.py`, `session.py` | ADR-007 COMPLETE |
| Git workspace management | `lib/workspace/git_manager.py`, `environment.py` | ADR-001 COMPLETE |
| Context window management | `lib/core/context.py` | ADR-002 COMPLETE |
| Error taxonomy | `lib/core/exceptions.py` | Gap 6 COMPLETE |
| LangGraph state | `lib/core/state.py` (TeamState TypedDict) | ADR-008 COMPLETE |
| Telemetry infrastructure | `lib/telemetry/instrumentation.py`, `middleware.py` | ADR-010 PARTIAL (unwired) |
| AcpChatModel provider | `lib/providers/acp_chat_model.py` (642 lines) | ADR-006 COMPLETE |
| Provider factory | `lib/providers/factory.py` | ADR-002 PARTIAL |
| Provider health probes | `lib/providers/probes/` | N/A |

### Stubbed (Requires Implementation or Deletion)

| Component | Current State | Action Required |
|---|---|---|
| `lib/api/endpoints.py` | Placeholder string (`router_placeholder`) | **REPLACE** with 6 REST routes |
| `lib/core/registry.py` | 2-line stub | **DELETE** per ADR-009 |
| `lib/core/permissions.py` | 2-line stub | **DELETE** per ADR-009 |
| `lib/protocols/mcp/`, `a2a/`, `adapter/` | Empty directories with `__init__.py` | Deferred (MCP server is out of scope for this plan) |

### Completely Missing (Must Create)

| Component | File Path | Blocking |
|---|---|---|
| FastAPI application | `lib/api/app.py` | **Everything** |
| REST endpoint implementation | `lib/api/endpoints.py` | Reconnection protocol, permissions |
| Provider facade | `lib/providers/__init__.py` (empty) | Import ergonomics |
| Core facade cleanup | `lib/core/__init__.py` (references deleted stubs) | Import correctness |
| OTel wiring into runtime | Aggregator, WS manager | ADR-010 compliance |
| TOML agent/team config | `lib/core/team_config.py`, `lib/core/presets/` | ADR-012, ADR-013 |

---

## Implementation Gaps

The nine gaps below are sourced from the implementation prompt, enriched with
ADR section references, audit findings, and ADR-012/ADR-013 requirements. Each
gap states what must be built, which files are affected, the ADR constraints
that govern it, and what the audit found about its current state.

---

### Gap 1: FastAPI Application Entry Point + Lifespan

**Audit status:** MISSING. No task currently owns this file. (Audit section 5,
CRITICAL item 1; Recommended Task A.)

**Create:** `lib/api/app.py`
**Modify:** `lib/api/__init__.py`, `pyproject.toml`

**Requirements:**

1. FastAPI application factory function `create_app()` using
   `@asynccontextmanager` lifespan (ADR-007 section 5 -- NOT deprecated `on_event`).
2. Lifespan startup order:
   a. Call `setup_app_tables()` to create application-level SQLite tables
      (Research section 2.3).
   b. Initialize `AsyncSqliteSaver` for LangGraph checkpointing (Research
      section 2.1; ADR-004 section 2).
   c. Call `configure_telemetry()` to start OTel TracerProvider (ADR-010
      section 2).
   d. Compile team graph via `compile_team_graph()` with checkpointer (ADR-008
      section 2).
   e. Start `EventAggregator` singleton (ADR-004 section 2).
   f. Bind `ConnectionManager` to the aggregator (ADR-004 section 2).
3. Lifespan shutdown: clean up telemetry, close DB connections, cancel
   aggregator tasks.
4. Mount `TelemetryMiddleware` (ADR-010 section 2).
5. Mount `CORSMiddleware` allowing `http://localhost:5173` in dev (Audit
   section 5, HIGH item: CORS middleware).
6. Mount REST router at `/api/` prefix (ADR-011 section 2.2).
7. Mount WebSocket endpoint at `/ws` (ADR-011 section 2.1).
8. Mount `StaticFiles` for `src/ui/build/` with fallback to `index.html`
   (ADR-007 section 2, item 4; Audit section 5, HIGH item: StaticFiles mount).
9. Add `Cache-Control` headers for static assets (ADR-007 section 5 pitfall).
10. Single Uvicorn process -- no workers (Windows ProactorEventLoop; ADR-007
    section 5).
11. Consider adding `__main__.py` or `pyproject.toml` `[project.scripts]`
    entry for launch.

**ADR References:** ADR-007 section 2, section 3, section 5; ADR-004 section 2;
ADR-009 section 2; ADR-010 section 2.

**Constraints:**
- No `uvloop` (Windows incompatible).
- `ProactorEventLoop` is default on Python 3.13/Windows.
- `anyio.create_task_group()` for managing background tasks during lifespan
  (ADR-007 section 5).

**Corresponds to:** Audit Recommended Task A.

---

### Gap 2: WebSocket Multiplexer Wiring

**Audit status:** WebSocket `ConnectionManager` is COMPLETE in
`lib/api/websocket.py`. What is missing is: (a) mounting the WS endpoint in the
FastAPI app, (b) `SEND_MESSAGE` command routing to graph invocation, (c)
`PERMISSION_RESPONSE` rejection over WS, and (d) server-side dead client
enforcement at 90 seconds.

**Modify:** `lib/api/websocket.py`, `lib/api/app.py`

**Requirements:**

1. Mount the `ConnectionManager.websocket_endpoint` handler at `/ws` in the
   FastAPI app (Gap 1).
2. `SEND_MESSAGE` command handler must enqueue a new graph invocation via the
   aggregator's `ingest()` method (Audit section 4: "Message Router -- MISSING";
   Audit section 5: CRITICAL item "Message routing").
3. `PERMISSION_RESPONSE` received over WebSocket MUST be rejected with an error
   event directing the client to use the REST endpoint (ADR-011 section 3.1:
   "REST fallback for permission responses").
4. Server-side enforcement: disconnect clients that have not sent any message
   (including `ping`) for 90 seconds (ADR-011 section 5: "Client considers
   connection dead after 90 seconds"; Audit section 5: MEDIUM item "Client dead
   timeout enforcement").
5. Inject OTel spans around `connect()`, `listen()`, and
   `_handle_client_message()` using `ws_span()` from `lib/telemetry/middleware.py`
   (ADR-010 section 5; Audit Recommended Task E).
6. All agent events must carry `agent_id` for client-side routing (ADR-011
   section 2.1).

**ADR References:** ADR-004 section 2, section 5; ADR-011 section 2.1, section 3,
section 5; ADR-010 section 5.

**Constraints:**
- Use existing Pydantic schemas for serialization:
  `ServerEvent.model_dump_json()`.
- Backpressure via bounded queue per client (oldest-message-drop on overflow;
  ADR-004 section 5; Research section 1.5).
- Sequence numbers monotonic per `thread_id` (ADR-011 section 5).

**Corresponds to:** Audit Recommended Tasks A (partial), B (partial), E (partial).

---

### Gap 3: Event Aggregator Wiring

**Audit status:** `EventAggregator` at `lib/core/aggregator.py` is COMPLETE with
debounce, chunking, backpressure, sequence numbering, and subscriber management.
The gap is integration: the aggregator is not started from any lifespan, not
bound to any graph invocation trigger, and does not have OTel spans.

**Modify:** `lib/core/aggregator.py`, `lib/api/app.py`

**Requirements:**

1. Start the aggregator as a singleton in the FastAPI lifespan (Gap 1 step 2e).
2. Wire `POST /api/threads` and `SEND_MESSAGE` WS command to call
   `aggregator.ingest(thread_id, graph, input, config)` (Audit section 5:
   CRITICAL item "Message routing").
3. Wire interrupt events to `PermissionRequestEvent` emission (ADR-003 section 2;
   ADR-011 section 2.1: `PermissionRequestEvent` schema).
4. Add `ws_span()` around `ingest()` and `_broadcast()` (ADR-010 section 5;
   Audit Recommended Task E).
5. Add OTel metrics: token count, WS connection count, active threads (ADR-010
   section 5; Audit section 5: HIGH item "OTel spans wired into aggregator").

**ADR References:** ADR-004 section 2; ADR-008 section 2; ADR-010 section 5;
ADR-011 section 2.1.

**Constraints:**
- `astream_events` version MUST be `"v2"` (Research section 1.2).
- The aggregator is the ONLY source of truth for event sequencing (ADR-011
  section 5).
- Must handle both streaming chunks AND interrupt events.

**Corresponds to:** Audit Recommended Task E (partial).

---

### Gap 4: REST Endpoint Implementation (6 Routes)

**Audit status:** `lib/api/endpoints.py` is a placeholder string -- zero
implementation. (Audit section 2, ADR-011: "REST endpoints (6 routes) MISSING";
Recommended Task B.)

**Modify:** `lib/api/endpoints.py` -- replace stub entirely.

Six endpoints per ADR-011 section 2.2:

| Route | Method | Request Schema | Response Schema | Purpose |
|---|---|---|---|---|
| `/api/threads` | POST | `CreateThreadRequest` | `CreateThreadResponse` | Create thread, invoke graph |
| `/api/threads` | GET | query params | `ThreadListResponse` | List threads (paginated) |
| `/api/threads/{id}/state` | GET | -- | `ThreadStateSnapshot` | State replay for reconnection |
| `/api/threads/{id}/messages` | POST | `SendMessageRequest` | `202 Accepted` | Send message to running thread |
| `/api/team/status` | GET | -- | `TeamStatusResponse` | Team overview |
| `/api/permissions/{id}/respond` | POST | `PermissionResponseRequest` | `PermissionResponseResult` | Permission response |

**Implementation Details:**

1. `POST /api/threads`: Create a thread record in the database via CRUD, then
   invoke `graph.ainvoke()` or `graph.astream()` with a new `thread_id`. Emit
   `AgentStatusEvent(submitted)`. When `team_preset` is provided (ADR-013
   section 6), load the corresponding `TeamConfig` and compile the graph with it;
   when `None`, fall back to `solo-coder` preset.
2. `GET /api/threads`: Paginated `list_threads` from database CRUD.
3. `GET /api/threads/{id}/state`: Call
   `graph.get_state({"configurable": {"thread_id": id}})` to produce a
   `ThreadStateSnapshot` for the reconnection protocol (ADR-011 section 2.3,
   steps 3-4; ADR-004 section 2).
4. `POST /api/threads/{id}/messages`: Enqueue into graph invocation via the
   aggregator.
5. `GET /api/team/status`: Return `TeamStatusResponse` with agent summaries
   including `role`, `display_name`, `description` sourced from node metadata
   (ADR-012 section 2.5; ADR-013 section 2.6).
6. `POST /api/permissions/{id}/respond`: Translate
   `PermissionResponseRequest` into `Command(resume=option_id)` against the
   correct `thread_id` and checkpoint (ADR-006 section 2; ADR-011 section 3.1).
   This is the ONLY path for permission responses (ADR-011 section 3).

**ADR References:** ADR-011 section 2.2, section 2.3, section 3; ADR-004
section 2; ADR-012 section 2.5; ADR-013 section 6.

**Constraints:**
- All endpoints validate against existing Pydantic schemas in `schemas/rest.py`
  and `schemas/snapshots.py`.
- `POST /api/threads` must accept optional `team_preset` field per ADR-013
  section 6 wire contract amendment.
- Add `GET /api/teams` endpoint returning `TeamPresetsResponse` to power the
  frontend team picker (ADR-013 section 6).

**Corresponds to:** Audit Recommended Task B.

---

### Gap 5: Host-side ACP RPC Handlers

**Audit status:** `AcpChatModel` covers Claude/Gemini with full ACP lifecycle.
All 9 subprocess patterns from ADR-006 section 5.1 are present. What is missing:
(a) ACP capability flags are hardcoded to `False`, (b) no host-side RPC dispatch
for `fs/*` and `terminal/*` methods, (c) `session/cancel` is sent as a
notification instead of an RPC with 3-second timeout.

**Modify:** `lib/providers/acp_chat_model.py`

**Requirements:**

1. Change `_initialize_session()`: set ACP capability flags based on
   `AgentConfig.capabilities` when `agent_config` is provided (ADR-012
   section 2.6). When `agent_config is None`, preserve current hardcoded-`False`
   behavior for backward compatibility (ADR-012 section 5).
2. Add `agent_config: AgentConfig | None = None` Pydantic field to
   `AcpChatModel` (ADR-012 section 2.6).
3. Expand `_handle_server_rpc()` to dispatch 7 new methods:
   - `fs/read_text_file` -- read file contents, return as string.
   - `fs/write_text_file` -- write string to file path.
   - `terminal/create` -- spawn async subprocess, return `terminal_id`.
   - `terminal/kill` -- kill subprocess by `terminal_id`.
   - `terminal/output` -- read stdout/stderr buffer for `terminal_id`.
   - `terminal/wait_for_exit` -- await subprocess completion, return exit code.
   - `terminal/release` -- cleanup terminal resources.
4. Fix `_cleanup_session()`: change `session/cancel` from notification to RPC
   with 3-second timeout (ADR-006 section 5.1, items 6 and 8; Audit
   section 5: MEDIUM item "`session/cancel` timeout enforcement").
5. Fix `_process_stdout_loop`: handle batch JSON-RPC (array of dicts, not just
   single dict).

**ADR References:** ADR-006 section 5.1 (all 9 patterns); ADR-012 section 2.6;
ADR-001 section 5 (Global git mutex for filesystem operations).

**Reference implementation:** Toad `agent.py` lines 348-468 (host-side RPC
handlers); Toad `protocol.py` (TypedDict definitions for terminal/fs types).

**Constraints:**
- File system operations MUST be sandboxed to the agent's `cwd` (ADR-001
  section 2; Audit section 5: MEDIUM item "Scoped MCP tool server filesystem
  path validation/isolation").
- Terminal processes tracked per-session, cleaned up on session teardown.
- File writes must respect the Global Git Mutex (ADR-001 section 2).

---

### Gap 6: Database Layer Integration

**Audit status:** `lib/database/` is COMPLETE with 4 SQLAlchemy models, CRUD,
WAL session, and facade. The gap is: (a) no integration with the FastAPI
lifespan (tables are never created at startup), (b) no migration tooling, (c)
the database is not connected to the REST endpoints.

**Modify:** `lib/database/session.py`, `lib/database/__init__.py`, `lib/api/app.py`

**Requirements:**

1. Ensure `setup_app_tables()` (or equivalent) is called from the FastAPI
   lifespan startup (Gap 1 step 2a) to create application-level tables
   (Research section 2.3).
2. Expose `get_db()` as a FastAPI dependency for REST endpoint injection
   (Research section 2.3; ADR-007 section 3).
3. Implement simple version-table migration runner:
   `lib/database/migrations/` with sequential numbered scripts and a
   `schema_migrations` table (Research section 2.5; Audit section 5: MEDIUM
   item "Database migration tooling").
4. Ensure the application database shares the same SQLite file as the LangGraph
   checkpointer (Research section 2.2) but uses a separate `aiosqlite`
   connection to avoid deadlocking LangGraph's internal lock (Research
   section 2.3).

**ADR References:** ADR-007 section 2, section 3, section 5; ADR-009 section 2.

**Constraints:**
- WAL mode is mandatory (ADR-007 section 3).
- Write batching or single-writer pattern for CRUD (ADR-007 section 5).
- `lib/core/config.py` already has `database_url` field.

---

### Gap 7: Provider Facade + Core Facade Cleanup

**Audit status:** `lib/providers/__init__.py` is empty (facade violation per
ADR-009 section 5). `lib/core/registry.py` and `lib/core/permissions.py` are
2-line stubs that ADR-009 mandates for deletion. `lib/core/__init__.py`
references these stubs.

This gap combines the original Gap 7 (Provider Facade) and Gap 8 (Core Facade
Cleanup) because they are both pure wiring changes with no external dependencies.

#### Part A: Provider Facade

**Modify:** `lib/providers/__init__.py`, add `__all__` to sub-modules that lack
it.

1. Export: `AcpChatModel`, `ProviderFactory`, `AcpError`, `AcpErrorCode`,
   `AcpPromptError`.
2. Use `X as X` re-export pattern (ruff F401 compliance; ADR-009 section 5).
3. Relative imports only.
4. Fix `factory.py` missing `Any` import from `typing`.

**Validation:** `from lib.providers import AcpChatModel, ProviderFactory` works.

#### Part B: Core Facade Cleanup

**Delete:** `lib/core/registry.py`, `lib/core/permissions.py`
**Modify:** `lib/core/__init__.py`, `lib/core/nodes/__init__.py`

ADR-009 "Key Architectural Shifts" table mandates:
- `registry.py` DELETED: LangGraph checkpointer replaces agent state tracking.
- `permissions.py` DELETED: LangGraph `interrupt()` in worker node replaces
  PermissionEngine.

1. DELETE `lib/core/registry.py` and `lib/core/permissions.py`.
2. Remove all imports/exports of `Registry` or `PermissionEngine` from
   `lib/core/__init__.py`.
3. Export `compile_team_graph`, `create_worker_node`, `create_supervisor_node`
   from `lib/core/`.
4. `lib/core/nodes/__init__.py`: add proper exports with `__all__`.
5. Add `__all__` to `lib/core/graph.py`, `lib/core/state.py`,
   `lib/core/config.py`, `lib/core/exceptions.py`.

**Validation:** `from lib.core import compile_team_graph` works.
`lib/core/registry.py` and `lib/core/permissions.py` are deleted.

**ADR References:** ADR-009 section 2, section 5; ADR-009 "Key Architectural
Shifts" table.

---

### Gap 8: Telemetry Wiring

**Audit status:** Telemetry infrastructure exists (`configure_telemetry`,
`get_tracer`, `get_meter`, `TelemetryConfig`, `TelemetryMiddleware`, `ws_span`,
`inject_trace_context`) but is NOT wired into any live code path. (Audit
section 2, ADR-010: "Instrumentation not yet wired into the aggregator, WS
manager, or graph execution layer.")

**Modify:** `lib/core/aggregator.py`, `lib/api/websocket.py`,
`lib/telemetry/instrumentation.py`, `lib/api/app.py`, `pyproject.toml`

**Requirements:**

1. Call `configure_telemetry()` from the FastAPI lifespan startup (Gap 1 step
   2c; ADR-010 section 2).
2. Add `ws_span()` around `ingest()` and `_broadcast()` in
   `lib/core/aggregator.py` (ADR-010 section 5; Audit Recommended Task E).
3. Add `ws_span()` around `connect()`, `listen()`, and
   `_handle_client_message()` in `lib/api/websocket.py` (ADR-010 section 5;
   Audit Recommended Task E).
4. Add `get_meter()` usage for: token count, WS connection count, active
   threads (Audit Recommended Task E).
5. Add OTel span propagation from incoming WS frame `_trace` field
   (ADR-010 section 5).
6. Ensure `opentelemetry-api`, `opentelemetry-sdk`,
   `opentelemetry-instrumentation-fastapi`, `opentelemetry-exporter-otlp` are
   in `pyproject.toml` dependencies.
7. Use `BatchSpanProcessor` (not `SimpleSpanProcessor`) to avoid blocking the
   event loop.
8. Exporter endpoint configurable via `lib/core/config.py` Settings.

**ADR References:** ADR-010 (entire document); ADR-009 section 2.

**Corresponds to:** Audit Recommended Task E.

---

### Gap 9: TOML Agent + Team Configuration

**Audit status:** Not tracked in the original implementation prompt or audit.
ADR-012 and ADR-013 were published on 2026-02-27 and introduce requirements
that refactor `compile_team_graph()` and the supervisor prompt.

**Create:** `lib/core/team_config.py`, `lib/core/presets/agents/*.toml`,
`lib/core/presets/teams/*.toml`, `lib/core/tests/test_team_config.py`
**Modify:** `lib/core/graph.py`, `lib/core/nodes/supervisor.py`,
`lib/core/state.py`, `lib/core/__init__.py`, `lib/api/schemas/rest.py`,
`lib/api/endpoints.py`, `lib/providers/acp_chat_model.py`

#### Part A: Agent Config (ADR-012)

1. Implement `AgentConfig` Pydantic model in `lib/core/team_config.py` with
   `from_toml(path)` classmethod (ADR-012 section 2.3).
2. Implement config discovery: workspace override at
   `{workspace_root}/.vaultspec/agents/{agent_id}.toml`, then bundled default
   at `lib/core/presets/agents/{agent_id}.toml`, then fail fast with
   `AgentConfigNotFoundError` (ADR-012 section 2.8).
3. Create four preset agent TOML files: `planner.toml`, `coder.toml`,
   `reviewer.toml`, `analyst.toml` (ADR-012 section 2.7).
4. Agent identity fields (`display_name`, `role`, `description`) stored as
   LangGraph node metadata, NOT in `TeamState` (ADR-012 section 2.5).
5. Add `agent_config: AgentConfig | None = None` field to `AcpChatModel` and
   wire capability flags in `_initialize_session()` (ADR-012 section 2.6;
   also addressed in Gap 5).

#### Part B: Team Config (ADR-013)

1. Implement `TeamConfig`, `TopologyConfig`, `WorkerRef`, `SupervisorConfig`,
   `TeamDefaultsConfig` Pydantic models in `lib/core/team_config.py` with
   `from_toml(path)` (ADR-013 section 2.4).
2. Implement config discovery: workspace at
   `{workspace_root}/.vaultspec/teams/{team_id}.toml`, then bundled default at
   `lib/core/presets/teams/{team_id}.toml`, then fail fast with
   `TeamConfigNotFoundError` (ADR-013 section 2.8).
3. Create four preset team TOML files: `coding-star.toml`,
   `coding-pipeline.toml`, `coding-loop.toml`, `solo-coder.toml` (ADR-013
   section 2.9).
4. Implement three-level model resolution precedence: `[[team.workers]]` model
   overrides > agent TOML `[agent.model]` > `[team.defaults]` (ADR-013
   section 2.3).

#### Part C: Graph Compilation Refactor

1. Refactor `compile_team_graph()` to accept `TeamConfig` +
   `dict[str, AgentConfig]` + optional checkpointer (ADR-013 section 5).
2. Remove old signature (`supervisor_model`, `worker_models`).
3. Implement three topology compilation strategies (ADR-013 section 2.5):
   - `star`: `add_conditional_edges(supervisor, ...)` with agent description
     roster injected into supervisor prompt (ADR-013 section 2.6).
   - `pipeline`: `add_sequence(order)` with no supervisor node.
   - `pipeline_loop`: `add_sequence()` + `add_conditional_edges(loop_node)`
     with `max_loops` guard via `TeamState.loop_count` (ADR-013 section 2.5).
4. Add `loop_count: int` field to `TeamState` (ADR-013 section 5).
5. Assemble `interrupt_before` from all agents with non-empty
   `require_approval_for` lists (ADR-013 section 2.7).
6. Store agent metadata on nodes via `builder.add_node(name, action,
   metadata={...})` (ADR-012 section 2.5).

#### Part D: Wire Contract Amendments

1. Add `role`, `display_name`, `description` fields to `AgentSummary` in
   `lib/api/schemas/` (ADR-012 section 6).
2. Add `team_preset: str | None = None` field to `CreateThreadRequest`
   (ADR-013 section 6).
3. Add `GET /api/teams` endpoint returning `TeamPresetsResponse` (ADR-013
   section 6).

**ADR References:** ADR-012 (entire document); ADR-013 (entire document);
ADR-008 section 2; ADR-009 section 2.

**Research References:** Model Capability Matrix section 5 (role-to-model
recommendations for preset TOML content).

---

## Phased Implementation Order

Phases are ordered by dependency. Within a phase, gaps marked "parallel" have no
dependency on each other and can be worked simultaneously.

### Phase A: Facade Cleanup (No Dependencies)

**Gaps:** 7 (Provider Facade + Core Facade Cleanup)

**Rationale:** These are pure wiring and deletion changes. They have zero
dependencies on any other gap and zero risk of breaking existing functionality
(other than removing dead imports). Completing these first ensures that all
subsequent phases import from clean, well-structured facades.

**Effort:** Small. ~1-2 hours.

**Deliverables:**
- `lib/providers/__init__.py` exports `AcpChatModel`, `ProviderFactory`,
  exception classes.
- `lib/core/registry.py` and `lib/core/permissions.py` deleted.
- `lib/core/__init__.py` exports `compile_team_graph`, worker/supervisor
  creators.
- All modules have `__all__`.
- All existing tests pass.

---

### Phase B: Foundation Layer (Depends on Phase A)

**Gaps:** 5 (Host-side ACP RPC), 6 (Database Integration), 8 (Telemetry Wiring)
-- all parallel.

**Rationale:** These three gaps are independent of each other but all depend on
clean facades from Phase A. They must complete before the FastAPI app can start
because:
- Gap 5 (ACP RPCs) unblocks agent tool execution.
- Gap 6 (Database) provides the session persistence that REST endpoints need.
- Gap 8 (Telemetry) provides the `configure_telemetry()` call that the lifespan
  requires.

**Effort:** Medium. ~3-5 hours per gap.

**Deliverables:**
- `AcpChatModel._handle_server_rpc()` dispatches `fs/*` and `terminal/*`
  methods.
- `_initialize_session()` respects `AgentConfig.capabilities` when provided.
- `session/cancel` is an RPC with 3-second timeout.
- Database tables created at startup, `get_db()` available as FastAPI dependency.
- Migration runner operational.
- OTel spans wired into aggregator and WS manager.
- OTel metrics for token count, WS connections, active threads.

---

### Phase C: Serving Layer (Depends on Phase B)

**Gaps:** 1 (FastAPI App), 3 (Event Aggregator Wiring) -- sequential (Gap 1
first, then Gap 3).

**Rationale:** The FastAPI application is the integration point for everything
built in Phases A and B. The aggregator wiring depends on having a running app
with a lifespan to start it.

**Effort:** Medium-Large. ~4-6 hours.

**Deliverables:**
- `uvicorn lib.api.app:create_app --factory` starts without errors.
- WebSocket connects at `/ws`, receives `ConnectedEvent`, then `HeartbeatEvent`
  every 30 seconds.
- Aggregator started in lifespan, bound to graph invocations.
- Static SPA served at `/`.
- CORS configured for dev.

---

### Phase D: Endpoint Wiring + Config System (Depends on Phase C)

**Gaps:** 2 (WebSocket Wiring), 4 (REST Endpoints), 9 (TOML Config) -- Gap 2
and 4 parallel; Gap 9 depends on Gap 4.

**Rationale:** REST endpoints and WebSocket command routing require the running
app from Phase C. TOML config (Gap 9) depends on the REST endpoints being
operational because it modifies `CreateThreadRequest` and adds `GET /api/teams`.

**Effort:** Large. ~6-10 hours total.

**Deliverables:**
- All 6+1 REST routes operational (6 original + `GET /api/teams`).
- `SEND_MESSAGE` WS command routes to graph invocation.
- `PERMISSION_RESPONSE` over WS rejected with error.
- 90-second dead client enforcement.
- `TeamConfig` and `AgentConfig` Pydantic models with TOML loading.
- 4 preset agents and 4 preset teams.
- `compile_team_graph()` accepts `TeamConfig`.
- Three topology compilation strategies operational.
- Supervisor prompt enhanced with agent description roster.

---

## Dependency Graph

```
Phase A: Gap 7 (facades)
    |
    v
Phase B: Gap 5 (ACP RPCs) | Gap 6 (DB integration) | Gap 8 (telemetry wiring)
    |                              |                          |
    +--------------+---------------+--------------------------+
                   |
                   v
Phase C: Gap 1 (FastAPI app) --> Gap 3 (aggregator wiring)
                   |
                   v
Phase D: Gap 2 (WS wiring) | Gap 4 (REST endpoints) --> Gap 9 (TOML config)
```

---

## Validation Criteria

These criteria define "done" for the entire plan. They are sourced from the
implementation prompt's validation section, expanded with audit acceptance
checks and ADR-012/ADR-013 requirements.

### Startup Validation

| # | Criterion | Source |
|---|---|---|
| V1 | `uvicorn lib.api.app:create_app --factory` starts without errors | Prompt V1 |
| V2 | SQLite database file created with WAL mode, application tables present | ADR-007 section 3 |
| V3 | OTel TracerProvider initialized at startup, `BatchSpanProcessor` active | ADR-010 section 2 |
| V4 | LangGraph `AsyncSqliteSaver` initialized, checkpointer tables created | ADR-004 section 2 |

### REST API Validation

| # | Criterion | Source |
|---|---|---|
| V5 | `GET /api/threads` returns `{"threads": []}` | Prompt V2 |
| V6 | `POST /api/threads` creates a thread and returns `{"thread_id": "..."}` | Prompt V3 |
| V7 | `GET /api/threads/{id}/state` returns `ThreadStateSnapshot` for reconnection | ADR-011 section 2.3 |
| V8 | `POST /api/permissions/{id}/respond` translates to `Command(resume=...)` | ADR-011 section 3.1 |
| V9 | `GET /api/teams` returns list of available team presets | ADR-013 section 6 |
| V10 | `POST /api/threads` with `team_preset` field compiles the correct topology | ADR-013 section 6 |

### WebSocket Validation

| # | Criterion | Source |
|---|---|---|
| V11 | WebSocket connects at `/ws`, receives `ConnectedEvent` with `client_id` | Prompt V4 |
| V12 | `HeartbeatEvent` received every 30 seconds | ADR-011 section 5 |
| V13 | `subscribe` command scopes events to a `thread_id` | Prompt V5 |
| V14 | `PERMISSION_RESPONSE` over WS is rejected with error | ADR-011 section 3.1 |
| V15 | Client disconnected after 90 seconds of inactivity | ADR-011 section 5 |

### Provider Validation

| # | Criterion | Source |
|---|---|---|
| V16 | Agent tool calls (`fs/read_text_file`, `terminal/create`) handled, not rejected with `-32601` | Prompt V6 |
| V17 | `_initialize_session()` sets ACP flags from `AgentConfig.capabilities` | ADR-012 section 2.6 |
| V18 | `session/cancel` is an RPC with 3-second timeout, not a notification | ADR-006 section 5.1 |

### Import Validation

| # | Criterion | Source |
|---|---|---|
| V19 | `from lib.core import compile_team_graph` works | Prompt V7 |
| V20 | `from lib.providers import AcpChatModel, ProviderFactory` works | Prompt V8 |
| V21 | `lib/core/registry.py` and `lib/core/permissions.py` are DELETED | Prompt V9 |
| V22 | `from lib.telemetry import configure_telemetry` works | Prompt V10 (adapted) |
| V23 | `from lib.core import TeamConfig, AgentConfig` works | ADR-012, ADR-013 |

### Config Validation

| # | Criterion | Source |
|---|---|---|
| V24 | `AgentConfig.from_toml()` loads preset agent TOML files without error | ADR-012 section 2.3 |
| V25 | `TeamConfig.from_toml()` loads preset team TOML files without error | ADR-013 section 2.4 |
| V26 | Three-level model resolution precedence produces correct values | ADR-013 section 2.3 |
| V27 | `topology.type="pipeline"` compiles a graph using `add_sequence()` | ADR-013 section 2.5 |
| V28 | `topology.type="pipeline_loop"` enforces `max_loops` guard | ADR-013 section 2.5 |
| V29 | Supervisor prompt includes agent description roster in `star` topology | ADR-013 section 2.6 |

### Test Validation

| # | Criterion | Source |
|---|---|---|
| V30 | All existing tests still pass (`pytest lib/`) | Prompt V11 |
| V31 | New tests for `team_config.py` pass (TOML loading, validation, model resolution) | ADR-012 section 5 |

---

## Risk Register

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| R1 | **LangGraph `astream_events` version drift.** LangGraph may change the `v2` event schema in a minor release, breaking aggregator mappings. | HIGH | Pin `langgraph` version in `pyproject.toml`. Test aggregator against live graph invocation, not mocked event data. |
| R2 | **Windows `ProactorEventLoop` limitations.** Some `asyncio` patterns that work on Linux (e.g., `add_reader`) are unavailable on the Proactor loop. | HIGH | All I/O must use `asyncio.create_subprocess_exec` or `aiosqlite` -- never raw socket operations. Test exclusively on Windows. |
| R3 | **SQLite concurrent write contention.** The application CRUD layer and the LangGraph checkpointer share the same database file. Under high concurrency, WAL mode still permits only one writer at a time. | MEDIUM | Use separate `aiosqlite` connections (Research section 2.3). Protect application writes with `asyncio.Lock()`. Batch writes where possible (ADR-007 section 5). |
| R4 | **ACP host-side RPC protocol changes.** Claude and Gemini CLIs may change their JSON-RPC method signatures or add new required capabilities. | MEDIUM | Follow Toad's `agent.py` as the canonical reference. Add version checks in `_initialize_session()` against the response `agentCapabilities`. |
| R5 | **TOML config schema evolution.** As agent and team definitions mature, the TOML schema will evolve. Existing workspace config files may become invalid. | LOW | Use Pydantic's `model_validate` with default values for new optional fields. Agent/team TOML files are user-facing -- schema changes require migration documentation. |
| R6 | **Telemetry dependency bloat.** OpenTelemetry SDK and exporters add significant transitive dependencies. | LOW | Make telemetry deps optional (extras group in `pyproject.toml`). `configure_telemetry()` already implements no-op fallback when SDK is absent. |
| R7 | **`compile_team_graph()` signature break.** Refactoring from raw model dicts to `TeamConfig` breaks all existing call sites and tests. | MEDIUM | Phase this in Gap 9 (Phase D) after all other gaps are complete. Update all call sites and tests atomically. Keep backward-compatible shim until migration is verified. |
| R8 | **Frontend-backend type drift.** Manual TypeScript types may diverge from Pydantic schemas as gaps add new fields (e.g., `team_preset`, `role`). | MEDIUM | Track as a follow-up task (Audit Recommended Task F). Establish `openapi-typescript` generation pipeline to eliminate manual type maintenance. |
| R9 | **Missing integration tests.** The audit notes that no integration tests, recorded WS fixtures, or CI config exist. Unit tests alone may mask wiring failures. | HIGH | After Phase D, write integration tests that exercise the full startup-to-WS-event flow. This is out of scope for this plan but is a critical follow-up. |
| R10 | **Background agent interference.** A background AI process (IDE watcher) has been observed rewriting `acp_chat_model.py` when it detects ruff warnings. | LOW | Maintain `# noqa: PLR0912 PLR0915` annotations on complex methods. Document this in the codebase. |

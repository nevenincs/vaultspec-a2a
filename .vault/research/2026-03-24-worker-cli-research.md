---
tags:
  - '#research'
  - '#entry-point-layer'
date: '2026-03-24'
related:
  - '[[2026-03-24-entry-point-decomposition-adr]]'
  - '[[2026-03-24-api-module-research]]'
  - '[[2026-03-24-cross-import-dependency-map-research]]'
---

<!-- DO NOT add 'Related:', 'tags:', 'date:', or other frontmatter fields
     outside the YAML frontmatter above -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

# `entry-point-layer` research: `worker-cli-static-analysis`

Static analysis of `worker/executor.py`, `worker/app.py`, `worker/ipc.py`, `cli/_team.py`, `cli/_agent.py`, `cli/_util.py`, and `api/schemas/internal.py` for Layer 2 decomposition.

---

## 1. executor.py Analysis (983 lines)

| Lines | Function/Class | Classification | Rationale |
|-------|---------------|----------------|-----------|
| 46-48 | `ConcurrentCapError` | **Business logic** | Domain error expressing capacity policy. Not HTTP-specific. |
| 50-51 | `GraphCompilationError` | **Business logic** | Domain error for graph compilation failure. Not protocol-specific. |
| 60-80 | `Executor.__init__` | **Business logic** | Wires together checkpointer, bridge, aggregator, provider factory, graph cache, ingest lock. Pure domain orchestration. |
| 82-107 | `Executor.__init__` (relay hook wiring) | **Business logic** | Creates a broadcast hook closure that converts `SequencedEvent` to dict and sends via bridge. Domain event relay policy. |
| 116-134 | `at_capacity`, `graph_count`, `active_ingest_count`, accessors | **Business logic** | Capacity checking and state introspection. Domain policy. |
| 136-159 | `_log_extra`, `_dispatch_log_extra` | **Business logic** | Structured logging context builders. Domain-specific field selection. |
| 165-191 | `_mark_ingest_active`, `_mark_ingest_done` | **Business logic** | Concurrency gating, thread lifecycle (track/untrack), permission pruning, sequence pruning. Core domain orchestration. |
| 196-256 | `handle_dispatch` | **Mixed: protocol translation + business logic** | Top-level dispatch router. The `match req.action` routing is business logic (domain policy). The telemetry span wrapping and exception guarding are infrastructure. |
| 262-323 | `_get_or_compile_graph` | **Business logic** | LRU cache management, graph compilation orchestration, aggregator registration, metadata relay. Pure domain logic with no HTTP/CLI awareness. |
| 325-347 | `_send_graph_registered` | **Business logic** | Extracts node metadata from compiled graph and relays via bridge. Domain event emission. |
| 353-426 | `_pre_flight_checkpoint` | **Business logic** | Checkpoint inspection for reconciliation after crash. Detects completed/failed/interrupted states from checkpoint pending_writes. Pure domain logic. |
| 428-571 | `_handle_ingest` | **Business logic** | Orchestrates pre-flight check, graph compilation, ingest gating, graph input construction, aggregator ingest call, terminal status emission, execution state projection. 100% domain orchestration. |
| 577-700 | `_handle_resume` | **Business logic** | Graph recompilation for resume, recursion limit resolution from team config, `Command(resume=...)` construction, aggregator ingest, terminal status + execution state projection. Pure domain orchestration. |
| 706-740 | `_emit_terminal_status` | **Business logic** | Terminal event emission policy (only for completed/failed/cancelled; not interrupted). Immediate flush policy for terminal events. Domain lifecycle management. |
| 742-815 | `_normalize_execution_state` | **Business logic** | Converts LangGraph `StateSnapshot` into `ExecutionStateProjectionPayload`. Pure domain data transformation with deep knowledge of LangGraph internals (tasks, interrupts, checkpoint structure). |
| 817-844 | `_emit_execution_state_projection` | **Business logic** | Fetches graph state via `aget_state`, normalizes, sends via bridge. Domain state projection with timeout/error handling. |
| 850-905 | `_build_graph_input` (static method) | **Business logic** | Constructs `TeamState`-compatible dict from `DispatchRequest`. Knows about first-ingest vs follow-up semantics, plan/agent/artifact/token field initialization, SDD blackboard fields. Core domain knowledge. |
| 911-973 | `_compile_graph` | **Business logic** | Loads team config, agent configs, supervisor config. Calls `compile_team_graph` with full parameter set. Domain graph compilation orchestration. |
| 979-983 | `shutdown` | **Business logic** | Aggregator shutdown, cache clearing. Domain lifecycle cleanup. |

### executor.py Summary

**983 lines, 0 lines of protocol translation, 983 lines of business logic.**

The entire `Executor` class is pure business logic. It has zero HTTP awareness -- it receives a typed `DispatchRequest` and operates entirely on domain objects (checkpointer, aggregator, graph cache, bridge). This is correctly in the "business logic that must move to a neutral location" category. However, its current position in `worker/` is architecturally defensible because the worker process is its sole consumer. The real problem is not that it lives in `worker/` but that it imports IPC types from `api/schemas/internal.py`.

---

## 2. worker/app.py Analysis (244 lines)

| Lines | Function/Class | Classification | Rationale |
|-------|---------------|----------------|-----------|
| 49 | `WorkerApp = FastAPI` | **Protocol translation** | Type alias for the wire protocol framework. |
| 52-72 | `_verify_dispatch_token` | **Protocol translation** | HTTP header extraction (`Authorization: Bearer ...`), environment-specific validation, HTTP error responses. Pure HTTP concern. |
| 75-153 | `_lifespan` | **Mixed** | Creates worker_id, configures telemetry, opens checkpointer, creates bridge, creates executor, starts heartbeat, handles shutdown. The lifespan *orchestration* is protocol-adjacent (FastAPI lifecycle), but the *composition* of domain objects (bridge, executor, checkpointer) is domain logic that should be injectable. |
| 155-218 | `create_worker_app` | **Protocol translation** | FastAPI app factory, route registration, middleware wiring. The `/dispatch` endpoint handler is thin protocol translation (extract request, check capacity → 429, fire-and-forget to executor). `/health` and `/admin/shutdown` are pure HTTP handlers. |
| 221-243 | `main` | **Protocol translation** | Console script entry point, uvicorn launch. |

### app.py Summary

**244 lines. ~160 lines protocol translation, ~84 lines mixed (lifespan domain object composition).**

This file is well-structured as a thin protocol adapter. The lifespan function does domain object composition (creating Executor, WorkerBridge) which could be extracted to a factory, but it's a minor concern.

---

## 3. worker/ipc.py Analysis (357 lines)

| Lines | Function/Class | Classification | Rationale |
|-------|---------------|----------------|-----------|
| 29-65 | `WorkerBridge.__init__` | **IPC contract** | HTTP client construction, auth header injection, event buffer initialization. IPC transport implementation. |
| 78-83 | `close` | **IPC contract** | Transport teardown. |
| 89-100 | `track_thread`, `untrack_thread`, `active_threads` | **Business logic** | Thread lifecycle tracking. Domain state management that happens to be co-located with the transport. |
| 106-137 | `send_event` | **IPC contract** | Event buffering with cap, deferred flush scheduling. Transport-level concern. |
| 139-239 | `_deferred_flush`, `flush_events` | **IPC contract** | Batch POST with retry, exponential backoff, re-queue on failure. Transport reliability concern. |
| 245-356 | `send_heartbeat`, `heartbeat_loop` | **IPC contract** | Heartbeat protocol with consecutive failure tracking and escalating log severity. Transport health concern. |

### ipc.py Summary

**357 lines. ~40 lines business logic (thread tracking), ~317 lines IPC transport.**

`WorkerBridge` is an IPC transport implementation. The thread tracking (`track_thread`/`untrack_thread`/`active_threads`) is lightweight domain state that's tightly coupled to the heartbeat protocol, so co-location is acceptable. The class belongs in a neutral IPC location since it's the counterpart to the gateway's internal event receiver.

---

## 4. cli/_team.py Analysis (825 lines)

| Lines | Function/Class | Classification | Rationale |
|-------|---------------|----------------|-----------|
| 12-30 | `_format_elapsed` | **Business logic** | Time delta formatting. Domain-level display logic, not CLI framework specific. Could live in a shared formatting utility. |
| 33-52 | `_fetch_thread_metadata` | **Business logic** | Fetches thread list from API and extracts metadata for a specific thread. This is a workaround for `ThreadStateSnapshot` not including identity fields. Domain data enrichment. |
| 56-57 | `team` click group | **Protocol translation** | CLI group definition. |
| 60-95 | `start` command | **Protocol translation** | Click decorators, argument parsing, body construction, POST to `/threads`, response formatting. Thin adapter. |
| 98-118 | `message` command | **Protocol translation** | Click decorators, argument parsing, POST to `/threads/{id}/messages`, response formatting. Thin adapter. |
| 122-178 | `respond` command | **Mixed** | Click decorators are protocol translation, but lines 131-142 fetch permission context before responding (business logic: "show what was approved"), and lines 152-178 interpret `action_status` values (business logic: domain-specific status interpretation). |
| 181-196 | `resume` command | **Protocol translation** | Thin adapter. Defaulting `"Continue."` when no message is provided is borderline business logic but trivial. |
| 199-214 | `cancel` command | **Protocol translation** | Thin adapter. Interpreting `cancelled` vs terminal state is minor display logic. |
| 217-238 | `delete`, `archive` commands | **Protocol translation** | Thin adapters. |
| 241-345 | `status` command | **Mixed** | Lines 241-260 are protocol translation (click decorators, API call). Lines 263-345 are **business logic**: complex rendering of thread state with knowledge of domain concepts (plan entries with status icons, agent states, pending permissions with option rendering, tool calls with kinds, interrupt counts). This is a domain-aware status renderer. |
| 348-436 | `list` command | **Mixed** | Lines 348-389 are protocol translation (click decorators, query params, API call). Lines 390-436 are **business logic**: summary dashboard with active state counting, table formatting with domain knowledge (active states set), permission summary from `/team/status` endpoint. |
| 439-796 | `watch` command + `_watch_async` | **Mixed: heavy business logic** | Lines 439-446 are protocol translation (click decorator, asyncio.run). Lines 449-796 (348 lines) are a **massive business logic block**: WebSocket protocol implementation (connect, subscribe, event loop), event rendering with domain knowledge for 10+ event types, permission prompt with option parsing (shortcut map construction, kind-based shortcuts), terminal state detection logic (thread_terminal event + supervisor agent_status fallback). This is the most business-logic-heavy function in the CLI layer. |
| 799-825 | `presets` command | **Protocol translation** | Thin adapter. |

### _team.py Summary

**825 lines. ~250 lines protocol translation, ~575 lines business logic.**

The heaviest business logic concentration is in `_watch_async` (348 lines) which implements:
- WebSocket client protocol (connect, handshake, subscribe)
- Event rendering for 10+ domain event types
- Interactive permission prompt with option shortcut mapping
- Terminal state detection policy (thread_terminal + supervisor fallback)

The `status` and `list` commands also contain significant domain-aware rendering logic (plan icons, agent state display, permission rendering).

---

## 5. cli/_agent.py Analysis (80 lines)

| Lines | Function/Class | Classification | Rationale |
|-------|---------------|----------------|-----------|
| 16-17 | `agent` click group | **Protocol translation** | CLI group definition. |
| 21-43 | `list` command | **Mixed** | Click decorators are protocol translation, but lines 27-28 directly access filesystem (`Path(...) / "core" / "presets" / "agents"`) to discover presets. This embeds domain knowledge about preset directory structure into the CLI. Should use a domain service. |
| 47-79 | `show` command | **Mixed** | Click decorators are protocol translation, but lines 54-64 implement preset discovery logic (check agents dir, fall back to teams dir). Lines 66-79 read and optionally parse TOML. Domain preset resolution logic leaked into CLI. |

### _agent.py Summary

**80 lines. ~30 lines protocol translation, ~50 lines business logic.**

Both commands bypass the API entirely and directly access the filesystem to read preset TOML files. This is a domain-layer concern (preset discovery and resolution) that has leaked into the CLI. The CLI should call an API endpoint or domain service for preset information.

---

## 6. cli/_util.py Analysis (174 lines)

| Lines | Function/Class | Classification | Rationale |
|-------|---------------|----------------|-----------|
| 29-36 | `_mask` | **Protocol translation** | Sensitive value masking for CLI display. Pure presentation concern. |
| 39-50 | `_show_config_callback` | **Protocol translation** | Click callback to dump settings. |
| 53-63 | `_handle_response` | **Protocol translation** | HTTP error → SystemExit translation. |
| 67-100 | `_preflight_check` | **Mixed** | Lines 67-77 are protocol translation (HTTP health check). Lines 78-100 interpret domain-specific health check response structure (circuit breaker state, worker status) and emit domain-specific warnings. Minor business logic leak. |
| 103-173 | `_api_client` | **Protocol translation** | Context manager wrapping httpx client with error handling. Catches `ConnectError`, `ConnectTimeout`, `RemoteProtocolError`, `ReadTimeout` and formats actionable error messages. Well-structured protocol adapter. |

### _util.py Summary

**174 lines. ~155 lines protocol translation, ~19 lines business logic (health check interpretation).**

This is the best-structured file in the CLI layer. Almost entirely protocol translation with minimal business logic leakage.

---

## 7. IPC Type Dependency Map

### Types defined in `api/schemas/internal.py` (101 lines)

| Type | Description | Importers |
|------|-------------|-----------|
| `DispatchRequest` | Work dispatch command (gateway → worker) | `api/app.py`, `api/endpoints.py`, `worker/app.py`, `worker/executor.py`, `worker/tests/test_executor.py`, `worker/tests/test_app.py` |
| `DispatchResponse` | Dispatch acknowledgment (worker → gateway) | `worker/app.py` |
| `HeartbeatMessage` | Worker heartbeat payload | *Not imported anywhere* (dead code — `WorkerBridge` constructs heartbeat dicts inline) |
| `ExecutionTaskProjectionPayload` | Normalized task summary | `worker/executor.py` (used internally by `_normalize_execution_state`) |
| `ExecutionStateProjectionPayload` | Normalized execution state snapshot | `worker/executor.py`, `api/internal.py` |
| `WorkerEventEnvelope` | Event wrapper for worker→gateway events | *Not imported anywhere* (dead code — `WorkerBridge.send_event` uses raw dicts) |

### Cross-boundary import violations

1. **`worker/executor.py` → `api/schemas/internal`**: Imports `DispatchRequest`, `ExecutionStateProjectionPayload`, `ExecutionTaskProjectionPayload`. This is an **inverted dependency** — a downstream process module depends on the gateway's schema namespace.

2. **`worker/app.py` → `api/schemas/internal`**: Imports `DispatchRequest`, `DispatchResponse`. Same inverted dependency.

3. **`worker/executor.py` → `api/event_adapter`**: Imports `sequenced_to_dict`. The worker depends on the API layer's event serialization logic. This is another inverted dependency.

### Proposed neutral location

Move `api/schemas/internal.py` contents to a new module: **`ipc/types.py`** (or `ipc/schemas.py`).

Rationale:
- These types define the **contract between gateway and worker** — they belong to neither.
- A top-level `ipc/` package is symmetric: both `api/` and `worker/` import from `ipc/`.
- `HeartbeatMessage` and `WorkerEventEnvelope` are dead code and should be deleted rather than moved.

Also move `api/event_adapter.sequenced_to_dict` to `ipc/event_adapter.py` or `streaming/event_adapter.py` since it's a serialization utility used by the worker.

---

## 8. Proposed Split for executor.py

### Current state: 983 lines, 100% business logic

The Executor has three distinct responsibilities:

### Responsibility 1: Graph Lifecycle Management (~300 lines)
- `_get_or_compile_graph` (LRU cache, compilation, registration)
- `_compile_graph` (config loading, `compile_team_graph` call)
- `_send_graph_registered` (metadata relay)
- `_build_graph_input` (input construction with first-ingest semantics)
- `shutdown` (cache cleanup)

**Proposed location:** `graph/lifecycle.py` or keep in `worker/executor.py` as `GraphLifecycleManager`

### Responsibility 2: Dispatch Orchestration (~400 lines)
- `handle_dispatch` (top-level router)
- `_handle_ingest` (ingest orchestration with pre-flight, compilation, execution, terminal emit)
- `_handle_resume` (resume orchestration with recompilation, recursion limit resolution)
- `_mark_ingest_active` / `_mark_ingest_done` (concurrency gating)

**Proposed location:** Keep in `worker/executor.py` but with graph lifecycle extracted

### Responsibility 3: State Projection & Terminal Events (~150 lines)
- `_normalize_execution_state` (StateSnapshot → ExecutionStateProjectionPayload)
- `_emit_execution_state_projection` (fetch state, normalize, send)
- `_emit_terminal_status` (terminal event emission + immediate flush)
- `_pre_flight_checkpoint` (checkpoint inspection for reconciliation)

**Proposed location:** `worker/state_projection.py` or `lifecycle/state_projection.py`

### Recommended decomposition

```
worker/
  executor.py          (~400 lines) — Dispatch routing + ingest/resume orchestration
  graph_lifecycle.py   (~300 lines) — Graph cache, compilation, input construction
  state_projection.py  (~150 lines) — Checkpoint inspection, state normalization, terminal events
  ipc.py               (~357 lines) — WorkerBridge (unchanged)
  app.py               (~244 lines) — FastAPI app (unchanged)
```

The `Executor` class would retain `handle_dispatch`, `_handle_ingest`, `_handle_resume`, and concurrency gating. It would delegate to:
- `GraphLifecycleManager` for graph compilation and caching
- `StateProjector` for checkpoint inspection, state normalization, and terminal event emission

---

## 9. Cross-Import Violations

### Violation 1: worker → api (inverted dependency)

| Source | Target | Import |
|--------|--------|--------|
| `worker/executor.py` | `api/schemas/internal` | `DispatchRequest`, `ExecutionStateProjectionPayload`, `ExecutionTaskProjectionPayload` |
| `worker/executor.py` | `api/event_adapter` | `sequenced_to_dict` |
| `worker/app.py` | `api/schemas/internal` | `DispatchRequest`, `DispatchResponse` |

**Impact:** The worker process cannot be packaged or tested independently of the API layer. Any refactoring of `api/schemas/` breaks the worker.

**Fix:** Move shared IPC types to `ipc/types.py`. Move `sequenced_to_dict` to `streaming/event_adapter.py` or `ipc/event_adapter.py`.

### Violation 2: cli/_agent.py bypasses API entirely

The `list` and `show` commands in `cli/_agent.py` directly access the filesystem to discover and read preset TOML files (`Path(...) / "core" / "presets" / "agents"`). This:
- Couples the CLI to the internal preset directory structure
- Bypasses any preset validation the API might do
- Will break if preset storage changes (e.g., database-backed presets)

**Fix:** Route through the API's `/teams` endpoint (which `_team.py presets` already uses) or add a `/agents` endpoint.

### Violation 3: No entry-point-to-entry-point imports

There are **no direct imports between `worker/` and `cli/`**, which is correct. The only cross-entry-point dependency is the shared dependency on `api/schemas/internal.py`, which should move to neutral ground.

---

## 10. Dead Code

| Type | Location | Evidence |
|------|----------|----------|
| `HeartbeatMessage` | `api/schemas/internal.py:57-63` | Zero importers. `WorkerBridge.send_heartbeat` constructs heartbeat payloads as inline dicts. |
| `WorkerEventEnvelope` | `api/schemas/internal.py:95-101` | Zero importers. `WorkerBridge.send_event` uses raw dicts. |

---

## 11. Key Findings Summary

1. **executor.py is 100% business logic** — it has zero protocol awareness and should not be considered a "protocol adapter" in any decomposition. Its position in `worker/` is acceptable since the worker process is its sole consumer, but its dependency on `api/schemas/internal` is an architectural violation.

2. **cli/_team.py has 575 lines of business logic** — primarily in `_watch_async` (348 lines of WebSocket client protocol, event rendering, permission prompting, terminal detection) and `status`/`list` (domain-aware rendering). These are candidates for extraction into domain services.

3. **The IPC types live in the wrong place** — `api/schemas/internal.py` defines the gateway-worker contract but lives in the API namespace, creating an inverted dependency from worker to api.

4. **Two IPC types are dead code** — `HeartbeatMessage` and `WorkerEventEnvelope` are never imported.

5. **cli/_agent.py bypasses the API** — directly reads preset TOML files from the filesystem instead of calling an API endpoint.

6. **worker/app.py and cli/_util.py are well-structured** — both are thin protocol adapters with minimal business logic leakage.

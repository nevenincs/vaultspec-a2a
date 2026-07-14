---
tags:
  - '#research'
  - '#entry-point-layer'
date: '2026-03-24'
modified: '2026-03-24'
related:
  - '[[2026-03-24-entry-point-decomposition-adr]]'
  - '[[2026-03-24-worker-cli-research]]'
  - '[[2026-03-24-cross-import-dependency-map-research]]'
---

# `entry-point-layer` research: `api-module-static-analysis`

Static analysis of `api/` module — 7 files, 5,722 total lines. Classifies every function/class as protocol-translation, business-logic, or infrastructure to guide Layer 2 decomposition.

---

## 1. Summary Stats

| File | Lines | Protocol Translation | Business Logic | Infrastructure |
|------|------:|---------------------:|---------------:|---------------:|
| endpoints.py | 1,883 | ~680 (36%) | ~1,050 (56%) | ~153 (8%) |
| app.py | 1,507 | ~350 (23%) | ~310 (21%) | ~847 (56%) |
| websocket.py | 719 | ~650 (90%) | ~40 (6%) | ~29 (4%) |
| projection.py | 491 | 0 (0%) | ~491 (100%) | 0 (0%) |
| event_adapter.py | 270 | ~270 (100%) | 0 (0%) | 0 (0%) |
| internal.py | 812 | ~230 (28%) | ~582 (72%) | 0 (0%) |
| auth.py | 40 | ~40 (100%) | 0 (0%) | 0 (0%) |

**Totals**: ~2,220 protocol (39%), ~2,473 business (43%), ~1,029 infrastructure (18%)

**Key finding**: Only 39% of the api/ module is actually protocol translation. 43% is business logic that should live in Layer 1 service modules.

---

## 2. endpoints.py Function-by-Function Table (1,883 lines)

| Function | Lines | Classification | Rationale | Proposed Destination |
|----------|-------|----------------|-----------|---------------------|
| `_trace_headers()` | 137-146 | protocol | OTel header injection for HTTP dispatch | stays in api/ (shared util) |
| `_mark_worker_connected()` | 149-161 | protocol | Updates app.state timestamp after dispatch | stays in api/ |
| `get_aggregator()` | 170-175 | protocol | FastAPI dependency injection | stays in api/ |
| `get_checkpointer()` | 178-183 | protocol | FastAPI dependency injection | stays in api/ |
| `get_worker_client()` | 186-191 | protocol | FastAPI dependency injection | stays in api/ |
| `get_circuit_breaker()` | 194-199 | protocol | FastAPI dependency injection | stays in api/ |
| `get_worker_spawner()` | 202-207 | protocol | FastAPI dependency injection | stays in api/ |
| `get_services()` | 210-221 | protocol | FastAPI dependency bundling | stays in api/ |
| `health()` | 229-324 | **mixed** | Route handler is protocol; health aggregation logic (DB probe, checkpoint check, worker probe, readiness calc) is **business logic** | Health aggregation logic -> `control/health.py` or `lifecycle/health.py`; route stays |
| `_process_metadata()` | 332-375 | **business** | Workspace validation, context ref discovery, nickname generation, team config loading -- pure domain logic | `thread/metadata_service.py` or `thread/creation.py` |
| `create_thread_endpoint()` | 378-604 | **mixed** | Route handler (protocol) wraps ~150 lines of thread creation orchestration: DB writes, metadata processing, context preamble building, vault index building, dispatch construction, circuit breaker coordination, status transitions | Thread creation orchestration -> `thread/creation.py`; dispatch logic -> `control/dispatch.py`; route stays as thin adapter |
| `list_threads_endpoint()` | 612-670 | **mixed** | Route handler is protocol; metadata JSON parsing + ThreadSummary enrichment (~30 lines) is **business** projection logic | Projection logic -> `thread/projection.py` or keep in api/projection.py |
| `get_thread_metadata_endpoint()` | 678-691 | protocol | Thin lookup + 404 mapping | stays in api/ |
| `_enrich_snapshot_from_state()` | 699-901 | **business** | 200-line domain projection: message extraction from LangChain objects, checkpoint parsing, plan/artifact extraction, agent state assembly, tool call classification, aggregator cross-referencing | `thread/snapshot.py` -- this is the single largest business logic block in endpoints.py |
| `_MinimalState` | 904-909 | **business** | Adapter for snapshot reuse | moves with `_enrich_snapshot_from_state` |
| `_load_checkpoint_history_depth()` | 912-922 | **business** | Checkpoint query logic | `thread/snapshot.py` |
| `_finalize_snapshot_replay_status()` | 925-950 | **business** | Replay/degradation policy decisions | `thread/snapshot.py` |
| `get_thread_state_endpoint()` | 953-1070 | **mixed** | Route handler wraps ~80 lines of snapshot assembly orchestration: checkpoint loading, timeout handling, projection merging, replay status finalization | Snapshot orchestration -> `thread/snapshot.py`; route stays as thin adapter |
| `send_message_endpoint()` | 1078-1270 | **mixed** | Route handler wraps ~120 lines of message dispatch orchestration: state validation, idempotency check, control action creation, dispatch construction, circuit breaker coordination, status transitions | Message dispatch orchestration -> `control/dispatch.py`; route stays |
| `get_team_status_endpoint()` | 1278-1334 | **mixed** | Route handler wraps ~40 lines of team status assembly: heartbeat thread merging, node summary/agent state assembly, permission merging from DB + aggregator | Team status assembly -> `team/status.py`; route stays |
| `list_team_presets_endpoint()` | 1342-1369 | **mixed** | Route handler wraps ~20 lines of preset discovery + config loading | Mostly protocol; discovery logic already in team/team_config.py |
| `respond_to_permission_endpoint()` | 1377-1654 | **mixed** | Route handler wraps ~250 lines of permission response orchestration: permission lookup, idempotency, state validation, plan-approval resume-value translation, control action journal, dispatch construction, aggregator permission resolution, thread status transitions | Permission response orchestration -> `control/permissions.py`; route stays |
| `cancel_thread_endpoint()` | 1662-1808 | **mixed** | Route handler wraps ~120 lines of cancel orchestration: state validation, idempotency, control action journal, dispatch, circuit breaker bypass, status transitions | Cancel orchestration -> `control/dispatch.py`; route stays |
| `delete_thread_endpoint()` | 1816-1834 | protocol | Thin route: lookup + guard + delete + commit | stays in api/ |
| `archive_thread_endpoint()` | 1842-1868 | protocol | Thin route: lookup + guard + status transition | stays in api/ |
| `shutdown_endpoint()` | 1876-1883 | protocol | Signal handler | stays in api/ |

---

## 3. app.py Function-by-Function Table (1,507 lines)

| Function | Lines | Classification | Rationale | Proposed Destination |
|----------|-------|----------------|-----------|---------------------|
| `_runtime_dir()` | 80-84 | infrastructure | File path resolution | `control/runtime.py` |
| `_worker_stderr_log_path()` | 87-89 | infrastructure | Log path | `control/runtime.py` |
| `_read_log_tail()` | 92-100 | infrastructure | Log reading | `control/runtime.py` |
| `_build_worker_restart_detail()` | 103-115 | infrastructure | Diagnostic string builder | `control/runtime.py` |
| `_build_sqlite_fallback_diagnostics()` | 118-151 | **business** | Database backend inspection, settings interrogation | `control/health.py` or `database/diagnostics.py` |
| `WorkerCircuitBreaker` | 159-233 | **infrastructure** | Generic circuit breaker pattern | `control/circuit_breaker.py` |
| `_CacheControlMiddleware` | 242-260 | protocol | HTTP middleware | stays in api/ |
| `_trace_headers()` (duplicate) | 268-272 | protocol | Same as endpoints.py -- duplicated | deduplicate into shared api util |
| `_classify_missing_ws_thread()` | 275-350 | **business** | Thread state drift classification, checkpoint verification, error categorization | `thread/diagnostics.py` |
| `_ws_mark_failed_and_broadcast()` | 353-386 | **mixed** | DB status update (business) + WS broadcast (protocol) | Split: DB update -> `thread/lifecycle.py`; broadcast stays |
| `_create_dispatch_message_handler()` | 389-523 | **mixed** | Factory is protocol; inner `_dispatch_message` contains ~100 lines of thread lookup, state validation, terminal/input-required guards, metadata extraction, dispatch construction, circuit breaker coordination -- all **business logic** | Dispatch orchestration -> `control/dispatch.py`; thin WS adapter stays |
| `_create_dispatch_control_handler()` | 526-594 | **mixed** | Factory is protocol; inner `_dispatch_control` contains state lookup, action mapping, dispatch -- **business logic** | Control orchestration -> `control/dispatch.py`; thin WS adapter stays |
| `_tcp_port_ready()` | 602-617 | infrastructure | TCP health probe | `control/worker_management.py` |
| `_check_worker_health()` | 620-633 | infrastructure | HTTP health probe | `control/worker_management.py` |
| `_spawn_worker()` | 636-751 | **infrastructure** | 115-line process spawning: env propagation, subprocess management, adaptive health polling | `control/worker_management.py` |
| `_shutdown_worker_process()` | 754-796 | infrastructure | Process teardown (Windows/Linux) | `control/worker_management.py` |
| `LazyWorkerSpawner` | 804-908 | **infrastructure** | Worker lifecycle management | `control/worker_management.py` |
| `WorkerWatchdog` | 915-1089 | **infrastructure** | 175-line crash detection + auto-restart | `control/worker_management.py` |
| `_lifespan()` | 1097-1304 | **mixed** | Startup/shutdown orchestration: DB init, checkpointer, aggregator, telemetry, worker client, spawner, circuit breaker, watchdog, WS handler wiring, reconciliation -- part protocol (FastAPI wiring), part **business** (DB init, reconciliation), part **infrastructure** (spawner/watchdog init) | Extract init sequences into `control/startup.py`; keep thin lifespan adapter |
| `main()` | 1307-1321 | protocol | Uvicorn entry point | stays in api/ |
| `create_app()` | 1324-1503 | **mixed** | App factory: middleware setup (protocol), inline `/health` endpoint (~100 lines of health assembly -- business), WS route (protocol), SPA mount (protocol) | Extract inline health endpoint; stays as thin factory |
| inline `health_endpoint()` | 1364-1479 | **business** | 115-line health assembly: worker status, circuit breaker state, spawner state, restart metadata, repair summary, SQLite fallback, readiness calc | `control/health.py` -- duplicates logic with `endpoints.py:health()` |

---

## 4. Inline Class Analysis (app.py)

### WorkerCircuitBreaker (lines 159-233, 75 lines)

**Interface**: `pre_dispatch()`, `record_success()`, `record_failure()`, `force_open()`, `state` property
**Dependencies**: `time.monotonic()`, `logging`, `fastapi.HTTPException` (lazy import in `pre_dispatch`)
**State**: `_consecutive_failures`, `_state`, `_opened_at`, `_failure_threshold`, `_recovery_timeout`
**Assessment**: Pure infrastructure pattern. No domain knowledge. The HTTPException in `pre_dispatch` is a protocol concern leaked in -- should return a result and let the caller raise.
**Proposed location**: `control/circuit_breaker.py`

### LazyWorkerSpawner (lines 804-908, 105 lines)

**Interface**: `ensure_worker()`, `shutdown()`, `spawned`, `process`, `stderr_log_path`, `worker_url`, `worker_port`, `replace_process()`
**Dependencies**: `_spawn_worker()`, `_check_worker_health()`, `_shutdown_worker_process()`, `asyncio.Lock`, `subprocess.Popen`, `Path`
**State**: `_process`, `_spawned`, `_lock`, `_worker_url`, `_worker_port`, `_auto_spawn`, `_stderr_log_path`
**Assessment**: Infrastructure. Manages subprocess lifecycle. No domain logic.
**Proposed location**: `control/worker_management.py`

### WorkerWatchdog (lines 915-1089, 175 lines)

**Interface**: `run()`, `_attempt_restart()`
**Dependencies**: `LazyWorkerSpawner`, `WorkerCircuitBreaker`, `app.state`, `settings`, `_spawn_worker()`, `_check_worker_health()`, `_build_worker_restart_detail()`
**State**: Writes extensively to `app.state` (worker_status, restart_count, restart_reason, etc.)
**Assessment**: Infrastructure. Process health monitoring and auto-restart. The `app.state` coupling is a design smell -- should use a dedicated state object.
**Proposed location**: `control/worker_management.py`

---

## 5. websocket.py Analysis (719 lines)

### ConnectionManager (lines 100-719, 620 lines)

**Classification**: Primarily **protocol translation** (90%).

| Method | Classification | Notes |
|--------|----------------|-------|
| `__init__` | protocol | Connection state setup |
| `set_message_handler` | protocol | Callback registration |
| `set_agent_control_handler` | protocol | Callback registration |
| `connect()` | protocol | WebSocket accept, ConnectedEvent send |
| `disconnect()` | protocol | Cleanup |
| `listen()` | protocol | Read loop with timeout, size validation |
| `_handle_subscribe` | protocol | Aggregator subscription |
| `_handle_unsubscribe` | protocol | Aggregator unsubscription |
| `_handle_send_message` | protocol | Delegates to message handler |
| `_handle_agent_control` | protocol | Delegates to control handler |
| `_handle_permission_response` | protocol | Reject with error (REST-only) |
| `_handle_ping` | protocol | Heartbeat response |
| `_send_error_event` | protocol | Error frame serialization |
| `_handle_client_message` | protocol | Command parsing + dispatch |
| `_writer_loop` | protocol | Event queue drain + heartbeat |
| `broadcast_to_thread` | protocol | Fan-out with backpressure |
| `shutdown` | protocol | Cleanup |

**Business logic leak**: `connect()` lines 159-166 source `worker_active_threads` from `websocket.app.state` -- this is a minor coupling to the worker health model. The ConnectedEvent population with active threads is borderline business logic but acceptable as protocol-level connection initialization.

### WebSocketCommandRejectedError (lines 79-97)

**Classification**: protocol -- structured error type for WS transport.

**Assessment**: websocket.py is the cleanest file in the module. It is a genuine protocol adapter. Stays in Layer 2.

---

## 6. Supporting Files Analysis

### projection.py (491 lines) -- **100% Business Logic**

Contains checkpoint projection, execution state projection, permission snapshot construction, and snapshot enrichment. This is pure domain logic operating on LangGraph checkpoint internals, DB models, and API snapshot assembly.

Key classes/functions:
- `ProjectedInterrupt`, `CheckpointProjection`, `ExecutionStateProjection` -- domain dataclasses
- `project_checkpoint_tuple()` -- checkpoint data extraction and normalization
- `apply_checkpoint_projection()` -- snapshot enrichment
- `project_execution_state_model()` -- execution state normalization
- `apply_execution_state_projection()` -- snapshot enrichment
- `enrich_snapshot_from_durable_state()` -- DB permission merge
- `enrich_snapshot_from_execution_state()` -- execution state freshness classification
- `_permission_snapshot_from_model()`, `_permission_snapshot_from_interrupt()` -- domain mapping

**Proposed destination**: `thread/snapshot.py` or `thread/projection.py`. This module has no HTTP/WS awareness -- it should never have been in api/ in the first place.

### event_adapter.py (270 lines) -- **100% Protocol Translation**

Clean domain-event-to-wire-event mapper. `domain_to_wire()` and `sequenced_to_wire()` are pure data transformation from `graph.events.*` to `api.schemas.events.*`. No side effects, no I/O.

**Assessment**: Correctly placed in Layer 2. This IS protocol translation -- converting internal domain events to the wire format. Stays in api/.

### internal.py (812 lines) -- **72% Business Logic**

The internal router contains significant business logic that should not be in a protocol adapter:

| Function | Lines | Classification |
|----------|-------|----------------|
| `_handle_terminal_event()` | 53-170 | **business** -- DB status updates, permission expiry, control action journaling, aggregator GC |
| `_handle_permission_event()` | 180-310 | **business** -- permission persistence, approval state machine, control action journal, thread status transitions |
| `_handle_progress_event()` | 313-394 | **business** -- permission application inference, approval state machine |
| `_handle_execution_state_event()` | 397-435 | **business** -- execution state persistence |
| `_validate_event_envelope()` | 438-449 | protocol |
| `_verify_internal_token()` | 452-475 | protocol |
| `_relay_worker_event()` | 485-550 | **mixed** -- WS broadcast (protocol) + orchestrates 4 business handlers |
| `worker_ws_endpoint()` | 553-615 | protocol -- WS accept, frame parsing, heartbeat handling |
| `internal_health()` | 618-621 | protocol |
| `receive_worker_event()` | 629-699 | **mixed** -- HTTP handler (protocol) + orchestrates same 4 business handlers |
| `receive_worker_event_batch()` | 702-790 | **mixed** -- batch HTTP handler (protocol) + orchestrates same 4 business handlers |
| `receive_worker_heartbeat()` | 793-812 | protocol |

**Proposed destination**: Extract `_handle_terminal_event`, `_handle_permission_event`, `_handle_progress_event`, `_handle_execution_state_event` into `control/event_handlers.py` or `lifecycle/event_handlers.py`. The internal.py routes stay as thin adapters that call these handlers.

### auth.py (40 lines) -- **100% Protocol Translation**

No-op stub. Correctly placed.

---

## 7. Duplicated Logic

### Dispatch orchestration (REST vs WS)

The dispatch-to-worker pattern is duplicated across **6 call sites**:

1. `endpoints.py:create_thread_endpoint()` -- lines 527-590
2. `endpoints.py:send_message_endpoint()` -- lines 1199-1249
3. `endpoints.py:respond_to_permission_endpoint()` -- lines 1588-1615
4. `endpoints.py:cancel_thread_endpoint()` -- lines 1745-1771
5. `app.py:_create_dispatch_message_handler()._dispatch_message()` -- lines 486-521
6. `app.py:_create_dispatch_control_handler()._dispatch_control()` -- lines 570-593

Each repeats: `ensure_worker()` -> `circuit_breaker.pre_dispatch()` -> `worker_client.post("/dispatch", ...)` -> `circuit_breaker.record_success/failure()` -> `_mark_worker_connected()` -> error handling. This is ~50-80 lines per site.

**Proposed fix**: Extract `dispatch_to_worker(client, dispatch, circuit_breaker, spawner)` into `control/dispatch.py`.

### Health endpoint duplication

Two health endpoints with overlapping but divergent logic:
1. `endpoints.py:health()` -- lines 229-324 (aggregated health with DB probe)
2. `app.py:create_app().health_endpoint()` -- lines 1364-1479 (liveness with worker metadata)

They share: worker_connected check, circuit breaker state, spawner state, repair_summary, sqlite_fallback_diagnostics. But each adds unique fields.

**Proposed fix**: Extract shared health-data assembly into `control/health.py`.

### `_trace_headers()` duplication

Identical function in both `endpoints.py:137-146` and `app.py:268-272`.

**Proposed fix**: Single definition in a shared util (e.g., `api/_utils.py` or `control/tracing.py`).

### Thread metadata extraction pattern

The pattern `json.loads(thread.thread_metadata)` -> `meta.get("workspace_root")` appears in:
1. `endpoints.py:send_message_endpoint()` -- lines 1171-1176
2. `endpoints.py:respond_to_permission_endpoint()` -- lines 1525-1530
3. `app.py:_dispatch_message()` -- lines 460-465

**Proposed fix**: Utility method on thread model or in `thread/metadata_service.py`.

### Event relay orchestration duplication

The sequence `broadcast_to_thread` -> `sync_worker_event` -> `_handle_permission_event` -> `_handle_execution_state_event` -> `_handle_progress_event` -> `_handle_terminal_event` is duplicated verbatim in:
1. `internal.py:_relay_worker_event()` -- lines 509-550
2. `internal.py:receive_worker_event()` -- lines 664-698
3. `internal.py:receive_worker_event_batch()` -- lines 765-788

**Proposed fix**: Extract into a single `relay_event(thread_id, payload, cm, agg, session_factory)` function.

---

## 8. Proposed Split for endpoints.py

Target: No file exceeds ~400 lines. Each file owns one REST resource.

```
api/
  routes/
    __init__.py          -- re-export all routers
    health.py            -- GET /health (~30 lines after extracting business logic)
    threads.py           -- POST/GET/DELETE /threads, POST /threads/{id}/archive (~150 lines)
    thread_state.py      -- GET /threads/{id}/state (~50 lines after extracting snapshot logic)
    thread_messages.py   -- POST /threads/{id}/messages (~50 lines after extracting dispatch logic)
    thread_cancel.py     -- POST /threads/{id}/cancel (~50 lines after extracting dispatch logic)
    thread_metadata.py   -- GET /threads/{id}/metadata (~15 lines)
    teams.py             -- GET /teams, GET /team/status (~60 lines)
    permissions.py       -- POST /permissions/{id}/respond (~60 lines after extracting orchestration)
    admin.py             -- POST /admin/shutdown (~10 lines)
  dependencies.py        -- get_aggregator, get_checkpointer, get_services, etc. (~60 lines)
```

**Extraction targets** (business logic moves OUT of api/):

| Current location | Lines | Destination |
|-----------------|------:|-------------|
| `_process_metadata()` | ~45 | `thread/creation.py` |
| `_enrich_snapshot_from_state()` | ~200 | `thread/snapshot.py` |
| `_MinimalState` | ~6 | `thread/snapshot.py` |
| `_load_checkpoint_history_depth()` | ~10 | `thread/snapshot.py` |
| `_finalize_snapshot_replay_status()` | ~25 | `thread/snapshot.py` |
| Thread creation orchestration | ~150 | `thread/creation.py` |
| Dispatch-to-worker pattern | ~80 | `control/dispatch.py` |
| Permission response orchestration | ~200 | `control/permissions.py` |
| Team status assembly | ~40 | `team/status.py` |
| Health aggregation logic | ~60 | `control/health.py` |

**Estimated result**: endpoints.py splits into 10 route files averaging ~50 lines each, with ~800 lines of business logic extracted to Layer 1.

---

## 9. Proposed Split for app.py

Target: app.py becomes a thin application factory (~200 lines). All infrastructure and business logic extracted.

```
api/
  app.py               -- create_app(), main(), _lifespan() thin adapter (~200 lines)
  middleware.py         -- _CacheControlMiddleware (~20 lines)

control/
  circuit_breaker.py   -- WorkerCircuitBreaker (~80 lines)
  worker_management.py -- LazyWorkerSpawner, WorkerWatchdog, _spawn_worker,
                          _shutdown_worker_process, _tcp_port_ready,
                          _check_worker_health (~450 lines)
  dispatch.py          -- dispatch_to_worker(), _create_dispatch_message_handler(),
                          _create_dispatch_control_handler() (~200 lines)
  health.py            -- Health assembly logic, _build_sqlite_fallback_diagnostics (~150 lines)
  runtime.py           -- _runtime_dir, _worker_stderr_log_path, _read_log_tail,
                          _build_worker_restart_detail (~40 lines)
  startup.py           -- Lifespan init/shutdown sequences (~100 lines)

thread/
  diagnostics.py       -- _classify_missing_ws_thread (~80 lines)
```

**Extraction targets**:

| Current location | Lines | Destination |
|-----------------|------:|-------------|
| `WorkerCircuitBreaker` | 75 | `control/circuit_breaker.py` |
| `LazyWorkerSpawner` | 105 | `control/worker_management.py` |
| `WorkerWatchdog` | 175 | `control/worker_management.py` |
| `_spawn_worker()` | 115 | `control/worker_management.py` |
| `_shutdown_worker_process()` | 43 | `control/worker_management.py` |
| `_tcp_port_ready()` | 16 | `control/worker_management.py` |
| `_check_worker_health()` | 14 | `control/worker_management.py` |
| `_classify_missing_ws_thread()` | 76 | `thread/diagnostics.py` |
| `_ws_mark_failed_and_broadcast()` | 34 | `thread/lifecycle.py` or `control/dispatch.py` |
| `_create_dispatch_message_handler()` | 135 | `control/dispatch.py` |
| `_create_dispatch_control_handler()` | 69 | `control/dispatch.py` |
| Runtime path helpers | 36 | `control/runtime.py` |
| `_build_sqlite_fallback_diagnostics()` | 34 | `control/health.py` |
| Inline `health_endpoint()` | 115 | `control/health.py` |
| `_CacheControlMiddleware` | 19 | `api/middleware.py` |
| Lifespan init/shutdown sequences | ~130 | `control/startup.py` (init logic only; lifespan adapter stays) |

**Estimated result**: app.py drops from 1,507 lines to ~200 lines (create_app factory + thin lifespan adapter + main entry point).

---

## 10. internal.py Proposed Refactoring

Extract the 4 business-logic event handlers:

```
control/
  event_handlers.py    -- _handle_terminal_event, _handle_permission_event,
                          _handle_progress_event, _handle_execution_state_event,
                          relay_event() orchestrator (~400 lines)
```

internal.py drops from 812 to ~400 lines (route handlers + WS endpoint + validation + auth).

---

## 11. projection.py Proposed Relocation

Move entirely to `thread/projection.py` or merge into `thread/snapshot.py`. This module is 100% business logic with zero HTTP/WS awareness. It was placed in api/ because it was used by endpoints.py's snapshot assembly, but that snapshot assembly is itself business logic that should move to thread/.

---

## 12. Priority Ranking for Decomposition

1. **Extract infrastructure classes** (WorkerCircuitBreaker, LazyWorkerSpawner, WorkerWatchdog, spawn/shutdown helpers) -> `control/`. These are self-contained, well-interfaced, and block nothing. ~470 lines out of app.py.

2. **Extract dispatch orchestration** (6 duplicated sites) -> `control/dispatch.py`. Eliminates the largest duplication. ~300 lines consolidated.

3. **Extract snapshot/projection business logic** (_enrich_snapshot_from_state, projection.py) -> `thread/snapshot.py`. The largest single block of business logic (700+ lines combined).

4. **Extract event handler business logic** from internal.py -> `control/event_handlers.py`. ~400 lines.

5. **Extract health assembly** -> `control/health.py`. Eliminates duplication between two health endpoints. ~200 lines.

6. **Split endpoints.py routes** into per-resource files. Mechanical once business logic is extracted (step 3).

7. **Split app.py** into thin factory + middleware. Mechanical once infrastructure is extracted (step 1).

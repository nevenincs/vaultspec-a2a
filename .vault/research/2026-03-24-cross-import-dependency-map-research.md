---
tags:
  - '#research'
  - '#entry-point-layer'
date: '2026-03-24'
modified: '2026-03-24'
related:
  - '[[2026-03-24-entry-point-decomposition-adr]]'
  - '[[2026-03-24-api-module-research]]'
  - '[[2026-03-24-worker-cli-research]]'
---

# `entry-point-layer` research: `cross-import-dependency-map`

Full Layer 2 cross-import and dependency analysis for `api/`, `worker/`, `cli/`, `protocols/`. Identifies boundary violations and determines decomposition order.

---

## 1. Full Import Matrix

### Legend

| Category | Description |
|---|---|
| **L1** | Layer 1 core: `thread/`, `context/`, `team/`, `graph/`, `streaming/`, `lifecycle/` |
| **L2-EP** | Layer 2 entry points: `api/`, `worker/`, `cli/`, `protocols/` |
| **L2-IS** | Layer 2 infra services: `database/`, `providers/`, `telemetry/`, `control/`, `workspace/`, `utils/` |
| **EXT** | External third-party packages |

---

### `api/` Module

| File | L1 Imports | L2-EP Imports | L2-IS Imports | External |
|---|---|---|---|---|
| `app.py` | `streaming.aggregator` | `(self: .endpoints, .internal, .websocket, .schemas)` | `control.config`, `database.checkpoints`, `database.crud`, `database.migrations`, `database.reconciliation`, `database.session`, `telemetry`, `telemetry.aggregator_hook`, `utils.asyncio_compat` | `fastapi`, `httpx`, `uvicorn`, `starlette`, `opentelemetry`, `sqlalchemy` |
| `endpoints.py` | `context.metadata`, `context.preamble`, `graph.compiler`, `streaming.aggregator`, `team.team_config`, `thread.errors` | `(self: .projection, .schemas.*)` | `control.config`, `database.checkpoints`, `database.crud`, `database.session` | `fastapi`, `httpx`, `langchain_core`, `langgraph`, `opentelemetry`, `sqlalchemy` |
| `event_adapter.py` | `graph.events` | `(self: .schemas.enums, .schemas.events)` | _(none)_ | `dataclasses` |
| `internal.py` | _(none)_ | `(self: .schemas.internal)` | `control.config` | `fastapi`, `datetime` |
| `projection.py` | _(none)_ | `(self: .schemas.enums, .schemas.snapshots)` | `database.crud` | `json`, `dataclasses` |
| `websocket.py` | `streaming.aggregator` | `(self: .event_adapter, .schemas.commands, .schemas.enums, .schemas.events)` | `control.config`, `telemetry.instrumentation`, `telemetry.middleware` | `pydantic`, `starlette` |
| `auth.py` | _(none)_ | _(none)_ | _(none)_ | `fastapi` |
| `__init__.py` | _(none)_ | `(self: .schemas)` | _(none)_ | _(none)_ |
| `schemas/base.py` | _(none)_ | `(self: .enums)` | _(none)_ | `pydantic` |
| `schemas/enums.py` | `graph.enums` (re-exports) | _(none)_ | _(none)_ | `enum` |
| `schemas/events.py` | `graph.enums` | `(self: .enums)` | _(none)_ | `pydantic` |
| `schemas/commands.py` | _(none)_ | `(self: .enums)` | _(none)_ | `pydantic` |
| `schemas/rest.py` | `context.metadata`, `graph.enums` | `(self: .enums, .events)` | _(none)_ | `pydantic` |
| `schemas/snapshots.py` | `graph.enums` | `(self: .enums)` | _(none)_ | `pydantic` |
| `schemas/internal.py` | _(none)_ | _(none)_ | `control.config` | `pydantic` |
| `schemas/__init__.py` | _(none)_ | `(self: re-exports all sub-schemas)` | _(none)_ | _(none)_ |

### `worker/` Module

| File | L1 Imports | L2-EP Imports | L2-IS Imports | External |
|---|---|---|---|---|
| **`app.py`** | _(none)_ | **`api.schemas.internal`** (DispatchRequest, DispatchResponse) | `control.config`, `database.checkpoints`, `telemetry`, `utils.asyncio_compat`, `utils.enums` | `fastapi`, `httpx`, `uvicorn`, `anyio` |
| **`executor.py`** | `graph.compiler`, `streaming.aggregator`, `team.team_config`, `thread.errors` | **`api.event_adapter`** (sequenced_to_dict), **`api.schemas.internal`** (DispatchRequest, ExecutionStateProjectionPayload, ExecutionTaskProjectionPayload) | `control.config`, `telemetry` | `langchain_core`, `langgraph` |
| `ipc.py` | _(none)_ | _(none)_ | `control.config` | `httpx`, `anyio`, `fastapi.encoders` |
| `__init__.py` | _(none)_ | `(self: .app, .executor, .ipc)` | _(none)_ | _(none)_ |
| `__main__.py` | _(none)_ | `(self: .app)` | _(none)_ | _(none)_ |

### `cli/` Module

| File | L1 Imports | L2-EP Imports | L2-IS Imports | External |
|---|---|---|---|---|
| `__init__.py` | _(none)_ | `(self: ._util, ._agent, ._team)` | _(none)_ | `click` |
| `_agent.py` | _(none)_ | _(none)_ | _(none)_ | `click`, `pathlib` |
| `_team.py` | _(none)_ | _(none)_ | `control.config` (lazy, in `_watch_async`) | `click`, `httpx`, `websockets` |
| `_util.py` | _(none)_ | _(none)_ | `control.config` (lazy) | `click`, `httpx` |

### `protocols/` Module

| File | L1 Imports | L2-EP Imports | L2-IS Imports | External |
|---|---|---|---|---|
| `__init__.py` | _(none)_ | `(self: .mcp)` | _(none)_ | _(none)_ |
| `mcp/__init__.py` | _(none)_ | `(self: .server)` | _(none)_ | _(none)_ |
| `mcp/server.py` | _(none)_ | _(none)_ | `control.config` | `httpx`, `mcp`, `pydantic` |
| `mcp/__main__.py` | _(none)_ | `(self: .server)` | `control.config` | `argparse`, `asyncio` |
| `a2a/__init__.py` | _(none)_ | _(none)_ | _(none)_ | _(none)_ |
| `adapter/__init__.py` | _(none)_ | _(none)_ | _(none)_ | _(none)_ |

---

## 2. Violation List

### VIOLATION V-01: `worker/app.py` imports from `api/schemas/internal.py`

- **File**: `src/vaultspec_a2a/worker/app.py`, line 34
- **Import**: `from ..api.schemas.internal import DispatchRequest, DispatchResponse`
- **Severity**: HIGH
- **Nature**: Entry point `worker/` imports from entry point `api/`. The IPC types `DispatchRequest` and `DispatchResponse` are used as the FastAPI request/response models for the `/dispatch` endpoint.

### VIOLATION V-02: `worker/executor.py` imports from `api/schemas/internal.py`

- **File**: `src/vaultspec_a2a/worker/executor.py`, lines 25-29
- **Import**: `from ..api.schemas.internal import DispatchRequest, ExecutionStateProjectionPayload, ExecutionTaskProjectionPayload`
- **Severity**: HIGH
- **Nature**: Entry point `worker/` imports from entry point `api/`. The executor uses `DispatchRequest` as the dispatch command type, and the `ExecutionState*` payloads as IPC message shapes.

### VIOLATION V-03: `worker/executor.py` imports from `api/event_adapter.py`

- **File**: `src/vaultspec_a2a/worker/executor.py`, line 24
- **Import**: `from ..api.event_adapter import sequenced_to_dict`
- **Severity**: MEDIUM
- **Nature**: Entry point `worker/` imports from entry point `api/`. The `sequenced_to_dict` function serializes `SequencedEvent` objects to plain dicts for bridge relay. This is a serialization concern that should live in a shared layer.

### Summary

| Violation | Source | Target | Types Imported | Severity |
|---|---|---|---|---|
| V-01 | `worker/app.py:34` | `api/schemas/internal` | `DispatchRequest`, `DispatchResponse` | HIGH |
| V-02 | `worker/executor.py:25-29` | `api/schemas/internal` | `DispatchRequest`, `ExecutionStateProjectionPayload`, `ExecutionTaskProjectionPayload` | HIGH |
| V-03 | `worker/executor.py:24` | `api/event_adapter` | `sequenced_to_dict` | MEDIUM |

**No circular dependencies exist** -- all violations are one-directional (`worker` -> `api`). The `cli/` and `protocols/` modules are clean: they communicate with the gateway exclusively via HTTP and have zero cross-entry-point imports.

---

## 3. Dependency Graph

```
                        Layer 1 Core
    ┌──────────────────────────────────────────────┐
    │  thread/  context/  team/  graph/            │
    │  streaming/  lifecycle/                      │
    └──────────────────────────────────────────────┘
                         ▲
                         │ (allowed)
                         │
    ┌──────────────────────────────────────────────┐
    │               Layer 2 Infra                  │
    │  control/  database/  providers/  telemetry/ │
    │  utils/  workspace/                          │
    └──────────────────────────────────────────────┘
                         ▲
                         │ (allowed)
          ┌──────────────┼──────────────┬──────────────┐
          │              │              │              │
    ┌─────┴─────┐  ┌─────┴─────┐  ┌────┴────┐  ┌─────┴──────┐
    │   api/    │  │  worker/  │  │  cli/   │  │ protocols/ │
    │ (gateway) │  │           │  │         │  │   (mcp)    │
    └───────────┘  └───────────┘  └─────────┘  └────────────┘
          ▲              │
          │   FORBIDDEN  │
          └──────────────┘
              V-01, V-02, V-03

          worker/ ──[V-01]──> api/schemas/internal  (DispatchRequest, DispatchResponse)
          worker/ ──[V-02]──> api/schemas/internal  (ExecutionStateProjectionPayload, etc.)
          worker/ ──[V-03]──> api/event_adapter     (sequenced_to_dict)
```

### Mermaid Diagram

```mermaid
graph TD
    subgraph "Layer 1 Core"
        thread["thread/"]
        context["context/"]
        team["team/"]
        graph["graph/"]
        streaming["streaming/"]
        lifecycle["lifecycle/"]
    end

    subgraph "Layer 2 Infra Services"
        control["control/"]
        database["database/"]
        providers["providers/"]
        telemetry["telemetry/"]
        utils["utils/"]
    end

    subgraph "Layer 2 Entry Points"
        api["api/ (gateway)"]
        worker["worker/"]
        cli["cli/"]
        protocols["protocols/"]
    end

    api --> streaming
    api --> context
    api --> team
    api --> graph
    api --> thread
    api --> control
    api --> database
    api --> telemetry
    api --> utils

    worker --> graph
    worker --> streaming
    worker --> team
    worker --> thread
    worker --> control
    worker --> database
    worker --> telemetry
    worker --> utils
    worker --> providers

    cli --> control

    protocols --> control

    worker -.->|"VIOLATION"| api
```

---

## 4. Decomposition Order

### Phase 0: Extract Shared IPC Types (PREREQUISITE)

**Rationale**: All three violations stem from shared IPC message types (`DispatchRequest`, `DispatchResponse`, `ExecutionStateProjectionPayload`, `ExecutionTaskProjectionPayload`) and one serialization helper (`sequenced_to_dict`). These must move to a neutral location before any entry point can be decomposed independently.

**Action**:
1. Create `src/vaultspec_a2a/ipc/` (new Layer 2 infra service module) containing:
   - `ipc/schemas.py` -- move `DispatchRequest`, `DispatchResponse`, `ExecutionStateProjectionPayload`, `ExecutionTaskProjectionPayload`, `HeartbeatMessage`, `WorkerEventEnvelope` from `api/schemas/internal.py`
   - `ipc/serializers.py` -- move `sequenced_to_dict` from `api/event_adapter.py`
2. Update imports in `worker/app.py`, `worker/executor.py`, `api/app.py`, `api/endpoints.py`, `api/internal.py`, `api/schemas/__init__.py` to point at `ipc/`.
3. Leave `api/schemas/internal.py` as a re-export shim temporarily, or delete it per the "no compat shims" rule.

**Unblocks**: All subsequent phases can proceed independently.

### Phase 1: `protocols/` (SELF-CONTAINED -- parallel with Phase 2-4)

**Rationale**: `protocols/` is already clean. Zero cross-entry-point imports. Only depends on `control.config` and external HTTP calls. The `a2a/` and `adapter/` sub-modules are stubs.

**Action**: No structural changes needed. Can be decomposed (if desired) without touching any other entry point.

### Phase 2: `cli/` (SELF-CONTAINED -- parallel with Phase 1, 3-4)

**Rationale**: `cli/` is already clean. No cross-entry-point imports. Communicates with the gateway exclusively via HTTP. Only infra dependency is `control.config` (for port/URL resolution).

**Action**: No structural changes needed.

### Phase 3: `worker/` (AFTER Phase 0)

**Rationale**: Once IPC types are extracted (Phase 0), worker/ has zero cross-entry-point imports. The remaining L1 dependencies (`graph.compiler`, `streaming.aggregator`, `team.team_config`, `thread.errors`) are correct and expected.

**Decomposition targets** (if modules exceed 1000 lines):
- `executor.py` (983 lines): Close to threshold. Consider splitting graph compilation (`_compile_graph`, `_get_or_compile_graph`) from graph execution (`_handle_ingest`, `_handle_resume`) if it grows.

### Phase 4: `api/` (AFTER Phase 0 -- LARGEST, most dependents)

**Rationale**: `api/` is the most complex entry point. After Phase 0 removes the inbound dependency from `worker/`, the `api/` can be decomposed without risk of breaking the worker.

**Decomposition targets**:
- `endpoints.py` (1883 lines): MUST split. Candidates:
  - Thread CRUD endpoints (create, list, delete, archive, cancel)
  - Thread state/snapshot endpoints (get state, reconnection)
  - Permission endpoints (respond, list pending)
  - Team endpoints (status, presets)
  - Health endpoint
  - Internal dispatch helpers
- `app.py` (1507 lines): MUST split. Candidates:
  - `WorkerCircuitBreaker` -> `api/circuit_breaker.py` or `ipc/circuit_breaker.py`
  - `LazyWorkerSpawner` -> `api/spawner.py`
  - `WorkerWatchdog` -> `api/watchdog.py`
  - `_CacheControlMiddleware` -> `api/middleware.py`
  - WS dispatch handlers -> `api/ws_dispatch.py`
  - Worker spawn helpers -> `api/worker_spawn.py`
  - Lifespan -> stays in `app.py` (reduced to ~100 lines)

---

## 5. Inline Class Audit: `api/app.py`

### 5.1 `WorkerCircuitBreaker` (lines 159-234)

**Purpose**: Track worker dispatch health and reject requests when the worker is down. Implements a standard three-state circuit breaker pattern (CLOSED -> OPEN -> HALF_OPEN -> CLOSED).

**Constructor**:
```python
__init__(self, failure_threshold: int, recovery_timeout: float) -> None
```

**Properties**:
| Property | Type | Description |
|---|---|---|
| `state` | `str` | Current circuit state (`"closed"`, `"open"`, `"half_open"`). Auto-promotes from `"open"` to `"half_open"` after `recovery_timeout` seconds. |

**Methods**:
| Method | Signature | Description |
|---|---|---|
| `pre_dispatch()` | `() -> None` | Call before each dispatch. Raises `HTTPException(503)` if state is `"open"`. |
| `record_success()` | `() -> None` | Record successful dispatch. Resets failure count and closes circuit. |
| `record_failure()` | `() -> None` | Record failed dispatch. Opens circuit if consecutive failures reach threshold. |
| `force_open()` | `() -> None` | Force circuit open immediately (used by watchdog on crash). |

**Internal state**: `_failure_threshold: int`, `_recovery_timeout: float`, `_consecutive_failures: int`, `_state: str`, `_opened_at: float`.

**Imports**: `fastapi.HTTPException` (lazy, inside `pre_dispatch`), `time.monotonic`, `logging`.

**Business logic**: NONE. Pure infrastructure pattern. No domain concepts, no database access, no L1 imports.

**Verdict**: Safe to extract to `api/circuit_breaker.py` or `ipc/circuit_breaker.py`.

---

### 5.2 `LazyWorkerSpawner` (lines 804-908)

**Purpose**: Defer worker process spawn to first dispatch instead of gateway startup. Read-only endpoints work immediately without waiting for the worker.

**Constructor**:
```python
__init__(self, worker_url: str, worker_port: int, auto_spawn: bool) -> None
```

**Properties**:
| Property | Type | Description |
|---|---|---|
| `spawned` | `bool` | Whether the worker has been spawned or detected as already running. |
| `process` | `subprocess.Popen[bytes] \| None` | The worker subprocess handle, if we spawned it. |
| `stderr_log_path` | `Path \| None` | The worker stderr log path for gateway-managed spawns. |
| `worker_url` | `str` | The worker's base URL. |
| `worker_port` | `int` | The worker's port number. |

**Methods**:
| Method | Signature | Description |
|---|---|---|
| `ensure_worker()` | `async () -> None` | Spawn the worker if not already running. No-op after first call. Uses `asyncio.Lock` for double-checked locking. |
| `replace_process()` | `(process: Popen \| None) -> None` | Replace the worker process handle (used by watchdog after restart). |
| `shutdown()` | `async () -> None` | Shut down the worker process if we spawned it. |

**Internal state**: `_worker_url`, `_worker_port`, `_auto_spawn`, `_process`, `_stderr_log_path`, `_spawned`, `_lock: asyncio.Lock`.

**Dependencies**: Calls module-level helpers `_check_worker_health()`, `_spawn_worker()`, `_shutdown_worker_process()`. These helpers depend on `settings`, `subprocess`, `asyncio`, `httpx`.

**Business logic**: NONE. Pure process lifecycle management. No domain concepts, no database access, no L1 imports.

**Verdict**: Safe to extract to `api/spawner.py`. Must also move the helper functions `_spawn_worker()`, `_shutdown_worker_process()`, `_check_worker_health()`, `_tcp_port_ready()`, `_worker_stderr_log_path()`, `_read_log_tail()`, `_build_worker_restart_detail()`, `_runtime_dir()`.

---

### 5.3 `WorkerWatchdog` (lines 915-1089)

**Purpose**: Background task monitoring worker health and auto-restarting on crash. Uses exponential backoff restarts and coordinates with the circuit breaker.

**Constructor**:
```python
__init__(self, spawner: LazyWorkerSpawner, circuit_breaker: WorkerCircuitBreaker, app_state: Any) -> None
```

**Properties**: None (reads/writes `app_state` attributes directly).

**Methods**:
| Method | Signature | Description |
|---|---|---|
| `run()` | `async () -> None` | Main watchdog loop. Runs until cancelled. Polls every `watchdog_poll_interval_seconds`. |
| `_attempt_restart()` | `async () -> tuple[bool, int]` | Try to restart the worker with exponential backoff. Returns `(succeeded, attempts)`. |
| `_heartbeat_stale()` | `() -> bool` | Check if last heartbeat exceeds timeout threshold. |
| `_process_crashed()` | `() -> bool` | Check if worker process has exited unexpectedly. |
| `_probe_worker_ready()` | `async () -> bool` | HTTP health probe against the worker. |
| `_mark_restart_started()` | `(reason: str, detail: str \| None) -> None` | Latch restart metadata on `app_state`. |
| `_mark_restart_finished()` | `(succeeded: bool, attempts: int) -> None` | Record terminal outcome of restart cycle. |

**State machine on `app_state`**: `worker_status` (`pending` -> `up` -> `restarting` -> `up` | `down`), plus `worker_restart_count`, `worker_last_restart_reason`, `worker_last_restart_detail`, `worker_last_restart_started_at`, `worker_last_restart_completed_at`, `worker_last_restart_succeeded`, `worker_last_restart_attempts`, `worker_stderr_log_path`.

**Dependencies**: `LazyWorkerSpawner`, `WorkerCircuitBreaker`, `settings`, `_check_worker_health()`, `_spawn_worker()`, `_shutdown_worker_process()`, `_build_worker_restart_detail()`.

**Business logic**: NONE. Pure infrastructure: process supervision, health monitoring, exponential backoff restart. No domain concepts, no database access, no L1 imports.

**Verdict**: Safe to extract to `api/watchdog.py`. Depends on `LazyWorkerSpawner` and `WorkerCircuitBreaker`, so those must be extractable first (or extracted to the same module).

---

## 6. Additional Observations

### `api/schemas/internal.py` imports `control.config`

The `DispatchRequest` model has a field `recursion_limit` with `default_factory=lambda: settings.graph_recursion_limit`. This creates a runtime dependency on `control.config.settings` at field-default evaluation time. When this file moves to `ipc/`, this dependency must be preserved (it's an L2-IS import, which is allowed).

### `api/event_adapter.py` has dual consumers

Both `api/websocket.py` (via `sequenced_to_wire`) and `worker/executor.py` (via `sequenced_to_dict`) consume this module. The `sequenced_to_dict` function (lines 266-270) is a simple 3-line serializer. Moving it to `ipc/serializers.py` is trivial. The `sequenced_to_wire` / `domain_to_wire` functions remain in `api/event_adapter.py` since they produce API-layer wire-protocol models.

### `api/internal.py` has late-bound database imports

All database/crud imports in `internal.py` are inside function bodies (lines 74-83, 191-206, 331-343, 407). This is intentional to avoid circular dependencies at module level. When decomposing `api/`, these can stay as-is.

### `cli/_agent.py` uses `Path` heuristic for preset discovery

`_agent.py` line 27: `presets_dir = Path(__file__).resolve().parent.parent / "core" / "presets" / "agents"`. This references the old `core/` directory. After the Layer 1 decomposition, presets may have moved. This is a latent bug but outside the scope of this analysis (it's a file-path assumption, not an import violation).

### `cli/_team.py` `_watch_async` has a lazy import of `control.config`

Line 478: `from ..control.config import settings`. This is inside a function body, so it's a lazy import. It's valid (L2-IS), but worth noting for completeness.

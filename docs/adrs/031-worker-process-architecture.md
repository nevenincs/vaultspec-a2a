---
adr_id: 031
title: Worker Process Architecture
date: 2026-03-04
status: Proposed
related:
  - docs/adrs/007-tech-stack-deployment.md
  - docs/adrs/010-observability-telemetry-integration.md
  - docs/adrs/017-containerization-strategy.md
  - docs/adrs/021-persistent-task-queue-schema.md
---

# ADR-031: Worker Process Architecture

**Date:** 2026-03-04
**Status:** Proposed

## 1. Context & Problem Statement

The VaultSpec backend has two distinct runtime concerns that benefit from
process-level separation:

- **Control surface** (`lib/api/`): Handles REST and WebSocket connections,
  thread lifecycle, permission responses, and SSE event streaming to the
  frontend. Latency-sensitive; must stay responsive even during long LLM calls.
- **Graph execution** (`lib/worker/`): Runs LangGraph agent graphs, invokes LLM
  providers, streams events back to the control surface. CPU- and I/O-bound;
  a single run can last minutes and spawn multiple async tasks.

Running both in a single process risks LLM execution saturating the event loop
and causing connection handler latency spikes. Process-level isolation also
enables independent scaling: the worker can be scaled horizontally while the
control surface remains a singleton (SQLite WAL limitation).

This ADR ratifies the implemented worker process design that was not covered by
an existing ADR (referenced in `lib/worker/app.py` and `lib/worker/executor.py`
as "ADR-019" which is incorrect — ADR-019 covers TeamState/SDD fields).

## 2. Decision

### 2.1 Process Topology

```
┌──────────────────────────────────────┐      ┌────────────────────────┐
│  Control Surface (lib/api/)          │      │  Worker (lib/worker/)  │
│  FastAPI app  :8000                  │ HTTP │  FastAPI app  :8001     │
│  REST + WebSocket endpoints          │─────▶│  /dispatch endpoint    │
│  Permission response handling        │      │  /health endpoint      │
│  Event fan-out to frontend           │◀─────│  Heartbeat POST :8000  │
└──────────────────────────────────────┘      └────────────────────────┘
         ▲                                              │
         │               SQLite WAL (shared)           │
         └─────────────────────────────────────────────┘
```

The control surface dispatches a graph run by POSTing a `DispatchRequest` to
the worker's `/dispatch` endpoint. The worker executes the graph and forwards
`ServerEvent` payloads back to the control surface via `WorkerBridge`.

### 2.2 IPC Protocol — HTTP over loopback

Communication between processes uses plain HTTP over `127.0.0.1`:

- **Control → Worker**: `POST /dispatch` (`DispatchRequest` JSON body)
- **Worker → Control**: `POST /api/internal/events` (`ServerEvent` JSON body)
- **Worker → Control**: `POST /api/internal/heartbeat` (empty body, periodic)

Both directions use `httpx.AsyncClient`. The internal API is authenticated via
`VAULTSPEC_INTERNAL_TOKEN` bearer token (optional in development).

This design was chosen over alternatives (see §4) because:
- HTTP is language-agnostic and requires no shared memory or named pipes.
- The existing FastAPI + Pydantic schema layer is reused for both sides.
- The worker can be deployed on a separate host (future scaling) with only a
  URL change.

### 2.3 Shared SQLite Checkpointer (WAL Mode)

Both the control surface and the worker open the **same SQLite database file**
(`settings.database_path`) using `AsyncSqliteSaver` with WAL mode enabled.

WAL mode allows one writer and multiple concurrent readers — the control surface
reads checkpoint state for `/api/threads/{id}/state` queries while the worker
writes checkpoints during graph execution.

**Constraint**: SQLite WAL mode breaks across NFS or distributed file systems.
Both processes must run on the same host or share a local filesystem mount.
This is consistent with the single-container production constraint in ADR-017.

### 2.4 Auto-Spawn vs. Standalone Modes

The control surface supports two worker deployment modes:

**Auto-spawn** (`VAULTSPEC_AUTO_SPAWN_WORKER=true`, default):
- Control surface spawns the worker as a child process via `subprocess.Popen`
  on startup.
- Worker inherits environment variables from the control surface process.
- Worker stdout/stderr is piped to the control surface logs.
- Suitable for development and single-host production.

**Standalone** (`VAULTSPEC_AUTO_SPAWN_WORKER=false`):
- Worker is started independently (e.g., Docker service, systemd unit).
- Control surface connects via `VAULTSPEC_WORKER_URL`.
- Suitable for Docker Compose multi-container deployments (ADR-017) and
  horizontal scaling.

### 2.5 Worker Module Structure

```
lib/worker/
  __init__.py       Public facade: exports WorkerApp, Executor, WorkerBridge
  __main__.py       Entry point: python -m lib.worker
  app.py            FastAPI application factory + lifespan (checkpointer, bridge, executor)
  executor.py       Executor class: graph compilation, EventAggregator, run dispatch
  ipc.py            WorkerBridge: httpx client for event forwarding and heartbeats
  health.py         /health endpoint implementation
  tests/
    test_executor.py  Unit tests for Executor (MemorySaver, FakeListChatModel)
```

### 2.6 Executor Responsibilities

`Executor` (`lib/worker/executor.py`) is the central graph execution engine:

- Maintains a `dict[str, CompiledStateGraph]` mapping `thread_id` to compiled
  graph (lazy compilation on first dispatch).
- Manages an `asyncio.Lock` per thread to prevent concurrent graph execution
  on the same thread (checkpointer race prevention).
- Enforces a `_DEFAULT_MAX_CONCURRENT_THREADS = 5` concurrent execution cap.
- Owns the `EventAggregator` consumer loop: calls `graph.astream()` and
  forwards events to `WorkerBridge`.
- Handles `Command` resume for interrupt flows (permission responses, plan
  approval).

### 2.7 Heartbeat Protocol

The worker sends a heartbeat `POST /api/internal/heartbeat` to the control
surface every 30 seconds. The control surface tracks the last-seen timestamp
per worker ID. If the heartbeat is missed for 90 seconds, the control surface
logs a warning (future: circuit-break new dispatches until the worker reconnects).

The heartbeat payload includes:
- `worker_id`: random hex assigned at startup
- `active_threads`: count of currently executing graph runs
- `uptime_seconds`: worker process uptime

## 3. Consequences

### Positive

- LLM execution is isolated from connection handler latency. Long-running graph
  runs do not block REST or WebSocket response times.
- The worker can be restarted without dropping frontend connections (the control
  surface buffers the SSE stream until the worker reconnects).
- Auto-spawn mode requires zero additional configuration for development.
- Standalone mode enables Docker Compose multi-service deployments and future
  horizontal worker scaling.

### Negative / Trade-offs

- HTTP IPC adds latency vs. in-process function calls (~1ms per event over
  loopback, acceptable for agent timescales).
- SQLite WAL mode limits the worker to single-host deployment. PostgreSQL
  migration (future) would remove this constraint.
- Auto-spawn mode creates a parent-child process relationship. The child worker
  inherits all environment variables and file descriptors — a potential
  security concern if secrets are in environment.
- Two processes means two log streams. Structured logging with `worker_id`
  correlation is required for coherent debugging.

## 4. Rejected Alternatives

### In-process execution (single FastAPI app)

The original implementation ran graph execution directly in the control surface
process via `asyncio.create_task()`. Rejected: long LLM calls saturated the
event loop, causing 10–30s latency spikes on unrelated REST calls during active
runs.

### Message queue (Redis/RabbitMQ)

HTTP IPC provides the same decoupling with less infrastructure. A message queue
would require an additional service, persistence configuration, and consumer
group management. Overkill for the current single-worker architecture.

### Unix domain sockets or named pipes

Platform-specific (Windows compatibility required). HTTP over loopback is
cross-platform and already implemented in the existing httpx stack.

### gRPC

Protocol Buffers schema management adds significant tooling overhead for a
two-service system with an existing Pydantic schema layer. HTTP+JSON reuses the
existing `ServerEvent`/`DispatchRequest` schemas without code generation.

## 5. Implementation Constraints

- `lib/worker/` must remain independent of `lib/api/` internals. It may import
  from `lib/api/schemas/` (shared schema types) but NOT from `lib/api/endpoints`,
  `lib/api/websocket`, or `lib/api/app`. The dependency arrow is:
  `lib/api/` → `lib/worker/` (for spawn), `lib/worker/` → `lib/api/schemas/`.
- The worker's internal HTTP port (`VAULTSPEC_WORKER_PORT=8001`) must not
  conflict with the control surface port (`VAULTSPEC_PORT=8000`).
- `VAULTSPEC_INTERNAL_TOKEN` must be set to a non-empty value in production.
  The control surface and worker must share the same token value.
- `Executor.ingest()` must use `asyncio.Lock` per thread to prevent concurrent
  graph execution on the same checkpointer thread_id.
- The `_DEFAULT_MAX_CONCURRENT_THREADS` cap must be enforced before accepting
  new dispatches. The worker must return HTTP 429 when the cap is reached.
- Graph compilation errors must be caught and returned as `HTTP 422` from the
  `/dispatch` endpoint — not silently logged.

## 6. Module Hierarchy

```
lib/
  worker/
    __init__.py     EXPORTS: WorkerApp, Executor, WorkerBridge (ADR-009 facade)
    app.py          WorkerApp = FastAPI; create_worker_app() factory; main() entry
    executor.py     Executor class; graph compilation + EventAggregator + run lifecycle
    ipc.py          WorkerBridge; httpx.AsyncClient; event forward + heartbeat
    health.py       /health endpoint; returns {"status": "ok", "active_threads": N}
    __main__.py     python -m lib.worker entry point
```

## 7. References

- `lib/worker/app.py` — FastAPI application + lifespan (checkpointer, bridge, executor)
- `lib/worker/executor.py` — Executor class (graph compilation, EventAggregator, run dispatch)
- `lib/worker/ipc.py` — WorkerBridge (httpx client for event forwarding)
- `lib/core/config.py` — `settings.worker_url`, `settings.worker_port`, `settings.auto_spawn_worker`
- [ADR-007](007-tech-stack-deployment.md) — FastAPI + SQLite tech stack rationale
- [ADR-010](010-observability-telemetry-integration.md) — OTel for worker spans
- [ADR-017](017-containerization-strategy.md) — Docker Compose multi-service deployment
- [ADR-021](021-persistent-task-queue-schema.md) — task queue integration with Executor

---
tags:
- '#adr'
- '#worker-process-architecture'
date: 2026-03-04
related:
- '[[2026-02-26-tech-stack-deployment-adr]]'
- '[[2026-02-26-observability-telemetry-integration-adr]]'
- '[[2026-02-28-containerization-strategy-adr]]'
- '[[2026-03-03-persistent-task-queue-schema-adr]]'
- '[[2026-03-31-docs-vault-migration-research]]'
---

# `worker-process-architecture` adr: `adr-25` | (**status:** `accepted`)

## Migration Note

This ADR was migrated from the legacy pre-pipeline documentation tree during the issue #19 cleanup so that the repository no longer depends on the removed `docs/` directory.

- Original ADR number: `ADR-25`
- Original title: `Worker Process Architecture`
- Legacy status at migration time: `Accepted`

## Original ADR

## ADR-031: Worker Process Architecture

**Date:** 2026-03-04
**Status:** Accepted

## 1. Context & Problem Statement

The VaultSpec backend has two distinct runtime concerns that benefit from
process-level separation:

- **Gateway** (`src/vaultspec_a2a/api/`): Handles REST and WebSocket connections,
  thread lifecycle, permission responses, and SSE event streaming to the
  frontend. Latency-sensitive; must stay responsive even during long LLM calls.
- **Graph execution** (`src/vaultspec_a2a/worker/`): Runs LangGraph agent graphs, invokes LLM
  providers, streams events back to the gateway. CPU- and I/O-bound;
  a single run can last minutes and spawn multiple async tasks.

Running both in a single process risks LLM execution saturating the event loop
and causing connection handler latency spikes. Process-level isolation also
enables independent scaling: the worker can be scaled horizontally while the
gateway remains a singleton (SQLite WAL limitation).

This ADR ratifies the implemented worker process design that was not covered by
an existing ADR (referenced in `src/vaultspec_a2a/worker/app.py` and `src/vaultspec_a2a/worker/executor.py`
as "ADR-019" which is incorrect — ADR-019 covers TeamState/SDD fields).

## 2. Decision

### 2.1 Process Topology

```text
┌──────────────────────────────────────┐      ┌────────────────────────┐
│  Gateway (src/vaultspec_a2a/api/)          │      │  Worker (src/vaultspec_a2a/worker/)  │
│  FastAPI app  :8000                  │ HTTP │  FastAPI app  :8001     │
│  REST + WebSocket endpoints          │─────▶│  /dispatch endpoint    │
│  Permission response handling        │      │  /health endpoint      │
│  Event fan-out to frontend           │◀─────│  Heartbeat POST :8000  │
└──────────────────────────────────────┘      └────────────────────────┘
         ▲                                              │
         │               SQLite WAL (shared)           │
         └─────────────────────────────────────────────┘
```text

The gateway dispatches a graph run by POSTing a `DispatchRequest` to
the worker's `/dispatch` endpoint. The worker executes the graph and forwards
`ServerEvent` payloads back to the gateway via `WorkerBridge`.

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

Both the gateway and the worker open the **same SQLite database file**
(`settings.database_path`) using `AsyncSqliteSaver` with WAL mode enabled.

WAL mode allows one writer and multiple concurrent readers — the gateway
reads checkpoint state for `/api/threads/{id}/state` queries while the worker
writes checkpoints during graph execution.

**Constraint**: SQLite WAL mode breaks across NFS or distributed file systems.
Both processes must run on the same host or share a local filesystem mount.
This is consistent with the single-container production constraint in ADR-017.

### 2.4 Auto-Spawn vs. Standalone Modes

The gateway supports two worker deployment modes:

**Auto-spawn** (`VAULTSPEC_AUTO_SPAWN_WORKER=true`, default):

- Gateway spawns the worker as a child process via `subprocess.Popen`
  on startup.
- Worker inherits environment variables from the gateway process.
- Worker stdout/stderr is piped to the gateway logs.
- Suitable for development and single-host production.

**Standalone** (`VAULTSPEC_AUTO_SPAWN_WORKER=false`):

- Worker is started independently (e.g., Docker service, systemd unit).
- Gateway connects via `VAULTSPEC_WORKER_URL`.
- Suitable for Docker Compose multi-container deployments (ADR-017) and
  horizontal scaling.

### 2.5 Worker Module Structure

```text
src/vaultspec_a2a/worker/
  __init__.py       Public facade: exports WorkerApp, Executor, WorkerBridge
  __main__.py       Entry point: python -m lib.worker
  app.py            FastAPI application factory + lifespan (checkpointer, bridge, executor)
  executor.py       Executor class: graph compilation, EventAggregator, run dispatch
  ipc.py            WorkerBridge: httpx client for event forwarding and heartbeats
  health.py         /health endpoint implementation
  tests/
    test_executor.py  Unit tests for Executor (MemorySaver, FakeListChatModel)
```text

### 2.6 Executor Responsibilities

`Executor` (`src/vaultspec_a2a/worker/executor.py`) is the central graph execution engine:

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
surface every 30 seconds. The gateway tracks the last-seen timestamp
per worker ID. If the heartbeat is missed for 90 seconds, the gateway
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

The original implementation ran graph execution directly in the gateway
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

- `src/vaultspec_a2a/worker/` must remain independent of `src/vaultspec_a2a/api/` internals. It may import
  from `src/vaultspec_a2a/api/schemas/` (shared schema types) but NOT from `src/vaultspec_a2a/api/endpoints`,
  `src/vaultspec_a2a/api/websocket`, or `src/vaultspec_a2a/api/app`. The dependency arrow is:
  `src/vaultspec_a2a/api/` → `src/vaultspec_a2a/worker/` (for spawn), `src/vaultspec_a2a/worker/` → `src/vaultspec_a2a/api/schemas/`.
- The worker's internal HTTP port (`VAULTSPEC_WORKER_PORT=8001`) must not
  conflict with the gateway port (`VAULTSPEC_PORT=8000`).
- `VAULTSPEC_INTERNAL_TOKEN` must be set to a non-empty value in production.
  The gateway and worker must share the same token value.
- `Executor.ingest()` must use `asyncio.Lock` per thread to prevent concurrent
  graph execution on the same checkpointer thread_id.
- The `_DEFAULT_MAX_CONCURRENT_THREADS` cap must be enforced before accepting
  new dispatches. The worker must return HTTP 429 when the cap is reached.
- Graph compilation errors must be caught and returned as `HTTP 422` from the
  `/dispatch` endpoint — not silently logged.

## 6. Module Hierarchy

```text
lib/
  worker/
    __init__.py     EXPORTS: WorkerApp, Executor, WorkerBridge (ADR-009 facade)
    app.py          WorkerApp = FastAPI; create_worker_app() factory; main() entry
    executor.py     Executor class; graph compilation + EventAggregator + run lifecycle
    ipc.py          WorkerBridge; httpx.AsyncClient; event forward + heartbeat
    health.py       /health endpoint; returns {"status": "ok", "active_threads": N}
    __main__.py     python -m lib.worker entry point
```text

## 7. References

- `src/vaultspec_a2a/worker/app.py` — FastAPI application + lifespan (checkpointer, bridge, executor)
- `src/vaultspec_a2a/worker/executor.py` — Executor class (graph compilation, EventAggregator, run dispatch)
- `src/vaultspec_a2a/worker/ipc.py` — WorkerBridge (httpx client for event forwarding)
- `src/vaultspec_a2a/core/config.py` — `settings.worker_url`, `settings.worker_port`, `settings.auto_spawn_worker`
- ADR-007 — FastAPI + SQLite tech stack rationale
- ADR-010 — OTel for worker spans
- ADR-017 — Docker Compose multi-service deployment
- ADR-021 — task queue integration with Executor

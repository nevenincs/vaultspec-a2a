# LangGraph Control Plane — Layer Mapping & Gap Analysis

**Date**: 2026-03-19
**Context**: Critical architecture research to map our control plane layers against LangGraph's design mandates. Triggered by audit finding that permission responses return `rejected_invalid_state` in live testing.

---

## Architecture Diagram

```mermaid
graph TB
    subgraph CLI["CLI Layer (cli/_team.py, _util.py)"]
        CLI_START["team start --preset X --message Y"]
        CLI_STATUS["team status --id X"]
        CLI_RESPOND["team respond --request-id X --option Y"]
        CLI_CLIENT["httpx.Client(base_url=settings.port)"]
    end

    subgraph GATEWAY["Gateway (api/ — port 8090)"]
        subgraph REST["REST Endpoints (endpoints.py)"]
            EP_CREATE["POST /threads — create_thread_endpoint()"]
            EP_STATE["GET /threads/{id}/state — get_thread_state_endpoint()"]
            EP_PERM["POST /permissions/{id}/respond — respond_to_permission_endpoint()"]
        end
        subgraph INTERNAL["Internal IPC (internal.py)"]
            IPC_BATCH["POST /internal/events/batch — _handle_batch_events()"]
            IPC_PERM["_handle_permission_event() — record_permission_request() to DB"]
        end
        subgraph GW_STATE["Gateway State"]
            GW_AGG["EventAggregator — _pending_permissions dict + _subscribers queues"]
            GW_WORKER["worker_client — httpx to settings.worker_url"]
            GW_CHECK["Checkpointer (read-only snapshot)"]
        end
        DB["SQLite DB — threads, permission_requests, control_actions"]
    end

    subgraph WORKER["Worker (worker/ — port 8091)"]
        subgraph EXEC["Executor (executor.py)"]
            W_DISPATCH["POST /dispatch — _handle_ingest() / _handle_resume()"]
            W_COMPILE["_compile_graph() — LangGraph StateGraph"]
        end
        subgraph W_AGG["Worker Aggregator"]
            W_EMIT["emit_permission_request() — _pending_permissions dict"]
            W_BROADCAST["_broadcast(event) — hook: _relay_event()"]
        end
        W_BRIDGE["WorkerBridge (ipc.py) — base_url = settings.mcp_api_base_url — POST /internal/events/batch"]
        W_CHECK["AsyncSqliteSaver Checkpointer (read-write)"]
    end

    subgraph LANGGRAPH["LangGraph Runtime"]
        LG_GRAPH["CompiledStateGraph — astream_events()"]
        LG_INT["interrupt(value) — raises GraphInterrupt"]
        LG_CMD["Command(resume=value) — scratchpad injection"]
        LG_CP["Checkpoint Storage — __interrupt__ channel"]
    end

    subgraph ACP["ACP Subprocess"]
        ACP_PROC["Claude / OpenAI / Zhipu via subprocess"]
        ACP_TOOL["Tool Execution — file write, shell, etc."]
    end
```text

---

## Layer Inventory

### Layer 1: CLI (`src/vaultspec_a2a/cli/`)

| Component | File | State | Notes |
|-----------|------|-------|-------|
| `team start` | `_team.py:15-49` | Working | Creates thread via POST /threads |
| `team status` | `_team.py:52-70` | Working | Shows minimal output (just "Status: running") |
| `team respond` | `_team.py:194-210` | **BROKEN** | Sends correct HTTP but misleading output |
| `_api_client()` | `_util.py:67-69` | Working | Uses `settings.port` for gateway URL |

**Config coupling**: CLI reads `settings.port` to construct base URL `http://127.0.0.1:{port}/api`. Does not use `settings.mcp_api_base_url`. Override via `VAULTSPEC_PORT` env var.

### Layer 2: Gateway REST API (`src/vaultspec_a2a/api/endpoints.py`)

| Endpoint | Lines | State | Notes |
|----------|-------|-------|-------|
| `POST /threads` | 360-509 | Working | Creates DB row, dispatches to worker |
| `GET /threads/{id}/state` | 902-1000+ | **Partial** | Shows permissions from aggregator memory, tool calls have null names |
| `POST /permissions/{id}/respond` | 1323-1550 | **Depends on DB** | Queries `permission_requests` table — works IF row exists |
| `GET /team/status` | — | Working | But shows 0 agents (heartbeat-based) |

### Layer 3: Gateway Internal IPC (`src/vaultspec_a2a/api/internal.py`)

| Handler | Lines | State | Notes |
|---------|-------|-------|-------|
| `POST /internal/events/batch` | 740-772 | **Working** | Receives worker events, calls _handle_permission_event |
| `_handle_permission_event()` | 190-268 | **Working** | Calls record_permission_request() → DB INSERT |
| `sync_worker_event()` | 528, 675, 767 | Working | Syncs into gateway aggregator memory |

### Layer 4: Worker Executor (`src/vaultspec_a2a/worker/executor.py`)

| Component | Lines | State | Notes |
|-----------|-------|-------|-------|
| `_handle_ingest()` | 415-559 | Working | Compiles graph, runs astream_events |
| `_handle_resume()` | 564-687 | Working | Command(resume=value) passed to aggregator.ingest() |
| `_relay_event` hook | 104-109 | Working | Bridges aggregator broadcast to IPC bridge |
| `_emit_interrupt_events()` | aggregator | Working | Post-execution checkpoint inspection |

### Layer 5: Worker IPC Bridge (`src/vaultspec_a2a/worker/ipc.py`)

| Component | Lines | State | Notes |
|-----------|-------|-------|-------|
| `WorkerBridge.__init__()` | 47-60 | **CONFIG HAZARD** | `base_url = settings.mcp_api_base_url` (default: `http://localhost:8000`) |
| `_flush_batch()` | 140-175 | Working | POST /internal/events/batch with retry |
| `send_event()` | 100-130 | Working | Buffers events, flushes on interval |

### Layer 6: Worker Aggregator (`src/vaultspec_a2a/core/aggregator.py`)

| Component | Lines | State | Notes |
|-----------|-------|-------|-------|
| `emit_permission_request()` | 869-909 | Working | Creates PermissionRequestEvent, stores in memory |
| `_broadcast()` | 523-572 | Working | Fans to subscribers + broadcast_hooks |
| `_emit_interrupt_events()` | 1491-1649 | Working | Reads checkpoint, extracts interrupts |
| `_pending_permissions` | dict | **Volatile** | Lost on worker restart |

### Layer 7: LangGraph Runtime

| Component | Source | State | Notes |
|-----------|--------|-------|-------|
| `interrupt(value)` | `langgraph/types.py:420-543` | **Standard** | Raises GraphInterrupt, stores in checkpoint |
| `Command(resume=value)` | `langgraph/types.py:368-401` | **Standard** | Resume via scratchpad injection |
| `Interrupt` type | `langgraph/types.py:161-214` | **Standard** | value + deterministic id (xxh3 hash) |
| `__interrupt__` channel | checkpoint | **Standard** | Stores interrupt tuple in channel_values |
| Scratchpad | `_loop.py:85-100` | **Standard** | Task-scoped, index-based resume matching |

### Layer 8: Checkpoint Storage

| Component | State | Notes |
|-----------|-------|-------|
| `AsyncSqliteSaver` | Working | Worker has read-write access |
| Gateway checkpointer | Working | Read-only snapshots via `aget_tuple()` |
| `__interrupt__` channel | Working | Persists interrupt state durably |

---

## The Three Permission Tracking Systems

The system has THREE separate permission tracking mechanisms that must stay synchronized:

### 1. LangGraph Checkpoint (Source of Truth)
- **Location**: `channel_values["__interrupt__"]` in checkpoint
- **Written by**: LangGraph runtime when `interrupt()` is called
- **Read by**: `aget_state()` in `_emit_interrupt_events()`
- **Durability**: Durable (SQLite/Postgres)
- **Survives restart**: Yes
- **Contains**: Interrupt value (type, request_id, tool_name, options)

### 2. Aggregator In-Memory Dict
- **Location**: `aggregator._pending_permissions` (both gateway and worker have separate instances)
- **Written by**: `emit_permission_request()` in worker aggregator
- **Synced to gateway by**: `sync_worker_event()` in gateway internal handler
- **Read by**: `get_pending_permissions()` for REST state snapshots
- **Durability**: Volatile (in-memory)
- **Survives restart**: No
- **Contains**: PermissionRequestEvent with full metadata

### 3. Database `permission_requests` Table
- **Location**: `PermissionRequestModel` in SQLite
- **Written by**: `record_permission_request()` in `internal.py:232`
- **Read by**: `get_permission_request()` in `endpoints.py:1361` (permission respond endpoint)
- **Durability**: Durable (SQLite)
- **Survives restart**: Yes
- **Contains**: request_id, thread_id, status, options, response

### How They Must Synchronize

```text
LangGraph Checkpoint    →    Worker Aggregator    →    Gateway IPC    →    DB Table
(interrupt() call)           (emit_permission)         (relay event)       (record_permission)
       |                           |                        |                    |
       |                           ↓                        ↓                    |
       |                    Worker _pending_perms    Gateway _pending_perms       |
       |                    (display on worker)      (display on REST /state)     |
       |                                                                         |
       ↓                                                                         ↓
  aget_state() reads                                              get_permission_request() reads
  (backup/recovery)                                               (permission respond endpoint)
```yaml

**The break point in our audit**: The worker IPC bridge (`settings.mcp_api_base_url`) pointed to `http://localhost:8000` but the gateway was on port 8090. Events never reached the gateway. The DB was never written. The respond endpoint queried an empty DB.

---

## LangGraph Design Mandates

### Mandate 1: Checkpoint IS the Source of Truth for Interrupts

LangGraph stores interrupts in `channel_values["__interrupt__"]`. The `aget_state()` API returns `StateSnapshot` with a `tasks` field containing `PregelTask` tuples, each with an `interrupts` tuple.

**Our compliance**: Partial. We read from the checkpoint via `aget_state()` in `_emit_interrupt_events()`, but we don't use the checkpoint as the authoritative source for REST queries. We use the aggregator's in-memory dict instead.

**Risk**: If the aggregator memory is lost (crash, restart), REST queries return empty permissions even though the checkpoint still has them.

### Mandate 2: Resume via `Command(resume=value)` Input

LangGraph resumes interrupted graphs by passing `Command(resume=value)` as input to `astream_events()`. The runtime injects the resume value into the scratchpad, and when the interrupted node re-executes, `interrupt()` returns the resume value instead of raising.

**Our compliance**: Full. `executor._handle_resume()` passes `Command(resume=req.option_id)` to `aggregator.ingest()`, which feeds it to `astream_events()`.

### Mandate 3: Interrupt IDs Are Deterministic

LangGraph computes interrupt IDs via `xxh3_128_hexdigest(namespace)`. They are stable across replays of the same node.

**Our compliance**: Partial. We use the interrupt's `.id` attribute when available, but fall back to `uuid4().hex` when missing. This makes IDs non-deterministic in the fallback case.

### Mandate 4: Resume Matching Is Index-Based

Within a single task (node execution), multiple `interrupt()` calls are matched by position. The scratchpad tracks `interrupt_counter` and resume values are consumed in order.

**Our compliance**: Implicit. We don't manage multi-interrupt matching ourselves — LangGraph handles it internally via the scratchpad. This works because we pass the resume value as `Command(resume=value)` and let LangGraph's runtime manage the rest.

### Mandate 5: Checkpointer Required for Interrupts

A checkpointer must be configured for interrupts to work. Without it, `interrupt()` raises but the state is lost.

**Our compliance**: Full. Both worker (`AsyncSqliteSaver`) and gateway (read-only) have checkpointers configured.

---

## Root Cause of Audit Failure

### The IPC Bridge URL Mismatch

```text
Worker IPC Bridge base_url = settings.mcp_api_base_url = "http://localhost:8000"
Gateway actually running on = http://127.0.0.1:8090
```yaml

**File**: `src/vaultspec_a2a/worker/app.py:97-100`
```python
bridge = WorkerBridge(
    settings.mcp_api_base_url,  # ← reads from config, defaults to http://localhost:8000
    worker_id,
    settings.internal_token,
)
```yaml

**File**: `src/vaultspec_a2a/worker/ipc.py:59-60`
```python
self._client = httpx.AsyncClient(
    base_url=self._api_url,  # ← http://localhost:8000 (wrong!)
```yaml

**Consequence**: All `POST /internal/events/batch` calls from the worker went to port 8000 (dead or stale process). The gateway on 8090 never received:
- Permission request events (so DB was never written)
- Thread status updates (so thread stayed "running" instead of "input_required")
- Heartbeats (so `worker_connected` stayed `false`)

**Why it partially worked**: Thread creation goes gateway→worker (the gateway knows the worker URL via `settings.worker_url`). But worker→gateway IPC goes the other direction using a **different config key** (`settings.mcp_api_base_url`). These two URLs are not linked.

### Config Key Asymmetry

| Direction | Config Key | Default | Purpose |
|-----------|-----------|---------|---------|
| Gateway → Worker | `settings.worker_url` | `http://127.0.0.1:8001` | Dispatch requests |
| Worker → Gateway | `settings.mcp_api_base_url` | `http://localhost:8000` | IPC event relay |
| CLI → Gateway | `settings.port` | `8000` | REST API calls |

Three different config keys for gateway communication, none linked. Changing the gateway port requires updating all three independently.

---

## Layer State Summary

| Layer | Status | Blocking Issue |
|-------|--------|----------------|
| CLI | Working | Misleading error messages on permission respond |
| Gateway REST | Working | Returns `rejected_invalid_state` when DB has no permission row |
| Gateway IPC | **Working but unreachable** | Correct code, but worker events don't arrive when ports mismatch |
| Gateway Aggregator | Working | Volatile memory, lost on restart |
| Database | **Empty** | Permission rows never written because IPC events don't arrive |
| Worker Executor | Working | Compiles graphs, runs LLM, detects interrupts |
| Worker Aggregator | Working | Emits permission events correctly |
| Worker IPC Bridge | **Misconfigured** | `mcp_api_base_url` not aligned with actual gateway port |
| LangGraph Runtime | Working | Interrupts, checkpoints, and resume all function correctly |
| Checkpoint Storage | Working | Durable, survives restarts |
| ACP Subprocess | Working | Real tool calls execute and create files |

**Assessment**: 7/10 layers are working. The break is in the IPC bridge configuration (Layer 5) which cascades to make the database empty (Layer ~DB) which makes the respond endpoint fail (Layer 2).

---

## Recommended Fixes (Priority Order)

### 1. Unify gateway URL configuration
The worker's IPC bridge should use the same URL the gateway tells the worker about, not a separate config key. Or at minimum, `mcp_api_base_url` should default to `http://127.0.0.1:{settings.port}` instead of a hardcoded `http://localhost:8000`.

### 2. Add checkpoint-based fallback for permission queries
When the aggregator's in-memory permissions are empty, fall back to reading the checkpoint's `__interrupt__` channel via `aget_state()`. This survives restarts and doesn't depend on IPC.

### 3. Validate IPC connectivity at worker startup
The worker should probe `{mcp_api_base_url}/internal/health` on startup and log a clear error if unreachable. Currently it silently fails to deliver events.

### 4. Stabilize permission request IDs
Use the LangGraph interrupt's deterministic `.id` field as the primary key. Fall back to a content hash, not UUID. This prevents ID cycling on state re-projection.

### 5. `service start` must coordinate all port-dependent config
When `service start gateway --port 8090` is used, the worker's `mcp_api_base_url` must automatically point to `http://127.0.0.1:8090`. Or: `service start all` must ensure both services use coordinated ports.

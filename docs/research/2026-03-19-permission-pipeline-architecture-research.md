# Permission Pipeline Architecture — Research Findings

**Date**: 2026-03-19
**Context**: Phase 5 of permission pipeline fix (deterministic IDs)
**Source**: Codebase exploration + implementation analysis

---

## Permission Event Flow

```text
LangGraph interrupt() → Aggregator._emit_interrupt_events()
  → emit_permission_request() → _broadcast() → WorkerBridge.send_event()
    → HTTP POST /internal/events/batch → Gateway internal.py
      → record_permission_request() [DB] → WebSocket broadcast
```

### Key Components

| Component | File | Role |
|-----------|------|------|
| Aggregator | `core/aggregator.py` | Detects interrupts, emits PermissionRequestEvent |
| WorkerBridge | `worker/ipc.py` | Batches events, HTTP relay to gateway |
| Internal router | `api/internal.py` | Records permission in DB, relays to WS |
| Respond endpoint | `api/endpoints.py:1323` | `POST /permissions/{request_id}/respond` |
| CRUD | `database/crud.py:726` | Create-or-update permission records |

## Permission ID Generation

### Previous (broken)

```python
request_id = str(
    payload.get("request_id")
    or getattr(interrupt_obj, "id", None)
    or f"{thread_id}:{uuid4().hex}"  # non-deterministic fallback
)
```

**Problem**: `uuid4()` generates a new UUID on every call to
`_emit_interrupt_events()`. The same interrupt gets a different ID on
each state inspection, breaking dedup and causing phantom duplicates.

### Current (fixed, Phase 5)

```python
task_idx = tasks.index(task)
interrupt_idx = task.interrupts.index(interrupt_obj)
request_id = str(
    payload.get("request_id")
    or getattr(interrupt_obj, "id", None)
    or f"{thread_id}:task{task_idx}:int{interrupt_idx}"
)
```

**Why position-based**: LangGraph's `state.tasks` list and each task's
`interrupts` list maintain stable ordering within a single graph
suspension. The task/interrupt index pair uniquely identifies a pending
approval request and is reproducible across repeated `aget_state()` calls.

## PermissionRequestEvent Schema

```python
class PermissionRequestEvent(EventEnvelope):
    type: Literal[ServerEventType.PERMISSION_REQUEST]
    request_id: str           # primary lookup key
    description: str          # user-facing
    options: list[PermissionOption]
    tool_call: str | None     # tool name or "plan_approval"
    tool_kind: ToolKind | None
```

Base `EventEnvelope` adds: `thread_id`, `timestamp`, `sequence`.

## DB Storage

`PermissionRequestModel` in `database/models.py:189-202`:

- `request_id: str` (primary key)
- `thread_id: str` (FK to threads)
- `request_status: str` (default "pending")

The CRUD function `record_permission_request()` uses create-or-update
semantics — if a `request_id` already exists, it refreshes the record.
This makes the system idempotent with deterministic IDs.

## Respond Endpoint Lookup

`POST /permissions/{request_id}/respond` (endpoints.py:1361-1364):

```python
permission = await get_permission_request(db, request_id)
thread_id = permission.thread_id if permission is not None else ""
if not thread_id and ":" in request_id:
    thread_id, _ = request_id.split(":", 1)
```

The fallback parsing splits on `:` to extract `thread_id`. Our format
`{thread_id}:task0:int0` preserves this convention.

## In-Memory Dedup

`_pending_permissions: dict[str, tuple[PermissionRequestEvent, float]]`

- Keyed by `request_id`
- Value = (event, monotonic timestamp)
- Phase 5 added: `if request_id in self._pending_permissions: continue`
- Pruned by `prune_stale_permissions(max_age_seconds=300)`

# Asyncio Memory Management for Long-Running Event Aggregators — 2026-03-08

## Context

VaultSpec A2A's `EventAggregator` (`src/vaultspec_a2a/core/aggregator.py`) is a
long-lived singleton that accumulates per-thread state for the entire process
lifetime. Task WRK-K02 identified that the worker's `EventAggregator` never
prunes completed thread state, causing unbounded memory growth proportional to
total threads processed, not active threads.

This document researches patterns for preventing memory leaks in long-running
async event aggregators. All patterns use stdlib asyncio primitives
(`asyncio.Queue`, `asyncio.Task`, `time.monotonic()`, `weakref`) which are
fully cross-platform (Windows, Linux, macOS) with identical behavior.

---

## 1. Current Leak Surface in EventAggregator

### 1.1 Per-Thread State Structures (line 307-363)

The `EventAggregator.__init__` allocates **12 dict-family structures** keyed by
thread_id or derived keys. All grow monotonically with thread creation:

| Structure | Key Type | Grows On | Pruned? |
|-----------|---------|----------|---------|
| `_sequences` | `str` (thread_id) | Every event emission | Partial: `prune_sequences()` exists but never called by worker |
| `_subscribers` | `str` (client_id) | WS subscribe | Yes: on WS disconnect |
| `_subscriptions` | `str` (client_id) | WS subscribe | Yes: on WS disconnect |
| `_ingest_queues` | `str` (thread_id) | `start_ingest()` | No |
| `_fanout_tasks` | `str` (thread_id) | `start_ingest()` | Only on shutdown |
| `_chunk_buffers` | `str` (thread_id) | Token streaming | No (defaultdict) |
| `_chunk_buffer_meta` | `str` (thread_id) | Token streaming | No |
| `_chunk_flush_tasks` | `str` (thread_id) | Chunk flush | Task cleanup only |
| `_tool_update_last_emit` | `(thread_id, tool_call_id)` | Tool update | Partial: AGG-03 per-thread at ingest end |
| `_plan_update_last_emit` | `str` (thread_id) | Plan update | Partial: per-thread at ingest end |
| `_pending_permissions` | `str` (request_id) | Permission request | TTL-based: `prune_stale_permissions(300s)` |
| `_agent_states` | `str` (agent_id) | Agent status | No |
| `_cancel_events` | `str` (thread_id) | Ingest start | Cleared at ingest end |
| `_node_metadata` | `str` (node_name) | `register_graph()` | Overwritten on re-register |

### 1.2 What Gets Cleaned Up

The `ingest()` method's `finally` block (line 1791-1812) cleans up **per-thread**:

- `_cancel_events[thread_id]` (cleared)
- `_chunk_buffers[thread_id]` (flushed)
- `_tool_update_last_emit` entries for `thread_id` (deleted)
- `_plan_update_last_emit[thread_id]` (deleted)

The `shutdown()` method (line 1819-1850) clears **everything** -- but this only
runs on process termination.

### 1.3 What Leaks

After a thread completes, these entries remain forever:

- `_sequences[thread_id]` -- 1 int per thread (small but unbounded)
- `_ingest_queues[thread_id]` -- `asyncio.Queue` object (non-trivial memory)
- `_fanout_tasks[thread_id]` -- `asyncio.Task` reference (may hold result/exc)
- `_chunk_buffers[thread_id]` -- empty list (from defaultdict, trivial)
- `_chunk_buffer_meta[thread_id]` -- dict with message_id etc.
- `_agent_states[agent_id]` -- bounded by agent count, not thread count (low risk)

### 1.4 Quantifying the Leak

Per completed thread, approximately:

- `_sequences`: ~100 bytes (str key + int value)
- `_ingest_queues`: ~500 bytes (Queue object + internal deque)
- `_fanout_tasks`: ~200 bytes (Task object, GC'd if done)
- `_chunk_buffer_meta`: ~200 bytes (small dict)

**Total: ~1KB per completed thread.** After 10,000 threads: ~10MB leaked. For a
desktop tool this is tolerable for short sessions but problematic for long-running
server deployments.

The real concern is `_ingest_queues` and `_fanout_tasks` -- these hold asyncio
objects that reference the event loop and may prevent garbage collection of
larger structures.

---

## 2. Existing Prune Methods (Implemented but Uncalled)

### 2.1 `prune_sequences(active_thread_ids)` (line 443-458)

```python
def prune_sequences(self, active_thread_ids: set[str]) -> int:
    stale = [tid for tid in self._sequences if tid not in active_thread_ids]
    for tid in stale:
        del self._sequences[tid]
    return len(stale)
```

**Status:** Implemented. Never called by worker code. The gateway's
`sync_worker_event` relay path could call this, but doesn't.

### 2.2 `prune_stale_permissions(max_age_seconds=300.0)` (line 943-955)

```python
def prune_stale_permissions(self, max_age_seconds: float = 300.0) -> int:
    stale_ids = [
        rid for rid, (_evt, created_at) in self._pending_permissions.items()
        if (time.monotonic() - created_at) > max_age_seconds
    ]
    for rid in stale_ids:
        del self._pending_permissions[rid]
    return len(stale_ids)
```

**Status:** Implemented. Called by the gateway on a periodic schedule (AGG-01/05).
Not called by the worker.

---

## 3. Pattern 1: TTL-Based Cleanup with Periodic Task

The simplest pattern: run a background `asyncio.Task` that periodically scans
and removes entries older than a TTL.

### 3.1 Design

```python
import asyncio
import time

class EventAggregator:
    _PRUNE_INTERVAL = 60.0  # Check every 60s
    _THREAD_TTL = 300.0     # Prune threads inactive for 5 min

    def __init__(self):
        self._sequences: dict[str, int] = {}
        self._last_activity: dict[str, float] = {}  # thread_id -> monotonic time
        self._prune_task: asyncio.Task | None = None

    def start_pruning(self) -> None:
        """Start the background prune loop. Call from lifespan startup."""
        self._prune_task = asyncio.create_task(self._prune_loop())

    async def _prune_loop(self) -> None:
        while True:
            await asyncio.sleep(self._PRUNE_INTERVAL)
            self._prune_stale_threads()

    def _prune_stale_threads(self) -> int:
        now = time.monotonic()
        stale = [
            tid for tid, last in self._last_activity.items()
            if (now - last) > self._THREAD_TTL
        ]
        for tid in stale:
            self._sequences.pop(tid, None)
            self._ingest_queues.pop(tid, None)
            self._fanout_tasks.pop(tid, None)
            self._chunk_buffers.pop(tid, None)
            self._chunk_buffer_meta.pop(tid, None)
            self._last_activity.pop(tid, None)
        return len(stale)
```

### 3.2 Pros/Cons

**Pros:**

- Simple to implement
- No external dependencies
- Works on both gateway and worker
- Configurable TTL per deployment

**Cons:**

- Requires tracking `_last_activity` per thread (one more dict)
- Periodic wake-up even when no pruning needed
- TTL must be tuned: too short risks pruning active threads, too long defeats the purpose

### 3.3 Recommendation for VaultSpec

**This is the recommended pattern.** The aggregator already has `prune_sequences()`
and `prune_stale_permissions()` -- they just need to be wired into a periodic
task and extended to cover all per-thread dicts.

---

## 4. Pattern 2: Explicit Cleanup on Thread Completion

Instead of periodic TTL scanning, clean up thread state immediately when the
thread reaches a terminal status (completed, failed, cancelled).

### 4.1 Design

```python
class EventAggregator:
    def cleanup_thread(self, thread_id: str) -> None:
        """Remove all per-thread state for a completed thread.

        Call this after the thread reaches a terminal status.
        """
        self._sequences.pop(thread_id, None)
        self._ingest_queues.pop(thread_id, None)

        task = self._fanout_tasks.pop(thread_id, None)
        if task and not task.done():
            task.cancel()

        self._chunk_buffers.pop(thread_id, None)
        self._chunk_buffer_meta.pop(thread_id, None)
        self._cancel_events.pop(thread_id, None)

        # Debounce maps (already cleaned in ingest finally, belt-and-suspenders)
        stale_tool_keys = [
            k for k in self._tool_update_last_emit if k[0] == thread_id
        ]
        for k in stale_tool_keys:
            del self._tool_update_last_emit[k]
        self._plan_update_last_emit.pop(thread_id, None)
```

### 4.2 Where to Call It

In the worker's `Executor.handle_dispatch()`, after the ingest loop completes
and the thread status is set to terminal:

```python
# After ingest completes:
outcome = await self._aggregator.ingest(...)
# outcome is "completed", "failed", "cancelled", "interrupted"
if outcome in ("completed", "failed", "cancelled"):
    self._aggregator.cleanup_thread(thread_id)
```

### 4.3 Pros/Cons

**Pros:**

- Immediate cleanup, no TTL delay
- No background task overhead
- Memory stays proportional to **active** threads only
- Simple call site

**Cons:**

- Requires a reliable "thread is terminal" signal
- If `ingest()` throws unexpectedly, cleanup might not run (need try/finally)
- Does not handle the case where a thread becomes terminal via external means
  (e.g., cancelled from the gateway while ingest is still running)

### 4.4 Edge Case: Interrupted Threads

Interrupted threads (permission request) are NOT terminal -- they may resume.
`cleanup_thread()` must NOT be called for interrupted threads. Only for:

- `completed`
- `failed`
- `cancelled`

---

## 5. Pattern 3: WeakRef-Based Automatic Cleanup

Use `weakref.WeakValueDictionary` or `weakref.finalize` to tie per-thread state
to a reference-counted object, so cleanup happens automatically when the object
is garbage collected.

### 5.1 Design Sketch

```python
import weakref

class _ThreadState:
    """Holds all per-thread aggregator state."""
    def __init__(self, thread_id: str):
        self.thread_id = thread_id
        self.sequence: int = 0
        self.ingest_queue: asyncio.Queue | None = None
        self.fanout_task: asyncio.Task | None = None
        self.chunk_buffer: list[str] = []
        self.chunk_buffer_meta: dict[str, str] = {}

class EventAggregator:
    def __init__(self):
        self._threads: weakref.WeakValueDictionary[str, _ThreadState] = (
            weakref.WeakValueDictionary()
        )
        self._thread_refs: dict[str, _ThreadState] = {}  # strong refs for active

    def activate_thread(self, thread_id: str) -> _ThreadState:
        state = _ThreadState(thread_id)
        self._thread_refs[thread_id] = state  # strong ref
        self._threads[thread_id] = state       # weak ref
        return state

    def deactivate_thread(self, thread_id: str) -> None:
        self._thread_refs.pop(thread_id, None)
        # WeakValueDictionary auto-removes when state is GC'd
```

### 5.2 Why This Does NOT Work Well for asyncio

**Problem 1: asyncio.Task prevents GC.** A running `asyncio.Task` holds a strong
reference to its coroutine, which holds references to all local variables. Even
if you remove the strong ref from `_thread_refs`, the Task keeps the
`_ThreadState` alive until the task completes.

**Problem 2: WeakValueDictionary + defaultdict conflict.** The aggregator uses
`defaultdict(int)` for `_sequences` -- this creates entries on access. A
`WeakValueDictionary` cannot hold `int` values (not reference types).

**Problem 3: Callback timing.** `weakref.finalize` callbacks run at GC time,
which is non-deterministic in CPython's cycle collector. Asyncio objects may be
cleaned up much later than expected, or not at all if there are reference cycles.

### 5.3 Verdict

**Not recommended for this use case.** WeakRef patterns work well for caches
where values are naturally short-lived, but asyncio Tasks and Queues have
complex reference graphs that defeat automatic GC-based cleanup.

---

## 6. Pattern 4: Bounded LRU Eviction

Cap the maximum number of per-thread entries and evict the least-recently-used
when the cap is exceeded.

### 6.1 Design

```python
from collections import OrderedDict

class BoundedThreadState:
    """Thread state dict with LRU eviction."""

    def __init__(self, maxsize: int = 1000):
        self._data: OrderedDict[str, int] = OrderedDict()
        self._maxsize = maxsize

    def touch(self, thread_id: str) -> int:
        """Access and bump thread_id to most-recent."""
        if thread_id in self._data:
            self._data.move_to_end(thread_id)
        else:
            self._data[thread_id] = 0
        self._data[thread_id] += 1
        while len(self._data) > self._maxsize:
            self._data.popitem(last=False)  # evict oldest
        return self._data[thread_id]
```

### 6.2 Pros/Cons

**Pros:**

- Guaranteed bounded memory regardless of thread count
- No background task
- Simple implementation

**Cons:**

- May evict state for active long-running threads
- Requires careful sizing of `maxsize`
- Does not clean up asyncio Tasks/Queues (only works for simple data)
- The existing `_evict_oldest()` helper (line 112-119) already implements this
  for debounce maps with `_DEBOUNCE_MAP_MAX_ENTRIES = 1000`

### 6.3 Verdict

**Good as a safety cap (already implemented for debounce maps), but not
sufficient as the primary cleanup strategy.** The `_evict_oldest()` approach
is correct for timestamp maps. For `_ingest_queues` and `_fanout_tasks`,
eviction must also cancel the task, which LRU eviction doesn't handle cleanly.

---

## 7. How LangGraph Handles Memory

### 7.1 InMemorySaver (MemorySaver)

Validated from installed source at
`.venv/Lib/site-packages/langgraph/checkpoint/memory/__init__.py`.

LangGraph's `InMemorySaver` uses three unbounded `defaultdict` structures:

- `storage`: thread_id -> checkpoint_ns -> checkpoint_id -> checkpoint data
- `writes`: (thread_id, checkpoint_ns, checkpoint_id) -> pending writes
- `blobs`: (thread_id, checkpoint_ns, channel, version) -> serialized blob

**No pruning.** `InMemorySaver` has `delete_thread(thread_id)` (line 410-426)
which removes all data for a thread from all three dicts, but it is never called
automatically. Memory grows without bound as threads are created.

**LangGraph's stance:** InMemorySaver is explicitly documented as "Only use for
debugging or testing purposes." Production deployments use `PostgresSaver` or
`AsyncSqliteSaver` where the database manages storage lifecycle.

### 7.2 AsyncSqliteSaver

Our production checkpointer. SQLite WAL mode with on-disk storage. Memory is
bounded by SQLite's page cache (`PRAGMA cache_size`), not by thread count.
Completed thread checkpoints persist on disk but don't consume Python heap.

**Implication:** The checkpointer is not the leak source. The `EventAggregator`
is.

### 7.3 LangGraph Graph Cache

The worker's `Executor` maintains `_graph_cache: dict[str, CompiledStateGraph]`
(compiled graphs) and `_thread_to_cache_key: dict[str, str]` (thread->graph
mapping). Both are cleared on `shutdown()` but not pruned per-thread.

This is a secondary leak source: graph objects are large (nodes, edges,
compiled functions). If each thread uses a unique graph config, the cache grows
unboundedly.

---

## 8. Recommended Solution for WRK-K02

### 8.1 Combined Approach: Explicit Cleanup + TTL Safety Net

Use **Pattern 2 (explicit cleanup)** as the primary strategy, with
**Pattern 1 (TTL)** as a safety net for edge cases.

### 8.2 Implementation Plan

**Step 1:** Add `cleanup_thread(thread_id)` method to `EventAggregator`:

```python
def cleanup_thread(self, thread_id: str) -> None:
    """Remove all per-thread state for a completed thread."""
    self._sequences.pop(thread_id, None)

    q = self._ingest_queues.pop(thread_id, None)
    # Queue doesn't need explicit cleanup -- GC handles it

    task = self._fanout_tasks.pop(thread_id, None)
    if task and not task.done():
        task.cancel()

    flush_task = self._chunk_flush_tasks.pop(thread_id, None)
    if flush_task and not flush_task.done():
        flush_task.cancel()

    self._chunk_buffers.pop(thread_id, None)
    self._chunk_buffer_meta.pop(thread_id, None)
    self._cancel_events.pop(thread_id, None)

    # Debounce maps (belt-and-suspenders)
    stale_tool_keys = [
        k for k in self._tool_update_last_emit if k[0] == thread_id
    ]
    for k in stale_tool_keys:
        del self._tool_update_last_emit[k]
    self._plan_update_last_emit.pop(thread_id, None)
```

**Step 2:** Call from `Executor.handle_dispatch()` on terminal outcomes:

```python
outcome = await self._aggregator.ingest(...)
if outcome in ("completed", "failed", "cancelled"):
    self._aggregator.cleanup_thread(thread_id)
    self._thread_to_cache_key.pop(thread_id, None)
```

**Step 3:** Add TTL safety net as a background task in the worker lifespan:

```python
async def _prune_loop(aggregator: EventAggregator, interval: float = 60.0):
    while True:
        await asyncio.sleep(interval)
        aggregator.prune_stale_permissions()
        # Additional TTL prune if needed
```

**Step 4:** Wire the prune loop into the worker's `_lifespan()`:

```python
tg.start_soon(_prune_loop, executor.aggregator)
```

### 8.3 Memory After Fix

With explicit cleanup, memory is proportional to **active threads** only:

- 0 completed thread entries (cleaned immediately)
- ~1KB per active thread (same as before)
- Permission TTL GC runs as safety net every 60s

For a typical desktop session with 1-5 concurrent threads, peak aggregator
memory stays under 10KB regardless of how many threads have been processed.

---

## 9. Gateway Aggregator Considerations

The gateway has its own `EventAggregator` (injected via DI in lifespan). It
receives events relayed from the worker via `sync_worker_event()`. The same
leak surface exists but is less severe because:

1. The gateway's aggregator doesn't create `_ingest_queues` or `_fanout_tasks`
   (those are worker-side only for `astream_events` consumption)
2. `_subscribers` and `_subscriptions` are cleaned on WS disconnect
3. `_sequences` grows but entries are small (int)

**Still recommended:** Call `cleanup_thread()` from the gateway when a thread
reaches terminal status (e.g., in `sync_worker_event()` when receiving a
terminal `AgentStatusEvent`).

---

## 10. Summary of Patterns

| Pattern | Best For | Downside | Recommended? |
|---------|----------|----------|--------------|
| TTL periodic | Safety net, permission GC | Delay before cleanup, tuning | Yes (secondary) |
| Explicit cleanup | Primary cleanup on terminal | Requires reliable terminal signal | **Yes (primary)** |
| WeakRef | Caches with simple values | asyncio Tasks prevent GC | No |
| LRU eviction | Debounce maps, bounded data | Can evict active entries | Yes (for debounce only) |

**Recommended combo for WRK-K02:**

1. `cleanup_thread()` called on terminal outcomes (immediate)
2. `prune_stale_permissions()` on 60s interval (safety net)
3. Existing `_evict_oldest()` for debounce maps (bounded cap)

# Worker Module Audit — 2026-03-06

**Auditor:** codebase-researcher (automated)
**Scope:** `src/vaultspec_a2a/worker/` — 6 source files (app.py, executor.py, ipc.py, health.py, **main**.py, **init**.py)
**Baseline:** Never fully audited (module created during ADR-019 service separation sprint, 2026-03-03)

---

## Cycle 1 — Full Module Scan

### CRITICAL Findings

#### CRIT-01: `_graphs` dict grows unboundedly — no eviction policy

**File:** `executor.py:81`

```python
self._graphs: dict[str, CompiledStateGraph] = {}
```text

Every new thread compiles and stores a `CompiledStateGraph` instance. There is no eviction, LRU, or TTL mechanism. In a long-running worker processing hundreds of threads, this will consume unbounded memory. `CompiledStateGraph` objects hold compiled node functions, edge logic, and potentially captured closures with model instances.

The companion `_graph_presets` dict at line 84 has the same issue but is lighter weight (just tuples).

**Severity:** CRITICAL — unbounded memory growth proportional to thread count, no ceiling.

#### CRIT-02: `_relay_event` broadcast hook serializes every event via HTTP POST

**File:** `executor.py:91-94`

```python
async def _relay_event(event: Any) -> None:
    thread_id = getattr(event, "thread_id", "")
    if thread_id:
        await _bridge_ref.send_event(thread_id, event.model_dump())
```text

Every single event emitted by the aggregator (message chunks, tool updates, heartbeats, status changes) is sent as an individual HTTP POST to the gateway. For a typical LLM response with 100+ streaming chunks, this generates 100+ HTTP requests per response turn. This is extremely inefficient — it should batch events or use a WebSocket/SSE connection for the relay.

Additionally, `event.model_dump()` is called inside the hook but the return of `model_dump()` produces a `dict`. If `event` is already a `dict` (which can happen from raw aggregator broadcasts), `model_dump()` will raise `AttributeError`.

**Severity:** CRITICAL (performance) — O(n) HTTP requests per token chunk, creating massive I/O overhead for the relay path.

---

### HIGH Findings

#### HIGH-01: `health.py` is an empty stub class

**File:** `health.py:1-8`

```python
class HealthCheck:
    """Periodic heartbeat emitter and /healthz endpoint handler."""
```text

The `HealthCheck` class has no methods or attributes — it's completely empty. Health checks are implemented in `app.py` (`/health` endpoint) and `ipc.py` (`heartbeat_loop`). This file is dead code.

#### HIGH-02: `__main__.py` docstring references old `lib.worker` path

**File:** `__main__.py:1`

```python
"""Allow running the worker as ``python -m lib.worker``."""
```text

Should be `python -m vaultspec_a2a.worker`.

#### HIGH-03: `app.py` docstring references old `lib.worker` facade path

**File:** `app.py:39`

```python
# Re-export so the facade ``lib.worker`` can expose ``WorkerApp``
```text

Should reference `vaultspec_a2a.worker`.

#### HIGH-04: `heartbeat_loop` docstring says "Defaults to 10 s" but signature says `interval: float = 30.0`

**File:** `ipc.py:142`

```python
async def heartbeat_loop(self, interval: float = 30.0) -> None:
    """...
    interval:
        Seconds between heartbeats.  Defaults to 10 s.
    """
```text

The docstring says 10s but the default parameter is 30s. However, the caller in `app.py:85` passes `10.0` explicitly:

```python
tg.start_soon(bridge.heartbeat_loop, 10.0)
```text

So the actual runtime behavior is 10s, but the signature default of 30s is misleading and the docstring is wrong relative to the signature.

#### HIGH-05: `send_event` in WorkerBridge does not handle backpressure

**File:** `ipc.py:88-114`

`send_event()` performs a blocking HTTP POST for every event. If the gateway is slow or unresponsive, events will queue up in the asyncio event loop. There's no:

- Rate limiting
- Queue with bounded size
- Batching window
- Circuit breaker for repeated failures

Combined with CRIT-02, this means a slow gateway can cause the worker's event loop to accumulate thousands of pending HTTP requests.

#### HIGH-06: Worker shutdown cancels task group AFTER executor shutdown

**File:** `app.py:91-95`

```python
yield
# Shutdown path
logger.info("Worker %s shutting down", worker_id)
await executor.shutdown()
await bridge.close()
tg.cancel_scope.cancel()
```text

The `tg.cancel_scope.cancel()` is called last, but the task group's heartbeat task (`bridge.heartbeat_loop`) is still running during `executor.shutdown()` and `bridge.close()`. After `bridge.close()` disposes the httpx client, the heartbeat loop's next `send_heartbeat()` call will raise `httpx.AsyncClientError`. The correct order would be to cancel the task group first, then shutdown executor and close bridge.

---

### MEDIUM Findings

#### MED-01: `_handle_ingest` does not pass SDD blackboard fields from DispatchRequest to graph_input

**File:** `executor.py:209-231`

The `DispatchRequest` schema has `active_feature`, `pipeline_phase`, `vault_index`, and `validation_errors` fields, but `_handle_ingest` only passes `messages` and `thread_id` to `graph_input` (plus `active_agent`, `artifacts`, `current_plan`, `token_usage` for first ingest). The SDD blackboard fields are silently dropped.

This means the gateway endpoint at `endpoints.py:272-294` carefully builds `vault_index` and `active_feature`, dispatches them to the worker, and the worker ignores them.

#### MED-02: `_handle_resume` re-resolves `preset_info` twice

**File:** `executor.py:306-307`

```python
preset_info = self._graph_presets.get(req.thread_id)
team_preset = preset_info[0] if preset_info else req.team_preset
```text

This is a duplicate lookup — `preset_info` was already resolved at line 267 and used for graph recompilation. The second lookup at line 306 produces identical results. Should reuse the earlier variable.

#### MED-03: `Executor` does not export `ConcurrentCapError` from facade

**File:** `worker/__init__.py:26-31`

`__init__.py` exports `Executor` but NOT `ConcurrentCapError` (declared in `executor.py:42-43`). `ConcurrentCapError` is listed in `executor.py.__all__` but not in the facade's `__all__`.

#### MED-04: `WorkerBridge.__init__` parameter `api_url` should be named `base_url` for consistency with httpx

**File:** `ipc.py:41`

The parameter is called `api_url` but the property name is `_api_url` and it's passed to `httpx.AsyncClient(base_url=...)`. This is a naming inconsistency — the caller in `app.py:72` passes `settings.mcp_api_base_url` which further confuses the naming (MCP vs internal IPC).

#### MED-05: `Executor._compile_graph` omits `feature_tag` parameter

**File:** `executor.py:381-390`

`compile_team_graph()` is called without `feature_tag`, meaning the compiled graph won't have feature-tag context for vault mounting. The `req.active_feature` field exists but is not forwarded.

---

### LOW Findings

#### LOW-01: `WorkerApp = FastAPI` type alias adds no semantic value

**File:** `app.py:41`

```python
WorkerApp = FastAPI
```text

This alias exists for facade re-export but doesn't constrain or extend `FastAPI` — it's just a rename. Any code using `WorkerApp` type hints would accept any `FastAPI` instance.

#### LOW-02: `_GRAPH_RECURSION_LIMIT = 100` duplicated between `executor.py` and `endpoints.py`

**Files:** `executor.py:49`, `endpoints.py:191`

Both define the same constant independently. A single source of truth would prevent drift.

#### LOW-03: `HealthCheck` class exists but is completely unused

**File:** `health.py`

Dead code that should be deleted. See HIGH-01.

---

## Summary

| Severity | Count | Key Themes |
|----------|-------|------------|
| CRITICAL | 2     | Unbounded graph cache, per-event HTTP relay overhead |
| HIGH     | 6     | Dead code, stale paths, shutdown ordering, no backpressure |
| MEDIUM   | 5     | Dropped SDD fields, duplicate lookups, facade gap |
| LOW      | 3     | Type alias, duplicated constant, dead code |

### Assessment

The worker module implements ADR-019 service separation correctly — graph compilation, execution, and event aggregation all run in the worker process. The `Executor` class is well-structured with proper ingest gating and lazy recompilation.

The main concerns are:

1. **CRIT-01**: The `_graphs` dict will grow unboundedly in production. An LRU eviction policy with configurable capacity is needed.
2. **CRIT-02**: Per-event HTTP POST relay is extremely chatty. Batching or switching to a persistent connection would dramatically reduce I/O.
3. **MED-01**: SDD blackboard fields (`vault_index`, `active_feature`) are carefully built by the API, dispatched to the worker, and silently dropped. This breaks ADR-020 vault mounting for newly created threads.

### Recommended Fix Priority

1. **CRIT-01**: Add LRU eviction to `_graphs` (e.g., `functools.lru_cache` or manual OrderedDict with max_size).
2. **CRIT-02**: Batch events into a bounded queue with periodic flush (e.g., every 50ms or 50 events).
3. **MED-01**: Forward `active_feature`, `vault_index`, `pipeline_phase`, `validation_errors` from `DispatchRequest` into `graph_input`.
4. **HIGH-06**: Fix shutdown ordering: cancel task group first, then shutdown executor and close bridge.
5. **HIGH-01 + LOW-03**: Delete `health.py` (dead code).

---

## Cycle 2 — Re-audit (2026-03-06)

### Verified Status

All findings remain **OPEN**. No fixes applied to the worker module since Cycle 1.

| Finding | Status | Task |
|---------|--------|------|
| CRIT-01 | OPEN | #14 (blocked by #11) |
| CRIT-02 | OPEN | #15 (blocked by #11) |
| HIGH-01 | OPEN | -- (health.py still exists, still empty) |
| HIGH-02 | OPEN | Part of task #19 (stale lib. refs) |
| HIGH-03 | OPEN | Part of task #19 |
| HIGH-04 | OPEN | -- |
| HIGH-05 | OPEN | -- |
| HIGH-06 | OPEN | -- |
| MED-01 | OPEN | -- (SDD fields still dropped in _handle_ingest) |
| MED-02 | OPEN | -- |
| MED-03 | OPEN | -- |
| MED-04 | OPEN | -- |
| MED-05 | OPEN | -- (feature_tag still not forwarded to compile_team_graph) |
| LOW-01/02/03 | OPEN | -- |

**Note:** CRIT-01 and CRIT-02 are blocked behind task #11 (dual aggregator fix), which is the coder's current focus. MED-01 (SDD blackboard field passthrough) is a significant correctness issue -- vault mounting for newly created threads is broken because the worker silently drops the fields that the API carefully builds.

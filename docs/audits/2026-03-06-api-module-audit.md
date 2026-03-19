# API Module Audit — 2026-03-06

**Auditor:** codebase-researcher (automated)
**Scope:** `src/vaultspec_a2a/api/` — all 12 source files (app.py, endpoints.py, internal.py, supervisor.py, websocket.py, auth.py, schemas/{**init**, base, commands, enums, events, internal, rest, snapshots}.py)
**Baseline:** Last audited 2026-02-28 (Third-Pass Deep Audit Fix Sprint)

---

## Cycle 1 — Full Module Scan

### CRITICAL Findings

*None identified.* The ADR-019 service separation refactor is well-structured. The API module acts purely as a gateway forwarding to the worker, which eliminates many classes of bugs.

---

### HIGH Findings

#### HIGH-01: `endpoints.py` imports private `_build_initial_vault_index` from `core.graph`

**File:** `endpoints.py:41`

```python
from ..core.graph import _build_initial_vault_index
```python

This imports a private function (leading underscore) from `core.graph`. Private symbols are not part of the public API and can be renamed/removed without notice. The function is used at line 276 to populate `vault_index` in the dispatch request. It should be exported via `core/__init__.py` or made public.

#### HIGH-02: `_dispatch_message` handler in `app.py` does inline `import json` with `noqa`

**File:** `app.py:123`

```python
import json as _json  # noqa: PLC0415
```python

This import is inside the closure body, executed on every WS message dispatch. While Python caches module imports, the `noqa` suppression and inline placement indicate this was added hastily. `json` is already used at module level in `endpoints.py` — it should be a module-level import in `app.py` too.

#### HIGH-03: `checkpointer.aget()` in `get_thread_state_endpoint` is undocumented API

**File:** `endpoints.py:506`

```python
checkpoint = await asyncio.wait_for(
    checkpointer.aget({"configurable": {"thread_id": thread_id}}),
    timeout=10.0,
)
```text

The memory notes from the LangGraph Alignment Sprint (WS1, LG-027) specifically state that `aget_tuple()` is the documented API and `aget()` is undocumented. This endpoint uses the undocumented `aget()` instead. While the code handles the return format correctly, this could break on LangGraph version upgrades.

#### HIGH-04: `_MinimalState` class defined inside endpoint function body

**File:** `endpoints.py:516-522`

```python
class _MinimalState:
    """Minimal adapter for _enrich_snapshot_from_state."""
    def __init__(self, values: dict, config: dict | None = None) -> None:
        self.values = values
        self.config = config
```typescript

A class is defined inside `get_thread_state_endpoint` and instantiated on every request. This works but is architecturally odd — the class is recreated on every call. It should be a module-level private class or the `_enrich_snapshot_from_state` function should accept a simpler interface (dict instead of StateSnapshot-like object).

#### HIGH-05: `list_team_presets_endpoint` docstring references old `lib/core/presets/teams/*.toml` path

**File:** `endpoints.py:697`

```text
Dynamically discovers presets by globbing ``lib/core/presets/teams/*.toml``.
```text

Should reference `src/vaultspec_a2a/core/presets/teams/*.toml` after the migration sprint.

#### HIGH-06: Dual dispatch paths for the same operation (WS send_message vs REST send_message)

**Files:** `app.py:109-157` (`_dispatch_message`) vs `endpoints.py:564-636` (`send_message_endpoint`)

Both paths dispatch an `ingest` action to the worker, but they construct the dispatch payload differently:

1. **WS path** (`_dispatch_message`): builds a raw dict `{"action": "ingest", ...}` — does NOT use `DispatchRequest` model, omits fields like `recursion_limit`, `active_feature`, `vault_index`, `validation_errors`
2. **REST path** (`send_message_endpoint`): builds a `DispatchRequest` model but also omits `recursion_limit`, `active_feature`, etc. for follow-up messages

The WS path bypasses Pydantic validation entirely. If `DispatchRequest` adds required fields or validation, the WS path will silently send invalid payloads.

---

### MEDIUM Findings

#### MED-01: `schemas/enums.py` docstring references old `lib.utils.enums` path

**File:** `schemas/enums.py:8`

```text
Note: ``Provider`` and ``Model`` live in ``lib.utils.enums`` and are
imported (not duplicated) where needed.
```text

Should be `vaultspec_a2a.utils.enums`.

#### MED-02: `schemas/__init__.py` docstring references old `lib.api.schemas` path

**File:** `schemas/__init__.py:5`

```text
Facade re-exporting all public types from the ``lib.api.schemas`` subpackage.
```text

Should be `vaultspec_a2a.api.schemas`.

#### MED-03: `internal.py` docstring references old `lib.worker.ipc` path

**File:** `internal.py:9`

```text
The ``WorkerBridge`` in ``lib.worker.ipc`` uses this approach.
```text

Should be `vaultspec_a2a.worker.ipc`.

#### MED-04: `websocket.py` docstring references old `lib.api.internal` path

**File:** `websocket.py:513`

```text
Used by the internal WebSocket relay (``lib.api.internal``) to forward
```text

Should be `vaultspec_a2a.api.internal`.

#### MED-05: `_PermissionSnapshot`, `_PermissionOptionSnapshot`, `_AgentSnapshot` not exported from schemas facade

**File:** `schemas/snapshots.py:60-84`

These three private models are used in `ThreadStateSnapshot` (which IS exported) but are not in `snapshots.__all__` or `schemas/__init__.py`. While they're private by convention, any consumer trying to construct or validate `ThreadStateSnapshot` programmatically would need access to these types.

#### MED-06: `internal.py` WS endpoint stores state on `websocket.app.state` without initialization

**File:** `internal.py:63-64`

```python
websocket.app.state.worker_ws = websocket
websocket.app.state.worker_last_heartbeat_ts = time.monotonic()
```text

These attributes are set dynamically on `app.state` without being initialized in the lifespan. If any code reads `app.state.worker_ws` before the worker connects, it would get an `AttributeError`. The lifespan in `app.py` does not initialize these attributes.

#### MED-07: `supervisor.py` uses `subprocess.Popen` (sync) instead of async subprocess

**File:** `supervisor.py:46-52`

```python
self._process = subprocess.Popen(cmd, stdout=None, stderr=None)
```text

The `start()` method is synchronous, using `subprocess.Popen` directly. While `stop()` correctly uses `run_in_executor` for the blocking `wait()`, the `start()` call blocks the event loop briefly during `Popen` initialization. This is acceptable for a one-time startup but inconsistent with the async patterns used elsewhere.

#### MED-08: `_enrich_snapshot_from_state` message_id fallback uses truncated SHA-256

**File:** `endpoints.py:445`

```python
message_id = (
    stored_id or hashlib.sha256(f"{role}:{content}".encode()).hexdigest()[:32]
)
```text

The deterministic hash approach is sound, but `role:content` as the hash input can collide if the same role sends identical content (e.g., two identical system messages). Adding the message index would eliminate this edge case.

#### MED-09: `cancel_thread_endpoint` marks thread as cancelled in DB even if worker dispatch fails

**File:** `endpoints.py:862-865`

```python
# Update DB status regardless of dispatch success
await update_thread_status(db, thread_id, ThreadStatus.CANCELLED)
await db.commit()
```python

The comment explicitly documents this as intentional, but it means the DB and worker can be out of sync: the DB says "cancelled" while the worker continues executing. There's no mechanism to reconcile this state.

---

### LOW Findings

#### LOW-01: `api/__init__.py` facade is intentionally minimal but underdocumented

**File:** `api/__init__.py:1-13`

The facade only exports 5 types (ClientCommand, ClientMessage, EventEnvelope, ServerEvent, ThreadStateSnapshot) and explicitly documents why `create_app`, `router`, etc. are excluded (circular import via `core.aggregator`). This is reasonable but consumers must deep-import for everything else, partially defeating the facade pattern.

#### LOW-02: `auth.py` is a no-op stub

**File:** `auth.py` (from previous session)

The auth module is a placeholder with no implementation. This is fine for development but should be clearly marked as a blocker for any deployment beyond local dev.

#### LOW-03: `_SERVER_VERSION` hardcoded in `websocket.py`

**File:** `websocket.py:83`

```python
_SERVER_VERSION = "0.1.0"
```text

Hardcoded version string that will drift from `pyproject.toml`. Should use `importlib.metadata.version("vaultspec-a2a")` or similar.

#### LOW-04: `CancelThreadResponse` uses `str` for status instead of `ThreadStatus` enum

**File:** `schemas/rest.py:71`

```python
status: str
```text

`CreateThreadResponse` and `ThreadSummary` also use `str` for status. These could use the `ThreadStatus` enum from `database.crud` for type safety, but this would couple the schema layer to the database layer.

---

## Summary

| Severity | Count | Key Themes |
|----------|-------|------------|
| CRITICAL | 0     | — |
| HIGH     | 6     | Private imports, undocumented API usage, stale paths, dual dispatch paths |
| MEDIUM   | 9     | Stale `lib.` path references, unexported types, sync subprocess, state init |
| LOW      | 4     | Minimal facade, auth stub, hardcoded version, string status fields |

### Assessment

The API module is well-structured after the ADR-019 service separation. The gateway pattern is clean — no graph execution runs locally, all work dispatches to the worker via HTTP. The schemas subpackage is comprehensive with proper discriminated unions and Pydantic models.

The main concerns are:

1. **HIGH-06**: The dual dispatch paths (WS vs REST) construct payloads differently, with the WS path bypassing `DispatchRequest` validation entirely. This will cause silent divergence as `DispatchRequest` evolves.
2. **HIGH-03**: Using the undocumented `checkpointer.aget()` instead of the documented `aget_tuple()` API.
3. **Stale paths**: 4 separate docstrings still reference `lib.*` instead of `vaultspec_a2a.*`.

### Recommended Fix Priority

1. **HIGH-06**: Unify WS and REST dispatch paths to both use `DispatchRequest.model_dump()`.
2. **HIGH-01**: Export `_build_initial_vault_index` as a public function from `core/__init__.py`.
3. **HIGH-03**: Switch from `checkpointer.aget()` to `checkpointer.aget_tuple()`.
4. **MED-01/02/03/04**: Batch update stale `lib.*` path references in docstrings.

---

## Cycle 2 — Dual Aggregator Deep Dive (2026-03-06)

**Focus areas** (per team-lead brief):

1. `app.py` lifespan — how EventAggregator is wired
2. `endpoints.py` — REST handlers reading aggregator state (stale/empty data?)
3. `websocket.py` — how WS subscribers get wired
4. `schemas/events.py` — discriminated union verification
5. Stale `lib.` imports (cross-check)

---

### Verified Fixes from Cycle 1

| Finding | Status | Notes |
|---------|--------|-------|
| HIGH-03 | **FIXED** | `endpoints.py:590-591` now uses `checkpointer.aget_tuple(config)` — documented API |
| HIGH-04 | **PARTIALLY FIXED** | `_MinimalState` still defined inside function body (line 600), but constructor param renamed from `config` to `cfg` to avoid shadow |

---

### NEW CRITICAL Findings

#### CRIT-01: REST handlers return stale/empty aggregator data until worker relays `graph_registered`

**Root cause:** The API-side `EventAggregator` (created at `app.py:254`) starts with ZERO state:

- `_node_metadata = {}` — populated ONLY when `sync_worker_event()` receives a `graph_registered` event from the worker (aggregator.py:891-908)
- `_agent_states = {}` — empty until `sync_worker_event()` processes `agent_status` events
- `_pending_permissions = {}` — empty until `sync_worker_event()` processes `permission_request`
- `_sequences = defaultdict(int)` — zero for all threads until events arrive

**Key dependency:** `sync_worker_event()` handles 4 event types: `agent_status`, `permission_request`, `permission_resolved`, and `graph_registered` (BE-12). The `graph_registered` event populates `_node_metadata` which `get_node_summaries()` reads. **However, the worker must explicitly emit this event** — if the worker fails to relay `graph_registered` after graph compilation, the API aggregator's `agents` list stays empty.

##### Affected REST endpoints

1. **`GET /team/status`** (`endpoints.py:732-773`): Returns `agents: []` until the worker sends `graph_registered`. After that, agent metadata (role, display_name, description) is available, but lifecycle states only appear after `agent_status` events.

2. **`GET /threads/{id}/state`** (`endpoints.py:555-639`): `last_sequence` is 0 until worker events arrive (sequences only advance for `agent_status` and `permission_request/resolved` events — NOT for message_chunk, tool_call, etc.). The `agents` and `pending_permissions` snapshots have the same dependency on relay timing.

**Impact:** Between thread creation and the first worker event relay, ALL REST aggregator queries return empty/zero data. The `last_sequence` field is unreliable for gap detection (ADR-011 S2.3) because it only advances for 3 of 12 event types.

**Severity:** CRITICAL — sequence counter gap makes reconnection unreliable; REST endpoints return stale data during the initial relay window.

---

### NEW HIGH Findings

#### HIGH-07: `sync_worker_event()` only handles 4 event types, silently drops the rest

**File:** `aggregator.py:829-908`

`sync_worker_event()` processes:

- `agent_status` → updates `_agent_states`, advances sequence
- `permission_request` → stores in `_pending_permissions`, advances sequence
- `permission_resolved` → removes from `_pending_permissions`, advances sequence
- `graph_registered` → populates `_node_metadata` (BE-12), does NOT advance sequence

All other event types (`message_chunk`, `tool_call_start`, `tool_call_update`, `plan_update`, `error`, `artifact_update`, `thought_chunk`) are silently dropped. This means:

- `get_sequence()` only advances for 3 of 12 event types — making `last_sequence` unreliable for gap detection
- `graph_registered` does not advance sequence either (no thread_id context)
- Any REST endpoint relying on aggregator state for non-agent/permission data gets stale results

#### HIGH-08: `broadcast_to_thread()` bypasses aggregator event queue

**File:** `websocket.py:506-537`

`broadcast_to_thread()` sends events directly to WebSocket clients via `websocket.send_json(payload)`, completely bypassing the aggregator's `_broadcast()` / queue mechanism. This means:

- Events sent via `broadcast_to_thread()` do NOT get sequence numbers stamped by the aggregator
- The `_writer_loop()` (which drains the aggregator queue) and `broadcast_to_thread()` can race on the same WebSocket connection — no ordering guarantee between aggregator-queued events and relay-broadcast events
- The aggregator's `_broadcast_hooks` are not invoked for relay events

This is by design (the docstring says "without round-tripping through the EventAggregator queue machinery"), but it creates a dual delivery path where some events go through the queue and others bypass it.

#### HIGH-09: `api/__init__.py` facade docstring references old `lib.*` paths

**File:** `api/__init__.py:5-6`

```python
They depend on ``lib.core.aggregator``, which in turn imports from
``lib.api.schemas``, creating a circular import if exposed here.
```text

Should be `vaultspec_a2a.core.aggregator` and `vaultspec_a2a.api.schemas`.

#### HIGH-10: 10 stale `lib.` path references across api/ module (including tests)

##### Files and locations

1. `websocket.py:511` — `lib.api.internal`
2. `internal.py:9` — `lib.worker.ipc`
3. `__init__.py:5-6` — `lib.core.aggregator`, `lib.api.schemas`
4. `schemas/enums.py:7` — `lib.utils.enums`
5. `schemas/enums.py:58` — `lib.utils.enums.AgentState`
6. `schemas/__init__.py:3` — `lib.api.schemas`
7. `tests/test_supervisor.py:55` — `python -m lib.worker`
8. `tests/test_websocket.py:404` — `lib.api`
9. `tests/__init__.py:1` — `lib.api`

All should reference `vaultspec_a2a.*` paths. Consolidating MED-01/02/03/04 from Cycle 1 and extending with newly found references.

---

### NEW MEDIUM Findings

#### MED-10: `ConnectedEvent.active_threads` returns subscription-based thread list, not DB-based

**File:** `websocket.py:148`

```python
active_threads=self._aggregator.get_active_thread_ids(),
```yaml

`get_active_thread_ids()` (aggregator.py:397-406) returns threads that have at least one WS subscriber. On first client connection, this is always `[]` (no one is subscribed yet). The client receives `active_threads: []` even if there are running threads in the database. This makes the `ConnectedEvent` useless for the frontend's initial thread list hydration.

#### MED-11: `_writer_loop` has duck-type fallback for non-Pydantic events

**File:** `websocket.py:455-459`

```python
payload = (
    event.model_dump(mode="json")
    if hasattr(event, "model_dump")
    else event
)
```text

The `hasattr(event, "model_dump")` check suggests non-Pydantic objects can enter the queue. But `asyncio.Queue[ServerEvent]` type annotation says only `ServerEvent` (all Pydantic models) should enter. Either the type annotation is wrong or the duck-type fallback is dead code.

#### MED-12: `_handle_permission_response` thread_id extraction is fragile

**File:** `websocket.py:345-347`

```python
_req_id = cmd.request_id or ""
_thread_id = _req_id.split(":", 1)[0] if ":" in _req_id else ""
```text

This parsing assumes `request_id` format is `{thread_id}:{uuid}`. If the format changes, this silently produces wrong thread_ids. Same pattern exists in `respond_to_permission_endpoint` at `endpoints.py:846-848`. Should have a shared utility or documented format contract.

---

### Discriminated Union Verification (schemas/events.py)

Status: CORRECT

The `ServerEvent` union at `events.py:257-271` uses `Field(discriminator="type")` with each member having a `Literal[ServerEventType.X]` type field. This enables O(1) dispatch via Pydantic's discriminated union mechanism. Verified all 12 event types have proper `Literal` discriminators:

| Event | Discriminator | Base |
|-------|--------------|------|
| AgentStatusEvent | `Literal[ServerEventType.AGENT_STATUS]` | EventEnvelope |
| MessageChunkEvent | `Literal[ServerEventType.MESSAGE_CHUNK]` | EventEnvelope |
| ThoughtChunkEvent | `Literal[ServerEventType.THOUGHT_CHUNK]` | EventEnvelope |
| ToolCallStartEvent | `Literal[ServerEventType.TOOL_CALL_START]` | EventEnvelope |
| ToolCallUpdateEvent | `Literal[ServerEventType.TOOL_CALL_UPDATE]` | EventEnvelope |
| PermissionRequestEvent | `Literal[ServerEventType.PERMISSION_REQUEST]` | EventEnvelope |
| ArtifactUpdateEvent | `Literal[ServerEventType.ARTIFACT_UPDATE]` | EventEnvelope |
| PlanUpdateEvent | `Literal[ServerEventType.PLAN_UPDATE]` | EventEnvelope |
| TeamStatusEvent | `Literal[ServerEventType.TEAM_STATUS]` | EventEnvelope |
| ErrorEvent | `Literal[ServerEventType.ERROR]` | EventEnvelope |
| ConnectedEvent | `Literal[ServerEventType.CONNECTED]` | BaseModel |
| HeartbeatEvent | `Literal[ServerEventType.HEARTBEAT]` | BaseModel |

Connection-scoped events (Connected, Heartbeat) correctly extend `BaseModel` directly (no thread_id/sequence). Thread-scoped events extend `EventEnvelope` which provides `thread_id`, `agent_id`, `timestamp`, `sequence`.

---

### WebSocket Subscriber Wiring (websocket.py)

Status: CORRECT but dual-path

The `ConnectionManager` is wired at `app.py:257`:

```python
cm = ConnectionManager(aggregator)
app.state.connection_manager = cm
```text

Subscriber lifecycle:

1. **connect()** (line 129): Accepts WS, generates `client_id`, calls `aggregator.add_subscriber(client_id)` to get a dedicated `asyncio.Queue[ServerEvent]`, starts heartbeat + writer tasks
2. **listen()** (line 208): Read loop dispatching client commands (SUBSCRIBE, UNSUBSCRIBE, SEND_MESSAGE, etc.)
3. **disconnect()** (line 182): Cancels tasks, calls `aggregator.remove_subscriber(client_id)`, removes connection

**Dual delivery path:** Events reach WS clients via TWO independent paths:

1. **Aggregator queue path**: `aggregator._broadcast()` → per-subscriber `Queue.put()` → `_writer_loop()` → `websocket.send_json()`
2. **Internal relay path**: `internal.py` → `cm.broadcast_to_thread()` → direct `websocket.send_json()`

In the ADR-019 architecture, path (2) is the primary delivery mechanism (worker events relayed via internal WS/HTTP). Path (1) is used for API-originated events like `emit_agent_status` (fallback on dispatch failure) or `emit_team_status`.

This dual path means a client can receive the same logical event twice if both paths fire for the same event — no dedup mechanism exists on either side.

---

### EventAggregator Wiring (app.py lifespan)

Summary for coder implementing Task #11 fix:

```text
app.py:254  aggregator = EventAggregator()        # empty, no graphs
app.py:255  app.state.aggregator = aggregator      # stored on app.state
app.py:257  cm = ConnectionManager(aggregator)     # WS manager holds ref
app.py:258  app.state.connection_manager = cm      # stored on app.state

internal.py:89-107  (WS relay):
  cm = request.app.state.connection_manager
  agg = request.app.state.aggregator
  → cm.broadcast_to_thread(thread_id, payload)  # direct to WS clients
  → agg.sync_worker_event(thread_id, payload)   # update API aggregator state

internal.py:128-161  (HTTP POST relay):
  → same pattern: broadcast_to_thread + sync_worker_event
```text

The aggregator's `sync_worker_event()` is the ONLY mechanism that populates API-side state from worker events. It handles `agent_status`, `permission_request`, and `team_status` event types. All other event types are silently dropped (HIGH-07).

---

## Cycle 2 Summary

| Severity | New | Previously Open | Key Themes |
|----------|-----|-----------------|------------|
| CRITICAL | 1   | 0               | Empty aggregator state on REST endpoints |
| HIGH     | 4   | 6               | sync_worker_event gaps, dual delivery path, stale paths |
| MEDIUM   | 3   | 9               | Active threads semantics, duck-type fallback, fragile parsing |
| LOW      | 0   | 4               | — |

Total open: 1 CRIT, 10 HIGH, 12 MED, 4 LOW

### Key Findings for Task #11 (Dual Aggregator Fix)

1. **CRIT-01**: REST endpoints return empty/stale data until worker relays events. `last_sequence` only advances for 3 of 12 event types, making reconnection gap detection unreliable.

2. **HIGH-07**: `sync_worker_event()` handles 4 event types (`agent_status`, `permission_request`, `permission_resolved`, `graph_registered`), silently drops 8 others. Sequence advancement is incomplete.

3. **HIGH-08**: WS events delivered via dual paths (aggregator queue vs direct relay) with no dedup, no shared sequence counter, and potential race conditions.

4. **Fix guidance**: The `sync_worker_event()` method needs to:
   - Advance sequence for ALL relayed event types (not just agent_status/permission)
   - Ensure `graph_registered` is emitted by the worker after every graph compilation
   - Consider unifying the dual WS delivery paths or adding sequence stamping to the relay path

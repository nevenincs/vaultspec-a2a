---
title: Derisking Coding Challenges — Event Pipeline Implementation
date: 2026-03-06
type: research
related:
  - docs/adrs/011-frontend-backend-contract.md
  - docs/adrs/019-teamstate-enrichment-sdd-blackboard.md
  - docs/adrs/021-persistent-task-queue-schema.md
  - docs/adrs/031-worker-process-architecture.md
---

## Derisking Coding Challenges: Event Pipeline Implementation

This document addresses four implementation risk areas in the multi-layer event
pipeline: LangGraph `astream_events` -> EventAggregator -> WorkerBridge -> API
WS relay -> frontend Zustand/TanStack Query.

## 1. ACP Tool Output Parsing

### 1.1 ACP Tool Call Structure (from Toad protocol.py)

The ACP `session/update` notification carries `ToolCall` and `ToolCallUpdate`
payloads with these fields:

```python
class ToolCall(TypedDict, total=False):
    toolCallId: str          # Unique ID
    title: str               # Human-readable tool name
    kind: ToolKind           # "read" | "edit" | "delete" | "move" | "search" | "execute" | "think" | "fetch" | "switch_mode" | "other"
    status: ToolCallStatus   # "pending" | "in_progress" | "completed" | "failed"
    content: list[ToolCallContent]  # Rich content blocks (see below)
    locations: list[ToolCallLocation]  # File path + optional line number
    rawInput: dict           # Raw tool arguments
    rawOutput: dict          # Raw tool result
    sessionUpdate: Literal["tool_call"]
```text

### 1.2 ToolCallContent Types

Three content block types exist:

| Type | Fields | Use Case |
|------|--------|----------|
| `content` | `{type: "content", content: {type: "text", text: "..."}}` | Text output (command results, explanations) |
| `diff` | `{type: "diff", path: "...", oldText: "...", newText: "..."}` | File edits with unified diff |
| `terminal` | `{type: "terminal", terminalId: "..."}` | Terminal session reference |

### 1.3 Detecting File-Modifying Tools

Use `kind` field for classification:

- **File writes**: `kind == "edit"` or `kind == "delete"` or `kind == "move"`
- **File reads**: `kind == "read"` or `kind == "search"`
- **Terminal**: `kind == "execute"`
- **Content with diff**: presence of `content` blocks with `type: "diff"`

For `ArtifactUpdateEvent` emission, detect:

1. `tool_call_update` with `status == "completed"` AND `kind in ("edit", "delete", "move")`
2. OR presence of `diff` content blocks in the `content` list
3. Extract `locations[0].path` as the artifact filename

### 1.4 Current Gap in AcpChatModel

`acp_chat_model.py` receives full `ToolCall`/`ToolCallUpdate` dicts via
`_on_tool_call` (line 1010) and `_on_tool_call_update` (line 1033), storing them
in `self._tool_calls[tid]`. However, it only forwards `toolCallId`, `title`, and
`input` as LangChain `ToolCallChunk` — the `kind`, `content`, `locations`, and
`status` fields are **discarded** before reaching LangGraph's `astream_events`.

**Implication**: The aggregator's `on_tool_start`/`on_tool_end` handlers cannot
extract rich content because it was stripped at the provider layer.

### 1.5 Fix Strategy

**Option A (Recommended): ACP-specific event emission in AcpChatModel**

Add a callback or event hook in `AcpChatModel` that emits wire events directly
when `tool_call`/`tool_call_update` session updates arrive, bypassing the
LangGraph `astream_events` pipeline for tool-specific data:

```python
# In _on_tool_call_update:
if self._event_hook and update.get("status") == "completed":
    kind = update.get("kind", "other")
    if kind in ("edit", "delete", "move"):
        # Emit ArtifactUpdateEvent via hook
        self._event_hook("artifact", {
            "filename": (update.get("locations") or [{}])[0].get("path", ""),
            "content": ...,  # extract from content blocks
        })
```yaml

**Option B: Stash rich data in AIMessageChunk.additional_kwargs**

In `_on_tool_call`, store the full ACP payload in `additional_kwargs` on the
`AIMessageChunk` so it survives through LangGraph to `on_tool_start`:

```python
chunk = ChatGenerationChunk(
    message=AIMessageChunk(
        content="",
        tool_call_chunks=[...],
        additional_kwargs={"acp_tool_call": dict(update)},
    )
)
```text

The aggregator can then inspect `chunk.additional_kwargs.get("acp_tool_call")`
in `on_tool_start`/`on_tool_end`. Risk: LangChain may strip or merge
`additional_kwargs` during chunk accumulation.

## 2. LangGraph State Diffing Patterns

### 2.1 Available Approaches

LangGraph does not provide a built-in state-diff callback. Three patterns exist:

**Pattern A: `stream_mode="updates"` (alternative to astream_events)**

`graph.astream(input, config, stream_mode="updates")` yields per-node state
deltas:

```python
async for chunk in graph.astream(input, config, stream_mode="updates"):
    # chunk = {"node_name": {"current_plan": [...], "artifacts": [...]}}
    print(chunk)
```text

This yields ONLY the fields a node returned — exactly the state diff. However,
using this mode means giving up `astream_events` (which provides token-level
streaming). The two modes can be combined:

```python
async for chunk in graph.astream(
    input, config,
    stream_mode=["messages", "updates"],
):
    # chunk is a tuple: (stream_mode, data)
    pass
```yaml

**Pattern B: Cache + compare in aggregator**

The aggregator maintains a per-thread state cache. On `on_chain_end` events
where `node` is known, compare `event_data["data"]["output"]` fields against
the cached state. Emit events for changed fields.

```python
# In process_langgraph_event, on_chain_end handler:
if node and event_kind == "on_chain_end":
    output = event_data.get("data", {}).get("output", {})
    new_plan = output.get("current_plan")
    if new_plan is not None and new_plan != self._cached_plan.get(thread_id):
        self._cached_plan[thread_id] = new_plan
        await self._emit_plan_update(thread_id, new_plan)
```yaml

**Risk**: `on_chain_end` `data.output` may contain the full state (not just the
node's return value) depending on the LangGraph version and graph structure.
Testing required to verify exact payload shape.

**Pattern C: Custom events via StreamWriter**

Nodes explicitly emit plan/artifact changes using `get_stream_writer()`:

```python
from langgraph.config import get_stream_writer

def supervisor_node(state):
    writer = get_stream_writer()
    new_plan = compute_plan(state)
    writer({"type": "plan_update", "entries": new_plan})
    return {"current_plan": new_plan}
```text

The aggregator's `on_custom_event` handler picks these up. This is the most
explicit and reliable pattern, but requires modifying every node that changes
plan/artifact state.

### 2.2 Recommendation

Use **Pattern B** (cache + compare) as the primary mechanism with **Pattern C**
(StreamWriter) as a supplement for nodes where precise timing matters. Pattern B
requires no node-level changes and works with the existing `astream_events` v2
pipeline. Pattern A (`stream_mode="updates"`) would require a significant
refactor of the ingest loop.

**Note**: The coder has already implemented Pattern B for PlanUpdateEvent
(Task #21) by inspecting `on_chain_end` output for `current_plan` changes.
The same pattern applies to artifacts.

## 3. Mock-Seeder to Event Pipeline Migration

### 3.1 Current State

`docker/run.py` (mock-seeder) calls `graph.astream(inputs, config,
stream_mode="values")` directly — bypassing EventAggregator, WorkerBridge, and
WS relay entirely. Mock threads write to DB but produce no WebSocket events.

### 3.2 Three Migration Options

| Option | Description | Complexity | Fidelity |
|--------|-------------|------------|----------|
| **A: REST API client** | Mock-seeder POSTs to `POST /api/threads` on the API server. API dispatches to worker. Full production pipeline fires. | Low | 100% |
| **B: Embedded aggregator** | Mock-seeder creates its own `EventAggregator` + HTTP relay hook POSTing to `POST /internal/events`. Uses `aggregator.ingest()` instead of `graph.astream()`. | Medium | ~90% |
| **C: Worker dispatch** | Mock-seeder POSTs `DispatchRequest(action="ingest")` to `http://worker:8001/dispatch`. | Low | 100% |

### 3.3 Recommendation: Option A

Rewrite `execute_mock_team()` as an HTTP client:

```python
async def execute_mock_team(api_base: str, preset_id: str) -> None:
    async with httpx.AsyncClient(base_url=api_base) as client:
        resp = await client.post("/api/threads", json={
            "initial_message": f"Execute mock protocol for {preset_id}.",
            "title": f"Mock: {preset_id}",
            "team_preset": preset_id,
        })
        resp.raise_for_status()
        thread_id = resp.json()["thread_id"]
        logger.info("Created mock thread %s for preset %s", thread_id, preset_id)
```text

Changes required:

- `docker/run.py`: Replace graph compilation + `astream()` with HTTP POST
- `docker-compose.dev.yml`: Add `depends_on: api` to mock-seeder service
- Environment: Add `API_BASE_URL=http://api:8000` to mock-seeder env

Benefits:

- Zero duplication of event pipeline logic
- Mock threads are indistinguishable from real threads in the frontend
- Mock-seeder becomes a thin "scenario driver" (~30 lines)

## 4. WebSocket Reconnection State Recovery

### 4.1 ADR-011 §2.3 Reconnect Protocol

The ADR specifies 7 steps. Steps 3-4 (re-fetch state snapshots, record
`last_sequence`) are currently NOT implemented.

### 4.2 Current Behavior on Reconnect

1. WS closes -> `handleClose()` -> state='reconnecting' -> scheduleReconnect()
2. WS reconnects -> server sends `ConnectedEvent(active_threads=[...])`
3. WS client re-subscribes (sends `SubscribeCommand`) -- DONE
4. **State snapshots NOT re-fetched** -- MISSING
5. Zustand still has stale `streamEvents` -- STALE
6. TQ cache still has stale data -- STALE
7. `useThreadStateQuery` has `enabled: !hasEvents` guard -- BLOCKS REFETCH

### 4.3 State That Survives Reconnect

| State | Location | Survives? | Problem |
|-------|----------|-----------|---------|
| `subscribedThreads` | wsClient Set | YES | Correct |
| `lastSequences` | wsClient Map | YES | Stale — events during gap are lost |
| `streamEvents[threadId]` | Zustand | YES | Stale — timeline has a hole |
| TQ thread state cache | queryClient | YES | Stale |
| `hasEvents` selector | Zustand | YES (true) | BLOCKS TQ refetch |

### 4.4 Minimal Fix (3 files)

**A. `ws-bridge.ts` — Add reconnect handler:**

```typescript
wsClient.setConnectedCallback((connectedEvent) => {
  const subscribedThreads = wsClient.getSubscribedThreadIds();
  for (const threadId of subscribedThreads) {
    // Clear stale Zustand events (unblocks TQ refetch)
    appStore.getState().clearThreadEvents(threadId);
    // Invalidate TQ thread state query (triggers refetch)
    queryClient.invalidateQueries({ queryKey: queryKeys.threads.state(threadId) });
  }
  // Refresh entity queries
  queryClient.invalidateQueries({ queryKey: queryKeys.threads.list() });
  queryClient.invalidateQueries({ queryKey: queryKeys.team.status() });
});
```text

**B. `websocket-client.ts` — Expose subscribed thread IDs:**

```typescript
getSubscribedThreadIds(): string[] {
  return [...this.subscribedThreads];
}
```text

**C. `use-thread-state.ts` — No changes needed.**

The existing `enabled: !hasEvents` guard works correctly once
`clearThreadEvents()` is called. After clearing, `hasEvents=false` unblocks the
TQ query. The query refetches the snapshot, calls `hydrateThreadEvents()`, which
rebuilds Zustand events and updates `lastSequence` on the WS client.

### 4.5 Sequence of Events After Fix

1. WS closes -> reconnecting -> scheduleReconnect()
2. WS reconnects -> `ConnectedEvent` received
3. Bridge `onConnected` fires:
   a. `clearThreadEvents(threadId)` for each subscribed thread
   b. `invalidateQueries(threads.state(threadId))`
4. WS client sends `SubscribeCommand` (existing behavior)
5. React re-renders -> `useThreadStateQuery` fires REST fetch
6. `queryFn` fetches `GET /threads/{id}/state` -> snapshot + `last_sequence`
7. `hydrateThreadEvents()` rebuilds Zustand + `wsClient.updateLastSequence()`
8. New WS events with `sequence > lastSequence` pass through; stale filtered

### 4.6 Edge Cases

- **Thread completed during disconnect**: Snapshot shows final state. No gap.
- **Thread still streaming**: Snapshot provides events up to `last_sequence`.
  WS picks up from there. Sequence filtering prevents duplicates.
- **Rapid reconnect flapping**: `clearThreadEvents` + `invalidateQueries` is
  safe even if called multiple times. TQ deduplicates concurrent fetches.

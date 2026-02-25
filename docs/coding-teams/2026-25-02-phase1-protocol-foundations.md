# Phase 1 Deliverable: Protocol Foundations for Control Surface

**Date**: 2026-02-25
**Phase**: 1 (Protocol Foundations)
**Status**: Complete

---

## 1. A2A SSE Event Capabilities → UI Render Mapping

### 1.1 What the wire carries

A2A SSE streams are `data: {json-rpc}\n\n` formatted. No named events, no
event IDs. Each payload is a JSON-RPC 2.0 response wrapping one of:

| Event Type | What It Contains | UI Render Capability |
|---|---|---|
| `Task` | Full task state snapshot (status, history, artifacts, metadata) | Full panel refresh: status badge, message history, artifact list |
| `TaskStatusUpdateEvent` | State change + optional `Message` with `Part[]` + `final` flag | Status badge update, progress text, "agent is thinking/working" indicator |
| `TaskArtifactUpdateEvent` | `Artifact` with `Part[]` + `append` flag + `last_chunk` flag | Code file streaming (append chunks), file list update, completion indicator |
| `Message` | Direct response (role, parts, metadata) | Chat message bubble, immediate response rendering |

### 1.2 What the status message actually is

`TaskStatusUpdateEvent.status.message` is **not free text**. It is a full
`Message` object with `role`, `parts[]`, `metadata`. Each `Part` can be:

- `text` (string) — agent's progress description
- `raw` (bytes) — binary data
- `url` (string) — reference to external resource
- `data` (JSON value) — structured data

This means status updates can carry rich content for UI rendering — not just
"working..." strings.

### 1.3 Artifact streaming mechanics

File artifacts stream via multiple `TaskArtifactUpdateEvent` messages:

```
Event 1: {artifactId: "abc", append: false, lastChunk: false, parts: [{text: "def foo():"}]}
Event 2: {artifactId: "abc", append: true,  lastChunk: false, parts: [{text: "    return 42"}]}
Event 3: {artifactId: "abc", append: true,  lastChunk: true,  parts: [{text: "\n# done"}]}
```

- Same `artifactId` = same file
- `append: true` = concatenate with previous
- `lastChunk: true` = file complete
- `Part.filename` and `Part.media_type` identify the file

### 1.4 Connection model

**One SSE connection per task.** No multiplexing.

For a multi-agent control surface, this means:
- N agents with M concurrent tasks = up to M SSE connections
- Each connection must be independently managed
- The orchestrator (not the web client) should maintain these connections
  and fan out events over a single WebSocket to the browser

### 1.5 Reconnection

A2A provides `tasks/resubscribe` (JSON-RPC) / `GET /v1/tasks/{id}:subscribe`
(REST). On reconnect:

1. Client calls resubscribe with task ID
2. Server returns current task state as first event
3. Stream continues from that point
4. **Events during disconnection are NOT replayed**

This means the client must call `GetTask` after reconnect to catch up on
any missed state changes.

### 1.6 Multi-subscriber support

`EventQueue.tap()` creates child queues that receive all future events.
Multiple server-side consumers can subscribe to the same task's events.
This enables the orchestrator to:
- Maintain its own event processing
- Fan out to multiple web clients
- Log/persist events independently

---

## 2. ACP Web-Native Host Feasibility

### 2.1 Transport abstraction: confirmed

ACP's `Connection` class accepts `asyncio.StreamReader/StreamWriter` — it is
**not hardwired to stdio**. The SDK only ships a stdio transport
(`spawn_stdio_transport()`), but the protocol layer is completely transport-
agnostic.

Replacing stdio with WebSocket requires only a thin adapter (~100 lines):

```python
class WebSocketStreamReader:
    async def readline(self) -> bytes:
        msg = await websocket.receive_str()
        return (msg + "\n").encode()

class WebSocketStreamWriter:
    async def write(self, data: bytes) -> None:
        await websocket.send_str(data.decode().rstrip("\n"))
```

**Verdict**: Web-native ACP host is 100% feasible with no protocol changes.

### 2.2 Session notification types (11 update types)

ACP streams 11 discriminated update types via `session/update`:

| Update Type | Discriminator | UI Rendering |
|---|---|---|
| `UserMessageChunk` | `user_message_chunk` | User chat bubble |
| `AgentMessageChunk` | `agent_message_chunk` | Agent chat bubble (streaming) |
| `AgentThoughtChunk` | `agent_thought_chunk` | Thinking/reasoning panel |
| `ToolCallStart` | `tool_call` | Tool call card (name, status) |
| `ToolCallProgress` | `tool_call_update` | Tool call progress bar / output |
| `AgentPlanUpdate` | `plan` | Plan checklist / step list |
| `AvailableCommandsUpdate` | `available_commands_update` | Command palette |
| `CurrentModeUpdate` | `current_mode_id` | Mode indicator badge |
| `ConfigOptionUpdate` | `config_option_update` | Settings panel |
| `SessionInfoUpdate` | `session_info_update` | Session metadata (title, etc.) |
| `UsageUpdate` | `usage_update` | Token/cost counter |

This is **far richer** than A2A's streaming. ACP distinguishes between
agent messages, thinking, tool calls, and plan updates at the protocol level.
A2A collapses everything into `Message.parts[]`.

### 2.3 SessionAccumulator as UI state source

`SessionAccumulator` merges streaming notifications into immutable
`SessionSnapshot` objects:

```
SessionSnapshot:
  session_id: str
  tool_calls: dict[str, ToolCallView]     ← all tool calls by ID
  plan_entries: tuple[PlanEntry, ...]      ← current plan
  current_mode_id: str | None
  available_commands: tuple[AvailableCommand, ...]
  user_messages: tuple[UserMessageChunk, ...]
  agent_messages: tuple[AgentMessageChunk, ...]
  agent_thoughts: tuple[AgentThoughtChunk, ...]
```

Snapshots are frozen (immutable). Each `apply()` returns a new snapshot.
Subscribers receive `(snapshot, notification)` pairs.

**For multi-agent control surface**: One `SessionAccumulator` per agent.
Each produces canonical UI state. The web client subscribes to all
accumulators. No manual state merging needed.

### 2.4 Permission flow

ACP permissions use blocking RPC: agent calls `session/request_permission`,
the coroutine `await`s, client shows modal, user responds, response unblocks
the agent. Execution pause is implicit in Python's `async/await`.

For a web host: the WebSocket adapter receives the permission RPC, pushes
it to the browser as a WebSocket message, browser shows modal, user clicks,
browser sends response via WebSocket, adapter routes response back to the
`Connection`, agent resumes.

---

## 3. WebSocket Protocol Design (Preliminary)

### 3.1 Architecture

```
Browser ←—WebSocket—→ Control Surface Server ←—SSE/stdio—→ Agents
          (single)                              (per-agent)
```

The server maintains per-agent connections (A2A SSE or ACP stdio) and
multiplexes all events onto a single WebSocket to the browser. The browser
sends commands (messages, permissions, lifecycle) back over the same
WebSocket.

### 3.2 Message format (preliminary)

**Server → Browser (events):**
```json
{
  "type": "agent_event",
  "agent_id": "coder-a",
  "event_type": "status_update",
  "data": { ... }
}
```

**Server → Browser (permissions):**
```json
{
  "type": "permission_request",
  "agent_id": "coder-a",
  "request_id": "req-123",
  "tool_call": { "title": "Delete old_auth.py", "kind": "write" },
  "options": [
    {"id": "approve", "label": "Approve", "kind": "allow_once"},
    {"id": "reject", "label": "Reject", "kind": "reject_once"}
  ]
}
```

**Browser → Server (commands):**
```json
{
  "type": "send_message",
  "agent_id": "coder-a",
  "message": "Also add input validation"
}

{
  "type": "permission_response",
  "request_id": "req-123",
  "decision": "approve"
}

{
  "type": "agent_control",
  "agent_id": "coder-a",
  "action": "terminate"
}
```

### 3.3 Channel multiplexing

Following Grafana Live's pattern: all agent subscriptions multiplexed on
one WebSocket. Messages carry `agent_id` for routing. Browser-side
dispatcher routes to per-agent UI components.

---

## 4. Key Architectural Insight

**ACP is the richer protocol for control surface purposes.** Its 11 update
types, SessionAccumulator, PermissionBroker, and ToolCallTracker provide
exactly the abstractions a control surface needs. A2A's SSE streaming is
simpler but less structured.

The recommended approach:
- **Agent processes**: Speak ACP (for rich streaming) or A2A (for protocol
  compliance). The control surface server adapts both.
- **Control surface server**: Maintains per-agent connections, runs
  SessionAccumulator per agent, multiplexes onto WebSocket.
- **Browser client**: Receives typed events, renders per-agent panels from
  SessionSnapshot state, sends commands/permissions back.

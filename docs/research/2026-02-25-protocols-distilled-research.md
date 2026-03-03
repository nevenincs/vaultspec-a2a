---
name: 'Protocols Domain - Distilled'
date: 2026-25-02
type: distilled
summary: 'Wire-level protocol details for A2A, MCP, and ACP. SSE event format, state mapping tables, artifact streaming mechanics, reconnection behavior, WebSocket protocol design. Complements the architecture distilled doc (which covers protocol-level architectural decisions).'
maturity: 45
sources:
  - docs/protocols/2026-25-02-phase1-protocol-foundations.md
  - docs/protocols/2026-25-02-mcp-tasks-a2a-compliance-research.md
feature: protocols-distilled
---

# Protocols Domain — Distilled

> [!WARNING]
> **DEPRECATION NOTICE: LANGGRAPH MIGRATION (2026-02-26)**
> The protocol strategies described in this document (A2A SSE streaming, ACP
> translation) have been superseded by native LangGraph streaming
> (`astream_events`) and MCP tools. This document remains for historical context.
> Please refer to ADR-003, ADR-004, and ADR-006 for the current binding
> architecture.

**Date**: 2026-02-25
**Status**: Distilled from Phase 1 protocol foundations + MCP/A2A compliance
**Scope**: Wire-level protocol mechanics (not architectural decisions — see
architecture distilled doc for those)

---

## 1. A2A Wire Protocol

### 1.1 SSE Stream Format

A2A SSE streams use `data: {json-rpc}\n\n`format. No named events. No event
IDs. Each payload is a JSON-RPC 2.0 response wrapping one of four event types:

| Event Type                | Payload                                                         | UI Capability                  |
| ------------------------- | --------------------------------------------------------------- | ------------------------------ |
| `Task`                    | Full task state snapshot (status, history, artifacts, metadata) | Full panel refresh             |
| `TaskStatusUpdateEvent`   | State change + optional`Message`with`Part[]`+`final`flag        | Status badge, progress text    |
| `TaskArtifactUpdateEvent` | `Artifact`with`Part[]`+`append`flag +`last_chunk`flag           | Code file streaming, file list |
| `Message`                 | Direct response (role, parts, metadata)                         | Chat message bubble            |

### 1.2 Status Messages Are Rich

`TaskStatusUpdateEvent.status.message`is a full`Message`object (not free
text). Each`Part`can be:

-`text`(string) — progress description -`raw`(bytes) — binary data -`url`(string) — external resource reference -`data`(JSON) — structured data

Status updates can carry rich content for UI rendering, not just "working..."
strings.

### 1.3 Artifact Streaming Mechanics

File artifacts stream via multiple`TaskArtifactUpdateEvent` messages:

```text
Event 1: {artifactId: "abc", append: false, lastChunk: false, parts: [{text: "def foo():"}]}
Event 2: {artifactId: "abc", append: true,  lastChunk: false, parts: [{text: "    return 42"}]}
Event 3: {artifactId: "abc", append: true,  lastChunk: true,  parts: [{text: "\n# done"}]}
```

- Same `artifactId`= same file -`append: true`= concatenate with previous chunks -`lastChunk: true`= file complete -`Part.filename`and`Part.media_type` identify the file

### 1.4 Connection Model

**One SSE connection per task.** No multiplexing at the A2A level.

For a multi-agent system with N agents and M concurrent tasks: up to M SSE
connections, each independently managed. The orchestrator (not the browser)
maintains these and fans out over a single WebSocket.

### 1.5 Multi-Subscriber Support

`EventQueue.tap()` creates child queues receiving all future events. Multiple
server-side consumers can subscribe to the same task. Enables:

- Orchestrator event processing
- Fan-out to multiple web clients
- Independent event logging/persistence

---

## 2. A2A Reconnection

`tasks/resubscribe`(JSON-RPC) or`GET /v1/tasks/{id}:subscribe`(REST).

On reconnect:

1. Client calls resubscribe with task ID
2. Server returns current task state as first event
3. Stream continues from that point
4. **Events during disconnection are NOT replayed**

The client must call`GetTask`after reconnect to recover any missed state.
This is a fundamental limitation: there is no event replay in A2A. The
orchestrator must implement its own event persistence for recovery.

---

## 3. A2A Task States

A2A defines 8 task states:

| State            | Type        | Description              |
| ---------------- | ----------- | ------------------------ |
| `SUBMITTED`      | Initial     | Received but not started |
| `WORKING`        | Active      | Agent is processing      |
| `INPUT_REQUIRED` | Interrupted | Agent needs user input   |
| `AUTH_REQUIRED`  | Interrupted | Agent needs credentials  |
| `COMPLETED`      | Terminal    | Successfully finished    |
| `FAILED`         | Terminal    | Error occurred           |
| `CANCELED`       | Terminal    | Cooperatively cancelled  |
| `REJECTED`       | Terminal    | Agent refused the task   |

Interrupted states are non-terminal — task resumes when client responds with
`SendMessage`carrying the same`task_id`and`context_id`.

Terminal states are immutable — a new task is needed for follow-up work.

### 3.1 A2A Native Async Modes

| Mode               | Mechanism                              | Use Case                                |
| ------------------ | -------------------------------------- | --------------------------------------- |
| Blocking           | `SendMessage(config={blocking=true})`  | Simple, holds connection                |
| Polling            | `GetTask(task_id)`in a loop            | Non-blocking, client controls frequency |
| Push notifications | Webhook URL in`PushNotificationConfig` | Server pushes state changes             |
| SSE streaming      | `sendMessageStream`                    | Real-time event stream                  |

### 3.2 What A2A Deliberately Omits

A2A is a peer-to-peer messaging protocol, not a workflow engine:

- No process management
- No dependency graphs
- No parallelism coordination
- No error recovery/retry
- No timeout enforcement
- No team coordination protocol
- No resource allocation

All orchestration logic is the client's responsibility.

---

## 4. MCP Task States and Mapping

MCP experimental tasks define 5 states:

| MCP State        | A2A State        | Compatible?                         |
| ---------------- | ---------------- | ----------------------------------- |
| `working`        | `WORKING`        | Direct match                        |
| `input_required` | `INPUT_REQUIRED` | Same concept, different wire format |
| `completed`      | `COMPLETED`      | Direct match                        |
| `failed`         | `FAILED`         | Direct match                        |
| `cancelled`      | `CANCELED`       | Spelling difference only            |
| —                | `SUBMITTED`      | No MCP equivalent                   |
| —                | `REJECTED`       | No MCP equivalent                   |
| —                | `AUTH_REQUIRED`  | No MCP equivalent                   |

### 4.1 Translation Rules

**MCP → A2A (clean):** All 5 MCP states map directly.

### A2A → MCP (lossy)

-`SUBMITTED`→`working`+ statusMessage="submitted" -`REJECTED`→`failed`+ statusMessage="rejected" -`AUTH_REQUIRED`→`input_required` (collapsed to generic input request)

### 4.2 Enum Wire Format

```text
MCP:  "status": "working"                    (lowercase)
A2A:  "state": "TASK_STATE_WORKING"          (SCREAMING_SNAKE_CASE, ProtoJSON)
```

Direct string comparison fails. Translation layer must normalize.

### 4.3 Lifecycle Differences

- **MCP**: Tasks go straight to `working`. No submission phase.
- **A2A**: Tasks can sit in `SUBMITTED` before processing starts (meaningful
  for queued systems).
- **Both**: Terminal states are immutable.

---

## 5. MCP Experimental Tasks — Status

### 5.1 Implementation Completeness

Despite "experimental" labeling, the implementation is functionally complete:

- Full task lifecycle
- Bidirectional elicitation (server asks client mid-task)
- Bidirectional sampling (server requests LLM completion from client)
- Polling with server-suggested intervals
- Cooperative cancellation
- TTL-based task expiration
- In-memory task store (no persistent store shipped)

### 5.2 Stability Risks

The SDK explicitly warns at every level:

- "APIs may change without notice"
- "Draft specifications still being refined"
- SDK is described as v2 pre-alpha
- No deprecation policy, stability guarantee, migration path, or timeline

### 5.3 The CLI Bridge Architecture

```text
CLI ──MCP tool──► Orchestrator ──A2A SendMessage──► Agent
CLI ◄──MCP poll── Orchestrator ◄──A2A GetTask────── Agent
```

Works cleanly for single-agent delegation. Gets complex for multi-agent teams:

- Orchestrator maps N A2A tasks to 1 MCP task (status aggregation undefined)
- Concurrent elicitation from multiple agents serializes through MCP's
  sequential elicitation
- A2A `AUTH_REQUIRED`has no MCP equivalent

### 5.4 Settled Decision

Use **stable MCP tools** (not experimental tasks) as the primary CLI bridge.
MCP tasks as optional enhancement if CLI support is confirmed and API
stabilizes. Both paths hit the same A2A backend. (See architecture distilled
doc for the tool surface design.)

---

## 6. ACP Streaming Richness

ACP provides 11 discriminated update types (vs A2A's generic`Message.parts[]`):

| #   | Update Type             | Discriminator               | UI Rendering             |
| --- | ----------------------- | --------------------------- | ------------------------ |
| 1   | UserMessageChunk        | `user_message_chunk`        | User chat bubble         |
| 2   | AgentMessageChunk       | `agent_message_chunk`       | Agent chat (streaming)   |
| 3   | AgentThoughtChunk       | `agent_thought_chunk`       | Thinking/reasoning panel |
| 4   | ToolCallStart           | `tool_call`                 | Tool call card           |
| 5   | ToolCallProgress        | `tool_call_update`          | Progress bar / output    |
| 6   | AgentPlanUpdate         | `plan`                      | Plan checklist           |
| 7   | AvailableCommandsUpdate | `available_commands_update` | Command palette          |
| 8   | CurrentModeUpdate       | `current_mode_id`           | Mode indicator           |
| 9   | ConfigOptionUpdate      | `config_option_update`      | Settings panel           |
| 10  | SessionInfoUpdate       | `session_info_update`       | Session metadata         |
| 11  | UsageUpdate             | `usage_update`              | Token/cost counter       |

### 6.1 ACP Web Transport Feasibility

ACP's`Connection`class accepts`asyncio.StreamReader/StreamWriter` — not
hardwired to stdio. WebSocket adapter requires ~100 lines:

```python
class WebSocketStreamReader:
    async def readline(self) -> bytes:
        msg = await websocket.receive_str()
        return (msg + "\n").encode()

class WebSocketStreamWriter:
    async def write(self, data: bytes) -> None:
        await websocket.send_str(data.decode().rstrip("\n"))
```

**Verdict**: Web-native ACP host is feasible with no protocol changes.

### 6.2 SessionAccumulator

Merges streaming notifications into immutable `SessionSnapshot` objects:

```text
SessionSnapshot:
  session_id: str
  tool_calls: dict[str, ToolCallView]
  plan_entries: tuple[PlanEntry, ...]
  current_mode_id: str | None
  available_commands: tuple[AvailableCommand, ...]
  user_messages: tuple[UserMessageChunk, ...]
  agent_messages: tuple[AgentMessageChunk, ...]
  agent_thoughts: tuple[AgentThoughtChunk, ...]
```

Each `apply()` returns a new frozen snapshot. Subscribers receive
`(snapshot, notification)`pairs.

**For multi-agent**: One`SessionAccumulator` per agent. No manual state
merging needed.

---

## 7. WebSocket Protocol Design (Preliminary)

### 7.1 Server → Browser (Events)

```json
{
  "type": "agent_event",
  "agent_id": "coder-a",
  "event_type": "status_update",
  "data": { ... }
}
```

### 7.2 Server → Browser (Permissions)

```json
{
  "type": "permission_request",
  "agent_id": "coder-a",
  "request_id": "req-123",
  "tool_call": { "title": "Delete old_auth.py", "kind": "write" },
  "options": [
    { "id": "approve", "label": "Approve", "kind": "allow_once" },
    { "id": "reject", "label": "Reject", "kind": "reject_once" }
  ]
}
```

### 7.3 Browser → Server (Commands)

```json
{ "type": "send_message", "agent_id": "coder-a", "message": "Add validation" }
{ "type": "permission_response", "request_id": "req-123", "decision": "approve" }
{ "type": "agent_control", "agent_id": "coder-a", "action": "terminate" }
```

### 7.4 Channel Multiplexing

Single WebSocket per browser client. All agent subscriptions multiplexed.
Messages carry `agent_id`for routing. Browser-side dispatcher routes to
per-agent UI components. Follows Grafana Live pattern.

---

## 8. A2A ↔ MCP Feature Comparison

| Feature            | A2A                          | MCP Tasks          | Gap                                          |
| ------------------ | ---------------------------- | ------------------ | -------------------------------------------- |
| Task lifecycle     | 8 states                     | 5 states           | MCP lacks submitted, rejected, auth_required |
| Polling            | GetTask RPC                  | tasks/get          | Both supported, different wire               |
| Streaming          | SSE (native)                 | Not supported      | MCP has no task streaming                    |
| Push notifications | Full webhook protocol        | Not supported      | A2A only                                     |
| Elicitation        | input_required + SendMessage | elicitation/create | Same concept, different mechanism            |
| Auth interruption  | auth_required                | Not supported      | Needs custom handling                        |
| Cancellation       | CancelTask RPC               | tasks/cancel       | Both supported                               |
| Blocking mode      | blocking=true flag           | Not supported      | A2A only                                     |
| Context grouping   | contextId                    | Not supported      | A2A groups related tasks                     |
| Task referencing   | referenceTaskIds             | Not supported      | A2A links task chains                        |
| Agent discovery    | Agent Cards                  | Tool listing       | Different abstractions                       |

**A2A is the richer protocol.** MCP provides a useful subset for CLI
integration. The translation layer is the cost of CLI compatibility.

---

## 9. Open Contradictions

### C1: Should Agents Speak ACP or A2A?

Protocol Foundations §4 recommends: "Agent processes speak ACP (for rich
streaming) or A2A (for protocol compliance). The control surface server adapts
both."

The settled architecture (see architecture distilled doc) says: "A2A + MCP are
the implementation pair. ACP concepts ported as patterns, not as transport."

**Status**: ✅ Resolved by ADR-003 and ADR-006. We abandoned both A2A and ACP in
favor of native LangGraph execution. Richness is preserved via
LangGraph's`astream_events`API (yielding`on_chat_model_stream`, `on_tool_start`,
etc.), mapped directly to the UI.

### C2: ACP Richness Gap Is Acknowledged but Not Addressed

Protocol Foundations explicitly states ACP is "far richer" for control surface
purposes. The architecture then adopts A2A events without addressing how the
richness gap will be bridged. The SessionAccumulator port to A2A event types
will lose the typed discrimination between thoughts, messages, tool calls, and
plan updates.

**Status**: ✅ Resolved by ADR-003. `astream_events`from LangGraph provides
granular, typed events (Thought, Tool Call, System Prompt, Message). The UI
consumes these natively over the multiplexed WebSocket, completely bypassing the
A2A richness degradation.

---

## 10. Knowledge Gaps

### G1: CLI Support for MCP Tasks [CRITICAL]

**Status**: ✅ Mitigated by ADR-003. We removed "agent as an MCP tool" from the
v1 scope. All MCP usage is strictly for boundary execution (agents calling MCP
tools, not users calling agents via MCP). This sidesteps CLI compatibility
issues.

### G2: Multi-Agent Status Aggregation

When the orchestrator maps N A2A tasks to 1 MCP task (or 1 dashboard session),
how is the aggregate status computed? Example: 1 agent completed, 2 working,
1 waiting = what overall status? No aggregation logic is defined.

**Status**: ✅ Resolved by ADR-004. LangGraph inherently manages state for the
entire multi-agent graph as a single monolithic state dictionary. The UI renders
the aggregate graph state centrally.

### G3: Concurrent Elicitation Handling

MCP elicitation is sequential — one request at a time. If 2+ agents
simultaneously enter`INPUT_REQUIRED`, the requests must be queued or
serialized. No queuing strategy is defined. This directly impacts the
permission flow and user experience.

**Status**: ✅ Resolved by ADR-004. LangGraph's native `interrupt()`feature
pauses graph execution natively. Concurrent interruptions are handled by the
graph's internal node resolution mechanics.

### G4: AUTH_REQUIRED Through MCP

A2A's`AUTH_REQUIRED` expects out-of-band credential exchange. MCP has no
equivalent. The orchestrator must either collapse it into generic elicitation
("please provide token") losing the semantic distinction, or handle auth flows
entirely within the orchestrator. Neither approach is specified.

**Status**: ✅ Obsolete per ADR-006. A2A is abandoned. External auth flows, if
needed, are pushed to the frontend/dashboard level or managed via statically
loaded environment variables.

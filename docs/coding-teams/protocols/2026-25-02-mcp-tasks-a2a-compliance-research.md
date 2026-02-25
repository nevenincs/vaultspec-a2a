---
name: "MCP Tasks A2A Compliance"
date: 2026-25-02
type: research
summary: "Analysis of MCP experimental async tasks, A2A state mapping, bridge architecture options, and recommendation to build on stable MCP tools."
maturity: 40
---

# Research: MCP Async Tasks — A2A Compliance, Risk, and Stack Implications

**Date**: 2026-02-25
**Status**: Preliminary Investigation
**Builds on**: `2026-25-02-coding-teams-architecture-research.md`

---

## 1. What "Experimental" Actually Means

### 1.1 The Hard Facts

MCP's async task system lives behind `.experimental` namespace access:

```python
server.experimental.enable_tasks()           # server-side
session.experimental.call_tool_as_task(...)   # client-side
```

This is not a soft label. The SDK explicitly states at every level:

- "These APIs are experimental and may change without notice"
- "These features implement **draft specifications** that are still being
  refined"
- The entire MCP Python SDK is described as **v2 pre-alpha** ("upcoming v2
  documentation (pre-alpha, in development on `main`)")

There is:
- **No deprecation policy** for experimental features
- **No stability guarantee** between minor versions
- **No documented migration path** for when/if tasks stabilize
- **No timeline** for stabilization
- **No production use commitment**

### 1.2 What's Actually Implemented

Despite the warnings, the implementation is functionally complete for basic
use cases:

- Full task lifecycle: `working → {completed, failed, cancelled}`
- Bidirectional elicitation (server asks client for input mid-task)
- Bidirectional sampling (server requests LLM completion from client)
- Polling with server-suggested intervals
- Cooperative cancellation
- TTL-based task expiration
- In-memory task store (no persistent store shipped)

### 1.3 The CLI Support Question

**This is the critical unknown.** The MCP SDK documents the task protocol
but provides **zero information** about which clients support it:

| Client | MCP Tasks Support | Evidence |
|--------|-------------------|----------|
| Claude CLI | **Unknown** | No documentation found |
| Gemini CLI | **Unknown** | Not mentioned anywhere |
| Cursor/Windsurf | **Unknown** | Not mentioned anywhere |
| Custom MCP clients | Yes | SDK provides client APIs |

If Claude CLI and Gemini CLI don't implement the `call_tool_as_task` flow,
our entire MCP-as-bridge architecture falls apart. The only confirmed client
is the SDK's own client library.

---

## 2. A2A's Native Async — What It Provides Without MCP

A2A has its own comprehensive answer to long-running work. Understanding this
is critical because MCP tasks may be unnecessary if A2A's native patterns
suffice.

### 2.1 Three Native Control Modes

**Mode 1: Blocking SendMessage**

A2A's `SendMessage` accepts a `blocking=true` configuration flag:

```
SendMessage(config={blocking=true})
→ Server holds HTTP connection
→ Returns only when task reaches terminal or interrupted state
→ Client blocks synchronously
```

This is A2A's simplest async pattern. The client sends a message and waits.
No polling needed. But it locks the connection.

**Mode 2: Polling via GetTask**

```
SendMessage(config={blocking=false}) → returns Task with state=SUBMITTED
GetTask(task_id) → returns current Task state
Loop until terminal (COMPLETED, FAILED, CANCELED, REJECTED)
  or interrupted (INPUT_REQUIRED, AUTH_REQUIRED)
```

Standard polling. Client controls frequency. No persistent connection.

**Mode 3: Push Notifications (Webhooks)**

A2A defines a full push notification wire protocol:

```
1. Client sends PushNotificationConfig with SendMessage
   - url: https://client.example/webhook
   - token: validation token
   - authentication: {scheme: "Bearer", credentials: "..."}

2. Server POSTs to webhook URL on state changes
   - Payload: StreamResponse (Task, TaskStatusUpdateEvent, etc.)
   - Authenticated via the scheme specified

3. Client webhook handler processes notifications
   - May call GetTask for full state
```

Push notifications require the agent's AgentCard to declare
`capabilities.push_notifications = true`.

### 2.2 Interrupted States: A2A's Answer to Elicitation

A2A has two interrupted states that serve the same purpose as MCP's
elicitation:

**`input_required`**: Agent needs more information from client.

```
1. Agent sets task state = INPUT_REQUIRED
   status.message contains the agent's question
2. Client receives this via poll/stream/push
3. Client responds with SendMessage:
   - Same task_id and context_id
   - Parts contain the user's answer
4. Agent resumes processing
```

**`auth_required`**: Agent needs credentials for an external system.

```
1. Agent sets task state = AUTH_REQUIRED
   status.message describes what auth is needed
2. Client obtains credentials OUT OF BAND
   (OAuth flow, browser redirect, key exchange — not defined by A2A)
3. Client responds with SendMessage containing credentials
4. Agent resumes with new credentials
```

Both are **non-terminal** — the task stays open and resumes when the client
responds.

### 2.3 What A2A Does NOT Provide

A2A is deliberately minimal on orchestration:

- No process management (who starts/stops agents)
- No dependency graphs (task A before task B)
- No parallelism coordination (client manages concurrent calls)
- No error recovery/retry (client implements)
- No timeout enforcement (client-side only)
- No team coordination protocol (client builds this)
- No resource allocation or queue management

This is intentional: A2A is a peer-to-peer messaging protocol, not a
workflow engine.

---

## 3. State Mapping: MCP Tasks ↔ A2A Tasks

### 3.1 State Comparison

| MCP State | A2A State | Compatible? | Notes |
|-----------|-----------|-------------|-------|
| `working` | `WORKING` | Yes | Direct match |
| `input_required` | `INPUT_REQUIRED` | Yes | Same concept, different wire format |
| `completed` | `COMPLETED` | Yes | Direct match |
| `failed` | `FAILED` | Yes | Direct match |
| `cancelled` | `CANCELED` | Yes | Spelling difference (UK vs US) |
| — | `SUBMITTED` | No MCP equivalent | A2A has explicit "received but not started" state |
| — | `REJECTED` | No MCP equivalent | A2A distinguishes rejection from failure |
| — | `AUTH_REQUIRED` | No MCP equivalent | A2A has dedicated auth interruption |

**MCP has 5 states. A2A has 8.** The mapping is lossy in one direction:

```
A2A → MCP (lossy):
  SUBMITTED → working + statusMessage="submitted"
  REJECTED → failed + statusMessage="rejected"
  AUTH_REQUIRED → input_required (collapse to generic input request)

MCP → A2A (clean):
  All 5 MCP states map directly to A2A equivalents
```

### 3.2 Lifecycle Differences

**MCP**: Task goes straight to `working`. No submission phase.

**A2A**: Task can sit in `SUBMITTED` before agent starts processing. This is
meaningful for queued systems where acceptance ≠ execution start.

**MCP**: `input_required ↔ working` is bidirectional (task can loop).

**A2A**: Same pattern, but with the additional `auth_required` variant for
credential-specific interruptions.

**Both**: Terminal states are immutable. Once completed/failed/canceled, a
new task is needed for follow-up work.

### 3.3 Enum Naming

This matters at the wire level:

```
MCP:  "status": "working"           (lowercase)
A2A:  "state": "TASK_STATE_WORKING"  (SCREAMING_SNAKE_CASE, ProtoJSON)
```

Direct string comparison fails. Translation layer must normalize.

---

## 4. Can MCP Tasks Wrap A2A Tasks?

### 4.1 The Bridge Architecture

```
CLI ──MCP tool call──► Orchestrator ──A2A SendMessage──► Agent
CLI ◄──MCP task poll── Orchestrator ◄──A2A GetTask────── Agent
```

The orchestrator maintains a mapping table:

```python
mcp_task_id="mcp-123" ↔ a2a_task_id="a2a-uuid-456"
```

### 4.2 Where It Works Cleanly

**Happy path**: User delegates task, agent works, completes.

```
1. CLI calls MCP tool → Orchestrator creates MCP task (mcp-123)
2. Orchestrator calls A2A SendMessage → gets A2A task (a2a-456)
3. Orchestrator stores mapping: mcp-123 → a2a-456
4. CLI polls MCP task → Orchestrator polls A2A task → translates state
5. A2A task completes → MCP task completes → CLI gets result
```

**Elicitation path**: Agent needs input.

```
1. A2A task goes INPUT_REQUIRED with question in status.message
2. Orchestrator detects via A2A poll
3. Orchestrator triggers MCP elicitation to CLI
4. CLI prompts user, gets answer
5. Orchestrator sends A2A SendMessage with answer (same task_id)
6. A2A task resumes
```

### 4.3 Where It Gets Messy

**Multi-agent team**: Orchestrator manages N A2A tasks per 1 MCP task.

```
MCP task mcp-123 maps to:
  - a2a-task-planner (completed)
  - a2a-task-coder-a (working)
  - a2a-task-coder-b (working)
  - a2a-task-reviewer (submitted, waiting)
```

The MCP task status must aggregate: what does "working" mean when one agent
is done and two are active? The orchestrator needs aggregation logic that
doesn't exist in either protocol.

**Concurrent elicitation**: Two agents need input simultaneously.

```
Coder A: INPUT_REQUIRED "Delete old_auth.py?"
Coder B: INPUT_REQUIRED "Use JWT or session tokens?"
```

MCP elicitation is sequential — one request at a time. Handling concurrent
agent inputs requires queuing or serialization.

**Auth flow**: A2A's AUTH_REQUIRED expects out-of-band credential exchange.
MCP has no equivalent. The orchestrator would need to either:
- Collapse auth_required into a generic elicitation ("please provide token")
- Handle auth flows entirely within the orchestrator

### 4.4 Verdict

MCP tasks **can** wrap A2A tasks for the single-agent-delegation case with
acceptable fidelity. For multi-agent teams, the orchestrator carries
significant translation burden that neither protocol was designed for.

---

## 5. Stack Implications

### 5.1 If We Use MCP Tasks as CLI Bridge

**What we build**:
- MCP server exposing team orchestration as tools
- Translation layer mapping MCP task lifecycle to A2A task lifecycle
- Aggregation logic for multi-agent → single MCP task status
- Elicitation routing (MCP elicitation ↔ A2A input_required)

**What we risk**:
- MCP experimental API changes break our translation layer
- CLI clients may not support MCP tasks at all
- Polling latency (500ms default) adds perceived slowness
- Sequential elicitation can't handle concurrent agent inputs

**What we gain**:
- CLI-agnostic integration (any MCP-supporting CLI works)
- Non-blocking delegation (CLI gets task ID, polls for status)
- Mid-task user input via elicitation
- Cancellation support

### 5.2 If We Skip MCP Tasks and Use A2A Directly

**What we build**:
- Custom CLI client that speaks A2A natively
- OR: simple MCP tools (no async tasks) that block during execution

**What we risk**:
- Custom CLI client limits to our tooling only
- Blocking MCP tools freeze the CLI during team work
- No mid-task user input without MCP tasks

**What we gain**:
- No dependency on experimental features
- Full A2A protocol fidelity (8 states, push notifications, SSE)
- No translation layer complexity

### 5.3 If We Build Our Own Async Protocol on MCP

**What we build**:
- Standard (non-experimental) MCP tools that return immediately
- Custom polling tools: `team/status(session_id)` returns progress
- Custom input tools: `team/respond(session_id, input)` sends user input
- All built on stable MCP tool API, no experimental dependency

**What we risk**:
- Reinventing what MCP tasks already provide
- No native elicitation UX in CLIs (user must explicitly call input tool)
- More tools = more cognitive load for the CLI's LLM to manage

**What we gain**:
- Zero dependency on experimental features
- Full control over the protocol surface
- Works with any MCP client today
- Can adopt MCP tasks later if they stabilize

### 5.4 Recommendation

**Option 3 (custom async on stable MCP) is the safest foundation**, with
Option 1 (MCP tasks) as an enhancement layer if/when CLI support is confirmed.

The tool surface would look like:

```
Stable MCP tools (works today, any CLI):
  team/delegate(task, config) → {session_id, status: "started"}
  team/status(session_id) → {status, agents: [...], progress}
  team/artifacts(session_id) → {files: [...]}
  team/respond(session_id, message) → {acknowledged}
  team/cancel(session_id) → {status: "canceling"}

Optional MCP task enhancement (if CLI supports it):
  team/delegate becomes TASK_OPTIONAL
  Elicitation replaces team/respond
  Polling replaces team/status
```

The stable tools work without MCP tasks. If a CLI supports MCP tasks, the
same orchestrator can expose the enhanced experience. Both paths hit the
same A2A backend.

---

## 6. A2A Protocol Compliance Summary

| Feature | A2A Support | MCP Task Support | Gap |
|---------|-------------|------------------|-----|
| Task lifecycle | 8 states | 5 states | MCP lacks submitted, rejected, auth_required |
| Polling | GetTask RPC | tasks/get | Both supported, different wire format |
| Streaming | SSE (native) | Not supported | MCP has no streaming for tasks |
| Push notifications | Full webhook protocol | Not supported | A2A-only feature |
| Elicitation | input_required + SendMessage | elicitation/create | Same concept, different mechanism |
| Auth interruption | auth_required | Not supported | Would need custom handling |
| Cancellation | CancelTask RPC | tasks/cancel | Both supported |
| Blocking mode | blocking=true flag | Not supported | A2A-only convenience |
| Context grouping | contextId | Not supported | A2A groups related tasks |
| Task referencing | referenceTaskIds | Not supported | A2A links task chains |
| Agent discovery | Agent Cards | Tool listing | Different abstractions |

**A2A is the richer protocol.** MCP tasks provide a useful subset for CLI
integration, but the orchestrator must use A2A natively for full team
coordination. The translation layer is the cost of CLI compatibility.

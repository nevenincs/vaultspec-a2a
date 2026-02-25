---
name: "Integration Assessment"
date: 2026-25-02
type: assessment
summary: "Phase 6 deliverable analyzing end-to-end data flow, feature complexity inventory, technology boundaries, minimum viable scope, and recommended tech stack."
maturity: 45
---

# Phase 6 Deliverable: Integration & Complexity Assessment

**Date**: 2026-02-25
**Phase**: 6 (Integration and Complexity Assessment)
**Status**: Complete
**Depends on**: Phases 1-5, 7

---

## 1. End-to-End Data Flow

### 1.1 User Sends Message to Agent via Web UI

```
Browser (SvelteKit)
  │ WebSocket JSON: {type: "send_message", agent_id: "coder-a", message: "add auth"}
  ▼
FastAPI WebSocket Handler
  │ Deserialize, validate, lookup agent connection
  ▼
Orchestrator (A2A Client)
  │ Build A2A Message (contextId, taskId from session state)
  │ POST /sendMessageStream to agent's A2A server
  ▼
Agent Process (Uvicorn subprocess, A2A Server)
  │ DefaultRequestHandler → AgentExecutor.execute(context, event_queue)
  │ Agent LLM processes, calls tools, enqueues events
  ▼
EventQueue (async queue, bounded 1024)
  │ TaskStatusUpdateEvent, TaskArtifactUpdateEvent
  ▼
SSE Stream back to Orchestrator
  │ data: {json-rpc}\n\n per event
  ▼
Orchestrator Event Aggregator
  │ Parse SSE events, update internal task state
  │ Translate to WebSocket message format
  ▼
FastAPI WebSocket broadcast
  │ JSON: {type: "agent_event", agent_id: "coder-a", event_type: "status_update", data: {...}}
  ▼
Browser (SvelteKit)
  │ Svelte 5 runes dispatch to per-agent component
  │ Update status badge, append to message stream, render artifact
  ▼
Rendered UI
```

### 1.2 Serialization Boundaries

| Boundary | Format | Failure Mode |
|---|---|---|
| Browser ↔ WebSocket | JSON | Connection drop, malformed JSON |
| FastAPI ↔ A2A Agent | JSON-RPC over HTTP/SSE | Connection timeout, agent crash, port unreachable |
| Agent ↔ MCP Tool Server | JSON-RPC over stdio | Subprocess crash, pipe broken, buffer overflow |
| Agent ↔ LLM API | HTTP JSON (model-specific) | API timeout, rate limit, auth failure |
| FastAPI ↔ SQLite | SQL via aiosqlite | DB locked, disk full, corruption |
| Agent ↔ Filesystem | Direct I/O (via MCP tools) | Permission denied, disk full, path not found |

### 1.3 Async Handoff Points

| Handoff | Mechanism | Risk |
|---|---|---|
| WebSocket → A2A client | asyncio task | Task leak if not properly cancelled |
| A2A SSE → Event aggregator | async generator iteration | Generator not properly closed on disconnect |
| Agent executor → EventQueue | queue.put() | Queue full (bounded 1024), producer blocks |
| EventQueue → SSE response | queue.get() with 0.5s timeout | Missed close signal, hung consumer |
| Process Manager → subprocess | create_subprocess_exec | Windows ProactorEventLoop restrictions |

---

## 2. Feature Complexity Inventory

### 2.1 Complexity Matrix

| # | Feature | Protocol Support | Custom Code | Library Deps | UI Complexity | Backend Complexity | Priority |
|---|---------|-----------------|-------------|--------------|--------------|-------------------|----------|
| 1 | Agent status monitoring | A2A: TaskStatusUpdateEvent | Event aggregator, WebSocket broadcast | None new | Status badge, progress text | Low | **v1** |
| 2 | Task list with filtering | A2A: GetTask, ListTasks (if available) | Task store queries, REST API | None new | Table with filters | Low | **v1** |
| 3 | Artifact browser | A2A: TaskArtifactUpdateEvent | Artifact storage, file serving | None new | File tree, code viewer | Medium | **v1** |
| 4 | Agent terminal view | NOT in A2A/ACP | stdout/stderr capture, WebSocket relay | xterm.js, xterm-svelte | Terminal emulator panel | **High** | **v1** |
| 5 | Permission management | ACP: PermissionBroker pattern | Permission store, runtime config API | None new | Toggle switches, approval modal | Medium | **v1** |
| 6 | Message send/receive | A2A: SendMessage + contextId | Message routing, context management | None new | Chat input, message bubbles | Medium | **v1** |
| 7 | Agent spawn/kill | NOT in any protocol | Process manager, port allocator, health checks | None new | Start/stop buttons, status indicators | **High** | **v1** |
| 8 | Team composition editor | NOT in any protocol | Agent registry, routing table, drain logic | None new | Agent list, add/remove/swap UI | **High** | **v2** |
| 9 | Session history & replay | NOT in any protocol | Event sourcing to SQLite, replay logic | aiosqlite | Timeline view, replay controls | **High** | **v2** |
| 10 | Cost/token tracking | ACP: UsageUpdate; A2A: metadata | Usage aggregator, budget enforcement | None new | Counter widgets, charts | Low | **v2** |

### 2.2 What Must Be Built From Scratch

These components have **no protocol support and no library coverage**:

1. **Process Manager** — Spawn/monitor/restart Uvicorn subprocesses on Windows.
   Custom state machine (CREATED → STARTING → READY → RUNNING → DRAINING →
   STOPPING → STOPPED/EXITED/FATAL). Must handle Windows-specific shutdown
   (CTRL_BREAK_EVENT, TerminateProcess). Estimated: significant effort.

2. **Event Aggregator** — Maintain per-agent SSE connections, parse events,
   translate to WebSocket messages, handle reconnection (tasks/resubscribe),
   fan out to multiple browser clients. Estimated: moderate effort.

3. **Port Allocator** — Find free ports, assign to agents, track allocation,
   reclaim on shutdown. Estimated: small effort.

4. **Agent stdout/stderr → WebSocket relay** — Capture subprocess output
   streams, buffer, broadcast to xterm.js terminals in browser.
   Must handle Windows buffering (PYTHONUNBUFFERED=1). Estimated: moderate.

5. **Scoped MCP Tool Server** — Per-agent MCP instances with filesystem root
   scoping, allowed command lists. No existing implementation. Estimated:
   moderate effort.

### 2.3 What Can Be Reused

| Component | Source | Adaptation Needed |
|---|---|---|
| A2A client/server | a2a-python SDK | None — use directly |
| Event queue + streaming | a2a-python EventQueue | None — use directly |
| SessionAccumulator pattern | ACP contrib | Port concept to our aggregator (don't need ACP transport) |
| PermissionBroker pattern | ACP contrib | Port concept to our permission system |
| ToolCallTracker pattern | ACP contrib | Port concept to our tool monitoring |
| Task store (SQLAlchemy) | a2a-python server/models.py | Configure for SQLite |
| Agent Card serving | a2a-python A2AStarletteApplication | None — use directly |

---

## 3. Technology Boundary Map

```
┌──────────────────────────────────────────────────────────────┐
│ BROWSER (SvelteKit / Svelte 5)                                │
│                                                                │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────────────┐  │
│  │ Agent    │ │ Chat     │ │ Terminal │ │ Code Viewer    │  │
│  │ Panels   │ │ Input    │ │ (xterm)  │ │ (CodeMirror 6) │  │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └───────┬────────┘  │
│       └──────┬──────┴──────┬─────┘               │           │
│              ▼             ▼                      │           │
│     ┌────────────────────────────┐               │           │
│     │ WebSocket Client           │               │           │
│     │ (single multiplexed conn)  │               │           │
│     └────────────┬───────────────┘               │           │
└──────────────────┼───────────────────────────────┼───────────┘
                   │ WebSocket (JSON)              │ HTTP (static)
                   ▼                               ▼
┌──────────────────────────────────────────────────────────────┐
│ CONTROL SURFACE SERVER (FastAPI + Uvicorn)                    │
│                                                                │
│  ┌─────────────┐ ┌──────────────┐ ┌────────────────────────┐│
│  │ WebSocket   │ │ REST API     │ │ Static File Server     ││
│  │ Handler     │ │ (tasks,      │ │ (SvelteKit bundle)     ││
│  │             │ │  agents,     │ │                        ││
│  │             │ │  artifacts)  │ │                        ││
│  └──────┬──────┘ └──────┬───────┘ └────────────────────────┘│
│         │               │                                     │
│  ┌──────▼───────────────▼──────────────────────────────────┐ │
│  │ Orchestrator Core                                        │ │
│  │                                                          │ │
│  │  ┌──────────────┐ ┌──────────────┐ ┌────────────────┐  │ │
│  │  │ Event        │ │ Process      │ │ Permission     │  │ │
│  │  │ Aggregator   │ │ Manager      │ │ Manager        │  │ │
│  │  └──────┬───────┘ └──────┬───────┘ └──────┬─────────┘  │ │
│  │         │               │                 │             │ │
│  │  ┌──────▼───────────────▼─────────────────▼──────────┐  │ │
│  │  │ Task Store (SQLite via aiosqlite)                  │  │ │
│  │  └───────────────────────────────────────────────────┘  │ │
│  └──────────────────────────────────────────────────────────┘ │
│         │               │                                     │
└─────────┼───────────────┼─────────────────────────────────────┘
          │ A2A HTTP/SSE  │ subprocess stdio
          ▼               ▼
┌─────────────────┐ ┌─────────────────┐
│ Agent Process 1 │ │ Agent Process 2 │
│ (Uvicorn)       │ │ (Uvicorn)       │
│                 │ │                 │
│ A2A Server      │ │ A2A Server      │
│ AgentExecutor   │ │ AgentExecutor   │
│ LLM Client      │ │ LLM Client      │
│ MCP Client ─────┼─┤ MCP Client ─────┼──► MCP Tool Server
│                 │ │                 │    (per-agent scoped)
└─────────────────┘ └─────────────────┘
```

### 3.1 Boundary Failure Analysis

| Boundary | Serialization | Failure | Latency | Throughput Limit |
|---|---|---|---|---|
| Browser ↔ WebSocket | JSON | Reconnect with state replay from SQLite event log | <1ms local | ~10K msgs/sec |
| WebSocket ↔ A2A Agent | JSON-RPC/HTTP | Agent health check fails → circuit breaker → restart | 1-10ms local | Limited by LLM API |
| Agent ↔ MCP Tool | JSON-RPC/stdio | Pipe broken → tool call fails → agent retries or fails task | <1ms | 100s of calls/sec |
| Agent ↔ LLM API | HTTPS JSON | Timeout/rate limit → retry with backoff → fail task | 200ms-30s | API rate limits |
| Server ↔ SQLite | SQL | DB locked (WAL mode mitigates) → retry | <1ms | 1000s writes/sec |
| Process Manager ↔ subprocess | OS signals | Windows TerminateProcess is ungraceful → state loss | <1ms | N/A |

---

## 4. Minimum Viable Control Surface (v1 Scope)

### 4.1 v1 Features

1. **Agent panel grid** — Per-agent cards showing name, status (badge), current task
2. **Agent terminal** — xterm.js view of agent stdout/stderr per agent
3. **Chat interface** — Send messages to the team (routed through orchestrator)
4. **Permission modal** — Approve/reject when agents request tool permissions
5. **Agent controls** — Start/stop/restart buttons per agent
6. **Task list** — Simple table of active/completed tasks with status
7. **Artifact viewer** — View generated code files (CodeMirror 6 read-only)

### 4.2 v1 Architecture (simplest that works)

- **Backend**: FastAPI, single process, uvicorn
- **Frontend**: SvelteKit, Vite build, bundled as package static files
- **State**: SQLite (aiosqlite, WAL mode)
- **Transport**: Single WebSocket per browser client
- **Agents**: asyncio subprocesses, auto-assigned ports
- **Terminal**: xterm.js via xterm-svelte, stdout relay over WebSocket

### 4.3 What's Deferred to v2

- Team composition editor (add/remove/swap agents at runtime)
- Session history and replay
- Cost/token tracking dashboard
- Multi-user support
- Agent-to-agent message visualization (thread view)
- Blue-green agent deployment
- Distributed agent support (non-local)
- MCP experimental task integration (pending CLI support confirmation)

---

## 5. Recommended Tech Stack Summary

| Layer | Choice | Rationale |
|---|---|---|
| Language | Python 3.13 | Project constraint |
| Package manager | uv | Project constraint |
| Backend framework | FastAPI | WebSocket + REST + lifespan, A2A SDK compatible |
| ASGI server | Uvicorn | Standard, used by all A2A samples |
| Frontend framework | SvelteKit (Svelte 5) | Fine-grained reactivity for streaming, proven by Open WebUI |
| Terminal emulator | xterm.js via xterm-svelte | Universal standard, no alternatives |
| Code viewer | CodeMirror 6 | 124KB vs Monaco's 2MB, read-only mode, incremental updates |
| Syntax highlighting | Shiki (for code blocks in messages) | VS Code quality, WASM |
| Markdown rendering | Incremark or Streamdown | O(n) streaming, avoids O(n²) re-parse |
| State store | SQLite via aiosqlite | Zero-config, WAL mode, single-file |
| Build tool | Vite (via SvelteKit) | Fast, standard |
| A2A SDK | a2a-python | Official, full protocol |
| Deployment | pip install + uvicorn | Like Jupyter |

---

## 6. Key Architectural Decisions (Preliminary)

### 6.1 Single Process Orchestrator (v1)

One Python process runs everything: FastAPI server, WebSocket handler,
process manager, event aggregator, A2A client connections. Agents are
subprocesses.

**Why**: Simplest deployment, no IPC complexity, adequate for single-user
local dev tool. Can be split later if needed.

### 6.2 WebSocket with Channel Multiplexing

One WebSocket per browser client, all agent events multiplexed with
`agent_id` routing. Following Grafana Live's pattern.

**Why**: Fewer connections, simpler client state, single reconnection
point.

### 6.3 ACP Patterns Without ACP Protocol

Adopt SessionAccumulator, ToolCallTracker, and PermissionBroker concepts
but implement them against A2A event types, not ACP session updates.

**Why**: ACP's abstractions are superior for UI state management, but
agents speak A2A. The control surface translates A2A events into
accumulator-friendly state updates.

### 6.4 Stable MCP Tools as CLI Bridge

Expose team orchestration as standard MCP tools (not experimental tasks).
Custom polling via `team/status` tool. No dependency on experimental
features.

**Why**: Works with every MCP-supporting CLI today. Can layer MCP tasks
later if they stabilize and CLIs add support.

### 6.5 Per-Agent Git Worktrees for Filesystem Isolation

Each coding agent works in its own git worktree. Merge happens after
review, not during coding.

**Why**: Strongest isolation for concurrent coding. Agents can't overwrite
each other. Natural integration with git-based review workflows.

---
name: "Scope Assessment"
date: 2026-25-02
type: assessment
summary: "Component inventory with complexity tiers, dependency graph, risk register, and sizing estimates for the coding teams implementation."
maturity: 35
---

# Scope Assessment: Agent Team Control Surface

**Date**: 2026-02-25
**Status**: Assessment (no commitments)

---

## What We're Assessing

A system with two faces:

1. **CLI bridge** — MCP tools that let any CLI delegate work to a coding team
2. **Control surface** — Web app for monitoring, messaging, and managing agents

Both backed by the same orchestrator process that coordinates A2A agents.

---

## The Component Map

Every line below is something that must exist. Grouped by what already
exists vs. what we build.

### Already exists (use directly)

```
a2a-python SDK
├── Types (Pydantic models for full protocol)
├── A2A Server (Starlette/FastAPI app, Agent Card serving)
├── A2A Client (HTTP/SSE/gRPC transports, card resolver)
├── DefaultRequestHandler (routes RPC to executor)
├── AgentExecutor interface (our agents implement this)
├── EventQueue (bounded async queue with tap/fan-out)
├── InMemoryTaskStore (dev) / SQLAlchemy TaskStore (prod)
└── Push notification sender

mcp-python-sdk
├── MCP Server (@mcp.tool() decorator, schema generation)
├── MCP Client (tool discovery, tool calling)
└── stdio/HTTP transports

FastAPI / Starlette
├── HTTP routing
├── WebSocket handling
├── Static file serving
├── Lifespan context manager
└── Uvicorn ASGI server
```

### Must be built — Orchestrator Core

```
Process Manager
├── Spawn agent as subprocess (asyncio.create_subprocess_exec)
├── Port allocation (socket.bind(('', 0)), pass to uvicorn)
├── Stdout/stderr capture and relay
├── Health check loop (HTTP probe to agent card endpoint)
├── Graceful shutdown (CTRL_BREAK_EVENT on Windows → timeout → terminate)
├── Restart with backoff (1s, 2s, 4s, 8s, max 30s)
├── State machine per agent (STARTING → READY → RUNNING → STOPPING → STOPPED)
└── Windows-specific: PYTHONUNBUFFERED=1, ProactorEventLoop constraints

Event Aggregator
├── Per-agent SSE connection management
├── SSE event parsing (data: {json-rpc}\n\n)
├── Reconnection via tasks/resubscribe
├── Event translation (A2A events → internal event format)
├── Fan-out to WebSocket clients
├── Event persistence to SQLite (for reconnection replay)
└── Task state tracking (accumulate events into current state)

Agent Registry
├── Agent card storage and lookup
├── Routing table (which agent handles what)
├── Agent health status tracking
└── Team composition state

Permission Manager
├── Per-agent permission rules (tool allow/deny lists)
├── Permission request routing (agent → WebSocket → browser → response)
├── Rule persistence (SQLite)
└── Runtime rule changes via REST API

MCP Tool Surface (CLI bridge)
├── team/delegate(description, config) → session_id
├── team/status(session_id) → aggregated progress
├── team/artifacts(session_id) → file list
├── team/respond(session_id, message) → acknowledgment
├── team/cancel(session_id) → status
└── Tool registration with mcp-python-sdk
```

### Must be built — Web Control Surface

```
Backend (FastAPI)
├── WebSocket handler (connection manager, broadcast, channel multiplexing)
├── REST API (agents CRUD, tasks list, artifacts serve, permissions CRUD)
├── Static file mount (SvelteKit bundle)
├── WebSocket reconnection + state replay from SQLite event log
└── Session management (single-user: no auth, localhost binding)

Frontend (SvelteKit / Svelte 5)
├── Agent panel grid (status badge, current task, agent name)
├── Terminal view per agent (xterm.js via xterm-svelte, WebSocket relay)
├── Chat interface (send messages, see responses, contextId carry)
├── Permission modal (approve/reject with tool call details)
├── Agent controls (start/stop/restart buttons)
├── Task list table (status, agent, timestamps, filtering)
├── Artifact viewer (file tree + CodeMirror 6 read-only)
├── WebSocket client (single connection, channel demux, reconnection)
└── State management (Svelte 5 runes, server-authoritative)
```

### Must be built — Agent Templates

```
Coding Agent Shell
├── AgentExecutor implementation
├── LLM client integration (model-agnostic)
├── MCP client for workspace tools
├── Agent Card definition (skills, capabilities)
└── Event emission patterns (status updates, artifact streaming)

Scoped MCP Tool Server (per-agent)
├── Filesystem tools (read/write scoped to worktree root)
├── Git tools (status, diff, commit — scoped to worktree)
├── Command runner (allowed commands only: pytest, ruff, etc.)
└── Scope enforcement (path validation, command allowlist)

Workspace Manager
├── Git worktree creation per task
├── Worktree cleanup on task completion
├── Branch naming convention
└── Merge strategy (manual for v1)
```

---

## Complexity Tiers

### Tier 1: Low complexity (well-understood, library-backed)

- A2A server/client setup (SDK does the work)
- MCP tool registration (decorator-based)
- SQLite state persistence (aiosqlite, standard)
- Agent Card definitions (JSON structure)
- REST API for CRUD operations (FastAPI standard)
- Static file serving (FastAPI mount)
- Basic Svelte components (badges, buttons, tables)

### Tier 2: Moderate complexity (patterns exist, must adapt)

- WebSocket connection manager with multiplexing
- SSE event parsing and aggregation
- Permission request/response flow (ACP pattern adapted)
- Chat with contextId carry-forward (a2a-samples pattern)
- xterm.js terminal setup and WebSocket relay
- CodeMirror 6 read-only viewer
- Agent Card discovery and routing
- MCP tool surface for CLI bridge
- Git worktree lifecycle management

### Tier 3: High complexity (novel, no direct reference)

- **Process Manager on Windows** — asyncio subprocess management with
  CTRL_BREAK_EVENT shutdown, health probes, restart backoff, port allocation.
  No library does this for A2A agents. Closest reference: Claude Agent SDK's
  SubprocessCLITransport, supervisord state machine.

- **Event Aggregator** — Multiple concurrent SSE connections, per-agent state
  accumulation, reconnection with replay, fan-out to WebSocket. ACP's
  SessionAccumulator is the conceptual model but must be rebuilt for A2A events.

- **Scoped MCP Tool Server** — Per-agent filesystem isolation with path
  validation and command allowlists. Nothing in the ecosystem does this.
  Must be built from MCP server primitives.

- **Streaming artifact rendering** — Incremental code display as agents emit
  file chunks via TaskArtifactUpdateEvent. JS coder sample shows the pattern
  but integration with CodeMirror/xterm requires custom glue.

---

## Dependency Graph

```
                    ┌─────────────────┐
                    │ A2A SDK types   │
                    │ (exists)        │
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
    ┌─────────────┐ ┌──────────────┐ ┌──────────────┐
    │ Agent       │ │ Orchestrator │ │ MCP Tool     │
    │ Templates   │ │ Core         │ │ Surface      │
    │             │ │              │ │              │
    │ • Executor  │ │ • Process Mgr│ │ • team/*     │
    │ • LLM glue  │ │ • Event Agg  │ │   tools      │
    │ • Agent Card│ │ • Registry   │ │              │
    └──────┬──────┘ │ • Permissions│ └──────┬───────┘
           │        └──────┬───────┘        │
           │               │                │
           ▼               ▼                │
    ┌─────────────┐ ┌──────────────┐        │
    │ Scoped MCP  │ │ Web Backend  │◄───────┘
    │ Tool Server │ │ (FastAPI)    │
    │             │ │              │
    │ • fs tools  │ │ • WebSocket  │
    │ • git tools │ │ • REST API   │
    │ • cmd runner│ │ • Static     │
    └──────┬──────┘ └──────┬───────┘
           │               │
           ▼               ▼
    ┌─────────────┐ ┌──────────────┐
    │ Workspace   │ │ Web Frontend │
    │ Manager     │ │ (SvelteKit)  │
    │             │ │              │
    │ • worktrees │ │ • Panels     │
    │ • branches  │ │ • Terminal   │
    │ • cleanup   │ │ • Chat       │
    └─────────────┘ │ • Artifacts  │
                    └──────────────┘
```

**Build order** (each layer depends on what's above it):

1. Agent Templates + Orchestrator Core (can be parallel)
2. Scoped MCP Tool Server (needs agent templates)
3. MCP Tool Surface + Web Backend (needs orchestrator core)
4. Web Frontend (needs web backend)
5. Workspace Manager (needs scoped MCP tool server)

---

## What's Hard and Why

### 1. Windows process management

Every sample runs on Linux/Mac. Windows subprocess lifecycle is different:

- `process.terminate()` is SIGKILL (no grace period)
- Need CTRL_BREAK_EVENT with CREATE_NEW_PROCESS_GROUP for graceful
- ProactorEventLoop (IOCP) is required and has limitations
- `create_subprocess_exec` only works from main thread
- No `os.killpg()` equivalent — need Job Objects for child cleanup

This is the single biggest platform risk.

### 2. SSE connection lifecycle

The orchestrator must maintain N concurrent SSE connections (one per agent
task). Each can drop, stall, or produce events faster than the WebSocket
can relay. Must handle:

- Connection pooling with httpx
- Reconnection via tasks/resubscribe (events during disconnect are lost)
- Backpressure (bounded EventQueue, 1024 items)
- Graceful shutdown (close all SSE when agent dies)

### 3. Scoped filesystem access

No MCP tool server implementation enforces path boundaries. We must build
path validation that prevents agents from escaping their worktree root.
This includes handling symlinks, `..` traversal, Windows path normalization
(forward/backward slashes, drive letters, UNC paths).

### 4. Consistent state across disconnections

When a browser tab closes and reopens, the UI must show current state.
Requires event sourcing to SQLite + snapshot reconstruction. When WebSocket
reconnects, server must determine what the client missed and replay or
send a full snapshot. Hybrid approach: rolling buffer (last N events per
agent) + full snapshot fallback.

---

## What's Surprisingly Easy

### 1. A2A agent creation

The SDK does nearly everything. Implement `AgentExecutor.execute()`, define
an `AgentCard`, wire up `DefaultRequestHandler`, run with uvicorn. ~50 lines
for a minimal agent.

### 2. MCP tool registration

```python
@mcp.tool()
def team_status(session_id: str) -> dict:
    return orchestrator.get_status(session_id)
```

That's it. Schema generated from type hints. Any MCP-supporting CLI can
call it.

### 3. ACP web feasibility

ACP's transport layer is abstracted. `Connection` takes
`asyncio.StreamReader/Writer` — not hardwired to stdio. WebSocket adapter
is ~100 lines. The entire SessionAccumulator/PermissionBroker/ToolCallTracker
stack works unchanged over WebSocket.

### 4. xterm.js integration

xterm-svelte wraps xterm.js for Svelte. Backend sends stdout lines over
WebSocket, frontend writes to terminal. Established pattern used by
code-server, Theia, JupyterLab.

---

## Risk Register

| Risk | Impact | Likelihood | Mitigation |
|---|---|---|---|
| Windows subprocess issues | High | High | Early spike: build ProcessManager first, test on Windows |
| MCP tasks never stabilize | Medium | Medium | Already mitigated: using stable tools, not experimental |
| CLI tools don't support our MCP tools well | Medium | Low | MCP tools are standard; any LLM can call them |
| xterm.js memory with many agents | Medium | Low | Limit scrollback (5K lines), persist to SQLite |
| Agent LLM costs spiral | High | Medium | Budget per task, token tracking, hard limits |
| A2A SDK breaking changes | Medium | Low | Pin version, abstract behind thin layer |
| SvelteKit learning curve | Low | Medium | Svelte 5 is simpler than React; Open WebUI proves pattern |
| SQLite contention under load | Low | Low | WAL mode, single-user tool, unlikely bottleneck |

---

## Sizing Estimate (Rough Order of Magnitude)

Not time estimates. Component count and relative weight.

| Component | Files | Relative Weight | Notes |
|---|---|---|---|
| Process Manager | 3-5 | Heavy | Windows-specific, state machine, health checks |
| Event Aggregator | 3-4 | Heavy | SSE management, state accumulation, replay |
| Agent Registry | 1-2 | Light | Dict + persistence |
| Permission Manager | 2-3 | Medium | Rules, routing, persistence |
| MCP Tool Surface | 1-2 | Light | 5 tool functions |
| Web Backend (FastAPI) | 3-5 | Medium | WebSocket, REST, static |
| Coding Agent Template | 2-3 | Medium | Executor, LLM glue, card |
| Scoped MCP Tool Server | 2-3 | Medium | fs/git/cmd with path validation |
| Workspace Manager | 1-2 | Light | Git worktree operations |
| Frontend (SvelteKit) | 10-15 | Heavy | Multiple interactive components |
| **Total** | **~30-45 files** | | |

The heaviest work is in three places: **Process Manager**, **Event
Aggregator**, and **Frontend components**. Everything else composes
from existing libraries and SDKs.

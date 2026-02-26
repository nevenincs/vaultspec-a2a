---
name: "Architecture Domain - Distilled"
date: 2026-25-02
type: distilled
summary: "Consolidated system architecture covering topology, tech stack, component inventory, data flows, build order, and risk register. Synthesized from 6 research documents. 15 refuted hypotheses removed. 7 contradictions and 11 knowledge gaps explicitly identified."
maturity: 50
sources:
  - docs/architecture/2026-25-02-coding-teams-research.md
  - docs/architecture/2026-25-02-coding-teams-architecture-research.md
  - docs/architecture/2026-25-02-web-app-architecture-research.md
  - docs/architecture/2026-25-02-scope-assessment.md
  - docs/architecture/2026-25-02-phase6-integration-assessment.md
  - docs/architecture/2026-25-02-gap-analysis-audit.md
---

# Architecture Domain — Distilled

**Date**: 2026-02-25
**Status**: Distilled from Phases 1–6 research + gap analysis audit
**Scope**: Full system architecture for A2A agent team orchestration

---

## 1. Settled Architecture

### 1.1 Problem Statement

A user working in any CLI agent (Claude, Gemini, Codex, or future tool)
delegates a coding task to a team of agents. The team works collaboratively —
planning, coding, reviewing — and returns results. The orchestration layer is
CLI-agnostic: not coupled to any single vendor's agent framework.

### 1.2 Protocol Stack

Three protocols at distinct layers:

| Layer | Protocol | Role |
|-------|----------|------|
| Client ↔ Agent | ACP | Session control, streaming, permissions (IDE integration) |
| Agent ↔ Agent | A2A | Discovery, tasks, artifacts, multi-turn collaboration |
| Agent ↔ Tools | MCP | Tool calling, resource access, prompts |

**Adopted position**: A2A + MCP are the implementation pair. ACP concepts
(SessionAccumulator, PermissionBroker) are ported as patterns without adopting
the ACP transport. ACP-as-protocol is deferred for future IDE integration.

### 1.3 Two-Interface Architecture

The system exposes two interfaces to the user:

**Interface 1 — CLI Bridge (MCP Tools)**

For Claude CLI, Gemini CLI, or any MCP-compatible tool. Delegation interface:

```
MCP Tool Surface:
  team/create(task_description, config) → session_id
  team/status(session_id) → {agents: [...], progress: ...}
  team/artifacts(session_id) → {files: [...]}
  team/approve(session_id, request_id, decision)
  team/message(session_id, text)
  team/cancel(session_id)
```

Uses stable MCP tools (not experimental MCP tasks). Custom polling via
`team/status`. No dependency on experimental features.

**Interface 2 — Web Dashboard (WebSocket)**

Rich monitoring when the CLI isn't enough. Observation interface:

```
WebSocket Events:
  agent_status_update(agent_id, status, message)
  agent_artifact_update(agent_id, artifact)
  permission_request(agent_id, tool_call, options)
  team_progress(overall_status, task_graph)
```

Per-agent panels, live code streaming, permission queue, chat input.

**Usage modes**: CLI-only (quick delegation + polling), dashboard-only (real-time
observation), or hybrid (delegate from CLI, observe in browser).

### 1.4 Process Topology

Hybrid architecture (orchestrator process + on-demand agent spawning):

```
┌────────────────────────────────────────────────────┐
│ Orchestrator Process                                │
│                                                     │
│  MCP Server (CLI interface)                        │
│  A2A Client (agent communication)                  │
│  Process Manager (spawn, health check, restart)    │
│  Event Aggregator (SSE fan-in, WebSocket fan-out)  │
│  Web UI Server (REST + WebSocket + static files)   │
│  Task Store (SQLite)                               │
└──────────────┬─────────────────┬───────────────────┘
               │ A2A HTTP/SSE    │ A2A HTTP/SSE
               ▼                 ▼
        ┌─────────────┐  ┌─────────────┐
        │ Coder Agent │  │ Review Agent│
        │ subprocess  │  │ subprocess  │
        │ port: auto  │  │ port: auto  │
        │ A2A Server  │  │ A2A Server  │
        │ MCP Client  │  │ MCP Client  │
        └─────────────┘  └─────────────┘
```

- Orchestrator is the only long-lived process
- Agents spawned as subprocesses on demand, ports auto-assigned
- Agents are ephemeral (spawned per task, killed when done) for v1
- Single orchestrator (not distributed) for v1

### 1.5 Team Composition

Flat + pipeline hybrid (supervisor pattern with internal loops):

```
Orchestrator (Supervisor)
├── Planner Agent     → produces implementation plan
├── Coder Agent(s)    → implements according to plan
├── Reviewer Agent    → reviews implementation
└── (loop: Coder fixes → Reviewer re-reviews → done)
```

The supervisor LLM routes to agents. The coder→reviewer loop runs as a
sub-pipeline within the flat team structure.

### 1.6 Tool Strategy

Three tool patterns used in combination:

1. **In-process tools** — Python functions callable by the agent LLM directly
2. **MCP tools over stdio** — Agent connects to a scoped MCP server for
   filesystem, git, and build operations
3. **A2A delegation as tools** — Host agent's "tools" are A2A client calls
   to other agents (the LLM sees `send_message` as a tool)

Each agent gets a **scoped MCP tool server** with filesystem root restricted
to its worktree and an allowed command set:

```
Planner:  read_file (any), NO write_file
Coder:    read_file (any), write_file (worktree only), run_command (build/test)
Reviewer: read_file (any), read_diff, NO write_file
```

### 1.7 Workspace Isolation

Git worktrees provide per-task filesystem isolation:

```
/repo (main)
├── .worktrees/
│   ├── task-001/   ← Coder A (dedicated branch)
│   └── task-002/   ← Coder B (dedicated branch)
```

Merge happens after review, not during coding. Orchestrator manages worktree
lifecycle.

### 1.8 State Management

- **Server-authoritative state** — agent state lives on the server; the browser
  is a view
- **Event sourcing to SQLite** — all agent events appended to ordered log;
  current state derived as a projection
- **WebSocket reconnection** — hybrid: rolling event buffer (last N per agent)
  - full snapshot fallback
- **Single multiplexed WebSocket** per browser client (Grafana Live pattern)
- **Client-local state** — UI-only: selected panel, scroll position, layout

### 1.9 ACP Pattern Adoption

ACP concepts ported without ACP transport:

| ACP Pattern | Our Adaptation |
|-------------|---------------|
| SessionAccumulator | Per-agent state accumulator consuming A2A events |
| PermissionBroker | Permission request routing: agent → WebSocket → browser → response |
| ToolCallTracker | Tool call monitoring per agent |

The `request_permission` blocking pattern (agent pauses until user responds) is
the cleanest human-in-the-loop mechanism and is adopted as the core permission
flow.

---

## 2. Tech Stack

### 2.1 Settled Choices

| Layer | Choice | Rationale |
|-------|--------|-----------|
| Language | Python 3.13 | Project constraint |
| Package manager | uv | Project constraint |
| Backend framework | FastAPI | DI, auto-docs, same Starlette WebSocket core |
| ASGI server | Uvicorn | Standard, used by all A2A samples |
| Frontend framework | SvelteKit (Svelte 5) | Runes reactivity, xterm-svelte, proven with FastAPI |
| UI Component System | shadcn-svelte + Tailwind v4 | High-readability primitives, fast CSS engine, overrides Vanilla CSS mandate |
| Terminal emulator | xterm.js via xterm-svelte | Universal standard |
| Code viewer | CodeMirror 6 | 124KB vs Monaco 2MB, read-only, incremental updates |
| Syntax highlighting | Shiki | VS Code quality, WASM-based |
| Markdown rendering | Incremark or Streamdown | O(n) streaming, avoids O(n²) re-parse |
| State store | SQLite via aiosqlite | Zero-config, WAL mode, single-file |
| Build tool | Vite (via SvelteKit) | Fast, standard |
| A2A SDK | a2a-python | Official, full protocol support |
| MCP SDK | mcp-python-sdk | For CLI integration + tool serving |
| Deployment | pip install + uvicorn | Follow Jupyter/Open WebUI model |

### 2.2 Undecided

| Component | Options | Status |
|-----------|---------|--------|
| Agent framework | Vanilla A2A SDK / LangGraph | Initial lean toward LangGraph for stateful agents; never confirmed |
| LLM provider abstraction | Direct SDKs / LiteLLM | LiteLLM mentioned but never evaluated |
| WebSocket lib | Starlette built-in | Effectively decided (comes with FastAPI) |
| Process management | asyncio subprocesses | Effectively decided (simplest for local) |

---

## 3. Component Inventory

### 3.1 Reusable (No Custom Code)

| Component | Source |
|-----------|--------|
| A2A server/client, Agent Card serving | a2a-python SDK |
| Event queue + streaming | a2a-python EventQueue |
| Task persistence (SQLAlchemy) | a2a-python server/models.py |
| MCP server with decorators | mcp-python-sdk |
| MCP client (tool discovery/calling) | mcp-python-sdk |
| HTTP + WebSocket + REST | FastAPI/Starlette |
| Terminal emulation | xterm.js via xterm-svelte |
| Code viewing | CodeMirror 6 |

### 3.2 Requires Adaptation

| Component | Source | Adaptation |
|-----------|--------|-----------|
| SessionAccumulator | ACP contrib | Port to A2A event types |
| PermissionBroker | ACP contrib | Port to our approval flow |
| Content helpers | ACP contrib | Inform A2A Part construction |
| xterm-svelte | npm package | WebSocket stdout relay integration |

### 3.3 Must Build From Scratch

| Component | Complexity | Notes |
|-----------|-----------|-------|
| **Process Manager** | HIGH | Windows subprocess lifecycle, CTRL_BREAK_EVENT, health probes, restart, port allocation. Highest risk. |
| **Event Aggregator** | HIGH | Multi-SSE fan-in, state accumulation, reconnection, WebSocket fan-out |
| **Scoped MCP Tool Server** | MEDIUM | Per-agent filesystem isolation, path validation, command allowlists |
| **Provider Adapter Layer** | MEDIUM | Per-provider CLI/API wrappers (see agents distilled doc) |
| **LLM Client Abstraction** | MEDIUM | Tool-calling translation across providers |
| **Permission Manager** | MEDIUM | Runtime policy engine, approval flow |
| **WebSocket Connection Manager** | MEDIUM | Channel multiplexing, reconnection |
| **Agent Registry** | LOW | id→port→health mapping |
| **Workspace Manager** | LOW | Git worktree lifecycle |
| **Message Router** | LOW | User→agent routing in team context |
| **Port Allocator** | LOW | Free port discovery + tracking |

### 3.4 Complexity Tiers

**Tier 3 (novel, no direct reference):** Process Manager, Event Aggregator,
Scoped MCP Tool Server, Streaming artifact rendering

**Tier 2 (patterns exist, must adapt):** WebSocket multiplexing, SSE parsing,
permission flow, chat with contextId, xterm.js setup, CodeMirror viewer, Agent
Card routing, MCP tool surface, git worktree management

**Tier 1 (well-understood, library-backed):** A2A server/client, MCP tools,
SQLite persistence, Agent Cards, REST API, static file serving, basic Svelte
components

---

## 4. Data Flows

### 4.1 End-to-End: User → Agent → Result

```
Browser (SvelteKit)
  │ WebSocket JSON: {type: "send_message", agent_id, message}
  ▼
FastAPI WebSocket Handler
  │ Validate, lookup agent
  ▼
Orchestrator (A2A Client)
  │ POST /sendMessageStream to agent A2A server
  ▼
Agent Process (Uvicorn subprocess)
  │ AgentExecutor.execute() → LLM → tools → events
  ▼
EventQueue (bounded 1024)
  │ TaskStatusUpdateEvent, TaskArtifactUpdateEvent
  ▼
SSE Stream → Orchestrator Event Aggregator
  │ Parse, update task state, translate
  ▼
WebSocket broadcast → Browser
  │ Svelte 5 runes → per-agent component update
  ▼
Rendered UI
```

### 4.2 Serialization Boundaries

| Boundary | Format | Key Failure Mode |
|----------|--------|-----------------|
| Browser ↔ WebSocket | JSON | Connection drop |
| FastAPI ↔ A2A Agent | JSON-RPC over HTTP/SSE | Agent crash, port unreachable |
| Agent ↔ MCP Tool Server | JSON-RPC over stdio | Subprocess crash, pipe broken |
| Agent ↔ LLM API | HTTP JSON | Timeout, rate limit, auth failure |
| FastAPI ↔ SQLite | SQL via aiosqlite | DB locked (WAL mitigates) |

### 4.3 Async Handoff Points

| Handoff | Risk |
|---------|------|
| WebSocket → A2A client | Task leak if not cancelled |
| A2A SSE → Event aggregator | Generator not closed on disconnect |
| Agent executor → EventQueue | Queue full (1024), producer blocks |
| Process Manager → subprocess | Windows ProactorEventLoop restrictions |

---

## 5. Build Order and Dependencies

```
Layer 1 (parallel):
  Agent Templates (Executor, Agent Card, LLM glue)
  Orchestrator Core (Process Mgr, Event Agg, Registry, Permissions)

Layer 2 (needs Layer 1):
  Scoped MCP Tool Server
  MCP Tool Surface (CLI bridge)
  Web Backend (FastAPI)

Layer 3 (needs Layer 2):
  Web Frontend (SvelteKit)
  Workspace Manager

```

### Sizing Estimate

| Component | Files | Weight |
|-----------|-------|--------|
| Process Manager | 3–5 | Heavy |
| Event Aggregator | 3–4 | Heavy |
| Frontend (SvelteKit) | 10–15 | Heavy |
| Permission Manager | 2–3 | Medium |
| Coding Agent Template | 2–3 | Medium |
| Scoped MCP Tool Server | 2–3 | Medium |
| Web Backend (FastAPI) | 3–5 | Medium |
| Agent Registry | 1–2 | Light |
| MCP Tool Surface | 1–2 | Light |
| Workspace Manager | 1–2 | Light |
| **Total** | **~30–45** | |

Heaviest work: Process Manager, Event Aggregator, Frontend components.

---

## 6. v1 Scope

### Included

1. Agent panel grid (name, status badge, current task)
2. Agent terminal (xterm.js per agent)
3. Chat interface (routed through orchestrator)
4. Permission modal (approve/reject)
5. Agent controls (start/stop/restart)
6. Task list (active/completed)
7. Artifact viewer (CodeMirror 6 read-only)

### Deferred to v2

- Team composition editor (runtime add/remove/swap)
- Session history and replay
- Cost/token tracking dashboard
- Multi-user support
- Agent-to-agent message visualization
- Long-lived agents
- Distributed agent support
- MCP experimental task integration

---

## 7. Risk Register

| Risk | Impact | Likelihood | Mitigation |
|------|--------|-----------|-----------|
| Windows subprocess issues | High | High | Build Process Manager first, test early |
| Agent LLM costs spiral | High | Medium | Budget per task, token tracking, hard limits |
| MCP tasks never stabilize | Medium | Medium | Already mitigated: using stable tools |
| xterm.js memory with many agents | Medium | Low | Limit scrollback (5K lines) |
| A2A SDK breaking changes | Medium | Low | Pin version, abstract behind thin layer |
| SvelteKit learning curve | Low | Medium | Svelte 5 is simpler than React |
| SQLite contention | Low | Low | WAL mode, single-user |

---

## 8. Open Contradictions

### C1: SSE Rejected for Users but Used Internally

Architecture research rejects SSE streaming for user-facing control (Mode A:
"CLI is frozen during work") but the system uses SSE internally for
agent→orchestrator communication without justifying why the same problems
don't apply internally.

**Needs resolution**: Articulate why internal SSE connections (managed by the
orchestrator with reconnection logic) are acceptable while user-facing SSE
(blocking the CLI) is not.

### C2: Subprocess Spawning — Solved Baseline vs Novel Tier 3

The core architecture document assumes subprocess spawning as a solved
baseline (Option C hybrid is "closest to what samples do"). The scope
assessment marks Process Manager as Tier 3 complexity with "no direct
reference" in the ecosystem.

**Needs resolution**: Acknowledge that agent spawning on Windows is novel work
and size the effort accordingly.

### C3: SQLite Only vs Postgres Mentioned

Web app architecture recommends SQLite exclusively for v1. The architecture
research mentions Postgres in passing. No migration path from SQLite to
Postgres is defined.

**Needs resolution**: Either commit to SQLite for both v1 and v2, or define the
migration path.

### C4: Ephemeral Agents Assumed Without Cold-Start Data

Architecture recommends ephemeral agents ("spawned per task, killed when done")
for v1. Cold-start cost (spawning a Uvicorn subprocess, LLM client init) is
never measured.

**Needs resolution**: Benchmark agent spawn time to validate the ephemeral model.

### C5: MCP Tasks — Most Promising vs Deferred

Architecture research calls MCP async tasks "the most promising pattern"
(Mode C) for CLI integration. Phase 6 then defers it: "Stable MCP tools as
CLI bridge... No dependency on experimental features."

**Settled position**: Use stable MCP tools for v1. The contradiction is
resolved in favor of Phase 6's conservative approach. MCP tasks can be
layered later if the API stabilizes.

### C6: LangGraph — Leaned Toward but Never Decided

Coding-teams research says "Leaning toward: Vanilla A2A SDK for orchestrator
- LangGraph internally for agents that need stateful reasoning loops." No
subsequent document confirms or rejects this.

**Needs resolution**: Evaluate LangGraph for agent internals (checkpointing,
conditional routing) vs keeping everything in vanilla A2A SDK.

### C7: CrewAI and LiteLLM — Listed but Never Evaluated

Both appear in options tables but are never discussed. CrewAI was listed as
an agent framework candidate; LiteLLM as an LLM provider abstraction.

**Needs resolution**: Either formally evaluate or formally discard.

---

## 9. Knowledge Gaps

Incorporates and extends the gap-analysis-audit.md findings.

### CRITICAL (blocks implementation)

**G1: No Provider Adapter Interface** — Four providers analyzed in isolation
but no unified `AgentAdapter` protocol exists. No standard launch command
patterns, credential injection mechanism, or common `LLMClient` interface.
Without this, each provider is a one-off integration.

**G2: LLM Integration Layer Missing** — Token counting, prompt templates,
context overflow handling, tool-calling translation, retry logic, model
selection, multi-turn state, and cost attribution are all undefined. This is
the core of agent behavior.

### HIGH (blocks confident design)

**G3: Process Manager Underspecified** — Health check endpoint, timeout
thresholds, port allocation range, graceful drain behavior, zombie prevention
(Windows Job Objects), cascading failure handling, and orchestrator restart
behavior are all undefined.

**G4: Event Aggregator Reliability Undefined** — SSE reconnection strategy,
event ordering across concurrent streams, deduplication, backpressure,
delivery semantics (at-least-once vs at-most-once), and failure recovery are
all unspecified.

**G5: Permission Flow Granularity Absent** — Approval granularity (per-call?
per-tool? per-session?), concurrent request handling, timeout, escalation,
persistence, and dangerous tool policy are undefined.

**G6: Error Recovery Strategy Absent** — No error taxonomy (transient vs
permanent), no retry logic per error type, no guidance on agent failure
mid-task, partial completion handling, or permission denial recovery.

**G8: Testing Strategy Absent** — Architecture docs contain zero testing
guidance. The "no mocks" mandate combined with complex infrastructure
(subprocesses, WebSockets, SSE) creates an unaddressed challenge.

**G9: Context Window Management Unaddressed** — No strategy for token limit
overflow, cross-agent context transfer, or cumulative token accounting.

**G11: LangGraph Decision Unmade** — Whether to use LangGraph for agent
internal state management (checkpointing, conditional routing) is open.

### MEDIUM (blocks detailed implementation)

**G7: State Persistence Schema Missing** — No database schema, no tables for
tasks/sessions/artifacts/permissions, no recovery protocol after restart, no
migration strategy.

**G10: Merge Conflict Strategy Missing** — No merge strategy (fast-forward?
rebase?), no conflict handling for concurrent coders, no worktree cleanup on
failure, no branch naming convention.

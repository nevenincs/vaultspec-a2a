---
name: 'Control Surface Research Plan'
date: 2026-25-02
type: plan
summary: 'Eight-phase research roadmap from protocol foundations through architecture decision records for the agent team control surface.'
maturity: 30
---

# Research Plan: Agent Team Control Surface

**Date**: 2026-02-25
**Status**: Research Plan (not findings — this defines the work to be done)
**Goal**: Build a comprehensive knowledge library to back architectural
decisions for a web-based control surface capable of monitoring, managing,
and interacting with coding agent teams.

---

## Scope Definition

The control surface is a **deployable web application** that provides:

1. **Monitoring**: Real-time visibility into what each agent is doing
2. **Listing**: See all active agents, tasks, artifacts, sessions
3. **Termination**: Kill agents, cancel tasks, abort sessions
4. **Restart**: Respawn failed agents, retry tasks
5. **MCP Permissions**: Set, view, and manage tool permissions per agent
6. **Interactive Messaging**: Send messages to running agents, receive
   responses, participate in multi-turn conversations
7. **Team Composition**: Add/remove/swap agents in a running team
8. **Terminal Interface**: Syntax-highlighted, web-based terminal view of
   agent output with interactive capability

This is not a dashboard that just shows metrics. It is an **operational
control plane** with full ACP-grade interactivity.

---

## Phase 1: Protocol Foundations

**Goal**: Understand what the protocols provide for real-time bidirectional
communication between a web UI and agent processes.

### 1.1 A2A Streaming Primitives

**Research questions**:

- What exactly can an SSE client receive during agent execution?
- Can a single SSE connection multiplex events from multiple agents?
- What is the reconnection protocol when SSE drops?
- How does `SubscribeToTask` (resubscription) work at the wire level?
- What data is in `TaskStatusUpdateEvent.status.message`? Is it
  structured enough for UI rendering, or just free text?

**Sources to investigate**:

- A2A specification proto files: message definitions for streaming
- `a2a-python` SSE transport implementation
- `a2a-python` client resubscription logic
- `a2a-samples` GUI host implementation (what it renders from events)

**Deliverable**: Document mapping SSE event types → UI render capabilities.

### 1.2 ACP Session Protocol

**Research questions**:

- Can ACP's `session/update` notification stream be consumed by a web
  client, or is it stdio-only?
- What would it take to bridge ACP stdio streams to WebSocket?
- How does `SessionAccumulator` work internally — can it be ported to
  JavaScript for client-side state management?
- What update types does ACP stream? (message chunks, thought chunks,
  tool call starts, tool call progress, plan updates, command updates)
- Is the ACP protocol documented enough to implement a web-native host?

**Sources to investigate**:

- ACP Python SDK interfaces.py — full protocol surface
- ACP contrib/session_state.py — SessionAccumulator internals
- ACP contrib/tool_calls.py — ToolCallTracker internals
- Toad source — how it renders ACP streams into TUI
- ACP specification (if separate from SDK)

**Deliverable**: Feasibility assessment for web-native ACP host.

### 1.3 WebSocket as Unified Transport

**Research questions**:

- Can A2A's SSE be proxied to WebSocket for bidirectional capability?
- What WebSocket libraries integrate with Starlette/FastAPI?
- What message format for the WebSocket channel? (JSON events? Protocol
  buffers? Custom framing?)
- How do existing agent UIs (ChatGPT, Claude.ai, Cursor) handle their
  WebSocket protocols?
- What are the connection lifecycle concerns? (heartbeat, reconnection,
  state recovery after disconnect)

**Sources to investigate**:

- Starlette WebSocket documentation
- FastAPI WebSocket patterns
- Open-source agent UI projects (Open WebUI, LibreChat, LobeChat)
- xterm.js WebSocket terminal protocol

**Deliverable**: WebSocket protocol design document for agent events.

---

## Phase 2: Terminal Emulation Research

**Goal**: Understand what's required for a web-based terminal that can
display agent output with syntax highlighting and interactive capability.

### 2.1 xterm.js Ecosystem

**Research questions**:

- What is xterm.js's architecture? (core, addons, rendering)
- How does xterm.js handle ANSI escape codes for color/formatting?
- What addons exist for search, fit, web links, Unicode?
- How does xterm.js connect to a backend? (WebSocket to PTY?)
- What is the performance ceiling? (thousands of lines? millions?)
- How do projects like VS Code's terminal, Theia, code-server use it?

**Sources to investigate**:

- xterm.js GitHub repository and documentation
- xterm.js addon ecosystem (xterm-addon-fit, xterm-addon-search, etc.)
- node-pty or conpty for backend PTY allocation
- code-server terminal implementation
- Wetty (web terminal) architecture

**Deliverable**: xterm.js integration architecture document.

### 2.2 Syntax Highlighting in Terminal Context

**Research questions**:

- How do you syntax-highlight code output in a terminal emulator?
  (ANSI codes? Overlaid HTML? Post-processing?)
- What libraries handle code syntax highlighting on the web?
  (Shiki, Prism, highlight.js, CodeMirror)
- Can syntax highlighting coexist with terminal ANSI codes?
- How do tools like `bat` (rust) or `rich` (Python) produce
  highlighted terminal output?
- What about diff highlighting for code review views?

**Sources to investigate**:

- Shiki documentation (VSCode's syntax engine, WASM-based)
- Monaco Editor (VS Code's editor component) — for code panels
- CodeMirror 6 architecture — for interactive code editing
- `rich` Python library — terminal-native syntax highlighting
- `bat` — syntax highlighting with ANSI output

**Deliverable**: Syntax highlighting strategy document (terminal vs.
code panel vs. hybrid approach).

### 2.3 Agent Output Rendering

**Research questions**:

- What format does agent output arrive in? (plain text, markdown,
  ANSI-colored, structured JSON, mixed?)
- How do existing agent UIs render streaming LLM output?
- What about rendering tool calls, thinking blocks, plan entries?
- How do you distinguish between "agent is streaming text" and
  "agent is showing terminal command output"?
- What about rendering file diffs, code blocks, error traces?

**Sources to investigate**:

- Claude Code CLI — how it renders to terminal currently
- ACP session/update payloads — exact content format
- Open WebUI / LibreChat message rendering
- Marked.js / markdown-it for markdown rendering
- react-diff-viewer or similar for diff rendering

**Deliverable**: Agent output rendering taxonomy and strategy.

---

## Phase 3: Application Architecture Research

**Goal**: Define the web application stack, understand the deployment model,
and map the full system architecture.

### 3.1 Web Framework Selection

**Research questions**:

- What Python web frameworks support both HTTP API and WebSocket
  simultaneously? (FastAPI, Starlette, Django Channels, Sanic)
- What frontend frameworks are best suited for real-time streaming UIs?
  (React, React, SolidJS, HTMX+Alpine)
- What is the build/deploy story? (single binary? Docker? pip install?)
- What existing "agent IDE" or "agent dashboard" projects exist that
  we can learn from or extend?

**Candidates to evaluate**:

- **Backend**: FastAPI (already in A2A stack) vs. Starlette (lighter)
- **Frontend**: React (ecosystem) vs. React (performance, simplicity)
  vs. HTMX (minimal JS, SSE-native)
- **Hybrid**: Gradio (fast prototyping) vs. Streamlit vs. Panel
- **Full-stack**: Next.js (if going Node) vs. Python-native

**Sources to investigate**:

- FastAPI WebSocket documentation and patterns
- React + React for real-time apps
- HTMX SSE extension documentation
- Open WebUI source code (full agent UI in React)
- Dify source code (agent workflow builder)
- Langflow source code (LangChain visual builder)

**Deliverable**: Framework comparison matrix with pros/cons for our use case.

### 3.2 State Management Architecture

**Research questions**:

- How do you maintain consistent state between server and all connected
  web clients?
- What happens when a client disconnects and reconnects? (state recovery)
- How do you handle optimistic UI updates vs. server-authoritative state?
- What state needs to be persistent (survives restart) vs. ephemeral?
- How do existing real-time apps (Figma, Google Docs, Slack) solve this?

**Topics to investigate**:

- Server-side event sourcing patterns
- CRDT (Conflict-free Replicated Data Types) for collaborative state
- Redux/Zustand/Pinia patterns for client-side state
- WebSocket reconnection and state replay protocols
- SQLite for embedded persistent state (vs. Redis, Postgres)

**Deliverable**: State management architecture document.

### 3.3 Authentication and Multi-User Concerns

**Research questions**:

- Is this single-user (local dev tool) or multi-user?
- If single-user, do we still need auth? (localhost binding sufficient?)
- If multi-user, how do agent permissions map to user permissions?
- How do existing dev tools handle this? (Jupyter, code-server, Gitpod)

**Deliverable**: Auth requirements document (probably "single-user for v1,
localhost-only, no auth needed").

---

## Phase 4: Agent Lifecycle Management Research

**Goal**: Understand the mechanics of managing agent processes from a web UI.

### 4.1 Process Management Patterns

**Research questions**:

- How do you spawn, monitor, and kill Python subprocesses from an async
  web server?
- What are the pitfalls of `asyncio.create_subprocess_exec` for
  long-lived processes?
- How do you capture stdout/stderr from agent subprocesses and route
  them to WebSocket clients?
- How do you handle zombie processes, orphaned agents, port leaks?
- What does graceful shutdown look like? (SIGTERM → wait → SIGKILL?)

**Sources to investigate**:

- Python asyncio subprocess documentation
- supervisord, circus, or pm2 patterns
- Jupyter kernel management (how Jupyter spawns/kills kernels)
- Docker SDK for Python (if containerizing agents)
- Windows-specific: how `asyncio.create_subprocess_exec` works on Win11

**Deliverable**: Process management design document.

### 4.2 Agent Hot-Swap and Team Composition

**Research questions**:

- Can you replace an agent mid-task? What happens to the A2A task?
- How do you drain an agent (let current work finish) vs. kill it?
- How does the orchestrator update its routing table when agents
  change?
- Can Agent Cards be refreshed at runtime, or are they static?
- How do A2A samples handle agent unavailability?

**Sources to investigate**:

- A2A protocol spec — agent availability and error handling
- Kubernetes rolling update patterns (conceptual analog)
- Circuit breaker pattern implementations
- A2A samples error handling code

**Deliverable**: Agent lifecycle state machine document.

### 4.3 MCP Permission Management

**Research questions**:

- How are MCP tool permissions currently managed? (per-server config?)
- Can permissions be changed at runtime, or only at startup?
- What does the Claude Agent SDK's permission model look like?
  (PermissionMode, CanUseTool callbacks)
- How would a web UI expose and manage per-agent tool permissions?
- What granularity is needed? (per-tool? per-directory? per-operation?)

**Sources to investigate**:

- Claude Agent SDK types.py — PermissionMode, permission structures
- MCP specification — security and authorization
- ACP permission request/response protocol
- Toad permission modal implementation

**Deliverable**: Permission model design document.

---

## Phase 5: Interactive Messaging Research

**Goal**: Understand how to send messages to running agents and handle
multi-turn conversations from a web UI.

### 5.1 A2A Message Injection

**Research questions**:

- Can you send an A2A message to a task that's in `WORKING` state?
  (Not `INPUT_REQUIRED` — just inject a message mid-work)
- What happens if you send a new message with the same `contextId`
  but no `taskId`? (Creates new task in same context?)
- Can you send messages to individual team agents, or only through
  the orchestrator?
- How does the Airbnb sample's routing agent handle mid-conversation
  instructions?

**Sources to investigate**:

- A2A spec: message routing rules
- A2A spec: contextId semantics for concurrent tasks
- a2a-samples multiagent host: how follow-up messages are routed
- ACP prompt method: how client sends input to agent

**Deliverable**: Message injection protocol document.

### 5.2 Multi-Turn Conversation UI

**Research questions**:

- What's the UX for chatting with an agent team? (single chat thread?
  per-agent threads? threaded conversation?)
- How do existing multi-agent UIs handle this? (AutoGen Studio,
  CrewAI Studio, ChatDev)
- How do you show which agent is responding in a team conversation?
- What about showing agent-to-agent messages (not just user↔agent)?

**Sources to investigate**:

- AutoGen Studio source code and UI patterns
- CrewAI Studio (if open source)
- ChatDev visualization of agent conversations
- Slack's thread model (relevant UX analog)

**Deliverable**: Conversation UI design document.

---

## Phase 6: Integration and Complexity Assessment

**Goal**: Map the full integration surface and identify the hardest
engineering problems.

### 6.1 End-to-End Data Flow

**Research task**: Trace the complete data path for one user action:

```
User clicks "Send message to Coder Agent" in web UI
→ WebSocket message to backend
→ Backend routes to orchestrator
→ Orchestrator sends A2A message to agent
→ Agent processes, streams events back
→ Orchestrator aggregates events
→ Backend pushes events over WebSocket
→ Frontend renders updated agent panel
```

Map every serialization boundary, every async handoff, every potential
failure point.

**Deliverable**: End-to-end data flow diagram with failure modes.

### 6.2 Complexity Inventory

**Research task**: For each control surface feature, estimate:

- Protocol support (does A2A/ACP/MCP provide it natively?)
- Custom code required (what must we build from scratch?)
- Library dependencies (what third-party code do we need?)
- UI complexity (simple button? Complex interactive widget?)
- Backend complexity (trivial? Moderate? Hard?)

Features to assess:

1. Agent status monitoring (real-time)
2. Task list with filtering and sorting
3. Artifact browser (view generated code)
4. Agent terminal view (live output stream)
5. Permission management panel
6. Message send/receive interface
7. Agent spawn/kill controls
8. Team composition editor
9. Session history and replay
10. Cost/token tracking dashboard

**Deliverable**: Complexity matrix with effort estimates per feature.

### 6.3 Technology Boundary Map

**Research task**: Identify every technology boundary in the system:

```
Frontend JS ←WebSocket→ Python Backend
Python Backend ←A2A HTTP→ Agent Process
Agent Process ←MCP stdio→ Tool Server
Agent Process ←LLM API→ Model Provider
Python Backend ←SQLite→ Task Store
Frontend JS ←HTTP→ Static Assets
```

For each boundary:

- What serialization format crosses it?
- What happens when it fails?
- What is the latency?
- What is the throughput limit?

**Deliverable**: Technology boundary map with failure mode analysis.

---

## Phase 7: Reference Implementation Survey

**Goal**: Find and study existing projects that have solved pieces of
this problem.

### 7.1 Agent UI Projects

| Project            | What to Study                         | Why                                |
| ------------------ | ------------------------------------- | ---------------------------------- |
| **Open WebUI**     | Full-stack agent UI, React, WebSocket | Mature, open source, similar scope |
| **AutoGen Studio** | Multi-agent conversation UI           | Direct competitor pattern          |
| **Dify**           | Workflow builder + agent execution    | Production-grade agent platform    |
| **Langflow**       | Visual agent builder                  | UI patterns for agent composition  |
| **LobeChat**       | Chat UI with plugin system            | Clean agent interaction patterns   |
| **code-server**    | VS Code in browser                    | Terminal + editor in web context   |
| **Jupyter**        | Kernel management, notebook UI        | Process management patterns        |
| **Grafana**        | Real-time dashboard                   | Monitoring UI patterns             |

**For each project**: Read architecture docs, understand tech stack,
identify reusable patterns, note what works and what doesn't.

**Deliverable**: Reference project analysis document.

### 7.2 Terminal-in-Browser Projects

| Project      | What to Study                  | Why                           |
| ------------ | ------------------------------ | ----------------------------- |
| **xterm.js** | Core terminal emulator         | Likely our terminal component |
| **Wetty**    | Web terminal over SSH          | Full stack reference          |
| **ttyd**     | Terminal sharing via WebSocket | Lightweight reference         |
| **Theia**    | Cloud IDE with terminal        | Enterprise-grade reference    |
| **Gotty**    | Terminal sharing (Go)          | Simple architecture reference |

**Deliverable**: Terminal implementation options document.

---

## Phase 8: Synthesis and Architecture Decision

**Goal**: Combine all research into actionable architecture decisions.

### 8.1 Architecture Decision Records (ADRs)

Based on all preceding research, write ADRs for:

1. **ADR: Web framework selection** (backend + frontend)
2. **ADR: Real-time communication protocol** (WebSocket design)
3. **ADR: Terminal emulation approach** (xterm.js vs. custom)
4. **ADR: State management strategy** (server-authoritative vs. CRDT)
5. **ADR: Agent process management** (subprocess vs. container vs. remote)
6. **ADR: Permission model** (per-agent scoping strategy)
7. **ADR: Message routing** (how user messages reach agents)
8. **ADR: Deployment model** (single binary vs. multi-service)

### 8.2 Prototype Scope Definition

Define the minimum viable control surface:

- Which features are v1 vs. v2?
- What can be stubbed vs. must be real?
- What's the simplest architecture that proves the concept?

---

## Execution Notes

### Parallelization

Phases 1-2 can run in parallel (protocol research + terminal research).
Phase 3 depends on Phase 1 findings.
Phases 4-5 can run in parallel.
Phase 6 depends on all preceding phases.
Phase 7 can run at any time (independent survey).
Phase 8 depends on everything.

### Estimated Depth

Each phase produces 1-3 research documents. Total expected output:
~15-20 documents forming a knowledge library in `docs/coding-teams/`.

### Research vs. Implementation

This plan produces **knowledge documents and architecture decisions only**.
No code is written during this research. Implementation planning starts
after Phase 8 synthesis.

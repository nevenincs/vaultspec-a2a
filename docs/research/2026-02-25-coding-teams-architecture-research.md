---
date: 2026-02-25
type: research
feature: coding-teams-architecture
description: "End-to-end system architecture analysis covering control modes, process topology, tool usage patterns, filesystem scoping, and the two-interface design."
name: "Coding Teams Architecture"
maturity: 35
summary: "End-to-end system architecture analysis covering control modes, process topology, tool usage patterns, filesystem scoping, and the two-interface design."
---

# Research: Architecture & App Considerations for Coding Agent Teams

**Date**: 2026-02-25
**Status**: Preliminary Investigation
**Builds on**: `2026-25-02-coding-teams-research.md`

---

## 1. The Control Problem

The fundamental architectural fork is this: once a CLI delegates work to a team
of agents, **how does the user maintain visibility and control?**

Three modes exist in the current ecosystem:

### 1.1 Mode A: CLI Blocks (Streaming SSE)

The CLI calls `sendMessageStream` and holds an open SSE connection. Events
arrive as they're generated:

```text
CLI ──POST /sendMessageStream──► Orchestrator
CLI ◄──SSE: TaskStatusUpdate────  "working: planning implementation..."
CLI ◄──SSE: TaskArtifactUpdate──  file: src/auth.py (partial)
CLI ◄──SSE: TaskStatusUpdate────  "working: reviewing code..."
CLI ◄──SSE: TaskArtifactUpdate──  file: src/auth.py (final)
CLI ◄──SSE: TaskStatusUpdate────  "completed"
```

**What the a2a-samples CLI host actually does** (`cli/__main__.py`):

- Opens async SSE stream via `send_message_streaming()`
- Iterates events in a `async for`loop
- Prints raw JSON for each event
- Blocks the user's terminal until completion or`input_required`
- Handles multi-turn via `contextId` carry-forward

**Problems for coding teams**:

- CLI is frozen during work. User can't do anything else in that terminal.
- If the connection drops, the team keeps working but the CLI loses visibility.
- No way to see what multiple agents are doing simultaneously — SSE is one
  linear stream from the orchestrator, not per-agent.
- The orchestrator must serialize all agent updates into a single stream,
  losing the inherent parallelism.

### 1.2 Mode B: Fire and Forget (Push Notifications)

The CLI sends a message, gets a task ID, and registers a webhook. The team
works independently and POSTs status updates to the webhook.

```text
CLI ──POST /sendMessage──────────► Orchestrator
CLI ◄──Response: {taskId: "abc"}──
CLI ──POST /setTaskCallback───────► {url: "http://localhost:5000/notify"}

(CLI resumes normal operation)

... later ...
Orchestrator ──POST /notify──► CLI webhook listener
  {taskId: "abc", status: "completed", artifacts: [...]}
```

**What the a2a-samples CLI host does for push notifications**:

- Starts a Starlette server in a daemon thread on a separate port
- Listens on `/notify`endpoint
- Validates via GET with`validationToken`
- Prints notifications to stdout as they arrive

**Problems for coding teams**:

- Fire-and-forget: no mid-stream user input without polling back
- No guaranteed delivery or retry logic in the samples
- User must run a local HTTP server to receive callbacks
- Hard to correlate multiple concurrent team sessions

### 1.3 Mode C: MCP Async Tasks (Experimental)

The CLI calls a tool that returns immediately with a task ID. The CLI polls
for progress and can receive mid-task elicitation requests.

```text
CLI ──call_tool_as_task("orchestrate", {...})──► MCP Server
CLI ◄──CreateTaskResult {taskId: "abc"}────────

CLI ──poll_task("abc")─────► MCP Server
CLI ◄──{status: "working", message: "planning..."}
CLI ──poll_task("abc")─────► MCP Server
CLI ◄──{status: "input_required"}
CLI ──get_task_result("abc")──► MCP Server
CLI ◄──elicitation: "Delete these 3 files? [y/n]"
CLI ──respond: "y"────────────► MCP Server
CLI ──poll_task("abc")─────► MCP Server
CLI ◄──{status: "completed", result: {...}}
```

**This is the most promising pattern** because:

- CLI is NOT blocked — it gets a task ID and can do other work
- Progress is available via polling (server suggests poll interval)
- Mid-task user input works via elicitation callbacks
- Cancellation is supported (cooperative)
- Multiple concurrent tasks trackable via `list_tasks()`

**Problems**:

- Experimental MCP feature — API may change
- Polling is inherently less responsive than SSE streaming
- No rich real-time view of agent internals (just status messages)
- In-memory task store only — no persistence across restarts

---

## 2. The UI Question

Given the control problem, a dedicated UI becomes not a luxury but an
architectural necessity for team orchestration. The samples confirm this:

### 2.1 What Exists in the Samples

**a2a_gui** (`samples/python/hosts/a2a_gui/`):

- FastAPI proxy backend + vanilla JS frontend
- Fetches Agent Card and displays capabilities
- Chat interface with real-time SSE streaming
- Debug panel showing raw JSON events
- Stats: time-to-first-chunk, total latency
- Context ID preserved for multi-turn
- **Limitation**: Single agent view, no team dashboard

**Airbnb Planner Gradio UI** (`airbnb_planner_multiagent/host_agent/`):

- Gradio ChatInterface on port 8083
- Shows tool calls with function names and arguments
- Shows tool responses as formatted JSON
- Final agent response rendered as chat message
- **Limitation**: Opaque — you see the host agent's tool calls to remote
  agents, but not what those agents are doing internally

### 2.2 What's Missing (And Needed)

Neither sample provides:

- **Multi-agent parallel view**: See what each team member is doing
- **Per-agent streaming**: Individual progress streams per coding agent
- **Permission aggregation**: Handle approval requests from multiple agents
- **Artifact preview**: See code being written in real-time
- **Task dependency graph**: Visualize which tasks block which
- **Cost tracking**: Token usage per agent per task

### 2.3 Candidate UI Architecture

```text
┌─────────────────────────────────────────────────┐
│                  Team Dashboard                   │
├──────────────┬──────────────┬───────────────────┤
│ Agent Panel  │ Agent Panel  │ Agent Panel       │
│ ┌──────────┐ │ ┌──────────┐ │ ┌──────────────┐ │
│ │ Planner  │ │ │ Coder A  │ │ │ Reviewer     │ │
│ │ Status:  │ │ │ Status:  │ │ │ Status:      │ │
│ │ complete │ │ │ working  │ │ │ waiting      │ │
│ │          │ │ │          │ │ │              │ │
│ │ Plan:    │ │ │ File:    │ │ │ Pending:     │ │
│ │ - step 1 │ │ │ auth.py  │ │ │ auth.py      │ │
│ │ - step 2 │ │ │ [live]   │ │ │              │ │
│ └──────────┘ │ └──────────┘ │ └──────────────┘ │
├──────────────┴──────────────┴───────────────────┤
│ Permission Requests                              │
│ ┌─────────────────────────────────────────────┐ │
│ │ Coder A wants to: delete old_auth.py        │ │
│ │ [Approve] [Reject] [Approve All Session]    │ │
│ └─────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────┤
│ Chat / Command Input                             │
│ > "Also add rate limiting to the auth module"    │
└─────────────────────────────────────────────────┘
```

---

## 3. Server Architecture Considerations

### 3.1 Process Topology Options

### Option A: Single Process, Multiple Agent Executors

```text
┌──────────────────────────────────────┐
│ Orchestrator Process (Python)        │
│                                      │
│  ┌──────────┐ ┌──────────┐         │
│  │ Planner  │ │ Coder    │  ...    │
│  │ Executor │ │ Executor │         │
│  └──────────┘ └──────────┘         │
│                                      │
│  Uvicorn (port 9000)                │
│  A2AStarletteApplication            │
│  EventQueue per task                │
└──────────────────────────────────────┘
```

- All agents share one process, one port
- Agents are `AgentExecutor` implementations, not separate servers
- Simplest to deploy and manage
- **But**: agents share memory, can't be independently restarted, single
  point of failure, can't use different models per agent easily

### Option B: Process Per Agent (A2A Native)

```text
┌────────────────┐  ┌────────────────┐  ┌────────────────┐
│ Orchestrator   │  │ Coder Agent    │  │ Reviewer Agent │
│ port 9000      │  │ port 9001      │  │ port 9002      │
│                │  │                │  │                │
│ A2A Client ────┼──► A2A Server     │  │ A2A Server     │
│                │  │ AgentExecutor  │  │ AgentExecutor  │
│ A2A Client ────┼──┼────────────────┼──► A2A Server     │
└────────────────┘  └────────────────┘  └────────────────┘
```

- Each agent is a separate Uvicorn process
- Full A2A protocol between them (Agent Cards, Tasks, Messages)
- Agents independently deployable, restartable, scalable
- **But**: requires process management, port allocation, health checks —
  none of which A2A provides out of the box

### Option C: Hybrid — Orchestrator Process + On-Demand Agent Spawning

```text
┌──────────────────────────────────────────────┐
│ Orchestrator Process                          │
│                                               │
│  ┌──────────────────────────────────────────┐│
│  │ Agent Manager                            ││
│  │  spawn_agent("coder", port=auto) ────────┼┼──► subprocess
│  │  spawn_agent("reviewer", port=auto) ─────┼┼──► subprocess
│  │  health_check() / shutdown()             ││
│  └──────────────────────────────────────────┘│
│                                               │
│  Uvicorn (port 9000) ← MCP + A2A Server     │
└──────────────────────────────────────────────┘
```

- Orchestrator is the only long-lived process
- Agents spawned as subprocesses on demand
- Port auto-assigned (OS picks free port)
- Orchestrator manages lifecycle (start, health check, restart, shutdown)
- **This is closest to what the Airbnb sample does** (minus the auto-spawn)

### 3.2 What the Samples Actually Do

Every sample uses **manual launch per terminal**. No automation. The typical
multi-agent system requires:

1. Terminal 1: `uv run weather_agent --port 10001`
2. Terminal 2: `uv run airbnb_agent --port 10002`
3. Terminal 3: `uv run host_agent`(connects to 10001, 10002 via env vars)

The walkthrough documents port ranges: agents on`9999-9996`, infrastructure
on separate ranges.

**What's NOT provided by any sample**:

- Process supervisor / auto-restart
- Dynamic port allocation
- Health check endpoints (one Azure sample has a custom `/health`)
- Service registry / discovery beyond manual Agent Card URLs
- Graceful shutdown coordination
- State persistence across restarts (InMemoryTaskStore only)

### 3.3 Recommended Architecture: Hybrid with Process Manager

```text
┌──────────────────────────────────────────────────────┐
│                   Orchestrator                        │
│                                                       │
│  MCP Server (for CLI integration)                    │
│  ├── tool: delegate_task(description) → task_id      │
│  ├── tool: check_progress(task_id) → status          │
│  ├── tool: get_results(task_id) → artifacts          │
│  └── tool: cancel_task(task_id)                      │
│                                                       │
│  A2A Client (for agent communication)                │
│  ├── discovers agents via Agent Cards                │
│  ├── sends tasks via sendMessage / sendMessageStream │
│  └── aggregates results into MCP tool responses      │
│                                                       │
│  Process Manager                                     │
│  ├── spawn agents as subprocesses                    │
│  ├── assign ports from pool                          │
│  ├── health check loop                               │
│  ├── restart on failure                              │
│  └── graceful shutdown                               │
│                                                       │
│  Web UI Server (for monitoring)                      │
│  ├── WebSocket for real-time updates                 │
│  ├── per-agent status streams                        │
│  └── permission request aggregation                  │
│                                                       │
│  Task Store (persistent)                             │
│  └── SQLite for local dev, Postgres for production   │
└──────────────────────────────────────────────────────┘
         │                    │
         ▼                    ▼
┌──────────────┐    ┌──────────────┐
│ Coder Agent  │    │ Review Agent │
│ subprocess   │    │ subprocess   │
│ port: auto   │    │ port: auto   │
│ A2A Server   │    │ A2A Server   │
│ MCP Client   │    │ MCP Client   │
│ (for tools)  │    │ (for tools)  │
└──────────────┘    └──────────────┘
```

---

## 4. Tool Usage and Filesystem Access

### 4.1 How Agents Actually Get Tools (From the Samples)

Three patterns observed:

### Pattern 1: In-Process Tools (Most Common)

Agent tools are Python functions in the same process. The LLM calls them via
tool-use, and they execute directly:

```python
# From a2a-samples: tools are just async functions
async def read_file(path: str) -> str:
    return Path(path).read_text()

async def write_file(path: str, content: str) -> str:
    Path(path).write_text(content)
    return f"Written to {path}"
```

Results flow back to the LLM within the same execution context. No protocol
overhead.

### Pattern 2: MCP Tools Over HTTP/SSE (a2a-mcp-without-framework)

Agent connects to an MCP server to discover and call tools:

```python
async with sse_client(mcp_url) as (read, write):
    async with ClientSession(read, write) as session:
        await session.initialize()
        tools = await session.list_tools()      # discover
        result = await session.call_tool(name, args)  # execute
```

This is the pattern for accessing external tool servers — filesystem, git,
build systems.

### Pattern 3: A2A Delegation as Tool Use (Host Agent Pattern)

The host agent's "tools" are actually A2A client calls to other agents:

```python
async def send_message(agent_name: str, message: str, tool_context: ToolContext):
    client = self.remote_agent_connections[agent_name]
    response = await client.send_message(request_message)
    # Store task_id, context_id in tool_context.state for next call
```

The LLM sees `send_message`as a tool. It doesn't know it's calling another
agent.

### 4.2 Filesystem Access: The Autonomy Problem

Coding agents need to read and write files. This is where autonomy gets
dangerous:

**Current state**: No sample implements filesystem scoping. If an agent has
a`write_file` tool, it can write anywhere the process has access.

**What we need**:

```text
Per-Agent Scoped Tool Provision:

Planner Agent:
  - read_file (any path)          ← needs to understand codebase
  - NO write_file                 ← plans, doesn't implement

Coder Agent:
  - read_file (any path)
  - write_file (scoped to worktree)  ← writes to isolated branch
  - run_command (scoped: build, test only)
  - NO delete_file without approval

Reviewer Agent:
  - read_file (any path)
  - read_diff (worktree vs main)
  - NO write_file                 ← reviews, doesn't modify
```

**Implementation approach**: Each agent gets its own MCP server instance with
a scoped filesystem root and allowed command set:

```python
# Conceptual
coder_mcp = create_scoped_mcp_server(
    filesystem_root="/repo/.worktrees/task-123",
    allowed_commands=["python", "pytest", "ruff"],
    write_enabled=True,
)

reviewer_mcp = create_scoped_mcp_server(
    filesystem_root="/repo",
    allowed_commands=["git diff", "ruff check"],
    write_enabled=False,
)
```

### 4.3 Workspace Isolation via Git Worktrees

The strongest isolation pattern for concurrent coding agents:

```text
/repo (main)
├── .worktrees/
│   ├── task-001/           ← Coder A works here
│   │   └── (full repo checkout on branch task-001)
│   └── task-002/           ← Coder B works here
│       └── (full repo checkout on branch task-002)
```

- Each coding task gets a worktree with a dedicated branch
- Agents can't accidentally overwrite each other's work
- Merge happens after review, not during coding
- The orchestrator manages worktree lifecycle

### 4.4 Tool Results Through A2A

When a coding agent finishes work, results flow back as A2A artifacts:

```python
# Agent executor publishes code artifacts
await event_queue.enqueue_event(TaskArtifactUpdateEvent(
    task_id=task.id,
    context_id=task.context_id,
    artifact=Artifact(
        artifact_id=str(uuid4()),
        name="src/auth.py",
        parts=[Part(root=FilePart(
            file=FileWithBytes(
                name="auth.py",
                bytes=base64.b64encode(code.encode()).decode()
            )
        ))],
    ),
    last_chunk=True,
))
```

The JS coder sample shows the streaming pattern: emit each file as an
artifact as soon as it's complete, don't wait for all files.

---

## 5. The ACP Angle: What Toad Teaches Us

Toad (ACP host) solves the control problem differently — through rich
bidirectional streaming with permission gates:

### 5.1 ACP's Control Model

```text
Agent ──session/update──► Client     (continuous streaming, no response needed)
Agent ──request_permission──► Client  (BLOCKS agent until user responds)
Client ──prompt──► Agent              (user input, not streamed)
```

**Key insight**: The `request_permission`RPC **pauses the agent**. The agent
literally waits on a JSON-RPC response. This is the cleanest human-in-the-loop
pattern in any of the protocols.

### 5.2 SessionAccumulator Pattern

ACP's`SessionAccumulator` maintains a canonical snapshot of agent state:

```python
accumulator = SessionAccumulator()

# Every notification merges into snapshot
for notification in agent_stream:
    snapshot = accumulator.apply(notification)
    # snapshot.tool_calls — all active/completed tool calls
    # snapshot.agent_messages — all streamed text chunks
    # snapshot.plan_entries — current plan state

# UI subscribes to snapshot changes
accumulator.subscribe(lambda snap, notif: render(snap))
```

**Why this matters**: For a team of agents, each agent gets its own
`SessionAccumulator`. The UI subscribes to all of them. No manual state
merging required.

### 5.3 Permission Flow for Teams

```python
# Conceptual team orchestrator using ACP patterns
class TeamOrchestrator:
    accumulators: dict[str, SessionAccumulator]  # per agent
    brokers: dict[str, PermissionBroker]         # per agent

    async def handle_permission(self, agent_id, tool_call):
        broker = self.brokers[agent_id]
        # This BLOCKS the requesting agent until user responds
        response = await broker.request_for(
            external_id=tool_call.id,
            description=f"{agent_id} wants to: {tool_call.title}"
        )
        return response
```

The user sees permission requests from all agents in a unified queue.
Each agent independently pauses until its request is approved.

---

## 6. Integration Strategy: Putting It Together

### 6.1 The Two-Interface Architecture

The system needs two interfaces:

### Interface 1: CLI Bridge (MCP)

For Claude CLI, Gemini CLI, or any MCP-compatible tool. This is the
"delegation" interface — user kicks off work and gets a handle.

```text
MCP Tool Surface:
  team/create(task_description, config) → session_id
  team/status(session_id) → {agents: [...], progress: ...}
  team/artifacts(session_id) → {files: [...]}
  team/approve(session_id, request_id, decision)
  team/message(session_id, text) → send instruction to team
  team/cancel(session_id)
```

Using MCP experimental tasks, `team/create` returns immediately with a
task ID. The CLI can poll for status. If a permission request comes in,
the MCP elicitation mechanism prompts the user.

### Interface 2: Web Dashboard (WebSocket)

For rich monitoring when the CLI isn't enough. This is the "observation"
interface — user watches work happen in real-time.

```text
WebSocket Events:
  agent_status_update(agent_id, status, message)
  agent_artifact_update(agent_id, artifact)
  permission_request(agent_id, tool_call, options)
  team_progress(overall_status, task_graph)
```

The dashboard shows per-agent panels, live code streaming, a permission
queue, and a chat input for sending instructions to the team.

### 6.2 Why Both Interfaces

- **CLI-only workflow**: Quick delegation. "Hey team, implement auth."
  User checks back later via `team/status`. Approves permissions via
  `team/approve`. Gets results via `team/artifacts`.

- **Dashboard workflow**: User opens browser alongside CLI. Watches agents
  work in real-time. Approves permissions via click. Sends mid-stream
  instructions. Sees code being written live.

- **Hybrid**: User delegates from CLI, opens dashboard when they want
  more detail, goes back to CLI for quick checks.

### 6.3 Communication Flow

```text
┌───────────┐     MCP      ┌───────────────────────────────────┐
│ Claude CLI │◄────────────►│                                   │
│ Gemini CLI │              │         Orchestrator              │
│ Any CLI    │              │                                   │
└───────────┘              │  ┌─────────────────────────────┐  │
                            │  │ MCP Server (CLI interface)  │  │
┌───────────┐   WebSocket  │  │ A2A Client (agent comms)    │  │
│ Dashboard │◄────────────►│  │ Process Manager              │  │
│ (Browser) │              │  │ Task Store                   │  │
└───────────┘              │  │ Event Aggregator             │  │
                            │  └─────────────────────────────┘  │
                            │                                   │
                            │  A2A Protocol (HTTP/SSE)          │
                            └────────┬──────────┬───────────────┘
                                     │          │
                            ┌────────▼──┐ ┌────▼───────┐
                            │ Coder     │ │ Reviewer   │
                            │ Agent     │ │ Agent      │
                            │ (subprocess)│ (subprocess)│
                            └───────────┘ └────────────┘
```

---

## 7. Tech Stack Candidates

### 7.1 Core (Decided)

| Component | Choice | Reason |
| ----------- | -------- | -------- |
| Language | Python 3.13 | Per project constraints |
| Package mgr | uv | Per project constraints |
| A2A SDK | a2a-python | Official SDK, full protocol support |
| MCP SDK | mcp-python-sdk | For CLI integration + tool serving |
| HTTP framework | Starlette or FastAPI | A2A SDK ships adapters for both |
| ASGI server | Uvicorn | Standard, used by all samples |

### 7.2 To Decide

| Component | Options | Notes |
| ----------- | --------- | ------- |
| Agent framework | Vanilla A2A SDK / LangGraph / Claude Agent SDK | Vanilla gives most control; LangGraph adds checkpointing; Claude SDK adds hooks |
| Task store | InMemory / SQLite / PostgreSQL | SQLite for local dev is pragmatic; A2A SDK has SQLAlchemy adapters |
| Web UI framework | Vanilla JS / HTMX / Gradio / React | Gradio is quick but limited; HTMX fits the SSE streaming model well |
| WebSocket lib | Starlette built-in / FastAPI WebSockets | No additional dependency needed |
| Process management | asyncio subprocesses / supervisord / custom | asyncio.create_subprocess_exec is simplest for local |
| LLM provider | Anthropic / Google / OpenAI / LiteLLM | A2A is model-agnostic; LiteLLM gives flexibility |

### 7.3 Agent Internal Architecture

Each coding agent would be:

```text
┌──────────────────────────────────────┐
│ Coding Agent Process                  │
│                                       │
│  A2A Server (Starlette + Uvicorn)    │
│  ├── AgentCard at /.well-known/      │
│  ├── DefaultRequestHandler           │
│  └── AgentExecutor (our logic)       │
│                                       │
│  LLM Client (model-specific)        │
│  ├── System prompt with role         │
│  ├── Tool definitions                │
│  └── Reasoning loop                  │
│                                       │
│  MCP Client (for workspace tools)    │
│  ├── filesystem (scoped to worktree) │
│  ├── git operations                  │
│  ├── build/test commands             │
│  └── LSP integration (future)       │
│                                       │
│  EventQueue → streams results back   │
└──────────────────────────────────────┘
```

---

## 8. Open Architecture Questions

### 8.1 Single Orchestrator or Distributed?

**Single orchestrator** (recommended for v1):

- One process manages everything
- Spawns agent subprocesses
- Aggregates all events
- Serves both MCP (for CLI) and WebSocket (for dashboard)
- Simpler to debug, deploy, and reason about

**Distributed** (future):

- Orchestrator is itself an A2A agent that other orchestrators can call
- Agents can run on different machines
- Requires service discovery, distributed task store, network auth

### 8.2 Agent Persistence Model

**Ephemeral agents** (recommended for v1):

- Spawned per task, killed when done
- No state between tasks
- Simpler lifecycle management

**Long-lived agents** (future):

- Run continuously, accept multiple tasks
- Maintain learned context (project conventions, file layout)
- Better performance (no cold start) but more complex management

### 8.3 How Many Ports?

Minimum viable:

- 1 port for orchestrator (MCP server + web UI + A2A client)
- 1 port per active agent (A2A server)
- Or: agents communicate via stdio instead of HTTP (eliminates ports
  but loses A2A protocol compliance)

### 8.4 MCP Task Maturity Risk

The experimental MCP task system is the ideal CLI bridge but:

- API explicitly marked experimental
- No persistence layer beyond in-memory
- Not yet widely supported in CLI tools
- May change in breaking ways

**Mitigation**: Abstract the CLI interface behind our own tool surface.
If MCP tasks break, we can fall back to simple tool calls with polling.

---

## 9. Sources

### Implementation Details

- **CLI streaming**: `a2a-samples/samples/python/hosts/cli/__main__.py`
- **GUI host**: `a2a-samples/samples/python/hosts/a2a_gui/`
- **Multi-agent host**: `a2a-samples/samples/python/hosts/multiagent/`
- **JS coder agent**: `a2a-samples/samples/js/src/agents/coder/`
- **Airbnb routing**:
  `a2a-samples/samples/python/agents/airbnb_planner_multiagent/`

### Protocol Internals

- **EventQueue**: `a2a-python/src/a2a/server/events/event_queue.py`
- **Client streaming**: `a2a-python/src/a2a/client/base_client.py`
- **Task tracking**: `a2a-python/src/a2a/client/client_task_manager.py`
- **MCP tasks**: `mcp-python-sdk/src/mcp/shared/experimental/tasks/`

### Control Patterns

- **ACP streaming**: `acp-python-sdk/src/acp/agent/connection.py`
- **SessionAccumulator**: `acp-python-sdk/src/acp/contrib/session_state.py`
- **PermissionBroker**: `acp-python-sdk/src/acp/contrib/permissions.py`
- **Toad audit**: `knowledge/repositories/toad-acp-audit.md`
- **Claude Agent SDK**: `knowledge/repositories/claude-agent-sdk/`

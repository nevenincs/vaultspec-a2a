---
date: 2026-02-25
type: research
feature: coding-teams
description: 'Foundational investigation of the A2A/ACP/MCP protocol landscape, team composition patterns, and key technical decisions for multi-agent coding teams.'
name: 'Coding Teams Research'
maturity: 30
summary: 'Foundational investigation of the A2A/ACP/MCP protocol landscape, team composition patterns, and key technical decisions for multi-agent coding teams.'
---

# Research: Coding Agent Teams via A2A Orchestration

**Date**: 2026-02-25
**Status**: Preliminary Investigation
**Scope**: Identifying sources, patterns, and candidate architectures for
delegating coding tasks from CLI agents to teams of coding agents.

---

## 1. Problem Statement

We want to enable a workflow where:

1. A user works inside a **CLI agent** (Claude CLI, Gemini CLI, or any future
   CLI tool).
2. The user delegates a coding task to a **team of coding agents**.
3. The team works collaboratively — planning, coding, reviewing — and returns
   results.
4. This must work **regardless of which CLI the user starts from**.

The key constraint is **CLI-agnosticism**: the orchestration layer must not be
coupled to any single vendor's agent framework.

---

## 2. Protocol Landscape

Three protocols form the relevant stack. Each operates at a different layer:

```text
┌─────────────────────────────────────────────────┐
│  ACP (Agent Client Protocol)                    │
│  Client ↔ Agent session control                 │
│  Streaming, permissions, terminal, files        │
│  Transport: stdio JSON-RPC                      │
├─────────────────────────────────────────────────┤
│  A2A (Agent-to-Agent Protocol)                  │
│  Agent ↔ Agent collaboration                    │
│  Discovery, tasks, artifacts, multi-turn        │
│  Transport: HTTP JSON-RPC / gRPC / REST + SSE   │
├─────────────────────────────────────────────────┤
│  MCP (Model Context Protocol)                   │
│  Agent ↔ Tools/Resources                        │
│  Tool calling, resource access, prompts         │
│  Transport: stdio / HTTP / SSE                  │
└─────────────────────────────────────────────────┘
```

### 2.1 A2A Protocol (Core of our approach)

**What it is**: Open standard (Google → Linux Foundation) for agent-to-agent
communication. Agents are opaque black boxes that discover each other via Agent
Cards and exchange work via Tasks.

**Core primitives**:

| Primitive  | Purpose                                                                                       |
| ---------- | --------------------------------------------------------------------------------------------- |
| Agent Card | JSON manifest at `/.well-known/agent-card.json`declaring identity, skills, auth, capabilities |
| Task       | Stateful unit of work with lifecycle:`pending → running → completed/failed/canceled`          |
| Message    | Single turn of communication (role: user or agent)                                            |
| Part       | Content container: text, file, or structured data                                             |
| Artifact   | Tangible output (code files, documents, data)                                                 |
| contextId  | Groups related tasks into a logical session                                                   |

**Interaction modes**:

- Request/Response (polling)
- Streaming via SSE
- Push notifications (webhooks for long-running work)

**Why it matters for us**: A2A is the only protocol designed for agent-to-agent
collaboration where agents are autonomous peers. It doesn't care what framework
or model powers each agent — only that they speak HTTP and JSON-RPC.

### 2.2 ACP (Agent Client Protocol)

**What it is**: Protocol for bidirectional client-agent sessions. Used by Toad
(the ACP host) for IDE/terminal integration.

**Relevant features**:

- Streaming agent output (`session/update`notifications)
- Permission request flows (human-in-the-loop)
- Terminal creation and management
- File read/write operations
- Session mode and model management

**Why it matters**: ACP describes how a CLI client talks to a single agent. If
we build the orchestration layer as an ACP-compatible agent, any ACP host
(including future ones) can drive it.

### 2.3 MCP (Model Context Protocol)

**What it is**: Protocol for connecting agents to tools and resources. Agents
discover capabilities and invoke them.

**Relevant features**:

- Tool registration with JSON schema
- Resource discovery
- Experimental async tasks (working → input_required → completed)
- Elicitation and sampling mid-task

**Why it matters**: MCP is how agents get their tools. Our coding agents need
file access, git operations, build commands, LSP integration — all exposable as
MCP tools. MCP is also how both Claude CLI and Gemini CLI already integrate with
external capabilities.

---

## 3. Existing Implementation Patterns

### 3.1 a2a-samples: Multi-Agent Host

**Source**:`knowledge/repositories/a2a-samples/samples/python/hosts/multiagent/`

The multi-agent host demonstrates the **Discovery → Delegation → Aggregation**
pattern:

1. **HostAgent** discovers remote agents by fetching Agent Cards
2. LLM-driven routing via two tools:
   - `list_remote_agents()`— returns available agents with descriptions -`send_message(agent_name, message)`— delegates to named agent
3. State tracked per context:`context_id`, `task_id`, `session_active`
4. Responses aggregated and returned to user

**Key insight**: The host agent is itself an LLM that decides _which_ remote
agent to invoke. This is the "supervisor" pattern.

### 3.2 a2a-samples: JS Coder Agent

**Source**: `knowledge/repositories/a2a-samples/samples/js/src/agents/coder/`

Demonstrates a coding-specific agent pattern:

- Uses Genkit + Gemini 2.5 Pro for code generation
- **Streaming artifacts**: Files emitted incrementally as completed
- **Markdown-based code protocol**: Backtick-delimited code blocks with filename
  metadata
- Custom output format definition tells LLM how to structure multi-file output
- Cancellation support via task tracking

**Key insight**: The coder agent treats each file as a streamable artifact,
emitting them as soon as they're ready rather than waiting for all files.

### 3.3 A2A Walkthrough: Four Framework Patterns

**Source**: `knowledge/repositories/a2a-walkthrough.md`

Documents four patterns for building A2A agents:

| Pattern | Framework       | Best For                            |
| ------- | --------------- | ----------------------------------- |
| A       | Vanilla A2A SDK | Lightweight agents, direct control  |
| B       | Google ADK      | Tool-heavy agents (search, APIs)    |
| C       | LangGraph + MCP | Stateful workflows with local tools |
| D       | BeeAI Concierge | Master router over multiple agents  |

**Key insight**: Pattern C (LangGraph + MCP) is the most relevant for coding
agents — stateful reasoning loops with local tool access (file system, git,
build tools).

### 3.4 Airbnb Planner: Routing Agent Pattern

**Source**:
`knowledge/repositories/a2a-samples/samples/python/agents/airbnb_planner_multiagent/`

Advanced routing with:

- Async factory pattern for agent initialization
- Dynamic instruction generation from agent roster
- Active agent tracking for session continuity
- Emphasis on agent autonomy: "Never seek user permission before engaging with
  remote agents"

**Key insight**: The routing agent maintains awareness of which sub-agent is
currently active, enabling seamless multi-turn conversations through the router.

### 3.5 Claude Agent SDK

**Source**: `knowledge/repositories/claude-agent-sdk/`

Anthropic's SDK for building on Claude Code:

- `ClaudeSDKClient`for bidirectional conversations -`query()`for one-shot async queries
- **Custom in-process MCP servers** via`@tool`decorator
- **Hooks system**: PreToolUse, PostToolUse, UserPromptSubmit, SessionStart
- **Permission modes**: default, acceptEdits, plan, bypassPermissions
- Extended thinking support

**Key insight**: The hooks system enables deterministic interception of agent
actions — critical for a team orchestrator that needs to enforce coding
standards, review policies, or safety constraints.

### 3.6 LangGraph State Machine Patterns

**Source**:`knowledge/repositories/langgraph/`

- State graph with typed schemas
- Conditional routing between nodes (agents)
- **Checkpointing** for persistence and "time travel"
- Subgraph pattern: wrap multi-agent workflow as single node

**Key insight**: Map A2A `contextId`to LangGraph`thread_id` for persistent
multi-turn team sessions. Checkpointing enables resumable coding sessions.

---

## 4. Candidate Architecture: CLI → Team Delegation

### 4.1 The Integration Point: MCP as Universal Bridge

Both Claude CLI and Gemini CLI support MCP servers. This is our primary
integration vector:

```text
┌──────────────┐     MCP      ┌──────────────────┐     A2A      ┌─────────────┐
│  Claude CLI  │◄────────────►│                  │◄────────────►│ Coder Agent │
│  Gemini CLI  │   (tools)    │  Team            │   (tasks)    │ Review Agent│
│  Any CLI     │              │  Orchestrator    │              │ Plan Agent  │
└──────────────┘              │  (MCP Server +   │              │ Test Agent  │
                              │   A2A Client)    │              └─────────────┘
                              └──────────────────┘
```

**The Team Orchestrator** is exposed as an MCP server with tools like:

- `delegate_task(description, constraints)`— send work to the team -`check_task_status(task_id)`— poll progress -`get_artifacts(task_id)`— retrieve completed work -`cancel_task(task_id)` — abort

Internally, the orchestrator is an A2A client that routes to specialized agents.

### 4.2 Alternative: ACP Agent

If the CLI supports ACP (like Toad), the orchestrator could be an ACP agent
instead of an MCP server. This gives richer streaming and permission flows but
limits compatibility to ACP-aware hosts.

**Verdict**: MCP is the safer bet for broad CLI compatibility today. ACP can
be layered on later for enhanced UX.

### 4.3 Alternative: Direct A2A from CLI

If the CLI itself becomes an A2A client, it can talk to the team directly. This
is the cleanest architecture but requires CLI-side changes (unlikely for
third-party CLIs).

**Verdict**: Only viable for our own tooling. Not a general solution.

---

## 5. Team Composition Patterns

### 5.1 Flat Team (Supervisor Pattern)

```text
Orchestrator (Supervisor)
├── Coder Agent A (specialist: backend)
├── Coder Agent B (specialist: frontend)
├── Reviewer Agent
└── Test Agent
```

The supervisor LLM decides which agent(s) to invoke for each sub-task. Simple,
proven (a2a-samples multiagent host uses this).

**Pros**: Simple routing, easy to reason about.
**Cons**: Bottleneck at supervisor, limited parallelism.

### 5.2 Hierarchical Team

```text
Orchestrator
├── Planning Agent
│   └── (produces task breakdown)
├── Implementation Lead
│   ├── Coder Agent A
│   ├── Coder Agent B
│   └── Coder Agent C
└── Quality Lead
    ├── Reviewer Agent
    └── Test Agent
```

Two levels of delegation. The orchestrator handles high-level coordination;
leads handle their domain.

**Pros**: Better parallelism, domain separation.
**Cons**: More complex, more A2A roundtrips, harder to debug.

### 5.3 Pipeline Team

```text
Planner → Coder → Reviewer → Tester → (loop or complete)
```

Sequential pipeline with feedback loops. Each stage is an A2A agent.

**Pros**: Clear quality gates, natural code review flow.
**Cons**: Slow for simple tasks, rigid.

### 5.4 Recommended Starting Point: Flat + Pipeline Hybrid

```text
Orchestrator (Supervisor)
├── Planner Agent     → produces implementation plan
├── Coder Agent(s)    → implements according to plan
├── Reviewer Agent    → reviews implementation
└── (loop: Coder fixes → Reviewer re-reviews → done)
```

The supervisor drives the overall flow but the coder→reviewer loop runs as a
sub-pipeline. This balances simplicity with quality.

---

## 6. Key Technical Decisions to Investigate

### 6.1 Agent Runtime

| Option           | Pros                                           | Cons                     |
| ---------------- | ---------------------------------------------- | ------------------------ |
| Vanilla A2A SDK  | Full control, minimal deps                     | More boilerplate         |
| LangGraph + A2A  | Checkpointing, state mgmt, conditional routing | Heavier, Google-adjacent |
| Claude Agent SDK | Native Claude integration, hooks, permissions  | Claude-only agents       |
| CrewAI + A2A     | Team-oriented abstractions                     | Less control             |

**Leaning toward**: Vanilla A2A SDK for the orchestrator + agent shells,
LangGraph internally for agents that need stateful reasoning loops.

### 6.2 Tool Exposure Strategy

Coding agents need workspace tools. Two approaches:

**A) Shared MCP server**: One MCP server exposes file/git/build tools. All
agents connect to it. Simple but creates contention.

**B) Per-agent MCP instances**: Each agent gets its own MCP server instance
with scoped access (e.g., coder gets write access, reviewer gets read-only).
Better isolation but more infrastructure.

**Leaning toward**: Per-agent scoped MCP instances for safety. The orchestrator
provisions them.

### 6.3 State and Persistence

- A2A `contextId`for session continuity across tasks
- A2A`TaskStore`for task state (in-memory for dev, SQL for prod)
- LangGraph checkpointers for agent-internal state
- Git worktrees for workspace isolation per coding task

### 6.4 CLI Integration Method

| CLI             | Integration Path                            | Notes                           |
| --------------- | ------------------------------------------- | ------------------------------- |
| Claude CLI      | MCP server config in`.claude/settings.json` | Native support, well-documented |
| Gemini CLI      | MCP server config                           | Supports MCP tools              |
| Cursor/Windsurf | MCP server                                  | IDE agents support MCP          |
| Custom CLI      | A2A client directly                         | Full protocol access            |

### 6.5 Model Agnosticism

A2A agents are model-agnostic by design. Each agent can use whatever model
suits its task:

- Planner: Claude Opus / Gemini 2.5 Pro (deep reasoning)
- Coder: Claude Sonnet / GPT-4.1 (fast, capable coding)
- Reviewer: Claude Opus (thorough analysis)
- Tester: Lighter model (structured test generation)

---

## 7. Sources and References

### Protocol Specifications

- **A2A Protocol**:`knowledge/repositories/A2A/docs/`— Full protocol docs,
  tutorials, ADRs
- **A2A Python SDK**:`knowledge/repositories/a2a-python/`— SDK source with
  types, server, client, transports
- **ACP Python SDK**:`knowledge/repositories/acp-python-sdk/`— Client-agent
  protocol with streaming and permissions
- **MCP Python SDK**:`knowledge/repositories/mcp-python-sdk/`— Tool protocol
  with experimental async tasks

### Implementation Examples

- **a2a-samples multiagent
  host**:`knowledge/repositories/a2a-samples/samples/python/hosts/multiagent/`—
  Supervisor pattern
- **a2a-samples CLI
  host**:`knowledge/repositories/a2a-samples/samples/python/hosts/cli/`— Client
  reference
- **a2a-samples JS
  coder**:`knowledge/repositories/a2a-samples/samples/js/src/agents/coder/`—
  Coding agent with streaming artifacts
- **Airbnb routing
  agent**:`knowledge/repositories/a2a-samples/samples/python/agents/airbnb_planner_multiagent/`—
  Advanced routing

### Framework References

- **Claude Agent SDK**:`knowledge/repositories/claude-agent-sdk/`— Hooks,
  permissions, custom tools
- **LangGraph**:`knowledge/repositories/langgraph/`— State graphs,
  checkpointing
- **LangChain**:`knowledge/repositories/langchain/`— Model abstractions,
  tool interfaces

### Custom Analysis

- **A2A Walkthrough**:`knowledge/repositories/a2a-walkthrough.md`— Four
  framework integration patterns
- **Toad ACP Audit**:`knowledge/repositories/toad-acp-audit.md`— ACP host
  implementation details
- **A2A Samples Deep Dive**:`knowledge/repositories/a2a-samples-deep-dive.md`

---

## 8. Open Questions for Next Phase

1. **Workspace isolation**: Should each coding agent work in its own git
   worktree, or share a workspace with file-level locking?

1. **Artifact format**: Should code artifacts use A2A's native `FilePart` with
   inline content, or reference files on a shared filesystem?

1. **Review loop**: How many coder→reviewer iterations before escalating to the
   user? Fixed count or LLM-judged quality gate?

1. **Parallelism**: Can multiple coders work on different files simultaneously?
   How do we handle merge conflicts?

1. **Context window management**: How do we prevent coding agents from running
   out of context on large tasks? Summarization? Chunked delegation?

1. **Error recovery**: When an agent fails mid-task, does the orchestrator
   retry, reassign, or escalate?

1. **Observability**: How do we expose the team's internal deliberation to the
   user? Full trace? Summary? On-demand?

1. **Cost control**: How do we prevent runaway token usage in agent loops?
   Budget per task? Per session?

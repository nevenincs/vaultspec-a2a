---
tags:
- '#adr'
- '#orchestration-topology-pipeline'
date: 2026-02-26
related:
- '[[2026-03-31-docs-vault-migration-research]]'
---

# `orchestration-topology-pipeline` adr: `adr-008` | (**status:** `proposed`)

## Migration Note

This ADR was migrated from the legacy pre-pipeline documentation tree during the issue #19 cleanup so that the repository no longer depends on the removed `docs/` directory.

- Original ADR number: `ADR-008`
- Original title: `Orchestration Topology & Pipeline (LangGraph Core)`
- Legacy status at migration time: `Proposed`

## Original ADR

## ADR-008: Orchestration Topology & Pipeline (LangGraph Core)

**Date:** 2026-02-26  
**Status:** Proposed

## 1. Context & Problem Statement

The orchestrator must structure the execution pipeline of the multi-agent
team. Previously, the design assumed spawning _Ephemeral Agent Subprocesses_
running native provider CLIs (Claude/Gemini/Codex) communicating via the
generic A2A standard. However, the discovery of severe Windows 11 PTY
sub-process incompatibilities, coupled with the "ACP Richness Gap", rendered
orchestrating independent processes too brittle for v1.

## 2. The Decision

1. **Native LangGraph Execution Core:** We are abandoning the "ephemeral
   subprocess" topology for _orchestration logic_. The graph, state
   transitions, tool dispatch, and agent routing execute natively inside the
   main orchestrator process using **LangGraph** and **LangChain**. LLM
   generation for Claude and Gemini is handled by `AcpChatModel` — a
   `BaseChatModel` wrapper that manages CLI subprocesses internally as
   private stdio pipes. These are not orchestration-level actors; they are
   an implementation detail of the provider layer.
2. **State Machine over Independent Processes:** The "Team" is no longer a
   collection of independently-spawned binaries managing their own
   lifecycles. It is a compiled LangGraph `StateGraph` where each node
   represents an agent role (e.g., Planner, Coder, Reviewer). CLI processes
   live and die inside `AcpChatModel`, invisible to the graph topology.
3. **SQLite Checkpointing:** Process isolation is replaced by absolute State
   Isolation via LangGraph's native `checkpoint-sqlite` engine, guaranteeing
   durability across orchestrator restarts.
4. **Two-Interface Design Maintained:** The orchestrator will still expose
   two simultaneous interfaces:
   - **Interface 1 (CLI Bridge):** An MCP server providing stable tools for
     upstream CLIs.
   - **Interface 2 (Gateway):** A WebSocket server providing
     real-time UI updates to the React dashboard.

## 3. Rationale

- **Resolving the Windows CLI Crisis:** The Windows PTY/pipe problem is
  solved by `AcpChatModel`'s zero-PTY, zero-batch subprocess strategy: Claude
  is invoked as `node.exe <dist/index.js>` (bypassing the `.CMD` shim), and
  Gemini as `gemini.exe` (a native binary). Neither ever passes through
  `cmd.exe`. The graph itself never touches subprocesses directly.
- **Solving the ACP Richness Gap:** LangGraph provides structured,
  programmatic callbacks (`on_tool_start`, `on_chat_model_end`). We no
  longer have to parse opaque text streams over A2A; we have exact typed
  data for the React dashboard.
- **Built-in H-I-T-L:** LangGraph's `interrupt_before` natively replaces the
  complex blocking permission queue we were attempting to build manually.
- **Eliminates Cold Start Latency:** Removing the need to boot Python
  virtual environments for every sub-agent saves 1-3 seconds of latency per
  delegation.

## 4. Rejected Alternatives

- **Ephemeral Orchestration Subprocesses (Original Design):** Rejected.
  Independent agent processes with their own port-juggling,
  `CTRL_BREAK_EVENT` lifecycle management, and unstructured stdout parsing
  across 3 different CLIs was a Tier-3 catastrophic implementation risk.
  `AcpChatModel` retains CLI invocation but confines it to a scoped,
  supervised subprocess with structured JSON-RPC framing — entirely different
  from the original unbounded process model.
- **CrewAI / Alternate Frameworks:** Rejected in favor of LangGraph.
  LangGraph's explicit graph-based state machine provides necessary
  fine-grained control and checkpointer serialization capabilities over the
  "black box" of other agentic frameworks.
- **LiteLLM:** Rejected. While LiteLLM was considered as a general LLM API
  abstraction, migrating to LangGraph inherently coupled the stack to
  LangChain's `BaseChatModel` ecosystem (`ChatAnthropic`,
  `ChatGoogleGenerativeAI`), which provides much tighter integration for
  tool-calling within the graph nodes.

## 5. Implementation Constraints & Pitfalls

- **Thread Blocking:** Because LangGraph executes natively in the FastAPI
  process, all tools and LLM chains _must_ be invoked using LangChain's
  `ainvoke` (async) methods. A synchronous tool call will block the entire
  Uvicorn ASGI event loop and freeze the WebSocket dashboard.
- **State Immutability:** The LangGraph `State` TypedDict must be strictly
  JSON-serializable so the SQLite checkpointer does not throw pickle
  errors.

## 6. Negative Consequences

- **Shared Memory Risk:** If a Python tool executed by LangGraph leaks memory
  or encounters a segfault via a C-extension, it will crash the entire
  Orchestrator (a risk previously mitigated by subprocess isolation).

## 7. References

- LangGraph Gap Audit Research
- **LangGraph:** `knowledge/repositories/langgraph/`

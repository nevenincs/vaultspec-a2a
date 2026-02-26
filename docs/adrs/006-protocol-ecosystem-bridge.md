---
adr_id: 006
title: Protocol Ecosystem & Bridge Strategy (LangGraph vs MCP)
date: 2026-02-26
status: Proposed
related:
  - docs/distilled/2026-25-02-protocols-distilled.md
  - docs/research/2026-26-02-langgraph-gap-audit-research.md
---

# ADR-006: Protocol Ecosystem & Bridge Strategy (LangGraph vs MCP)

**Date:** 2026-02-26  
**Status:** Proposed

## 1. Context & Problem Statement

The ecosystem presents several competing protocols for agent workflows: A2A (Agent-to-Agent), ACP (Agent Client Protocol), and MCP (Model Context Protocol). Previously, we attempted to bridge all three by using A2A for inter-agent routing, ACP for UI state extraction via wrapper processes, and MCP for tool execution. This proven to be architecturally fragile, particularly on Windows, due to process management and opaque CLI outputs.

We must decide on a simplified, robust protocol architecture that provides stateful multi-agent orchestration while remaining compatible with standard tooling ecosystems.

## 2. The Decision

We completely abandon the A2A and ACP protocol integrations in favor of a native LangGraph architecture, with MCP serving strictly as the boundary protocol:

1. **Core Internal Engine:** **LangGraph** replaces A2A as the authoritative mechanism for how agents discover, interact, and delegate tasks to one another. The overarching orchestration, state machine logic, and message routing occur entirely via native Python graph edges and `Command(goto="node")` returns, totally bypassing network-level SSE protocol translations for internal routing.
2. **Tool Execution Boundary:** **MCP** (Model Context Protocol) is retained exclusively for standardized tool execution at the system boundaries.
    * **Consuming Tools:** Individual LangGraph nodes (Agents) can consume tools exposed by remote or local MCP Servers.
    * **Exposing the Orchestrator:** The Orchestrator itself runs an MCP Server to allow external IDEs (Cursor, Windsurf) to trigger specific LangGraph workflows as if they were simple tools.
3. **Abandoning CLI Wrappers:** We no longer wrap the Claude Code CLI or use the `claude-code-acp` adapter. Anthropic/Gemini agents are implemented natively using LangChain's `ChatAnthropic` and `ChatGoogleGenerativeAI`, allowing us to capture intermediate state (thoughts, tool calls) directly via LangChain callbacks rather than parsing JSON-RPC over `stdio`.
4. **Native Human-in-the-Loop:** Instead of relying on ACP's Permission Broker to halt processes for user input, we rely on LangGraph's native `interrupt` exceptions. When a tool requires approval, the node raises an `interrupt`, the graph suspends safely to SQLite, and resumes only when the frontend submits the approval via the REST API.

## 3. Rationale

* **Architectural Simplicity:** Eliminating A2A and ACP removes thousands of lines of fragile translation code. LangGraph natively solves the state management and multi-agent routing problems that A2A and ACP attempted to address at the networking layer.
* **Visibility and Telemetry:** Using native LangChain LLM wrappers directly in the unified Uvicorn process allows the Event Aggregator to stream high-fidelity `astream_events` (tool starts, token generation) to the UI without the opacity of a third-party CLI wrapper.
* **Native Interrupt Security:** Suspending a LangGraph state machine to disk via `interrupt` is infinitely more robust than leaving an OS subprocess blocked on an open `stdin` pipe waiting for user approval (which often caused timeouts).

## 4. Rejected Alternatives

* **A2A (Agent-to-Agent Protocol):** Rejected. While Google's A2A SDK is powerful, bringing it alongside LangGraph is highly redundant. LangGraph's multi-agent supervisor/worker patterns handle delegation more natively within the Python ecosystem.
* **ACP (Agent Client Protocol):** Rejected. ACP was necessary to extract structured UI updates from the Claude Code CLI. Since we no longer execute the CLI as a subprocess, the need for ACP JSON-RPC translation is eliminated entirely.

## 5. Implementation Constraints & Pitfalls

* **MCP Tool Mapping:** Exposing a complex LangGraph workflow (which might take 10 minutes and human interaction) as a synchronous MCP tool to a client like Cursor requires careful timeout management. The MCP server must immediately return a "Task Started, track progress at [URL]" response rather than holding the MCP connection open indefinitely.
* **Callback Flood:** Directly capturing LangChain events can flood the frontend. We must strictly filter `astream_events` to only broadcast relevant updates (e.g., `on_chat_model_stream`, `on_tool_start`) and drop internal graph routing noise.

## 6. Negative Consequences

* **Vendor Lock-in (LangChain):** By deeply integrating LangGraph and LangChain models, we are heavily coupled to their ecosystem. If we wish to support a novel LLM or workflow pattern not supported by LangChain, we must write custom wrappers rather than just spawning a new binary.
* **Loss of CLI Prowess:** We lose the highly optimized, out-of-the-box performance and caching of the official Claude Code CLI by reverting to the baseline REST APIs via LangChain.

## 7. References

* [LangGraph Gap Audit Research](../research/2026-26-02-langgraph-gap-audit-research.md)
* [Protocols Domain - Distilled](../distilled/2026-25-02-protocols-distilled.md)

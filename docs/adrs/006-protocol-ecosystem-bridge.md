---
adr_id: 006
title: Protocol Ecosystem & Bridge Strategy (ACP vs A2A vs MCP)
date: 2026-02-25
status: Proposed
related:
  - docs/distilled/2026-25-02-protocols-distilled.md
  - docs/distilled/2026-25-02-protocols-gaps-research.md
  - docs/distilled/2026-25-02-agents-distilled.md
  - docs/distilled/2026-25-02-agents-gaps-research.md
  - docs/protocols/2026-25-02-mcp-tasks-a2a-compliance-research.md
  - knowledge/repositories/acp-python-sdk.md
  - knowledge/repositories/claude-agent-sdk.md
  - knowledge/repositories/mcp-python-sdk.md
---

# ADR-006: Protocol Ecosystem & Bridge Strategy (ACP vs A2A vs MCP)

**Date:** 2026-02-25  
**Status:** Proposed

## 1. Context & Problem Statement

The ecosystem presents three overlapping protocols: A2A (Agent-to-Agent), ACP (Agent Client Protocol), and MCP (Model Context Protocol).

* **A2A** excels at stateful agent collaboration and task delegation but its SSE streaming is rudimentary (collapsing all updates into generic `Message.parts[]`).
* **ACP** (used by Zed/Toad) excels at UI integration, offering 11 discriminated streaming updates (e.g., `agent_thought_chunk`, `tool_call_update`) and a robust blocking `request_permission` flow, but is strictly designed for IDE-to-Agent stdio communication.
* **MCP** is the standard for tool execution but lacks native multi-agent task orchestration logic.
* **Claude Code Contention:** The Claude Code CLI natively supports MCP but does *not* expose an ACP or A2A server out of the box. Integrating it requires choosing the correct wrapping strategy.

We must decide how to structure the protocol bridge so the orchestrator can manage agents via A2A, expose tools via MCP, and render a rich UI using ACP-like concepts.

## 2. The Decision

We will implement a **Hybrid Protocol Architecture**:

1. **Core Inter-Agent Communication:** **A2A** is the authoritative protocol for how agents discover, message, and delegate sub-tasks to one another. The orchestrator acts as the primary A2A Client.
2. **Tool & CLI Interface:** **MCP** is used strictly for two purposes:
    * Exposing the orchestrator's capabilities to external CLIs (via stable MCP tools, not experimental tasks).
    * Providing scoped filesystem/git access to individual agent subprocesses via a local MCP server.
3. **Porting ACP Patterns (Without the Transport):** We will **not** adopt the ACP protocol over stdio for internal orchestrator communication. Instead, we will extract and port ACP's highest-value structural patterns—specifically the `SessionAccumulator` for state management and the `request_permission` blocking pattern—and reimplement them within our A2A/WebSocket event aggregator.
4. **Claude Code Integration:** We will explicitly wrap Claude Code using the community/official **`claude-code-acp` adapter** (or equivalent python wrapper). The orchestrator will spawn this wrapper as a subprocess, capture its rich ACP JSON-RPC output over stdio, and translate those 11 discriminated update types into our internal A2A-compatible event stream for the UI.

## 3. Rationale

* **Best of Both Worlds:** A2A provides the necessary primitives for task lifecycle and delegation, while ACP's `SessionAccumulator` logic is the only proven way to cleanly manage UI state for high-frequency streaming LLM outputs.
* **Claude Wrapper Necessity:** Running the raw `claude` binary provides opaque, hard-to-parse terminal output. Using the `claude-code-acp` wrapper forces Claude to emit structured JSON-RPC, exposing its internal thoughts, tool calls, and permission requests, which are vital for the Control Surface UI.
* **Blocking Permissions:** ACP's approach of halting the agent process entirely while `await`ing a JSON-RPC permission response is the cleanest, safest human-in-the-loop pattern, vastly superior to asynchronous polling.

## 4. Rejected Alternatives

* **Pure A2A (Rejecting ACP entirely):** Rejected. A2A's event stream collapses thoughts, tool calls, and text into generic parts, making it impossible to build the rich, segmented UI (like AutoGen Studio) required by the control surface.
* **Pure ACP (Rejecting A2A entirely):** Rejected. ACP is designed for a 1:1 IDE-to-Agent relationship. It lacks the primitives for multi-agent delegation, Agent Cards, and task lifecycles.
* **MCP Async Tasks for CLI:** Rejected for v1 (as per ADR-003). While promising, they are too experimental to serve as the foundational bridge.

<h2>5. Implementation Constraints & Pitfalls</h2>
*   **Protocol Translation Overhead:** The orchestrator must act as a real-time translation layer. It must take the ACP stdio output from the `claude-code-acp` subprocess, parse the JSON-RPC, and map it cleanly into the unified Event Aggregator pipeline.
*   **Adapter Maintenance:** Relying on the `claude-code-acp` wrapper means we are dependent on an ecosystem adapter. Changes to Anthropic's internal CLI could break the adapter, requiring swift patches to our orchestrator's parsing logic.

<h2>6. Negative Consequences</h2>
*   **Architectural Complexity:** Mixing A2A paradigms with ACP state management patterns creates a steep learning curve for developers entering the codebase, as they must understand the nuances of both protocols.
*   **Process Overhead:** Wrapping Claude Code in an additional node/python ACP adapter process adds slight memory and startup latency overhead compared to executing a raw binary.

## 7. References

### 7.1 Local Research & Distilled Docs
* [Protocols Domain - Distilled](../distilled/2026-25-02-protocols-distilled.md)
* [Protocols Gaps Research](../distilled/2026-25-02-protocols-gaps-research.md)
* [Agents Domain - Distilled](../distilled/2026-25-02-agents-distilled.md)
* [Agents Gaps Research](../distilled/2026-25-02-agents-gaps-research.md)
* [MCP Tasks A2A Compliance Research](../protocols/2026-25-02-mcp-tasks-a2a-compliance-research.md)

### 7.2 Codebase Modules & Patterns
* **ACP Session Accumulator:** `acp.contrib.session_state.SessionAccumulator` (referenced in `knowledge/repositories/acp-python-sdk/src/acp/contrib/session_state.py`) for managing rich UI state.
* **ACP Permission Broker:** `acp.contrib.permissions.PermissionBroker` (referenced in `knowledge/repositories/acp-python-sdk/src/acp/contrib/permissions.py`) for handling interactive, blocking permission requests.
* **A2A Event Structures:** `a2a.types.Message`, `a2a.types.Task`, `a2a.types.TaskStatusUpdateEvent` (referenced in `knowledge/repositories/a2a-python/src/a2a/types.py`) for core A2A event definitions.
* **MCP Server Stdio:** `mcp.server.stdio` (referenced in `knowledge/repositories/mcp-python-sdk/src/mcp/server/stdio.py`) for stdio-based MCP communication.
* **Claude Code ACP Adapter:** External Python/Node.js wrapper (e.g., `claude-code-acp`) used to translate Claude Code's native output into structured ACP JSON-RPC.

### 7.3 Online Reference Implementation
* **ACP Specification:** [Agent Client Protocol Specification](https://agentclientprotocol.com) (referenced for rich UI update types like `agent_thought_chunk`).
* **MCP Specification:** [Model Context Protocol Specification](https://modelcontextprotocol.io/specification) (referenced for standard tool execution and CLI interface).
* **A2A Specification:** Located in `knowledge/repositories/A2A/specification/a2a.proto` (defines inter-agent communication and task delegation).
* **Claude Code CLI:** [Claude Code CLI Documentation](https://code.claude.com/docs/) (referenced for native MCP support).

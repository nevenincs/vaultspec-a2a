---
adr_id: 003
title: Protocol Bridging & Translation (A2A ↔ MCP)
date: 2026-02-25
status: Proposed
related:
  - docs/distilled/2026-25-02-protocols-distilled.md
  - docs/distilled/2026-25-02-protocols-gaps-research.md
  - docs/protocols/2026-25-02-mcp-tasks-a2a-compliance-research.md
  - docs/protocols/2026-25-02-phase1-protocol-foundations.md
---

# ADR-003: Protocol Bridging & Translation (A2A ↔ MCP)

**Date:** 2026-02-25  
**Status:** Proposed

## 1. Context & Problem Statement

The orchestrator must act as a universal translator between the multi-agent team (speaking A2A) and the user's CLI (expecting MCP). This involves mapping states, handling concurrent user inputs, and ensuring protocol compliance across distinct communication models.

## 2. The Decision

1. **Aggregator State Machine:** Implement a strict state reduction function that maps the 8 granular A2A states (`SUBMITTED`, `WORKING`, `INPUT_REQUIRED`, `AUTH_REQUIRED`, `COMPLETED`, `FAILED`, `CANCELED`, `REJECTED`) into the 5 MCP states (`working`, `input_required`, `completed`, `failed`, `cancelled`).
   * Terminal A2A states (`COMPLETED`, `FAILED`, `CANCELED`, `REJECTED`) will map directly to their MCP equivalents.
   * `SUBMITTED` will map to `working` with a status message indicating submission.
   * `AUTH_REQUIRED` will map to `input_required`.
2. **Elicitation Serializer:** Utilize an `asyncio.Queue` to serialize concurrent `INPUT_REQUIRED` or `AUTH_REQUIRED` requests originating from multiple agents. This ensures prompts are presented sequentially to the user via the MCP host.
3. **MCP Protocol Compliance & Auth Handling:** Rely exclusively on stable MCP tools for CLI interaction. Experimental MCP tasks are deferred. A2A's discrete `AUTH_REQUIRED` state will **NOT** be collapsed into a `stdin` prompt, as the decoupled subprocess execution model makes routing `stdin` back to the initiating CLI tool (e.g., Claude) architecturally fragile.
   * Instead, when `AUTH_REQUIRED` is encountered, the MCP server will **suspend the task** and return a structured message instructing the user to authenticate via the Control Surface web dashboard or by setting environment variables *prior* to resuming.

## 3. Rationale

* **CLI Consistency:** Providing a unified, simpler MCP state model to the CLI is crucial for usability. Exposing the full 8 A2A states would complicate CLI interactions unnecessarily.
* **Concurrency Management:** An `asyncio.Queue` prevents race conditions and simplifies UI logic by serializing interactive prompts from multiple agents, ensuring a predictable user experience.
* **Stability & Decoupled Execution:** Relying on stable MCP tools minimizes risk. Crucially, attempting to pipe `stdin` through an MCP tool call to satisfy a decoupled subprocess's authentication request is unworkable in most IDEs and CLI hosts. Suspending the task and routing authentication through the web Control Surface ensures a secure, human-in-the-loop flow without breaking the MCP host's execution model.

## 4. Rejected Alternatives

* **Direct A2A Exposition to CLI:** Rejected because CLIs (like Claude, Gemini) are not built for the complexity of A2A's 8 granular states and streaming SSE, leading to poor user experience and implementation complexity.
* **Merging Concurrent Elicitations:** Rejected. This would break trace integrity, as responses would need to be correlated to specific agents and tasks. It also requires complex client-side logic to disentangle merged responses.

## 5. Implementation Constraints & Pitfalls

* **Exhaustive State Mapping:** The state reduction function must be exhaustive to cover all A2A states and map them correctly to MCP states, preventing unexpected or unhandled states in the CLI.
* **Queue Management:** The `asyncio.Queue` must be properly bounded and managed to prevent memory leaks or deadlocks if the client stalls or fails to respond.
* **Prompt Clarity:** Collapsing `AUTH_REQUIRED` into `input_required` means the prompt text must clearly indicate the *type* of input needed (e.g., "Provide API Key for tool X" vs. "Enter value for Y").

## 6. Negative Consequences

* **Loss of A2A Granularity:** The CLI view will abstract away A2A-specific states like `SUBMITTED`, `REJECTED`, and `AUTH_REQUIRED`. This detail will only be available in richer UIs or logs, requiring the orchestrator's prompt text to bridge this information gap.
* **Sequential Prompting Latency:** If multiple agents require input concurrently, users will experience sequential prompting, potentially introducing minor delays in the overall task completion time.

## 7. References

### 7.1 Local Research & Distilled Docs
* [Protocols Domain - Distilled](../distilled/2026-25-02-protocols-distilled.md)
* [Protocols Gaps Research](../distilled/2026-25-02-protocols-gaps-research.md)
* [MCP Tasks A2A Compliance](../protocols/2026-25-02-mcp-tasks-a2a-compliance-research.md)
* [Protocol Foundations](../protocols/2026-25-02-phase1-protocol-foundations.md)

### 7.2 Codebase Modules & Patterns
* **A2A Task States:** `a2a.server.models.TaskState` (referenced in `knowledge/repositories/a2a-python/src/a2a/server/models.py`).
* **A2A Result Aggregation:** `a2a.server.tasks.result_aggregator.ResultAggregator` (observed pattern in `knowledge/repositories/a2a-python/src/a2a/server/tasks/result_aggregator.py`).
* **MCP Tool Definitions:** `mcp.types` (`knowledge/repositories/mcp-python-sdk/src/mcp/types/__init__.py`) for standardizing tool interaction payloads.
* **MCP Elicitation Flow:** `mcp.server.elicitation` (`knowledge/repositories/mcp-python-sdk/src/mcp/server/elicitation.py`) for handling mid-task user requests.
* **Concurrency Control:** `asyncio.Queue` (Python standard library) for serializing elicitation requests.
* **MCP Tool Handling:** `mcp.server.mcpserver.tools.tool_manager.ToolManager` for managing and dispatching tool calls from the CLI.

### 7.3 Online Reference Implementation
* **MCP Specification:** [Model Context Protocol Specification](https://modelcontextprotocol.io/specification) (referenced for state model and tool calling lifecycle).
* **A2A SDK Documentation:** [A2A Python SDK Guide](https://github.com/google/a2a-python) (referenced for task state transitions and SSE event mapping).

---
adr_id: 008
title: Orchestration Topology & Pipeline
date: 2026-02-25
status: Proposed
related:
  - docs/distilled/2026-25-02-architecture-distilled.md
  - docs/distilled/2026-25-02-process-distilled.md
  - docs/distilled/2026-25-02-protocols-distilled.md
  - docs/distilled/2026-25-02-control-surface-distilled.md
  - docs/distilled/2026-25-02-process-gaps-research.md
  - docs/distilled/2026-25-02-protocols-gaps-research.md
---

# ADR-008: Orchestration Topology & Pipeline

**Date:** 2026-02-25  
**Status:** Proposed

## 1. Context & Problem Statement

The orchestrator must structure the execution pipeline of the multi-agent team. Should agents run within a single shared memory space, as long-lived independent microservices, or as ephemeral subprocesses? Additionally, we must define the core control flow mechanisms—specifically, how state is aggregated and permissions are routed between the user (via CLI or UI) and the agents.

## 2. The Decision

1. **Hybrid Process Topology:** The system will use a Single Orchestrator Process (the FastAPI/Uvicorn server) that spawns **Ephemeral Agent Subprocesses** on-demand. The orchestrator is the only long-lived service.
2. **Ephemeral Agents:** Agents are spun up for a specific task and aggressively terminated when the task completes or fails. They do not persist across multiple tasks to avoid state contamination and memory leaks.
3. **Two-Interface Design:** The orchestrator will expose two simultaneous interfaces:
    * **Interface 1 (CLI Bridge):** An MCP server providing stable tools for delegation and polling (e.g., `team/create`, `team/status`) intended for upstream agents like Claude CLI.
    * **Interface 2 (Control Surface):** A WebSocket server providing real-time events, terminal streaming, and a permission queue for the SvelteKit dashboard.
4. **Reusable Toad Patterns:** We will port the **`SessionAccumulator`** and **`PermissionBroker`** classes from the `acp-python-sdk` (Toad implementation) directly into our A2A Event Aggregator pipeline.

## 3. Rationale

* **Isolation vs. Complexity:** A single-process design (agents as coroutines) risks crashing the entire orchestrator if one agent faults or leaks memory. A fully distributed design (agents as independent microservices) requires complex service discovery (Consul/etcd) and network auth. The hybrid model (subprocess per agent) offers the perfect balance: crash isolation without the overhead of microservices.
* **Clean State:** Ephemeral agents eliminate the insidious bugs caused by stale context, unclosed file handles, or lingering LLM memory from previous tasks.
* **Toad Component Provenance:** Toad's `SessionAccumulator` is already designed to immutably merge streaming notifications into a canonical `SessionSnapshot`. Porting it saves massive development time. Its `PermissionBroker` provides the exact "pause agent, request user input, resume" `asyncio` blocking logic we require for human-in-the-loop safety.

## 4. Rejected Alternatives

* **Single-Process (All-in-Memory):** Rejected. If a Python A2A agent executor causes a segmentation fault (e.g., via a bad native library call), it will take down the central orchestrator and all other agents.
* **Long-Lived Agent Daemons:** Rejected for v1. While it avoids cold-start latency, managing long-lived daemons introduces "zombie" state bugs and requires a much more complex Process Manager to handle graceful reloading between tasks.
* **Building Custom State Aggregators:** Rejected. Re-implementing the complex logic of merging sequential stream chunks into a coherent UI state is unnecessary when Toad's `SessionAccumulator` pattern is readily available and audited.

## 5. Implementation Constraints & Pitfalls

* **Dynamic Port Allocation:** Spawning ephemeral agent subprocesses requires the orchestrator to dynamically allocate free network ports for the A2A servers to bind to. This logic must be race-condition-proof to ensure two agents are not assigned the same port simultaneously.
* **ACP to A2A Structural Impedance:** Toad's `SessionAccumulator` was built for the 11 specific ACP update types (e.g., `agent_thought_chunk`). Developers must meticulously refactor its ingest logic to accept and correctly map A2A's generic `Message.parts[]` payload instead.
* **Subprocess Startup Latency:** Ephemeral agents incur a cold-start penalty (spawning a Python interpreter and Uvicorn server). This latency must be monitored; if it exceeds acceptable UX thresholds, the decision to use ephemeral agents may need to be revisited in v2.

## 6. Negative Consequences

* **Cold-Start Overhead:** Users will experience a slight delay (typically 1-3 seconds) when a task is delegated while the ephemeral subprocess boots up and establishes its A2A network bindings.
* **Resource Spikes:** Spawning multiple Python subprocesses concurrently can cause brief CPU and memory spikes on the host machine compared to running everything in a single process thread pool.

## 7. References

### 7.1 Local Research & Distilled Docs
* [Architecture Domain - Distilled](../distilled/2026-25-02-architecture-distilled.md)
* [Process Domain - Distilled](../distilled/2026-25-02-process-distilled.md)
* [Protocols Domain - Distilled](../distilled/2026-25-02-protocols-distilled.md)
* [Control Surface Domain - Distilled](../distilled/2026-25-02-control-surface-distilled.md)
* [Process Gaps Research](../distilled/2026-25-02-process-gaps-research.md)
* [Protocols Gaps Research](../distilled/2026-25-02-protocols-gaps-research.md)

### 7.2 Codebase Modules & Patterns
* **Process Spawning:** `subprocess.Popen` (Python standard library) for managing ephemeral agent subprocesses.
* **MCP Server Implementation:** `mcp.server.mcpserver.server.MCPServer` (from `mcp-python-sdk`) for exposing CLI bridge.
* **WebSocket Server Implementation:** `fastapi.websockets.WebSocket` and `fastapi.routing.APIRoute` for Control Surface.
* **ACP Session State Aggregation:** `acp.contrib.session_state.SessionAccumulator` (from `acp-python-sdk`) for merging streaming notifications.
* **ACP Permission Handling:** `acp.contrib.permissions.PermissionBroker` (from `acp-python-sdk`) for human-in-the-loop requests.
* **A2A Agent Communication:** `a2a.types.Message`, `a2a.types.Task`, `a2a.server.events.event_queue.EventQueue` (from `a2a-python`) for internal inter-agent communication.
* **Dynamic Port Allocation:** Python `socket` module (`socket.socket(socket.AF_INET, socket.SOCK_STREAM)`) for finding free ports.

### 7.3 Online Reference Implementation
* **FastAPI Process Management:** [FastAPI Background Tasks](https://fastapi.tiangolo.com/tutorial/background-tasks/) (referenced for managing subprocesses within FastAPI).
* **ACP Specification:** Located in `knowledge/repositories/acp-python-sdk/schema/schema.json` (referenced for `SessionAccumulator` and `PermissionBroker` patterns).
* **A2A Specification:** Located in `knowledge/repositories/A2A/specification/a2a.proto` (referenced for core agent communication).
* **MCP Specification:** [Model Context Protocol Specification](https://modelcontextprotocol.io/specification) (referenced for CLI bridge patterns).

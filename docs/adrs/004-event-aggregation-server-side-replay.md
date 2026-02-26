---
adr_id: 004
title: Event Aggregation & Server-Side Replay
date: 2026-02-25
status: Proposed
related:
  - docs/distilled/2026-25-02-control-surface-distilled.md
  - docs/distilled/2026-25-02-control-surface-gaps-research.md
  - docs/process/2026-25-02-agent-process-lifecycle-research.md
---

# ADR-004: Event Aggregation & Server-Side Replay

**Date:** 2026-02-25  
**Status:** Proposed

## 1. Context & Problem Statement

The orchestrator must handle a high volume of diverse event streams from multiple concurrent agent subprocesses (A2A SSE, raw `stdout`/`stderr`). The frontend Control Surface requires a single, multiplexed WebSocket to display these events in real-time. Crucially, the frontend also needs to reliably reconstruct an agent's terminal history upon browser reconnects or refreshes, and client-side terminal state serialization is brittle and experimental.

## 2. The Decision

1. **Unified Event Aggregator:** A central Python component within the orchestrator will serve as the Event Aggregator. Its responsibilities include:
    * Ingesting all A2A SSE streams originating from agent subprocesses.
    * Capturing and parsing raw `stdout`/`stderr` from all agent subprocesses.
    * Performing necessary transformations (e.g., adding timestamps, `agent_id`).
    * Broadcasting these unified events over a single, multiplexed WebSocket connection to the Control Surface frontend.
2. **SQLite Event Sourcing:** All incoming A2A events (e.g., `TaskStatusUpdateEvent`, `TaskArtifactUpdateEvent`, `Message`) will be event-sourced. They will be stored in an immutable, ordered log within the SQLite database.
3. **Server-Side Terminal Replay (ANSI Ring Buffer):** For each agent's terminal output, the orchestrator will maintain a rolling, in-memory **2000-line ring buffer** of raw ANSI-encoded `stdout`/`stderr` data.
4. **Robust Frontend Reconnection:** Upon a frontend reconnect or refresh, the Control Surface will first request the last 2000 lines of terminal history for each active agent via a dedicated REST endpoint. This historical buffer will be piped into a fresh `xterm.js` instance, followed immediately by live WebSocket updates for ongoing events.

## 3. Rationale

* **Unified Stream:** A centralized Event Aggregator simplifies event processing and fan-out logic, eliminating the need for complex client-side event merging and ensuring a single source of truth for all agent activity.
* **Reliable History & Auditability:** Event sourcing to SQLite provides a durable, auditable record of all agent actions, enabling future features like full session replay (v2) and forensic analysis.
* **Robust Terminal Reconstruction:** Server-Side Replay, using the ANSI ring buffer, guarantees 100% accurate terminal history reconstruction. This approach avoids the brittleness and experimental nature of client-side terminal serialization addons (`@xterm/addon-serialize`), which often fail to reliably restore private modes, alternate screen buffers, and complex cursor states. The client (browser) remains largely stateless.

## 4. Rejected Alternatives

* **Client-Side Terminal Serialization:** Rejected. `xterm.js`'s `@xterm/addon-serialize` is explicitly marked as experimental and unreliable for complex terminal state restoration. Relying on it would introduce significant frontend fragility.
* **Replaying from Full SQLite History:** Rejected for immediate terminal reconstruction. Replaying an entire session's worth of raw `stdout`/`stderr` from SQLite could be very slow and inefficient for long-running tasks. The 2000-line ring buffer provides a fast, bounded history for immediate display, with full history accessible via a separate (v2) log viewer.
* **Per-Agent WebSockets:** Rejected. A single multiplexed WebSocket is more efficient for browser resources and simplifies connection management compared to maintaining multiple, independent WebSocket connections for each agent.

## 5. Implementation Constraints & Pitfalls

* **WebSocket Backpressure:** The Event Aggregator must implement robust backpressure mechanisms for the WebSocket connection. If the browser client is slow or disconnects, the aggregator must prevent its own outgoing buffer from growing indefinitely (e.g., by dropping old events or temporarily pausing processing).
* **Ring Buffer Memory Management:** The 2000-line ring buffer for ANSI output (per agent) must be implemented efficiently in Python to avoid excessive memory consumption within the orchestrator, especially when managing many concurrent agents.
* **Event Ordering:** Guaranteeing strict event ordering and accurate timestamping across heterogeneous sources (A2A SSE streams vs. raw `stdout`/`stderr`) can be challenging and requires careful synchronization within the Aggregator.

## 6. Negative Consequences

* **Limited Immediate History:** The 2000-line limit for terminal history means that very long scrollback will not be immediately available upon reconnect; users would need to rely on a separate log viewer or full session replay (deferred to v2) for older data.
* **Increased Orchestrator Memory:** Maintaining multiple in-memory ANSI ring buffers will increase the orchestrator's memory footprint compared to a purely stateless event forwarding mechanism. This is a deliberate trade-off for frontend robustness.

## 7. References

### 7.1 Local Research & Distilled Docs
* [Control Surface Domain - Distilled](../distilled/2026-25-02-control-surface-distilled.md)
* [Control Surface Gaps Research](../distilled/2026-25-02-control-surface-gaps-research.md)
* [Agent Process Lifecycle Research](../process/2026-25-02-agent-process-lifecycle-research.md)

### 7.2 Codebase Modules & Patterns
* **A2A Event Management:** `a2a.server.events.event_queue.EventQueue` and `a2a.server.events.event_consumer.EventConsumer` (knowledge/repositories/a2a-python/src/a2a/server/events/) for managing asynchronous A2A event flows.
* **Structured Concurrency:** `asyncio.TaskGroup` (Python standard library) for managing concurrent stdout/stderr reading tasks.
* **Circular Buffers:** `collections.deque(maxlen=2000)` (Python standard library) for implementing the in-memory ANSI ring buffer.
* **Event Persistence:** Pattern similar to `a2a.server.tasks.task_store.DatabaseTaskStore` (knowledge/repositories/a2a-python/src/a2a/server/tasks/database_task_store.py) for event sourcing to SQLite.
* **Multiplexed Transport:** Patterns observed in `mcp.server.sse` and `mcp.server.websocket` (knowledge/repositories/mcp-python-sdk/src/mcp/server/) for managing complex stream transports.

### 7.3 Online Reference Implementation
* **xterm.js State Recovery:** [xterm.js addon-serialize Documentation](https://www.npmjs.com/package/@xterm/addon-serialize) (referenced for experimental status and limitations).
* **Python collections.deque:** [Python collections.deque Documentation](https://docs.python.org/3/library/collections.html#collections.deque) (referenced for circular buffer implementation).
* **FastAPI WebSocket:** [FastAPI WebSocket Guide](https://fastapi.tiangolo.com/advanced/websockets/) (referenced for multiplexed connection management).

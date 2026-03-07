---
adr_id: 004
title: Event Aggregation & State Replay (LangGraph Core)
date: 2026-02-26
status: Proposed
related:
  - docs/distilled/2026-25-02-control-surface-distilled.md
  - docs/research/2026-26-02-langgraph-gap-audit-research.md
---

# ADR-004: Event Aggregation & State Replay (LangGraph Core)

**Date:** 2026-02-26  
**Status:** Proposed

## 1. Context & Problem Statement

The orchestrator must handle a high volume of diverse event streams
originating from multiple concurrent LangGraph agent executions. The
frontend Gateway requires a single, multiplexed WebSocket
connection to display these events in real-time. Crucially, because
LangGraph executions are highly stateful, the frontend needs to be able
to reliably reconstruct the current state of an agent (including its
memory, tool calls, and pending interrupts) upon browser reconnects or
refreshes.

## 2. The Decision

We will handle Event Aggregation and State Replay via the following
mechanisms:

- **Native LangGraph Stream Aggregator:** A central Python component
  within the orchestrator will serve as the Event Aggregator. Its
  responsibilities include:
  - Ingesting LangGraph's `astream` (node state updates) and
    `astream_events` (granular LangChain callback events like tokens
    streaming, tool starts, tool ends).
  - Performing necessary payload transformations (e.g., adding
    universally formatted timestamps, grouping `run_id`s, structuring
    message arrays).
  - Broadcasting these unified JSON events over a single, multiplexed
    WebSocket connection to the Gateway frontend.
- **SQLite Checkpoint Sourcing:** Rather than reinventing a custom
  event-sourcing database, all graph state transitions and checkpoints
  are inherently persisted by LangGraph's `checkpointer` (via
  `langgraph-checkpoint-sqlite`).
- **Server-Side State Replay:** Upon a frontend reconnect or refresh,
  the Gateway will request the latest persisted Graph State for
  a given `thread_id` via a dedicated REST endpoint.
  - The server will retrieve the state using `graph.get_state(config)`.
  - This state object (containing the entire message history and
    current node values) serves as the "source of truth", allowing the
    frontend to immediately render the full conversational history and
    UI components without needing to replay individual granular events,
    followed immediately by live WebSocket updates for ongoing
    operations.

## 3. Rationale

- **Unified Stream & Ecosystem Alignment:** Utilizing LangGraph's native
  `astream_events` provides a rich, deeply integrated stream of
  execution data (far superior to parsing raw stdout text). Aggregating
  this centrally simplifies client-side logic.
- **Checkpoint Reliability:** LangGraph's `checkpointer` is specifically
  designed for this exact use case—fault-tolerant state persistence.
  Leaning on it entirely removes the need for us to maintain separate,
  complex SQLite event-sourcing schemas for conversational history.
- **Robust Frontend Recovery:** Reconstructing UI from a final holistic
  State Object (rather than streaming thousands of historical delta
  events to the browser just to rebuild state on the client) is
  dramatically faster and far less prone to race conditions or sync
  errors during reconnects.

## 4. Rejected Alternatives

- **Raw Subprocess Stdout Ring Buffers (Original Design):** Rejected.
  Since we no longer run CLI binaries as subprocesses, there is no raw
  ANSI stdout/stderr to capture. Agents run natively as python
  functions.
- **Custom Event Logging Database:** Rejected. LangGraph's
  `checkpoint-sqlite` covers 95% of our event persistence needs
  natively. Building a parallel, custom event-sourcing database
  introduces unnecessary complexity and potential data divergence.

## 5. Implementation Constraints & Pitfalls

- **Payload Bloat:** LangGraph `astream_events` can be extremely noisy
  (e.g., emitting an event for every single chunk of a streaming LLM
  response). The Event Aggregator must carefully batch or debounce
  certain high-frequency events before broadcasting them over the
  WebSocket to prevent blowing out the browser's memory or network
  queue.
- **Differentiating Threads:** The multiplexed WebSocket must strictly
  encapsulate all payloads with their corresponding LangGraph
  `thread_id` to ensure the frontend routes updates to the correct
  agent UI instance.

## 6. Negative Consequences

- **Loss of "Terminal" View:** Because we are no longer piping raw ANSI
  stdout, the "Terminal" view concept in the Gateway is
  deprecated. It must be replaced with structured UI components (e.g.,
  Chat Bubbles, Tool Call components, Markdown renderers) that
  visualize the structured LangGraph JSON payloads. While this is
  cleaner, it requires more frontend work than simply dropping
  `xterm.js` on the page.

## 7. References

- [LangGraph Gap Audit Research](../research/2026-02-26-langgraph-gap-audit-research.md)
- [Gateway Domain - Distilled](../research/2026-02-25-control-surface-distilled-research.md)

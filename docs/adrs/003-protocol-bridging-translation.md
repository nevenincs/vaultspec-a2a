---
adr_id: 003
title: Protocol Bridging & Translation (LangGraph ↔ MCP)
date: 2026-02-26
status: Proposed
related:
  - docs/distilled/2026-25-02-protocols-distilled.md
  - docs/research/2026-26-02-langgraph-gap-audit-research.md
---

# ADR-003: Protocol Bridging & Translation (LangGraph ↔ MCP)

**Date:** 2026-02-26  
**Status:** Proposed

## 1. Context & Problem Statement

The orchestrator must act as a translator between our internal
LangGraph state-machine (which emits complex graph node transitions and
LangChain tool callbacks) and the user's CLI (expecting standard MCP
tool calling states). This involves mapping execution states, handling
interactive user inputs (human-in-the-loop), and ensuring protocol
compliance without leaking LangGraph-specific mechanics to the MCP
clients.

## 2. The Decision

We will handle Protocol Bridging via the following mechanisms:

* **Graph State Aggregator:** We will map native LangGraph node
  execution events (e.g., transitioning to a `tool_node` or `agent`
  node) and LangChain asynchronous callback events (e.g.,
  `on_tool_start`, `on_llm_new_token`) into the 5 standard MCP states
  (`working`, `input_required`, `completed`, `failed`, `cancelled`).
  * LangGraph trajectory updates and `on_tool_start` callbacks will map
    to the `working` state, allowing us to stream rich tool execution
    names to the CLI.
  * Terminal states from the graph will map directly to their MCP
    equivalents.
* **Native Interrupts for Elicitation:** For human-in-the-loop
  workflows (such as an agent requesting missing authentication keys or
  requiring user approval for a destructive action), we will utilize
  LangGraph's native `interrupt` and `Command(resume=...)` architecture.
  * When a node raises an interrupt, the graph execution suspends and
    saves its state to SQLite.
  * The orchestrator translates this suspended state into an MCP
    `input_required` state, signaling the CLI host (or the Control
    Surface web dashboard) to elicit the required input.
* **MCP Protocol Compliance:** We rely exclusively on stable MCP tools
  for CLI interaction. Experimental MCP tasks are deferred. The
  orchestrator acts as an MCP Server, exposing the LangGraph agent
  triggers as standard MCP tools.

## 3. Rationale

* **CLI Consistency:** Exposing the raw JSON payload of a LangGraph
  state update directly to an MCP CLI host is incompatible with the MCP
  specification. We must translate the rich graph transitions into
  standard MCP lifecycle states.
* **Native Interrupt Security:** Using LangGraph's `interrupt`
  mechanism for Authentication and Approvals is significantly more
  reliable than the previous design (which attempted to parse arbitrary
  decoupled A2A auth requests). The state is safely checked-pointed to
  SQLite before prompting the user, ensuring the agent doesn't timeout
  or crash while waiting for human input.
* **Stability:** Relying on standard MCP tool execution semantics
  ensures our agents can be consumed by any standard MCP client (e.g.,
  Cursor, Claude Desktop) without requiring custom plugins to
  understand our internal LangChain callbacks.

## 4. Rejected Alternatives

* **Direct A2A Exposition to CLI (Original Design):** Rejected. The
  previous design attempted to map 8 granular A2A SSE states to MCP.
  Since we have abandoned the A2A subprocess model in favor of
  LangGraph, this mapper is obsolete.
* **Leaking LangChain Contexts via MCP:** Rejected. We will not forward
  raw LangChain `run_id` or callback kwargs directly over the MCP wire,
  as this breaks encapsulation and confuses standard MCP clients. All
  output must be formatted as standard MCP text or resource blocks.

## 5. Implementation Constraints & Pitfalls

* **Callback Mapping Complexity:** Translating asynchronous LangChain
  callbacks (like `on_chat_model_start`) into meaningful MCP `working`
  status updates requires stateful tracking within the MCP Server
  bridge to avoid spamming the CLI with noisy, low-level event data.
* **Interrupt Resumption Routing:** When the user replies to an
  `input_required` prompt, the orchestrator must accurately route that
  payload back to the exact `thread_id` and LangGraph checkpoint that
  requested it using `Command(resume=...)`.

## 6. Negative Consequences

* **Loss of Graph Granularity:** The CLI view will abstract away the
  complex internal state of the LangGraph (e.g., memory arrays,
  specific tool kwargs). This detailed telemetry will only be visible
  in the rich web Control Surface or via separate tracing tools like
  LangSmith.

## 7. References

* [LangGraph Gap Audit Research](../research/2026-02-26-langgraph-gap-audit-research.md)
* [Protocols Domain - Distilled](../research/2026-02-25-protocols-distilled-research.md)

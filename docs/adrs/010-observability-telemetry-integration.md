---
adr_id: 010
title: Observability & Telemetry Integration (OpenTelemetry)
date: 2026-02-26
status: Proposed
related:
  - docs/distilled/2026-25-02-process-distilled.md
  - docs/distilled/INDEX.md
---

## ADR-010: Observability & Telemetry Integration (OpenTelemetry)

**Date:** 2026-02-26  
**Status:** Proposed

## 1. Context & Problem Statement

Tracing asynchronous subprocesses and intricate LangGraph state machine
executions across multiple components (WebSockets, REST APIs, SQLite, LLM
API calls) is highly complex. A gap was identified during process research
(Gap X4 / G3): despite monitoring research recommending OpenTelemetry
integration from day one, it was initially deferred from the v1 scope.
Operating this distributed architecture without tracing presents a severe
operational risk.

## 2. The Decision

We mandate that **OpenTelemetry (OTel)** must be integrated from day one in
the v1 architecture.

1. **Native LangChain/LangSmith Tracing:** Because the core orchestrator
   heavily utilizes LangGraph and LangChain, we natively adopt their
   `langsmith` tracing primitives for internal agent logic, which can emit
   OTel-compatible spans.
2. **FastAPI & Uvicorn Instrumentation:** The REST API and WebSocket
   interfaces will be instrumented using standard
   `opentelemetry-instrumentation-fastapi`.
3. **Exporting vs. Dashboarding:** The bespoke React gateway is
   restricted strictly to _real-time control_ (agent lifecycles, streaming
   state). We will not build complex historical time-travel or cost-matrix
   widgets in v1. Instead, all spans and token metrics will be exported via
   OTLP (OpenTelemetry Protocol) to standard external observability backends
   (e.g., Jaeger, Datadog, or Grafana Tempo) or LangSmith.

## 3. Rationale

- **Risk Mitigation:** Given the complexity of the LangGraph event stream and
  the high volume of asynchronous operations, "print debugging" is
  insufficient. Distributed tracing is necessary to diagnose why an agent
  blocked on an MCP tool call or context transfer.
- **Separation of Concerns:** By explicitly delegating historical aggregation
  and cost/latency analysis to external OTel-compatible backends, we
  dramatically reduce the scope and complexity of our bespoke React
  frontend UI.

## 4. Rejected Alternatives

- **Deferred Telemetry (Original v1 Plan):** Rejected. Waiting until v2 to
  implement tracing guarantees that v1 debugging will be a nightmare,
  especially when dealing with complex asynchronous streaming endpoints.
- **Building Custom Time-Travel Debugger:** Rejected. Creating a custom tool
  to visualize the LangGraph execution history inside the React dashboard
  is redundant when tools like LangSmith and Grafana already exist.

## 5. Implementation Constraints & Pitfalls

- **Context Propagation over WebSockets:** Injecting OTel Trace IDs into
  WebSocket frames requires careful manual context propagation, as standard
  HTTP header injection does not automatically flow through sustained
  WebSocket messages.

## 6. References

- [Process Domain - Distilled](../research/2026-02-25-process-distilled-research.md)

---
tags:
- '#adr'
- '#observability-telemetry-integration'
date: 2026-02-26
modified: '2026-10-08'
body_hash: 'sha256:d2bd51fe44254756cfbf56df6c633f2984cd686757b41ef91491c455e5a5057d'
related:
- '[[2026-03-31-docs-vault-migration-research]]'
---

# `observability-telemetry-integration` adr: `adr-8` | (**status:** `accepted`)

## Migration Note

This ADR was migrated from the legacy pre-pipeline documentation tree during the issue #19 cleanup so that the repository no longer depends on the removed `docs/` directory.

- Original ADR number: `ADR-8`
- Original title: `Observability & Telemetry Integration (OpenTelemetry)`
- Legacy status at migration time: `Proposed`

## Original ADR

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

- Process Domain - Distilled

## Amendment (2026-10-08): reconciled with the telemetry module as built, and accepted

Accepted 2026-10-08 under the owner's 2026-10-07 delegation of ADR work for `2026-10-06-codebase-remediation-plan` (decision D20, plan Step W04.P09.S45). This record described a live capability while carrying `proposed`, with three statements of fact from the removed frontend and WebSocket era. The decision stands; the facts are corrected. Grounding: X10 and the R1 WebSocket-surface findings in `2026-10-06-codebase-remediation-audit`. Code paths are under `src/vaultspec_a2a/`.

- **Decision 2, corrected.** HTTP instrumentation is this project's own `TelemetryMiddleware`, not auto-instrumentation. `opentelemetry-instrumentation-fastapi` is a declared dependency and `FastAPIInstrumentor().instrument()` is deliberately never called, because running both would emit duplicate spans for every request; the reason is recorded at the seam (`telemetry/instrumentation.py`). The middleware carries W3C traceparent propagation and the semantic-convention attributes, and it is the single home of both the span helper and the outbound header builder (`telemetry/middleware.py`: `operation_span`, `trace_headers`). There is no WebSocket interface to instrument.
- **Decision 3, corrected.** There is no bespoke React gateway in this repository. A2A is headless and ships no bundled UI; the dashboard is a separate repository fronting A2A across a loopback HTTP edge, governed by `2026-07-14-a2a-edge-conformance-adr`. The clause's substance survives the frontend's disappearance: historical aggregation and cost and latency analysis are delegated to OTel-compatible backends or LangSmith, and this project builds no such views. Export is as described, with the OTLP gRPC exporter an optional extra (`otlp`) and the provider wiring, exporter selection and LangSmith resolution all in one module (`telemetry/instrumentation.py`; providers installed by `api/app.py` and `worker/app.py`).
- **Section 5, replaced.** The WebSocket context-propagation pitfall names a transport this project does not have: no production module imports or serves a WebSocket. The real pitfall is the one the code already guards: two instrumentation sources on one HTTP surface produce duplicate spans, so auto-instrumentation stays off while the middleware owns the span, and trace context crosses the gateway-to-worker hop through `trace_headers()` on the HTTP request rather than through any sustained connection.

Nothing else in the record changes. The decision to mandate OpenTelemetry from day one, its rationale and its rejected alternatives are unchanged and are what the implementation does.

# Telemetry and Tracing Gaps Research — 2026-03-08

## Context

ADR-010 mandates OpenTelemetry from day one. This document audits the current
telemetry implementation across all three processes (MCP Server, Gateway,
Worker) to identify coverage gaps, cross-process propagation issues, and
LangSmith integration depth.

---

## 1. Telemetry Initialization Audit

### 1.1 Gateway: `configure_telemetry()` Call

**Location**: `api/app.py:619` (inside `create_app` lifespan)

```python
configure_telemetry()
```

**Status**: PRESENT and CORRECT.

The gateway calls `configure_telemetry()` during FastAPI lifespan startup.
This sets the global `TracerProvider` and `MeterProvider` via
`telemetry/instrumentation.py:220-285`.

**What it configures**:
- SDK TracerProvider with Resource (`service.name`, `service.version`)
- OTLP gRPC exporter (if `opentelemetry-exporter-otlp-proto-grpc` installed)
- Console exporter (if `OTEL_EXPORTER_CONSOLE=true`)
- MeterProvider with optional OTLP metric reader
- LangSmith tracing via `LANGCHAIN_TRACING_V2` (read by LangChain, not by us)

### 1.2 Worker: `configure_telemetry()` Call

**Location**: `worker/app.py` -- **NOT CALLED**

**Status**: GAP FOUND (TEL-GAP-01).

The worker process (`worker/app.py:44-96`) never calls `configure_telemetry()`.
This means:
- The worker runs with the OTel no-op provider
- No spans are emitted from the worker process
- No metrics are recorded by the worker
- LangSmith tracing still works (LangChain reads env vars directly)

**Impact**: MEDIUM. LangGraph execution in the worker produces no OTel spans.
The full distributed trace chain is broken: Gateway span -> (gap) -> LangSmith
trace. The two systems cannot be correlated by trace ID.

**Fix**: Add `configure_telemetry()` to `_lifespan()` in `worker/app.py`,
ideally with `OTEL_SERVICE_NAME=vaultspec-a2a-worker` to distinguish spans.

### 1.3 MCP Server: `configure_telemetry()` Call

**Location**: `protocols/mcp/server.py` -- **NOT CALLED**

**Status**: GAP FOUND (TEL-GAP-02).

The MCP server runs as a standalone process (stdio mode). It never calls
`configure_telemetry()`. All MCP tool operations produce no OTel spans.

**Impact**: LOW. The MCP server is a thin HTTP proxy. Its operations are
short-lived and already visible via the gateway's HTTP spans (every MCP tool
call becomes an HTTP request to the gateway, which the gateway's
TelemetryMiddleware instruments).

**Fix**: Optional. If added, use `OTEL_SERVICE_NAME=vaultspec-a2a-mcp`.

---

## 2. Cross-Process Trace Propagation

### 2.1 Client -> Gateway (HTTP)

**Status**: CORRECT.

`TelemetryMiddleware` (`telemetry/middleware.py:77-156`) extracts W3C
`traceparent` and `tracestate` headers from incoming HTTP requests and
attaches them to the OTel context. Tested in
`telemetry/tests/test_telemetry.py:371`.

### 2.2 Gateway -> Worker (IPC Dispatch)

**Status**: GAP FOUND (TEL-GAP-03).

The gateway dispatches work to the worker via `POST /dispatch`
(`api/app.py:182-248`, `api/endpoints.py:835-852`). The dispatch uses a plain
`httpx.AsyncClient` with no trace context injection.

The `DispatchRequest` schema (`api/schemas/internal.py`) has no
`traceparent` field. The worker receives no trace context from the gateway.

**Impact**: HIGH. This is the most significant trace propagation gap. Even if
the worker called `configure_telemetry()`, it would start new root spans
rather than continuing the gateway's trace. The distributed trace chain would
show disconnected spans:
- Gateway: `POST /api/threads/send` -> `POST /dispatch`
- Worker: (new root) `handle_dispatch` -> LangGraph execution

**Fix**: Inject `traceparent` into the dispatch HTTP request headers. The
worker should extract it and attach to the `handle_dispatch` span. This
requires:
1. Gateway dispatch code: `inject_trace_context(headers)` before POST
2. Worker dispatch handler: `propagate.extract(request.headers)` before
   starting the execution span

### 2.3 Worker -> Gateway (Event Relay)

**Status**: GAP FOUND (TEL-GAP-04).

`WorkerBridge.send_event()` (`worker/ipc.py:110-130`) sends events to
`/internal/events/batch` with a `ts` (monotonic timestamp) but no trace
context.

The gateway's event relay handler (`api/internal.py`) does not extract or
propagate trace context from worker events.

**Impact**: MEDIUM. Events cannot be correlated back to the dispatch that
produced them. The aggregator processes events without any trace lineage.

**Fix**: Include `traceparent` in each event payload at the worker side.
The gateway's event handler can extract it to link event processing spans
to the original dispatch trace.

### 2.4 Gateway -> Browser (WebSocket)

**Status**: CORRECT.

`inject_trace_context()` (`telemetry/middleware.py:210-237`) is called in
the WS writer loop (`api/websocket.py:476`) to inject `_trace.traceparent`
into outgoing WS JSON frames. Tested in
`telemetry/tests/test_telemetry.py:268-304`.

### 2.5 MCP Server -> Gateway (HTTP Proxy)

**Status**: PARTIAL (TEL-GAP-05).

The MCP server uses `_shared_client` (`protocols/mcp/server.py:106-121`),
a plain `httpx.AsyncClient` with no trace context injection. Since the MCP
server does not call `configure_telemetry()`, there is no active span to
inject.

**Impact**: LOW. The MCP server is a thin proxy; its HTTP calls to the
gateway are instrumented on the gateway side. The missing link is that
MCP tool invocations cannot be correlated with gateway spans by trace ID.

---

## 3. Telemetry Coverage Matrix

| Layer | OTel Init | Spans Emitted | Metrics | Trace Propagation |
|-------|-----------|---------------|---------|-------------------|
| MCP Server | NO | None | None | Not propagated (no active context) |
| Gateway HTTP | YES | All HTTP requests | ws.heartbeats_sent, ws.events_sent | Incoming: W3C extracted. Outgoing WS: injected |
| Gateway WS | YES | Per-operation (subscribe, message, permission) | Counters | Injected in outgoing frames |
| Gateway -> Worker | YES (gateway side) | Gateway span ends at dispatch POST | None | **NOT PROPAGATED** (TEL-GAP-03) |
| Worker | NO | None (no-op provider) | None | Not extracted (no `configure_telemetry`) |
| Worker -> Gateway | N/A | None | None | **NOT PROPAGATED** (TEL-GAP-04) |

---

## 4. LangSmith Tracing Depth

### 4.1 How It Works

LangSmith tracing is completely independent of OTel. LangChain reads these
env vars at import time:
- `LANGCHAIN_TRACING_V2=true`: Enables tracing
- `LANGCHAIN_API_KEY`: Auth key
- `LANGCHAIN_PROJECT`: Project name

When enabled, LangChain automatically traces:
- All `ChatModel.ainvoke()` / `astream()` calls
- All tool calls
- LangGraph node transitions
- Token usage and latency

### 4.2 Coverage

LangSmith tracing fires in the **worker process** because that's where
`Executor.handle_dispatch()` runs LangGraph. The worker subprocess inherits
env vars from the gateway (which inherits from the MCP server or shell).

**Status**: CORRECT for LLM tracing. LangSmith captures the full graph
execution with token counts, tool calls, and node transitions.

**Gap**: No correlation between OTel trace IDs and LangSmith run IDs.
These are separate tracing systems with no bridge.

### 4.3 LangSmith in Production

**Risk**: `LANGCHAIN_TRACING_V2=true` in production sends all LLM traffic
to LangSmith cloud. The audit flagged this as PROD-061 (tracing leak via
env_file in Docker compose). The fix is to explicitly set
`LANGCHAIN_TRACING_V2=false` in the production compose file.

---

## 5. Metrics Coverage

### 5.1 Gateway Metrics

The gateway defines OTel counters and histograms via `telemetry/get_meter()`:
- `api/websocket.py:56-61`: `ws.events_sent`, `ws.heartbeats_sent`,
  `ws.connections_active`
- `api/endpoints.py`: Request latency (via TelemetryMiddleware spans)

### 5.2 Worker Metrics

**Status**: GAP (TEL-GAP-06). No metrics are defined in the worker process.
The worker has no `get_meter()` calls. No dispatch latency, graph execution
time, or event buffer depth metrics.

### 5.3 MCP Server Metrics

**Status**: GAP (TEL-GAP-07). No metrics in the MCP server.

---

## 6. Gap Summary

| ID | Severity | Gap | Impact | Fix Effort |
|----|----------|-----|--------|------------|
| TEL-GAP-01 | MED | Worker never calls `configure_telemetry()` | No OTel spans from worker | Low: add 1 line to `_lifespan()` |
| TEL-GAP-02 | LOW | MCP server never calls `configure_telemetry()` | No OTel spans from MCP (proxy layer) | Low: optional |
| TEL-GAP-03 | HIGH | Gateway -> Worker dispatch has no traceparent | Broken distributed trace chain | Med: inject + extract headers |
| TEL-GAP-04 | MED | Worker -> Gateway events have no traceparent | Events cannot be correlated to dispatch | Med: add field + extract |
| TEL-GAP-05 | LOW | MCP -> Gateway HTTP has no traceparent | MCP tool calls not correlated with gateway spans | Low: inject after init |
| TEL-GAP-06 | MED | Worker has no OTel metrics | No observability into worker performance | Med: define counters/histograms |
| TEL-GAP-07 | LOW | MCP server has no OTel metrics | No MCP-layer metrics (proxy layer) | Low: optional |

---

## 7. Recommended Fix Priority

### Immediate (Phase 2)

1. **TEL-GAP-01**: Add `configure_telemetry()` to `worker/app.py` lifespan
   with service name `vaultspec-a2a-worker`
2. **TEL-GAP-03**: Inject `traceparent` in gateway dispatch request headers;
   extract in worker dispatch handler

### Near-term (Phase 3)

3. **TEL-GAP-04**: Include `traceparent` in worker event payloads
4. **TEL-GAP-06**: Add worker metrics (dispatch latency, concurrent threads,
   event buffer depth)

### Future

5. **TEL-GAP-02/05/07**: MCP server OTel initialization and metrics
   (low value, proxy layer)
6. **OTel-LangSmith bridge**: Correlation between OTel trace IDs and
   LangSmith run IDs (requires custom callback handler)

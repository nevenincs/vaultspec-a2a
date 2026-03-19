# Cross-Process W3C Traceparent Propagation — 2026-03-08

## Context

VaultSpec A2A has three processes: MCP Server, Gateway, Worker. Trace context
must flow across all process boundaries for end-to-end distributed tracing.
This document researches W3C traceparent propagation patterns in Python asyncio
with httpx, covering both HTTP IPC and subprocess spawning.

---

## 1. W3C TraceContext Standard

### Format

```
traceparent: 00-{trace_id}-{span_id}-{flags}
             ^^  ^^^^^^^^   ^^^^^^^^   ^^^^^
             |   32 hex     16 hex     2 hex (01=sampled)
             version (00)
```

Example: `00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01`

### Headers

- `traceparent`: Required. Carries trace ID, span ID, and sampling flag.
- `tracestate`: Optional. Vendor-specific key-value pairs.

---

## 2. OpenTelemetry Python Propagation API

### Core API

```python
from opentelemetry import propagate

# Inject: write current trace context into a carrier (dict)
carrier = {}
propagate.inject(carrier)
# carrier now contains {"traceparent": "00-...", "tracestate": "..."}

# Extract: read trace context from a carrier (dict) into OTel context
ctx = propagate.extract(carrier)
# Use ctx to continue the trace
```

The global `propagate` module uses the configured propagator (default:
`TraceContextTextMapPropagator` for W3C format).

### Manual Propagator Usage

```python
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

propagator = TraceContextTextMapPropagator()

# Inject
headers = {}
propagator.inject(headers)

# Extract
ctx = propagator.extract(carrier={"traceparent": "00-..."})
```

---

## 3. HTTP IPC Propagation (Gateway <-> Worker)

### Pattern: Inject on Outgoing HTTP Request

When the gateway dispatches work to the worker via `POST /dispatch`, it
should inject the current trace context into the HTTP headers.

```python
from opentelemetry import propagate

# In gateway dispatch code:
headers = {}
propagate.inject(headers)
resp = await worker_client.post(
    "/dispatch",
    json=dispatch_body,
    headers=headers,  # Contains traceparent
)
```

### Pattern: Extract on Incoming HTTP Request

The worker extracts trace context from incoming request headers and uses
it as the parent for the execution span.

```python
from opentelemetry import propagate, trace

# In worker dispatch handler:
ctx = propagate.extract(dict(request.headers))
with trace.get_tracer(__name__).start_as_current_span(
    "handle_dispatch",
    context=ctx,
    kind=trace.SpanKind.SERVER,
) as span:
    # All spans created within this context are children of the gateway span
    await executor.handle_dispatch(req)
```

### Our Current State

**Gateway -> Worker dispatch** (`api/app.py:182-248`, `api/endpoints.py`):
No trace context injection. The `DispatchRequest` is sent as JSON body only.

**Worker dispatch handler** (`worker/app.py:110-134`):
No trace context extraction. The worker starts unlinked spans.

**Gap: TEL-GAP-03** (HIGH). This is the most significant trace propagation
gap. Fix requires:

1. Gateway: inject headers before POST /dispatch
2. Worker: extract headers and use as parent context

### Implementation Plan

#### Step 1: Gateway Injection

In `_dispatch_to_worker()` (`api/app.py:182`):

```python
from opentelemetry import propagate

async def _dispatch_to_worker(
    worker_client: httpx.AsyncClient,
    dispatch: DispatchRequest,
    circuit_breaker: WorkerCircuitBreaker,
    *,
    spawner: LazyWorkerSpawner | None = None,
) -> DispatchResponse:
    # Inject trace context into HTTP headers
    headers: dict[str, str] = {}
    propagate.inject(headers)

    circuit_breaker.pre_dispatch()
    try:
        resp = await worker_client.post(
            "/dispatch",
            json=dispatch.model_dump(),
            headers=headers,
        )
        # ...
```

#### Step 2: Worker Extraction

In `dispatch_endpoint()` (`worker/app.py:110`):

```python
from opentelemetry import propagate, trace
from fastapi import Request

@app.post("/dispatch", response_model=DispatchResponse)
async def dispatch_endpoint(req: DispatchRequest, request: Request) -> DispatchResponse:
    # Extract trace context from incoming headers
    ctx = propagate.extract(dict(request.headers))

    # Start execution span linked to gateway trace
    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span(
        "worker.handle_dispatch",
        context=ctx,
        kind=trace.SpanKind.SERVER,
        attributes={"thread_id": req.thread_id, "dispatch_id": req.dispatch_id},
    ):
        executor: Executor = app.state.executor
        tg.start_soon(executor.handle_dispatch, req)
        return DispatchResponse(status="dispatched", thread_id=req.thread_id)
```

---

## 4. Event Relay Propagation (Worker -> Gateway)

### Pattern: Include traceparent in Event Payload

When the worker sends events back to the gateway via
`POST /internal/events/batch`, each event should carry the trace context
of the span that produced it.

```python
# In WorkerBridge.send_event():
from opentelemetry import propagate

carrier: dict[str, str] = {}
propagate.inject(carrier)

self._event_buffer.append({
    "thread_id": thread_id,
    "payload": payload,
    "ts": time.monotonic(),
    "trace_context": carrier,  # NEW: carry traceparent
})
```

### Gateway-Side Extraction

In the internal event handler (`api/internal.py`), extract the trace context
from each event and create a child span for event processing:

```python
for event in batch:
    ctx = propagate.extract(event.get("trace_context", {}))
    with tracer.start_as_current_span(
        "relay_event",
        context=ctx,
        attributes={"thread_id": event["thread_id"]},
    ):
        # Process and relay the event
```

### Our Current State

**Gap: TEL-GAP-04** (MED). Events have `ts` (monotonic timestamp) but no
trace context. Events cannot be correlated to the dispatch span that
produced them.

---

## 5. Subprocess Trace Propagation (MCP -> Gateway)

### Pattern: Environment Variable Carrier

The OTel spec defines `TRACEPARENT` and `TRACESTATE` environment variables
for subprocess context propagation.

```python
import os
from opentelemetry import propagate

# Parent: inject into env dict
env = dict(os.environ)
propagate.inject(env)
# env now contains TRACEPARENT and TRACESTATE (if using env carrier)

process = await asyncio.create_subprocess_exec(
    sys.executable, "-m", "uvicorn", ...,
    env=env,
)
```

### Limitation

The standard `TraceContextTextMapPropagator` injects `traceparent` and
`tracestate` (lowercase HTTP header names) into the carrier. For environment
variable propagation, the OTel spec recommends uppercase `TRACEPARENT`.

The Python SDK provides `EnvironmentGetter` for reading from env vars, but
this pattern is not widely used in practice because:

1. Subprocess startup is a one-time event
2. The trace context is stale by the time the subprocess starts
3. HTTP-level propagation (Step 3 above) is more useful

### Our Assessment

For our use case, MCP -> Gateway trace propagation via env vars has LOW
value. The MCP server is a thin proxy; its HTTP calls to the gateway are
already instrumented on the gateway side. The trace link between "MCP tool
invocation" and "gateway HTTP request" is more naturally established via
HTTP header propagation (which requires `configure_telemetry()` in the MCP
server first -- TEL-GAP-02).

---

## 6. WebSocket Trace Propagation (Gateway -> Browser)

### Our Current Implementation (CORRECT)

`inject_trace_context()` (`telemetry/middleware.py:210-237`):

```python
def inject_trace_context(carrier: dict[str, Any]) -> None:
    propagate.inject(carrier)
```

Called in `_writer_loop()` (`api/websocket.py:476`):

```python
trace_carrier: dict[str, str] = {}
inject_trace_context(trace_carrier)
if trace_carrier:
    payload["_trace"] = trace_carrier
```

This correctly injects `traceparent` into outgoing WebSocket JSON frames,
allowing the frontend to reconstruct the distributed trace.

---

## 7. Complete Trace Flow (After Fixes)

```
IDE / CLI
  | HTTP request with traceparent header
  v
Gateway (TelemetryMiddleware extracts traceparent)
  | HTTP span: "POST /api/threads/send"
  |
  | propagate.inject(headers)  [TEL-GAP-03 fix]
  v
Worker (propagate.extract(headers))
  | Span: "worker.handle_dispatch" (child of gateway span)
  |
  | LangGraph execution (auto-instrumented by LangSmith)
  |
  | propagate.inject(event.trace_context)  [TEL-GAP-04 fix]
  v
Gateway (propagate.extract(event.trace_context))
  | Span: "relay_event" (child of worker span)
  |
  | inject_trace_context(ws_frame._trace)  [already done]
  v
Browser / Frontend
  | Reads _trace.traceparent from WS frame
  | Can reconstruct full distributed trace
```

---

## 8. OTel Auto-Instrumentation for httpx

### opentelemetry-instrumentation-httpx

The `opentelemetry-instrumentation-httpx` package automatically injects
trace context into all outgoing httpx requests. This would solve TEL-GAP-03
without manual `propagate.inject()` calls.

```python
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

HTTPXClientInstrumentor().instrument()
# Now ALL httpx requests automatically carry traceparent
```

### Trade-offs

| Approach | Pros | Cons |
|----------|------|------|
| Manual `propagate.inject()` | Explicit, no dependency | Must remember every call site |
| `HTTPXClientInstrumentor` | Automatic, covers all calls | Extra dependency, instruments ALL clients |

### Recommendation

Use `HTTPXClientInstrumentor` for the gateway (where all httpx calls are
to the worker). Use manual injection for the worker bridge (where event
payloads need custom trace context fields, not HTTP headers).

---

## 9. Testing Trace Propagation

### InMemorySpanExporter Pattern

```python
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory import InMemorySpanExporter

exporter = InMemorySpanExporter()
provider = TracerProvider()
provider.add_span_processor(SimpleSpanProcessor(exporter))

# After test execution:
spans = exporter.get_finished_spans()
gateway_span = next(s for s in spans if s.name == "POST /dispatch")
worker_span = next(s for s in spans if s.name == "worker.handle_dispatch")

# Verify parent-child relationship:
assert worker_span.parent.trace_id == gateway_span.context.trace_id
assert worker_span.parent.span_id == gateway_span.context.span_id
```

### Cross-Process Testing

For real subprocess tests, each process has its own `TracerProvider`.
Options:

1. Use `OTEL_EXPORTER_CONSOLE=true` and parse stdout/stderr
2. Use OTLP exporter to a test collector (e.g., Jaeger all-in-one)
3. Use `InMemorySpanExporter` in-process only (for gateway spans)

---

## 10. Gap Summary and Fix Priority

| Gap | Severity | Fix | Effort |
|-----|----------|-----|--------|
| TEL-GAP-01 | MED | Add `configure_telemetry()` to worker lifespan | 1 line |
| TEL-GAP-03 | HIGH | Inject traceparent in gateway dispatch headers | 3 lines |
| TEL-GAP-03b | HIGH | Extract traceparent in worker dispatch handler | 5 lines |
| TEL-GAP-04 | MED | Include trace_context in event payloads | 3 lines per site |
| TEL-GAP-04b | MED | Extract trace_context in gateway event handler | 5 lines |
| TEL-GAP-02 | LOW | Add `configure_telemetry()` to MCP server | Optional |

### Recommended Fix Order

1. TEL-GAP-01 (worker init) -- prerequisite for all worker spans
2. TEL-GAP-03 (dispatch propagation) -- highest value, completes the trace chain
3. TEL-GAP-04 (event propagation) -- correlates events to dispatches
4. TEL-GAP-02 (MCP init) -- low value, optional

Total estimated code change: ~25 lines across 4 files.

Sources:

- [OpenTelemetry Python Propagation](https://opentelemetry.io/docs/languages/python/propagation/)
- [OpenTelemetry Context Propagation Concepts](https://opentelemetry.io/docs/concepts/context-propagation/)
- [Environment Variables as Context Carriers](https://opentelemetry.io/docs/specs/otel/context/env-carriers/)
- [W3C TraceContext Propagator (Python SDK)](https://github.com/open-telemetry/opentelemetry-python/blob/main/opentelemetry-api/src/opentelemetry/trace/propagation/tracecontext.py)

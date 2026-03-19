# OTel Cross-Process Propagation — 2026-03-08

## Context

VaultSpec A2A operates as a 3-process chain: MCP Server -> Gateway -> Worker.
Distributed tracing requires W3C traceparent propagation across all HTTP
boundaries. This document researches httpx inject/extract patterns, the
LangSmith-OTel bridge gap, and implementation-ready solutions for TEL-GAP-03
(our highest-severity telemetry gap).

Related documents:

- `2026-03-08-cross-process-tracing.md` — W3C format, gap catalog, fix plan
- `2026-03-08-telemetry-tracing-gaps.md` — full gap audit (TEL-GAP-01 through 07)
- `telemetry/instrumentation.py` — SDK setup, `configure_telemetry()`
- `telemetry/middleware.py` — `TelemetryMiddleware`, `inject_trace_context()`

---

## 1. httpx Trace Context Injection Patterns

### 1.1 Manual Injection via `propagate.inject()`

The simplest pattern: inject the current span's trace context into a dict,
then pass that dict as HTTP headers.

```python
from opentelemetry import propagate

headers: dict[str, str] = {}
propagate.inject(headers)
# headers == {"traceparent": "00-{trace_id}-{span_id}-01", "tracestate": ""}

resp = await client.post("/dispatch", json=body, headers=headers)
```

**Pros**: Zero new dependencies, explicit control, works with any HTTP client.
**Cons**: Must remember every call site. If a new dispatch path is added without
injection, the trace chain silently breaks.

### 1.2 httpx Event Hooks (Recommended for Our Architecture)

httpx supports `event_hooks` on `AsyncClient` — callbacks that fire on every
request/response cycle. This is the cleanest way to inject trace context
without a new dependency.

```python
from opentelemetry import propagate

def _inject_traceparent(request: httpx.Request) -> None:
    """Inject W3C traceparent into every outgoing request."""
    carrier: dict[str, str] = {}
    propagate.inject(carrier)
    for key, value in carrier.items():
        request.headers[key] = value

client = httpx.AsyncClient(
    base_url="http://localhost:8001",
    event_hooks={"request": [_inject_traceparent]},
)
```

**Pros**: Configures once at client creation. Every request through this client
automatically carries trace context. No new dependency.
**Cons**: Injects into ALL requests from this client (acceptable when the client
is dedicated to worker IPC).

### 1.3 `opentelemetry-instrumentation-httpx` (Auto-Instrumentation)

The OTel ecosystem provides `opentelemetry-instrumentation-httpx` which
monkey-patches httpx globally or per-client.

```python
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

# Global: instruments ALL httpx clients
HTTPXClientInstrumentor().instrument()

# Per-client: instruments only the given client
HTTPXClientInstrumentor.instrument_client(client)
```

**What it does**:

- Injects `traceparent`/`tracestate` into outgoing request headers
- Creates a CLIENT span for each outgoing request
- Records `http.method`, `http.url`, `http.status_code` attributes
- Links request spans as children of the current span

**Trade-offs for our codebase**:

| Factor | event_hooks | instrumentation-httpx |
|--------|------------|----------------------|
| New dependency | No | Yes (`opentelemetry-instrumentation-httpx`) |
| Scope control | Per-client | Global or per-client |
| CLIENT spans | No (just propagation) | Yes (creates spans) |
| Integration test noise | None | Extra spans in test output |
| Semantic convention compliance | Manual | Automatic (v1.23+) |

**Recommendation**: Use **event_hooks** for TEL-GAP-03. We already have
`TelemetryMiddleware` creating SERVER spans on the receiving side. Adding
CLIENT spans from the auto-instrumentor would create duplicate span coverage
for the same HTTP call. The event_hooks approach gives us propagation without
span duplication.

If we later need CLIENT spans for latency analysis (e.g., measuring gateway->
worker round-trip time separate from worker processing time), we can add
`opentelemetry-instrumentation-httpx` as a second step.

---

## 2. Server-Side Extraction Patterns

### 2.1 FastAPI Middleware Extraction (Current: Gateway)

Our `TelemetryMiddleware` already extracts trace context on the gateway side:

```python
# telemetry/middleware.py:121-123
carrier: dict[str, str] = dict(request.headers)
ctx = propagate.extract(carrier)
token = otel_context.attach(ctx)
```

This correctly links incoming HTTP requests to the upstream caller's trace.

### 2.2 Worker Endpoint Extraction (Missing: TEL-GAP-03b)

The worker's `/dispatch` endpoint does NOT extract trace context. It starts
an unlinked root span (or no span at all, since `configure_telemetry()` is
also missing per TEL-GAP-01).

**Implementation pattern for worker extraction**:

```python
from opentelemetry import propagate, trace
from fastapi import Request

@app.post("/dispatch", response_model=DispatchResponse)
async def dispatch_endpoint(
    req: DispatchRequest,
    request: Request,
) -> DispatchResponse:
    # Extract trace context from gateway's injected headers
    ctx = propagate.extract(dict(request.headers))

    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span(
        "worker.dispatch",
        context=ctx,
        kind=trace.SpanKind.SERVER,
        attributes={
            "thread_id": req.thread_id,
            "dispatch_id": req.dispatch_id or "",
        },
    ):
        # All downstream spans (LangGraph execution) inherit this context
        executor: Executor = app.state.executor
        tg.start_soon(executor.handle_dispatch, req)
        return DispatchResponse(status="dispatched", thread_id=req.thread_id)
```

**Critical detail**: The `context=ctx` parameter on `start_as_current_span`
makes the new span a child of the gateway's span. Without this parameter,
`propagate.extract` returns a context but it is never used, and the span
starts as a new root.

### 2.3 Extraction from Non-HTTP Carriers (Event Payloads)

For worker->gateway event relay (TEL-GAP-04), trace context is embedded
in JSON payloads, not HTTP headers. The extraction is identical:

```python
# Worker side: inject into event payload
carrier: dict[str, str] = {}
propagate.inject(carrier)
event = {"thread_id": tid, "payload": data, "ts": mono, "trace_ctx": carrier}

# Gateway side: extract from event payload
ctx = propagate.extract(event.get("trace_ctx", {}))
with tracer.start_as_current_span("process_event", context=ctx):
    ...
```

---

## 3. LangSmith-OTel Bridge

### 3.1 The Two-System Problem

VaultSpec A2A runs two independent tracing systems:

1. **OpenTelemetry**: Infrastructure-level tracing (HTTP requests, WS events,
   IPC dispatch). Configured by `configure_telemetry()`. Exports to OTLP
   collector.

2. **LangSmith**: LLM-level tracing (model invocations, tool calls, graph
   transitions, token usage). Configured by `LANGCHAIN_TRACING_V2=true`.
   Exports to LangSmith cloud.

These systems produce independent trace trees with no correlation:

```
OTel Trace:
  Gateway: POST /api/threads/send (trace_id=abc)
    -> POST /dispatch (trace_id=abc)
      -> [GAP — worker has no OTel]

LangSmith Trace:
  ChatModel.astream (run_id=xyz)
    -> ToolCall: read_file (run_id=...)
    -> ToolCall: edit_file (run_id=...)
```

The `trace_id=abc` and `run_id=xyz` are completely unrelated. An operator
cannot look at an OTel trace and find the corresponding LangSmith run, or
vice versa.

### 3.2 Bridge Strategy: OTel Span Attributes on LangSmith Runs

LangChain's callback system passes `run_id` (UUID) through all events. Our
aggregator already extracts `run_id` from LangGraph events
(`aggregator.py:1228`). The bridge strategy is to embed the OTel trace_id
as metadata on the LangSmith run:

```python
from opentelemetry import trace

# When starting a LangGraph invocation:
current_span = trace.get_current_span()
span_ctx = current_span.get_span_context()
otel_trace_id = format(span_ctx.trace_id, "032x")

# Pass to LangGraph via config metadata
config = {
    "configurable": {"thread_id": thread_id},
    "metadata": {
        "otel_trace_id": otel_trace_id,
        "dispatch_id": dispatch_id,
    },
}
result = await graph.ainvoke(state, config)
```

LangSmith stores `config.metadata` as run metadata, making it searchable:

```python
from langsmith import Client

client = Client()
# Find the LangSmith run for a given OTel trace
runs = client.list_runs(
    project_name="vaultspec-a2a",
    filter='eq(metadata_key, "otel_trace_id", "abc...")',
)
```

### 3.3 Bridge Strategy: LangSmith Run ID as OTel Span Attribute

The reverse direction: embed the LangSmith run_id in OTel span attributes.

```python
# In executor.handle_dispatch(), after LangGraph invocation starts:
from opentelemetry import trace

span = trace.get_current_span()

# LangGraph streams events with run_id
async for event in graph.astream_events(state, config, version="v2"):
    run_id = event.get("run_id")
    if run_id and span.is_recording():
        span.set_attribute("langsmith.run_id", str(run_id))
        break  # Only need the root run_id
```

This allows OTel trace viewers (Jaeger, Grafana Tempo) to display the
LangSmith run_id, enabling manual cross-reference.

### 3.4 Bridge Strategy: Custom Callback Handler (Most Complete)

The most thorough bridge uses a custom LangChain callback handler that
creates OTel spans for each LangSmith event:

```python
from langchain_core.callbacks import AsyncCallbackHandler
from opentelemetry import trace

class OTelBridgeCallback(AsyncCallbackHandler):
    """Bridge LangSmith events to OTel spans."""

    def __init__(self) -> None:
        self._tracer = trace.get_tracer("langsmith-bridge")
        self._spans: dict[str, trace.Span] = {}

    async def on_llm_start(self, serialized, prompts, *, run_id, **kwargs):
        span = self._tracer.start_span(
            f"llm.{serialized.get('name', 'unknown')}",
            attributes={"langsmith.run_id": str(run_id)},
        )
        self._spans[str(run_id)] = span

    async def on_llm_end(self, response, *, run_id, **kwargs):
        span = self._spans.pop(str(run_id), None)
        if span:
            span.set_attribute("llm.token_count", response.llm_output.get("token_usage", {}).get("total_tokens", 0))
            span.end()

    async def on_tool_start(self, serialized, input_str, *, run_id, **kwargs):
        span = self._tracer.start_span(
            f"tool.{serialized.get('name', 'unknown')}",
            attributes={"langsmith.run_id": str(run_id)},
        )
        self._spans[str(run_id)] = span

    async def on_tool_end(self, output, *, run_id, **kwargs):
        span = self._spans.pop(str(run_id), None)
        if span:
            span.end()
```

**Trade-offs**:

| Approach | Complexity | Correlation | Operational Cost |
|----------|-----------|-------------|-----------------|
| OTel trace_id in LangSmith metadata | Low | One-way (OTel -> LangSmith) | None |
| LangSmith run_id in OTel attributes | Low | One-way (LangSmith -> OTel) | None |
| Both metadata + attributes | Medium | Bidirectional (manual lookup) | None |
| Custom callback handler | High | Full (unified trace tree) | Duplicate span storage |

**Recommendation**: Start with **both metadata + attributes** (bidirectional
manual lookup). This is 10 lines of code with zero new dependencies. The
custom callback handler is overkill until we have an operational need for
unified trace visualization.

### 3.5 LangSmith OTel Exporter (Upcoming)

LangSmith has announced (but not yet GA'd) an OTel-compatible exporter
that can receive OTel spans and display them alongside LangSmith traces.
When available, this would be the ideal bridge:

```python
# Future: configure OTel to export to LangSmith's OTLP endpoint
# This is NOT yet available in the stable SDK
exporter = OTLPSpanExporter(endpoint="https://api.smith.langchain.com/otel")
```

Until this ships, the metadata/attribute approach is the best option.

---

## 4. TEL-GAP-03 Implementation Plan (Ready to Code)

TEL-GAP-03 is the highest-severity telemetry gap: gateway->worker dispatch
has no trace context propagation. Here is the implementation-ready plan.

### 4.1 Prerequisites

1. **TEL-GAP-01** must be fixed first: `configure_telemetry()` must be called
   in the worker's `_lifespan()`. Without this, the worker's OTel provider
   is no-op and extracted trace context is silently ignored.

2. No new dependencies required.

### 4.2 Gateway Side: Inject into Worker Client

**File**: `src/vaultspec_a2a/api/app.py`

The gateway creates an `httpx.AsyncClient` for worker communication. Add
an event hook at client creation:

```python
# In create_app() lifespan, where worker_client is created:
def _inject_trace_context(request: httpx.Request) -> None:
    carrier: dict[str, str] = {}
    propagate.inject(carrier)
    for key, value in carrier.items():
        request.headers[key] = value

worker_client = httpx.AsyncClient(
    base_url=f"http://localhost:{worker_port}",
    event_hooks={"request": [_inject_trace_context]},
)
```

**Alternative** (if event_hooks are awkward with the existing client setup):
inject directly in `_dispatch_to_worker()`:

```python
async def _dispatch_to_worker(
    worker_client: httpx.AsyncClient,
    dispatch: DispatchRequest,
    circuit_breaker: WorkerCircuitBreaker,
    *,
    spawner: LazyWorkerSpawner | None = None,
) -> DispatchResponse:
    headers: dict[str, str] = {}
    propagate.inject(headers)

    circuit_breaker.pre_dispatch()
    try:
        resp = await worker_client.post(
            "/dispatch",
            json=dispatch.model_dump(),
            headers=headers,
        )
```

### 4.3 Worker Side: Extract in Dispatch Handler

**File**: `src/vaultspec_a2a/worker/app.py`

```python
from opentelemetry import propagate, trace

@app.post("/dispatch", response_model=DispatchResponse)
async def dispatch_endpoint(
    req: DispatchRequest,
    request: Request,
) -> DispatchResponse:
    ctx = propagate.extract(dict(request.headers))
    tracer = trace.get_tracer(__name__)

    with tracer.start_as_current_span(
        "worker.dispatch",
        context=ctx,
        kind=trace.SpanKind.SERVER,
        attributes={
            "thread_id": req.thread_id,
            "dispatch_id": req.dispatch_id or "",
        },
    ):
        executor: Executor = app.state.executor
        tg.start_soon(executor.handle_dispatch, req)
        return DispatchResponse(status="dispatched", thread_id=req.thread_id)
```

**Important**: The `start_as_current_span` context manager sets the extracted
context as the active span context. All spans created within this block
(including LangGraph internal spans, if OTel is initialized) will be children
of the gateway's dispatch span.

### 4.4 Verification

After implementing TEL-GAP-01 + TEL-GAP-03:

```python
# In integration tests (conftest.py span_collector fixture):
spans = span_collector.get_finished_spans()

gateway_span = next(s for s in spans if "POST /dispatch" in s.name)
worker_span = next(s for s in spans if s.name == "worker.dispatch")

# Verify parent-child relationship
assert worker_span.parent is not None
assert worker_span.parent.trace_id == gateway_span.context.trace_id
assert worker_span.parent.span_id == gateway_span.context.span_id
```

**Cross-process testing challenge**: Gateway and worker run in separate
processes with separate `TracerProvider` instances. The `InMemorySpanExporter`
only captures spans from the current process. Options:

1. **OTLP test collector**: Run a lightweight collector (Jaeger all-in-one)
   in the test and query its API for spans. Most accurate but requires
   Docker/testcontainers.

2. **OTLP file exporter**: Configure both processes to export to a shared
   file (`OTEL_EXPORTER_OTLP_PROTOCOL=file`). Parse the file after the test.

3. **Console exporter + stderr capture**: Set `OTEL_EXPORTER_CONSOLE=true`
   in both process envs and capture stderr. Parse span JSON from output.
   This is what our existing `conftest.py` could do with `_start_and_wait`.

4. **Hybrid**: Use `InMemorySpanExporter` in the gateway (in-process), and
   verify the worker side by checking that the dispatched request contains
   a `traceparent` header (mock-free: just inspect the request object in the
   worker handler).

**Recommendation**: Option 4 (hybrid) for CI. Option 1 (OTLP test collector)
for full distributed trace verification in `@pytest.mark.live` tests.

---

## 5. Event Relay Trace Propagation (TEL-GAP-04)

### 5.1 Current State

`WorkerBridge.send_event()` (`worker/ipc.py:110-130`) buffers events as:

```python
{"thread_id": tid, "payload": payload, "ts": time.monotonic()}
```

No trace context is included. The gateway processes these events without
any trace lineage.

### 5.2 Implementation

**Worker side** (`worker/ipc.py`):

```python
async def send_event(self, thread_id: str, payload: dict[str, Any]) -> None:
    carrier: dict[str, str] = {}
    propagate.inject(carrier)

    self._event_buffer.append({
        "thread_id": thread_id,
        "payload": payload,
        "ts": time.monotonic(),
        "trace_ctx": carrier,  # NEW
    })
```

**Gateway side** (`api/internal.py`):

```python
for event in batch:
    ctx = propagate.extract(event.get("trace_ctx", {}))
    with tracer.start_as_current_span(
        "relay_event",
        context=ctx,
        kind=trace.SpanKind.INTERNAL,
        attributes={"thread_id": event["thread_id"]},
    ):
        await process_event(event)
```

### 5.3 Schema Consideration

The `trace_ctx` field must pass through the event batch schema. Options:

1. **Untyped dict pass-through**: The batch endpoint already accepts
   `list[dict[str, Any]]`. The `trace_ctx` key is simply present or absent.
   No schema change needed.

2. **Typed field**: Add `trace_ctx: dict[str, str] | None = None` to a
   Pydantic event model. Cleaner but requires schema migration.

**Recommendation**: Start with untyped pass-through (option 1). The trace_ctx
is infrastructure metadata, not business data. Typing it adds schema coupling
without operational benefit.

---

## 6. Subprocess Environment Propagation (MCP -> Gateway)

### 6.1 OTel Spec for Environment Carriers

The OTel specification defines `TRACEPARENT` and `TRACESTATE` as environment
variable names for subprocess propagation:

```python
env = dict(os.environ)
propagate.inject(env)
# env now has "traceparent" (lowercase — HTTP header convention)

process = await asyncio.create_subprocess_exec(
    sys.executable, "-m", "uvicorn", ...,
    env=env,
)
```

**Limitation**: The standard `TraceContextTextMapPropagator` injects lowercase
`traceparent` (HTTP header convention). For environment variables, the OTel
spec recommends uppercase `TRACEPARENT`. Python's `os.environ` on Windows is
case-insensitive, so this works on Windows but may not on Linux.

### 6.2 Why This Has Low Value for Us

The MCP server spawns the gateway as a subprocess. Injecting `TRACEPARENT`
into the gateway's environment would link the gateway's first spans to the
MCP server's startup span. However:

1. **Stale context**: The subprocess startup trace context is fixed at spawn
   time. It does not update for subsequent requests. The gateway handles
   thousands of requests, each with its own trace context from HTTP headers.

2. **One-time event**: Process spawning is a single event. The operational
   value of tracing "MCP spawned gateway" is minimal compared to tracing
   actual request flows.

3. **HTTP propagation covers it**: Every MCP tool call becomes an HTTP
   request to the gateway. The gateway's `TelemetryMiddleware` extracts
   trace context from those HTTP headers. This is the correct propagation
   point.

**Decision**: Do not implement env var propagation for MCP->Gateway.
Focus on HTTP-level propagation (TEL-GAP-03) which has much higher value.

---

## 7. Complete Trace Flow After All Fixes

```
CLI / IDE
  | HTTP POST /api/threads/send
  | Headers: traceparent: 00-{trace_id}-{span_A}-01
  v
Gateway (TelemetryMiddleware)
  | Extracts traceparent -> span_B (parent=span_A)
  | POST /dispatch to worker
  | Injects traceparent: 00-{trace_id}-{span_B}-01  [TEL-GAP-03 fix]
  v
Worker
  | configure_telemetry() active  [TEL-GAP-01 fix]
  | Extracts traceparent -> span_C (parent=span_B)
  |
  | LangGraph execution
  |   ChatModel.astream (LangSmith run_id in metadata.otel_trace_id)
  |   ToolCall spans (children of span_C)
  |
  | Event relay: trace_ctx injected  [TEL-GAP-04 fix]
  v
Gateway (internal event handler)
  | Extracts trace_ctx -> span_D (parent=span_C)
  | Processes event, broadcasts to WebSocket
  |
  | inject_trace_context(ws_frame._trace)  [already implemented]
  v
Browser / Frontend
  | Reads _trace.traceparent from WS JSON frame
  | Full distributed trace reconstructible
```

**Correlation chain**:

- OTel: trace_id links all spans across processes
- LangSmith: run metadata contains otel_trace_id for cross-reference
- Combined: operator can find LangSmith run from OTel trace, or vice versa

---

## 8. Dependency and Effort Summary

### No New Dependencies Required

All propagation uses `opentelemetry.propagate` (already in `opentelemetry-api`,
a mandatory dependency). No need for `opentelemetry-instrumentation-httpx`.

### Fix Effort Matrix

| Gap | Files Changed | Lines of Code | Dependency |
|-----|--------------|---------------|------------|
| TEL-GAP-01 | `worker/app.py` | 2 | None (prerequisite) |
| TEL-GAP-03 gateway | `api/app.py` | 5 | TEL-GAP-01 |
| TEL-GAP-03 worker | `worker/app.py` | 8 | TEL-GAP-01 |
| TEL-GAP-04 worker | `worker/ipc.py` | 3 | TEL-GAP-01 |
| TEL-GAP-04 gateway | `api/internal.py` | 5 | None |
| LangSmith bridge | `worker/executor.py` | 6 | None |
| **Total** | **4 files** | **~29 lines** | **0 new deps** |

### Implementation Order

1. TEL-GAP-01: Worker `configure_telemetry()` (unblocks everything)
2. TEL-GAP-03: Gateway inject + Worker extract (highest value)
3. LangSmith bridge: Metadata + attribute correlation
4. TEL-GAP-04: Event relay trace context (medium value)

---

## 9. Anti-Patterns to Avoid

### 9.1 Propagating via JSON Body Instead of HTTP Headers

```python
# WRONG: embedding traceparent in the JSON body
resp = await client.post("/dispatch", json={
    **dispatch.model_dump(),
    "traceparent": carrier["traceparent"],  # Bad: schema pollution
})
```

HTTP headers are the correct carrier for W3C trace context. Embedding
in JSON body:

- Pollutes the business schema with infrastructure concerns
- Requires custom extraction (cannot use `propagate.extract(request.headers)`)
- Breaks compatibility with standard OTel auto-instrumentation

### 9.2 Global Instrumentation in Multi-Client Code

```python
# DANGEROUS in gateway: instruments ALL httpx clients including test clients
HTTPXClientInstrumentor().instrument()
```

The gateway may have multiple httpx clients (worker IPC, external APIs).
Global instrumentation cannot distinguish between them. Use per-client
configuration (event_hooks or `instrument_client()`).

### 9.3 Forgetting `context=ctx` on `start_as_current_span`

```python
# WRONG: extracts context but does not use it
ctx = propagate.extract(dict(request.headers))
with tracer.start_as_current_span("worker.dispatch"):  # Missing context=ctx!
    ...  # This span is a NEW ROOT, not a child of the gateway span
```

The `context` parameter is required to link the new span to the extracted
parent. Without it, `start_as_current_span` uses the current (empty) context
and creates a disconnected root span.

### 9.4 Injecting After the Span Ends

```python
# WRONG: span has ended, inject captures stale/no context
with tracer.start_as_current_span("dispatch"):
    resp = await client.post("/dispatch", json=body)

# inject() here captures the PARENT span, not the dispatch span
headers = {}
propagate.inject(headers)
```

Always inject WITHIN the span's context manager, before the HTTP call.

---

## 10. Key Findings

1. **httpx event_hooks are the best injection mechanism** for our architecture.
   They provide automatic injection on every request without a new dependency
   or span duplication.

2. **LangSmith-OTel correlation is achievable in ~6 lines** via bidirectional
   metadata/attribute embedding. No custom callback handler needed.

3. **TEL-GAP-03 is ~15 lines total** (5 gateway + 8 worker + 2 import).
   Blocked only on TEL-GAP-01 (1 line to fix).

4. **No new dependencies required**. Everything uses `opentelemetry.propagate`
   from the existing `opentelemetry-api` package.

5. **Cross-process trace testing** is best done with a hybrid approach:
   in-process `InMemorySpanExporter` for the gateway, header inspection
   for the worker, and an OTLP test collector for full E2E verification
   in live tests.

Sources:

- OpenTelemetry Python SDK: `opentelemetry.propagate` module (installed, verified)
- httpx event_hooks: <https://www.python-httpx.org/advanced/event-hooks/>
- W3C TraceContext: <https://www.w3.org/TR/trace-context/>
- LangSmith metadata search: <https://docs.smith.langchain.com/observability/how_to_guides/filter_traces_in_application>
- Existing codebase: `telemetry/middleware.py`, `worker/ipc.py`, `core/aggregator.py`

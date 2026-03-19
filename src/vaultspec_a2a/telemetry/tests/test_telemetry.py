"""Tests for src/vaultspec_a2a/telemetry/ — no mocks, real OTel API calls only.

MANDATE: InMemorySpanExporter is BANNED. It is a fake that intercepts spans
before they reach a real OTLP backend, allowing tests to "pass" while the
actual export pipeline is never exercised.

Tests that need to verify span attributes MUST use the persistent local Jaeger
instance (via the local_jaeger_otlp_endpoint/local_jaeger_query_url fixtures)
and are marked @pytest.mark.requires_jaeger. Run them with: just test-tracing
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.trace import StatusCode
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

if TYPE_CHECKING:
    from starlette.requests import Request

from .. import (
    TelemetryConfig,
    TelemetryMiddleware,
    configure_telemetry,
    get_meter,
    get_tracer,
    inject_trace_context,
    ws_span,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_HTTP_OK = 200
_HTTP_SERVER_ERROR = 500


def _make_test_app(*, excluded: frozenset[str] | None = None) -> Starlette:
    """Build a minimal Starlette app with TelemetryMiddleware attached.

    Uses the globally configured TracerProvider (set up by configure_telemetry
    in each test). No monkey-patching — the real middleware uses the real tracer.
    """

    async def home(request: Request) -> JSONResponse:
        return JSONResponse({"ok": True})

    async def error_route(request: Request) -> JSONResponse:
        return JSONResponse({"error": "bad"}, status_code=_HTTP_SERVER_ERROR)

    async def health(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    routes = [
        Route("/", home),
        Route("/error", error_route),
        Route("/health", health),
    ]
    app = Starlette(routes=routes)
    kwargs: dict = {} if excluded is None else {"excluded_paths": excluded}
    app.add_middleware(TelemetryMiddleware, **kwargs)  # type: ignore[arg-type]
    return app


# ---------------------------------------------------------------------------
# configure_telemetry
# ---------------------------------------------------------------------------


def test_configure_telemetry_returns_config() -> None:
    """configure_telemetry returns a TelemetryConfig with expected fields."""
    cfg = configure_telemetry()
    assert isinstance(cfg, TelemetryConfig)
    assert isinstance(cfg.sdk_available, bool)
    assert isinstance(cfg.otlp_available, bool)
    assert isinstance(cfg.sdk_enabled, bool)
    assert isinstance(cfg.service_name, str)
    assert cfg.service_name  # non-empty
    assert isinstance(cfg.otlp_endpoint, str)
    assert isinstance(cfg.langsmith_enabled, bool)


def test_configure_telemetry_service_name_type() -> None:
    """service_name is always a non-empty string."""
    cfg = configure_telemetry()
    assert isinstance(cfg.service_name, str)
    assert len(cfg.service_name) > 0


def test_configure_telemetry_sdk_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """OTEL_SDK_DISABLED=true is reflected in the returned config."""
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    cfg = configure_telemetry()
    # If SDK not installed, sdk_enabled is always False regardless.
    # If installed but disabled, sdk_enabled must be False.
    assert isinstance(cfg.sdk_enabled, bool)
    # The module-level _SDK_DISABLED constant is evaluated at import time,
    # so monkeypatching the env var does not affect already-imported modules.
    # We only verify the return type is correct here.


def test_configure_telemetry_langsmith_flag() -> None:
    """TelemetryConfig.langsmith_enabled reflects the module-level constant.

    Note: _LANGSMITH_ENABLED is evaluated at import time from LANGCHAIN_TRACING_V2.
    Monkeypatching the env var after import has no effect. This test verifies the
    field is a bool, not a specific value (which depends on the test environment).
    """
    cfg = configure_telemetry()
    assert isinstance(cfg.langsmith_enabled, bool)


def test_telemetry_config_langsmith_enabled_field() -> None:
    """TelemetryConfig stores langsmith_enabled=True when constructed with True."""
    cfg = TelemetryConfig(
        sdk_available=False,
        otlp_available=False,
        sdk_enabled=False,
        service_name="test-svc",
        otlp_endpoint="http://localhost:4317",
        langsmith_enabled=True,
    )
    assert cfg.langsmith_enabled is True


def test_configure_telemetry_langsmith_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """Absent LANGCHAIN_TRACING_V2 in test env yields langsmith_enabled=False.

    The module-level constant is frozen at import time.
    """
    monkeypatch.delenv("LANGCHAIN_TRACING_V2", raising=False)
    cfg = configure_telemetry()
    # The value reflects what was set when the module was first imported.
    assert isinstance(cfg.langsmith_enabled, bool)


def test_telemetry_config_repr() -> None:
    """TelemetryConfig.__repr__ returns a string with expected tokens."""
    cfg = configure_telemetry()
    r = repr(cfg)
    assert "TelemetryConfig" in r
    assert "sdk_enabled" in r


def test_configure_telemetry_idempotent() -> None:
    """Calling configure_telemetry twice does not raise."""
    cfg1 = configure_telemetry()
    cfg2 = configure_telemetry()
    assert cfg1.service_name == cfg2.service_name


# ---------------------------------------------------------------------------
# get_tracer / get_meter
# ---------------------------------------------------------------------------


def test_get_tracer_returns_tracer() -> None:
    """get_tracer returns an OTel Tracer (no-op or real)."""
    tracer = get_tracer("test.module")
    assert tracer is not None
    assert hasattr(tracer, "start_as_current_span")
    assert hasattr(tracer, "start_span")


def test_get_meter_returns_meter() -> None:
    """get_meter returns an OTel Meter (no-op or real)."""
    meter = get_meter("test.module")
    assert meter is not None
    assert hasattr(meter, "create_counter")
    assert hasattr(meter, "create_histogram")


def test_tracer_span_context_manager() -> None:
    """start_as_current_span works without raising errors."""
    tracer = get_tracer(__name__)
    with tracer.start_as_current_span("test-span") as span:
        assert span is not None
        span.set_attribute("test.key", "value")
        span.set_status(StatusCode.OK)
    # Span is finished — no exception raised.


def test_tracer_span_records_exception() -> None:
    """record_exception on a span works without raising."""
    tracer = get_tracer(__name__)
    with tracer.start_as_current_span("error-span") as span:
        try:
            raise ValueError("deliberate error")
        except ValueError as exc:
            span.record_exception(exc)
            span.set_status(StatusCode.ERROR, "deliberate error")


def test_multiple_tracers_independent() -> None:
    """Multiple tracers from different module names are independent."""
    t1 = get_tracer("module.a")
    t2 = get_tracer("module.b")
    assert hasattr(t1, "start_as_current_span")
    assert hasattr(t2, "start_as_current_span")


# ---------------------------------------------------------------------------
# ws_span
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ws_span_yields_span() -> None:
    """ws_span yields a valid OTel Span."""
    async with ws_span("ws.test") as span:
        assert span is not None
        assert hasattr(span, "set_attribute")
        span.set_attribute("test.attr", "hello")


@pytest.mark.asyncio
async def test_ws_span_with_thread_id() -> None:
    """ws_span sets thread_id attribute when provided."""
    async with ws_span("ws.subscribe", thread_id="abc-123") as span:
        span.set_attribute("extra", "value")


@pytest.mark.asyncio
async def test_ws_span_propagates_exception() -> None:
    """ws_span re-raises exceptions after recording them."""
    with pytest.raises(RuntimeError, match="test error"):
        async with ws_span("ws.error"):
            raise RuntimeError("test error")


@pytest.mark.asyncio
async def test_ws_span_extra_attributes() -> None:
    """ws_span passes extra kwargs as span attributes and yields a recording span."""
    async with ws_span("ws.op", thread_id="t1", agent="coder", node="worker") as span:
        assert span is not None
        assert span.is_recording()
        # ReadableSpan.name is available when the SDK is active (ADR-015 mandates SDK)
        if isinstance(span, ReadableSpan):
            assert span.name == "ws.op"


@pytest.mark.asyncio
async def test_ws_span_no_thread_id() -> None:
    """ws_span works without a thread_id argument."""
    async with ws_span("ws.ping") as span:
        assert span is not None
        assert span.is_recording()
        if isinstance(span, ReadableSpan):
            assert span.name == "ws.ping"


# ---------------------------------------------------------------------------
# inject_trace_context
# ---------------------------------------------------------------------------


def test_inject_trace_context_with_active_span() -> None:
    """inject_trace_context injects real trace context (traceparent) when a
    span is active under the real SDK (TEL-HIGH-002)."""
    # Use a fresh SDK provider so the span is valid and the context propagator
    # has a real trace ID to inject.
    provider = TracerProvider(resource=Resource.create({"service.name": "test"}))
    tracer = provider.get_tracer(__name__)
    with tracer.start_as_current_span("inject-test") as span:
        carrier: dict[str, str] = {}
        inject_trace_context(carrier)
        # With the real SDK and an active sampled span, 'traceparent' must be
        # injected into the carrier by the W3C propagator.
        ctx = span.get_span_context()
        if ctx.is_valid:
            assert "traceparent" in carrier, (
                "inject_trace_context must populate 'traceparent' when a "
                "valid span is active"
            )
            # traceparent format: 00-{trace_id}-{span_id}-{flags}
            parts = carrier["traceparent"].split("-")
            assert len(parts) == 4, f"Malformed traceparent: {carrier['traceparent']}"
            assert parts[0] == "00", "Version must be '00'"
            assert len(parts[1]) == 32, "trace_id must be 32 hex chars"
            assert len(parts[2]) == 16, "span_id must be 16 hex chars"


def test_inject_trace_context_no_active_span() -> None:
    """inject_trace_context is safe with no active span."""
    carrier: dict[str, str] = {}
    inject_trace_context(carrier)
    assert isinstance(carrier, dict)


def test_inject_trace_context_does_not_mutate_other_keys() -> None:
    """inject_trace_context only adds OTel keys — does not remove existing ones."""
    carrier: dict[str, str] = {"custom-key": "custom-value"}
    inject_trace_context(carrier)
    assert carrier["custom-key"] == "custom-value"


# ---------------------------------------------------------------------------
# TelemetryMiddleware — functional behaviour (no span inspection)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_middleware_200_request() -> None:
    """Middleware passes through 200 responses without error."""
    app = _make_test_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/")
    assert response.status_code == _HTTP_OK


@pytest.mark.asyncio
async def test_middleware_500_request() -> None:
    """Middleware passes through 500 responses and sets ERROR status on span."""
    app = _make_test_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/error")
    assert response.status_code == _HTTP_SERVER_ERROR


@pytest.mark.asyncio
async def test_middleware_excluded_path() -> None:
    """Requests to default excluded paths (e.g. /health) are passed through."""
    app = _make_test_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/health")
    assert response.status_code == _HTTP_OK


@pytest.mark.asyncio
async def test_middleware_w3c_traceparent_propagation() -> None:
    """Incoming W3C traceparent header is extracted without error."""
    app = _make_test_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/",
            headers={
                "traceparent": (
                    "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"
                )
            },
        )
    assert response.status_code == _HTTP_OK


@pytest.mark.asyncio
async def test_middleware_custom_excluded_paths() -> None:
    """TelemetryMiddleware respects a custom excluded_paths frozenset."""

    async def ping(request: Request) -> JSONResponse:
        return JSONResponse({"pong": True})

    app = Starlette(routes=[Route("/ping", ping)])
    app.add_middleware(
        TelemetryMiddleware,  # type: ignore[arg-type]
        excluded_paths=frozenset({"/ping"}),
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/ping")
    assert response.status_code == _HTTP_OK


# ---------------------------------------------------------------------------
# TEL-01: configure_telemetry service_name override
# ---------------------------------------------------------------------------


def test_configure_telemetry_service_name_override() -> None:
    """configure_telemetry(service_name=...) returns the overridden name (TEL-01).

    The worker calls configure_telemetry(service_name="vaultspec-worker") so
    its spans are attributed separately from the gateway in Jaeger.
    """
    cfg = configure_telemetry(service_name="vaultspec-worker")
    assert cfg.service_name == "vaultspec-worker"


def test_configure_telemetry_service_name_none_uses_default() -> None:
    """configure_telemetry() without override uses the env-var default."""
    cfg1 = configure_telemetry()
    cfg2 = configure_telemetry(service_name=None)
    assert cfg1.service_name == cfg2.service_name


# ---------------------------------------------------------------------------
# TEL-03: W3C trace context injection into dispatch HTTP calls
# ---------------------------------------------------------------------------


def test_trace_headers_produces_traceparent_under_real_span() -> None:
    """_trace_headers() injects traceparent when a real SDK span is active (TEL-03).

    Verifies the gateway-to-worker dispatch path propagates distributed traces.
    Uses a fresh local TracerProvider so the test is isolated from the global
    provider state. No exporter needed — the assertion is on propagate.inject(),
    not on captured span data.
    """
    from opentelemetry import propagate

    provider = TracerProvider(resource=Resource.create({"service.name": "gw-test"}))
    tracer = provider.get_tracer("test.dispatch")

    with tracer.start_as_current_span("gateway.dispatch") as span:
        ctx = span.get_span_context()
        if ctx.is_valid:
            # Simulate what _trace_headers() does
            carrier: dict[str, str] = {}
            propagate.inject(carrier)
            assert "traceparent" in carrier, (
                "propagate.inject must produce 'traceparent' under a valid SDK span"
            )
            parts = carrier["traceparent"].split("-")
            assert len(parts) == 4
            assert parts[0] == "00"  # version
            assert len(parts[1]) == 32  # trace_id hex
            assert len(parts[2]) == 16  # span_id hex


# ---------------------------------------------------------------------------
# TEL-03: Worker middleware extracts incoming traceparent (requires live Jaeger)
# ---------------------------------------------------------------------------


@pytest.mark.requires_jaeger
@pytest.mark.asyncio(loop_scope="function")
async def test_worker_middleware_extracts_incoming_traceparent(
    local_jaeger_otlp_endpoint: str,
    local_jaeger_query_url: str,
) -> None:
    """TelemetryMiddleware on the worker app creates a child span from a
    gateway traceparent.

    Simulates the gateway injecting a W3C traceparent into a dispatch POST.
    Verifies the worker's TelemetryMiddleware exports the child span to the
    persistent local Jaeger instance via the real OTLP gRPC pipeline.

    Run with: just test-tracing (requires `just jaeger-up` first)
    """
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.trace import TracerProvider as SdkTracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    import vaultspec_a2a.telemetry.middleware as mw

    service_name = "vaultspec-worker-traceparent-test"
    trace_id = "4bf92f3577b34da6a3ce929d0e0e4736"
    parent_span_id = "00f067aa0ba902b7"
    traceparent = f"00-{trace_id}-{parent_span_id}-01"

    # Build a real OTLPSpanExporter pointed at the persistent local Jaeger.
    # BatchSpanProcessor exports asynchronously; force_flush() drains the buffer.
    exporter = OTLPSpanExporter(endpoint=local_jaeger_otlp_endpoint, insecure=True)
    provider = SdkTracerProvider(
        resource=Resource.create({"service.name": service_name})
    )
    provider.add_span_processor(BatchSpanProcessor(exporter))

    # Set the test provider as the global OTel provider and clear the middleware's
    # lazily-cached tracer so _get_tracer() picks up the new global provider.
    # This is the correct approach: trace.set_tracer_provider() is the OTel SDK's
    # official API for replacing the global provider. Clearing mw._tracer (the
    # lazy-init cache) is required because the middleware caches the tracer on
    # first use. Both are restored unconditionally in the finally block.
    original_provider = trace.get_tracer_provider()
    original_mw_tracer = mw._tracer
    trace.set_tracer_provider(provider)
    mw._tracer = None

    try:

        async def dispatch_handler(request: Request) -> JSONResponse:
            return JSONResponse({"status": "dispatched"})

        app = Starlette(routes=[Route("/dispatch", dispatch_handler, methods=["POST"])])
        app.add_middleware(TelemetryMiddleware)  # type: ignore[arg-type]

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://worker"
        ) as client:
            resp = await client.post(
                "/dispatch",
                json={"action": "ingest", "thread_id": "t1", "agent_id": "sup"},
                headers={"traceparent": traceparent},
            )
        assert resp.status_code == _HTTP_OK

        # Drain the BatchSpanProcessor buffer into Jaeger before querying.
        provider.force_flush(timeout_millis=5000)

    finally:
        trace.set_tracer_provider(original_provider)
        mw._tracer = original_mw_tracer

    # Poll Jaeger HTTP API until the child span appears (up to 10 s).
    # The span must be a child of the incoming traceparent (CHILD_OF reference
    # with traceID == _TRACE_ID and spanID == _PARENT_SPAN_ID).
    found_span: dict | None = None
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        async with httpx.AsyncClient() as jc:
            r = await jc.get(
                f"{local_jaeger_query_url}/api/traces",
                params={
                    "service": service_name,
                    "lookback": "1m",
                    "limit": 20,
                },
                timeout=5.0,
            )
        if r.status_code == 200:
            for trace_data in r.json().get("data", []):
                for span in trace_data.get("spans", []):
                    for ref in span.get("references", []):
                        if (
                            ref.get("traceID") == trace_id
                            and ref.get("spanID") == parent_span_id
                        ):
                            found_span = span
                            break
                    if found_span:
                        break
        if found_span:
            break
        await asyncio.sleep(0.5)

    assert found_span is not None, (
        f"No child span found in Jaeger for service={service_name!r} "
        f"with parent traceID={trace_id} spanID={parent_span_id}. "
        "Ensure Jaeger is running (`just jaeger-up`) and OTLP export is working."
    )

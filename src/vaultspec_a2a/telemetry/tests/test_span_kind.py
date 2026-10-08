"""Fix-locking tests for PV33 + Q29: span kind, and the folded aggregator-hook opener.

``operation_span`` used to open every in-process span (worker dispatch, graph
compilation) under ``SpanKind.SERVER``, which is reserved for a real inbound
HTTP request (``TelemetryMiddleware``). ``OTelAggregatorHook.start_span`` also
carried its own, separate span-opening implementation. This module locks both
fixes: the kind change, and the fold of the second opener onto
``open_internal_span`` (the shared core behind both callers).

Uses ``opentelemetry-sdk``'s own ``InMemorySpanExporter``, attached to a real
``TracerProvider`` through the SDK's public ``add_span_processor`` extension
point — the officially supported way to observe what a real tracer records,
not a mock or a fake of any class this repository owns. ``test_telemetry.py``
bans this exporter for attribute-redaction CERTIFICATION, which it routes to
the real OTLP-to-Jaeger round trip in ``service_tests/`` instead; this module
asserts a structural property of span creation (the recorded ``SpanKind``)
that round trip does not assert any more precisely than this does, and the
orchestrator's PV33 brief directs this exact exporter for this exact check.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import pytest
from httpx import ASGITransport, AsyncClient
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from opentelemetry.trace import SpanKind
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from .. import configure_telemetry, operation_span
from ..aggregator_hook import OTelAggregatorHook
from ..middleware import TelemetryMiddleware, open_internal_span

if TYPE_CHECKING:
    from starlette.requests import Request


def _isolated_tracer() -> tuple[InMemorySpanExporter, Any]:
    """A fresh SDK TracerProvider wired to its own in-memory exporter.

    Fully isolated from the process-global OTel registry: nothing here reads
    or writes ``trace.get_tracer_provider()``, so this cannot interact with
    any other test's telemetry state.
    """
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return exporter, provider.get_tracer("pv33.test")


# ---------------------------------------------------------------------------
# open_internal_span: the shared core
# ---------------------------------------------------------------------------


def test_open_internal_span_records_internal_kind_and_attributes() -> None:
    """The shared opener records SpanKind.INTERNAL and every attribute given."""
    exporter, tracer = _isolated_tracer()

    with open_internal_span(tracer, "pv33.shared", {"foo": "bar"}) as span:
        if isinstance(span, ReadableSpan):
            assert span.kind == SpanKind.INTERNAL

    [finished] = exporter.get_finished_spans()
    assert finished.name == "pv33.shared"
    assert finished.kind == SpanKind.INTERNAL
    assert finished.attributes is not None
    assert finished.attributes["foo"] == "bar"


# ---------------------------------------------------------------------------
# operation_span: PV33 kind fix
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_operation_span_uses_internal_kind_not_server() -> None:
    """operation_span now opens SpanKind.INTERNAL, not SERVER (PV33).

    A worker dispatch or a graph compilation is not a server handling an
    inbound request, so SERVER over-claims what the span represents.
    """
    configure_telemetry()
    from opentelemetry import trace as otel_trace

    exporter = InMemorySpanExporter()
    provider = otel_trace.get_tracer_provider()
    assert isinstance(provider, TracerProvider)
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    async with operation_span("pv33.operation_span.kind", thread_id="t1") as span:
        if isinstance(span, ReadableSpan):
            assert span.kind == SpanKind.INTERNAL

    matches = [
        s for s in exporter.get_finished_spans() if s.name == "pv33.operation_span.kind"
    ]
    assert len(matches) == 1
    assert matches[0].kind == SpanKind.INTERNAL


# ---------------------------------------------------------------------------
# TelemetryMiddleware: SERVER kind stays for real inbound HTTP
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_telemetry_middleware_keeps_server_kind_for_real_inbound_http() -> None:
    """A real inbound HTTP request still opens SpanKind.SERVER (PV33 scope).

    PV33 narrows SERVER to real inbound HTTP; TelemetryMiddleware is that
    case and must be unaffected by the operation_span kind change.
    """
    configure_telemetry()
    from opentelemetry import trace as otel_trace

    exporter = InMemorySpanExporter()
    provider = otel_trace.get_tracer_provider()
    assert isinstance(provider, TracerProvider)
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    async def home(request: Request) -> JSONResponse:
        return JSONResponse({"ok": True})

    app = Starlette(routes=[Route("/pv33-http-kind", home)])
    app.add_middleware(cast("Any", TelemetryMiddleware))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/pv33-http-kind")
    assert response.status_code == 200

    matches = [
        s for s in exporter.get_finished_spans() if s.name == "GET /pv33-http-kind"
    ]
    assert len(matches) == 1
    assert matches[0].kind == SpanKind.SERVER


# ---------------------------------------------------------------------------
# OTelAggregatorHook.start_span: Q29 fold onto open_internal_span
# ---------------------------------------------------------------------------


def test_aggregator_hook_start_span_folds_onto_open_internal_span() -> None:
    """OTelAggregatorHook.start_span's own source calls open_internal_span (Q29).

    Not merely a behavioural coincidence: this reads ``start_span``'s own
    compiled code object for a reference to ``open_internal_span`` by name, so
    a second, independent span-opening implementation that happened to yield
    the same kind would still fail this.
    """
    names = OTelAggregatorHook.start_span.__code__.co_names
    assert "open_internal_span" in names


def test_aggregator_hook_start_span_records_internal_kind_and_attributes() -> None:
    """The aggregator hook's spans carry SpanKind.INTERNAL and given attrs."""
    configure_telemetry()
    from opentelemetry import trace as otel_trace

    exporter = InMemorySpanExporter()
    provider = otel_trace.get_tracer_provider()
    assert isinstance(provider, TracerProvider)
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    hook = OTelAggregatorHook("pv33.aggregator.module.attrs")
    with hook.start_span("pv33.aggregator.attrs", role="worker") as span:
        if isinstance(span, ReadableSpan):
            assert span.kind == SpanKind.INTERNAL

    matches = [
        s for s in exporter.get_finished_spans() if s.name == "pv33.aggregator.attrs"
    ]
    assert len(matches) == 1
    assert matches[0].kind == SpanKind.INTERNAL
    assert matches[0].attributes is not None
    assert matches[0].attributes["role"] == "worker"

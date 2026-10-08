"""HTTP request tracing, operation spans and outbound trace propagation.

OpenTelemetry instrumentation from day one. This module provides:

- ``TelemetryMiddleware``: Starlette/FastAPI middleware that starts an OTel span
  for every HTTP request, continues the W3C ``traceparent`` / ``tracestate``
  context the caller sent, and records the request method, route and response
  status.

- ``operation_span``: Async context manager that opens a span around one named
  operation the request span does not delimit, such as a worker dispatch or a
  graph compilation.

- ``trace_headers``: Returns the current trace context as W3C headers for an
  outbound HTTP call, so the receiving process continues the same trace.

HTTP URL attributes mask user information and omit query strings and
fragments. Request headers and bodies are not recorded. Paths and
caller-supplied operation attributes remain diagnostic data.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager, contextmanager
from typing import TYPE_CHECKING, Any, override

from opentelemetry import context as otel_context
from opentelemetry import propagate, trace
from opentelemetry.trace import SpanKind, StatusCode
from starlette.middleware.base import BaseHTTPMiddleware

from ..utils import redact_url
from .instrumentation import get_tracer, telemetry_settings

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Awaitable, Callable, Generator, Mapping

    from starlette.requests import Request
    from starlette.responses import Response
    from starlette.types import ASGIApp

__all__ = [
    "TelemetryMiddleware",
    "open_internal_span",
    "operation_span",
    "trace_headers",
]

logger = logging.getLogger(__name__)

# _tracer is initialised lazily on first use via _get_tracer() to
# ensure it is created after configure_telemetry() has run and the real
# TracerProvider is installed.  A module-level tracer would bind to the
# no-op provider if this module is imported before configure_telemetry().
_tracer: trace.Tracer | None = None


def _get_tracer() -> trace.Tracer:
    """Return the module tracer, creating it lazily on first call."""
    global _tracer
    if _tracer is None:
        _tracer = get_tracer(__name__)
    return _tracer


# Paths that generate too much noise if traced at span level.
_EXCLUDED_PATHS: frozenset[str] = frozenset(
    {
        "/health",
        "/healthz",
        "/ready",
        "/metrics",
    }
)

_HTTP_SERVER_ERROR = 500


class TelemetryMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that instruments every HTTP request with an OTel span.

    Propagates W3C TraceContext (``traceparent`` / ``tracestate``) from
    incoming request headers so that distributed traces from upstream CLIs or
    the dashboard are correctly linked.

    Recorded span attributes (OTel Semantic Conventions v1.23+):
        http.request.method: GET, POST, etc.
        http.route: Full request path.
        url.full: Request URL with user information masked, and no query or
            fragment.
        http.response.status_code: Response status code.
        server.address: Server hostname.

    Args:
        app: The ASGI application to wrap.
        excluded_paths: Set of paths to skip tracing for (health probes, etc.).
    """

    def __init__(
        self,
        app: ASGIApp,
        excluded_paths: frozenset[str] | None = None,
    ) -> None:
        """Initialise middleware with optional path exclusion set."""
        super().__init__(app)
        self._excluded: frozenset[str] = (
            excluded_paths if excluded_paths is not None else _EXCLUDED_PATHS
        )

    @override
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Process an HTTP request, wrapping it in an OTel span.

        Args:
            request: The incoming Starlette request.
            call_next: The next middleware / endpoint handler.

        Returns:
            The response from the downstream handler.
        """
        if request.url.path in self._excluded:
            return await call_next(request)

        # Extract W3C trace context from incoming headers.
        carrier: dict[str, str] = dict(request.headers)
        ctx = propagate.extract(carrier)
        token = otel_context.attach(ctx)

        span_name = f"{request.method} {request.url.path}"

        try:
            with _get_tracer().start_as_current_span(
                span_name,
                kind=SpanKind.SERVER,
                context=ctx,
            ) as span:
                # use OTel semantic conventions v1.23+ attribute names.
                span.set_attribute("http.request.method", request.method)
                span.set_attribute(
                    "url.full",
                    redact_url(str(request.url.replace(query="", fragment=""))),
                )
                span.set_attribute("http.route", request.url.path)
                span.set_attribute("server.address", request.url.hostname or "")
                if request.url.port:
                    span.set_attribute("server.port", request.url.port)

                response = await call_next(request)

                span.set_attribute("http.response.status_code", response.status_code)
                if response.status_code >= _HTTP_SERVER_ERROR:
                    span.set_status(StatusCode.ERROR, f"HTTP {response.status_code}")
                else:
                    span.set_status(StatusCode.OK)

                return response
        finally:
            otel_context.detach(token)


@contextmanager
def open_internal_span(
    tracer: trace.Tracer,
    name: str,
    attributes: Mapping[str, Any],
) -> Generator[trace.Span]:
    """Open ``name`` on ``tracer`` as an ``INTERNAL`` span and set ``attributes``.

    The one span-opening body behind every in-process operation span this
    process creates. ``INTERNAL`` is the correct kind for both callers: a
    worker dispatch or graph compilation is work this process does to itself,
    not a server handling an inbound request, and the streaming aggregator's
    per-event spans were never inbound requests either (``SpanKind.SERVER``
    is reserved for ``TelemetryMiddleware``, which spans a real inbound HTTP
    request).

    :func:`operation_span` wraps this in an async context manager for the
    worker and gateway's in-process operations;
    ``OTelAggregatorHook.start_span`` (``telemetry/aggregator_hook.py``) calls
    it directly, keeping its own tracer scope (``vaultspec_a2a.streaming.aggregator``,
    DECISIONS Q48) while sharing this opening logic (Q29) so the kind and the
    attribute-setting loop cannot drift between the two callers.

    Args:
        tracer: The tracer to open the span on.
        name: Span name.
        attributes: String span attributes to set before yielding.

    Yields:
        The active OTel ``Span``.
    """
    with tracer.start_as_current_span(name, kind=SpanKind.INTERNAL) as span:
        for key, value in attributes.items():
            span.set_attribute(key, value)
        yield span


@asynccontextmanager
async def operation_span(
    operation: str,
    thread_id: str | None = None,
    **attributes: str,
) -> AsyncGenerator[trace.Span]:
    """Open a span around one named operation of this process.

    ``TelemetryMiddleware`` spans each inbound HTTP request, but much of the
    work a request starts outlives it or runs where no request is in scope: a
    worker's dispatch, ingest, resume and graph compilation. Each gets its own
    span from this helper, opened ``INTERNAL`` rather than ``SERVER`` because
    none of it is a server handling an inbound request. An exception leaving
    the block is recorded on the span and marks it as an error before it
    propagates.

    Args:
        operation: Span name (e.g. ``"executor.ingest"``).
        thread_id: Optional LangGraph thread_id to attach as a span attribute.
        **attributes: Additional string span attributes.

    Yields:
        The active OTel ``Span`` for this operation.

    Example:
        ```python
        from vaultspec_a2a.telemetry import operation_span

        async with operation_span("executor.ingest", thread_id=tid) as span:
            span.set_attribute("is_first_ingest", first)
            await run_turn()
        ```
    """
    # when the OTel SDK is explicitly disabled, skip real span creation
    # and yield a no-op span to avoid unnecessary overhead.
    if telemetry_settings().sdk_disabled:
        yield trace.NonRecordingSpan(trace.INVALID_SPAN_CONTEXT)
        return

    span_attributes: dict[str, Any] = dict(attributes)
    if thread_id is not None:
        span_attributes["thread_id"] = thread_id
    with open_internal_span(_get_tracer(), operation, span_attributes) as span:
        yield span


def trace_headers() -> dict[str, str]:
    """Return the current trace context as headers for an outbound HTTP call.

    Injects the active span's W3C ``traceparent`` / ``tracestate`` into a fresh
    carrier so the process receiving the call continues this trace. The carrier
    is empty when no span is active, and is a new dict on every call, so a
    caller may add its own headers to it.

    Example:
        ```python
        from vaultspec_a2a.telemetry import trace_headers

        response = await client.post("/dispatch", json=body, headers=trace_headers())
        ```
    """
    carrier: dict[str, str] = {}
    propagate.inject(carrier)
    return carrier

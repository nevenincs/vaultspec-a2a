"""FastAPI and WebSocket trace context injection middleware.

ADR-010: OpenTelemetry instrumentation from day one. This module provides:

- ``TelemetryMiddleware``: Starlette/FastAPI middleware that starts an OTel span
  for every HTTP request, propagates W3C ``traceparent`` / ``tracestate`` headers,
  and records ``http.method``, ``http.route``, ``http.status_code`` attributes.

- ``ws_span``: Async context manager that opens a span for a WebSocket operation.
  HTTP header propagation does not apply to sustained WS frames, so each distinct
  WS operation (subscribe, message, permission) is instrumented via manually
  started child spans using this helper.

- ``inject_trace_context``: Injects the current trace context into a dict (e.g.
  a WebSocket JSON frame) so downstream consumers can reconstruct the trace.
  Per ADR-010 §5: context propagation over WebSockets requires manual injection.

Credential safety (ADR-002): no secrets are read, logged, or emitted as span
attributes by this module.
"""

from __future__ import annotations

import logging

from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from typing import Any

from opentelemetry import context as otel_context
from opentelemetry import propagate, trace
from opentelemetry.trace import SpanKind, StatusCode
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from .instrumentation import _SDK_DISABLED, get_tracer


__all__ = [
    "TelemetryMiddleware",
    "inject_trace_context",
    "ws_span",
]

logger = logging.getLogger(__name__)

# TEL-H5: _tracer is initialised lazily on first use via _get_tracer() to
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
    the React frontend are correctly linked.

    Recorded span attributes (OTel Semantic Conventions v1.23+):
        http.request.method: GET, POST, etc.
        http.route: Full request path.
        url.full: Full request URL.
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

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
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
                # H22: use OTel semantic conventions v1.23+ attribute names.
                span.set_attribute("http.request.method", request.method)
                span.set_attribute("url.full", str(request.url))
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
        except Exception as exc:
            # M33: use `span` directly — get_current_span() is redundant here
            span.set_status(StatusCode.ERROR, str(exc))
            span.record_exception(exc)
            raise
        finally:
            otel_context.detach(token)


@asynccontextmanager
async def ws_span(
    operation: str,
    thread_id: str | None = None,
    **attributes: str,
) -> AsyncGenerator[trace.Span]:
    """Async context manager that opens a child span for a WebSocket operation.

    HTTP header propagation does not flow through individual WebSocket frames,
    so distinct WS operations (subscribe, unsubscribe, send_message, permission
    response) each get their own span via this helper.

    Args:
        operation: Human-readable operation name (e.g. ``"ws.subscribe"``).
        thread_id: Optional LangGraph thread_id to attach as a span attribute.
        **attributes: Additional string span attributes.

    Yields:
        The active OTel ``Span`` for this operation.

    Example:
        ```python
        from lib.telemetry import ws_span

        async with ws_span("ws.subscribe", thread_id=tid) as span:
            span.set_attribute("client_id", client_id)
            aggregator.subscribe(tid, send_fn)
        ```
    """
    # TEL-M1: when the OTel SDK is explicitly disabled, skip real span creation
    # and yield a no-op span to avoid unnecessary overhead.
    if _SDK_DISABLED:
        yield trace.NonRecordingSpan(trace.INVALID_SPAN_CONTEXT)
        return

    with _get_tracer().start_as_current_span(
        operation,
        kind=SpanKind.SERVER,
    ) as span:
        if thread_id is not None:
            span.set_attribute("thread_id", thread_id)
        for key, value in attributes.items():
            span.set_attribute(key, value)
        try:
            yield span
        except Exception as exc:
            span.set_status(StatusCode.ERROR, str(exc))
            span.record_exception(exc)
            raise


def inject_trace_context(carrier: dict[str, Any]) -> None:
    """Inject the current W3C trace context into a mutable dict.

    Use this to embed trace context into outgoing WebSocket JSON frames so
    that downstream consumers (frontend, external services) can continue the
    trace. The injected keys follow the W3C TraceContext format
    (``traceparent``, ``tracestate``).

    Per ADR-010 §5: "Injecting OTel Trace IDs into WebSocket frames requires
    careful manual context propagation."

    Args:
        carrier: The mutable dict to inject into (e.g. a WS event payload's
            ``_trace`` sub-dict).

    Example:
        ```python
        from lib.telemetry import inject_trace_context

        payload: dict[str, Any] = {"type": "message_chunk", "content": chunk}
        trace_meta: dict[str, str] = {}
        inject_trace_context(trace_meta)
        if trace_meta:
            payload["_trace"] = trace_meta
        await ws.send_json(payload)
        ```
    """
    propagate.inject(carrier)

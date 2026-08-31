"""Shared utilities for the API layer.

Consolidates helpers that were duplicated across ``endpoints.py`` and
``app.py`` (R-02 deduplication).
"""

from opentelemetry import propagate as _otel_propagate

__all__ = [
    "trace_headers",
]


def trace_headers() -> dict[str, str]:
    """Build W3C trace context headers for gateway-to-worker HTTP calls.

    Injects the current OTel span context (``traceparent`` / ``tracestate``)
    into a headers dict so distributed traces continue from gateway to worker.
    Returns an empty dict when no active span is present (no-op mode).
    """
    carrier: dict[str, str] = {}
    _otel_propagate.inject(carrier)
    return carrier

"""Shared utilities for the API layer.

Consolidates helpers that were duplicated across ``endpoints.py`` and
``app.py`` (R-02 deduplication).
"""

import time

from fastapi import Request
from opentelemetry import propagate as _otel_propagate

__all__ = [
    "mark_worker_connected",
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


def mark_worker_connected(request: Request) -> None:
    """Update the gateway heartbeat timestamp after a confirmed worker dispatch.

    Sets ``worker_last_heartbeat_ts`` to the current monotonic clock value so
    that the ``/health`` endpoint reports ``worker_connected: true`` immediately
    after the first successful dispatch rather than waiting for the worker's
    next periodic heartbeat.

    The value written here is identical in shape to the timestamp written by
    ``POST /internal/heartbeat``, so existing liveness logic is reused without
    any new state fields.
    """
    request.app.state.worker_last_heartbeat_ts = time.monotonic()

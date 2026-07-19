"""Expose tracing and metrics integration.

Public configuration controls OpenTelemetry and LangSmith integration. Tracer
and meter accessors support instrumentation without duplicating provider setup.

:mod:`vaultspec_a2a.telemetry.middleware` instruments
:mod:`vaultspec_a2a.api` and provides trace injection across outbound
inter-process communication (IPC) and WebSocket boundaries.
:mod:`vaultspec_a2a.telemetry.instrumentation` configures tracing and metrics
providers.

Import this package for telemetry configuration, middleware, accessors, and
trace propagation. It doesn't own application startup.
"""

from .instrumentation import (
    TelemetryConfig as TelemetryConfig,
)
from .instrumentation import (
    configure_telemetry as configure_telemetry,
)
from .instrumentation import (
    get_meter as get_meter,
)
from .instrumentation import (
    get_tracer as get_tracer,
)
from .middleware import (
    TelemetryMiddleware as TelemetryMiddleware,
)
from .middleware import (
    inject_trace_context as inject_trace_context,
)
from .middleware import (
    ws_span as ws_span,
)

__all__ = [
    "TelemetryConfig",
    "TelemetryMiddleware",
    "configure_telemetry",
    "get_meter",
    "get_tracer",
    "inject_trace_context",
    "ws_span",
]

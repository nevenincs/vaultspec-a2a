"""Expose tracing and metrics integration.

Public configuration controls OpenTelemetry and LangSmith integration. Tracer
and meter accessors support instrumentation without duplicating provider setup.

:mod:`vaultspec_a2a.telemetry.middleware` instruments the gateway and worker
HTTP applications, spans named operations, and supplies the trace headers that
outbound inter-process communication (IPC) carries.
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
    operation_span as operation_span,
)
from .middleware import (
    trace_headers as trace_headers,
)

__all__ = [
    "TelemetryConfig",
    "TelemetryMiddleware",
    "configure_telemetry",
    "get_meter",
    "get_tracer",
    "operation_span",
    "trace_headers",
]

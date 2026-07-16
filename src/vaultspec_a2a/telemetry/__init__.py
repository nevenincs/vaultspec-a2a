"""Telemetry sub-module: OpenTelemetry + LangSmith instrumentation.

Facade exposing the public telemetry API. Consumers should import from here
rather than from sub-modules directly (facade pattern).

Usage:
    ```python
    from vaultspec_a2a.telemetry import configure_telemetry, get_tracer, ws_span

    # Once at FastAPI lifespan startup:
    cfg = configure_telemetry()

    # In any module:
    _tracer = get_tracer(__name__)
    with _tracer.start_as_current_span("my-operation"):
        ...

    # In WebSocket handlers:
    async with ws_span("ws.subscribe", thread_id=tid):
        ...
    ```
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

"""OpenTelemetry TracerProvider and MeterProvider setup for the orchestrator.

ADR-010 mandates OTel from day one. This module configures the global
TracerProvider and MeterProvider with OTLP export when the optional
``opentelemetry-sdk`` and ``opentelemetry-exporter-otlp-proto-grpc``
packages are installed. Without those packages the opentelemetry-api
no-op implementation is used, so all instrumented code remains functional
with zero overhead.

LangSmith tracing is configured separately via environment variables
(``LANGCHAIN_TRACING_V2`` / ``LANGCHAIN_API_KEY``) and does not require
any code here — LangChain reads those variables automatically on import.

Credential safety (ADR-002): this module never reads, logs, or forwards
``CLAUDE_CODE_OAUTH_TOKEN``, ``ANTHROPIC_API_KEY``, or any other secret.
The only env vars consumed are the standard OTel and LangSmith vars listed
below.

Environment variables consumed:
    OTEL_SERVICE_NAME: Service name emitted in every span (default: vaultspec-a2a).
    OTEL_SERVICE_VERSION: Version string (default: 0.1.0).
    OTEL_EXPORTER_OTLP_ENDPOINT: gRPC endpoint (default: http://localhost:4317).
    OTEL_EXPORTER_OTLP_INSECURE: Set to "true" to disable TLS (default: true).
    OTEL_SDK_DISABLED: Set to "true" to force no-op mode.
    OTEL_EXPORTER_CONSOLE: Set to "true" to log spans to stdout (dev only).
    LANGCHAIN_TRACING_V2: Set to "true" to enable LangSmith tracing.
    LANGCHAIN_API_KEY: LangSmith API key (read by LangChain — never logged here).
    LANGCHAIN_PROJECT: LangSmith project name.
"""

from __future__ import annotations

import logging
import os

from opentelemetry import metrics, trace


__all__ = [
    "TelemetryConfig",
    "configure_telemetry",
    "get_meter",
    "get_tracer",
]

logger = logging.getLogger(__name__)

_SERVICE_NAME = os.environ.get("OTEL_SERVICE_NAME", "vaultspec-a2a")
_SERVICE_VERSION = os.environ.get("OTEL_SERVICE_VERSION", "0.1.0")
_OTLP_ENDPOINT = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
_SDK_DISABLED = os.environ.get("OTEL_SDK_DISABLED", "").lower() in (
    "1",
    "true",
    "yes",
)
_INSECURE = os.environ.get("OTEL_EXPORTER_OTLP_INSECURE", "true").lower() in (
    "1",
    "true",
    "yes",
)
_CONSOLE_EXPORT = os.environ.get("OTEL_EXPORTER_CONSOLE", "").lower() in (
    "1",
    "true",
    "yes",
)
_LANGSMITH_ENABLED = os.environ.get("LANGCHAIN_TRACING_V2", "").lower() in (
    "1",
    "true",
    "yes",
)
_LANGSMITH_PROJECT = os.environ.get("LANGCHAIN_PROJECT", "default")


class TelemetryConfig:
    """Runtime snapshot of the active telemetry configuration.

    Attributes:
        sdk_available: True when opentelemetry-sdk is installed.
        otlp_available: True when the OTLP gRPC exporter is installed.
        sdk_enabled: True when SDK is installed and OTEL_SDK_DISABLED is not set.
        service_name: The OTel service name in use.
        otlp_endpoint: The configured OTLP endpoint.
        langsmith_enabled: True when LANGCHAIN_TRACING_V2=true is set.
    """

    def __init__(  # noqa: PLR0913
        self,
        *,
        sdk_available: bool,
        otlp_available: bool,
        sdk_enabled: bool,
        service_name: str,
        otlp_endpoint: str,
        langsmith_enabled: bool,
    ) -> None:
        """Initialise immutable telemetry config snapshot."""
        self.sdk_available = sdk_available
        self.otlp_available = otlp_available
        self.sdk_enabled = sdk_enabled
        self.service_name = service_name
        self.otlp_endpoint = otlp_endpoint
        self.langsmith_enabled = langsmith_enabled

    def __repr__(self) -> str:
        """Return developer-friendly representation."""
        return (
            f"TelemetryConfig("
            f"sdk_enabled={self.sdk_enabled}, "
            f"otlp_available={self.otlp_available}, "
            f"service={self.service_name!r}, "
            f"langsmith={self.langsmith_enabled})"
        )


def _check_sdk() -> bool:
    """Return True if opentelemetry-sdk is importable."""
    try:
        import opentelemetry.sdk.trace  # noqa: F401, PLC0415  # type: ignore[unresolved-import]
    except ImportError:
        return False
    return True


def _check_otlp() -> bool:
    """Return True if the OTLP gRPC exporter is importable."""
    try:
        import opentelemetry.exporter.otlp.proto.grpc.trace_exporter  # noqa: F401, PLC0415  # type: ignore[unresolved-import]
    except ImportError:
        return False
    return True


def _build_sdk_provider(*, otlp_available: bool) -> trace.TracerProvider:
    """Construct a real SDK TracerProvider with resource and optional OTLP export.

    Args:
        otlp_available: Whether the OTLP gRPC exporter package is installed.

    Returns:
        A configured SDK ``TracerProvider``.
    """
    from opentelemetry.sdk.resources import (  # noqa: PLC0415  # type: ignore[unresolved-import]
        Resource,
    )
    from opentelemetry.sdk.trace import (  # noqa: PLC0415  # type: ignore[unresolved-import]
        TracerProvider as SdkTracerProvider,
    )
    from opentelemetry.sdk.trace.export import (  # noqa: PLC0415  # type: ignore[unresolved-import]
        BatchSpanProcessor,
        ConsoleSpanExporter,
    )

    resource = Resource.create(
        {
            "service.name": _SERVICE_NAME,
            "service.version": _SERVICE_VERSION,
        }
    )
    provider = SdkTracerProvider(resource=resource)

    if otlp_available:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (  # noqa: PLC0415  # type: ignore[unresolved-import]
            OTLPSpanExporter,
        )

        exporter = OTLPSpanExporter(endpoint=_OTLP_ENDPOINT, insecure=_INSECURE)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        logger.info(
            "OTel OTLP exporter configured endpoint=%s",
            _OTLP_ENDPOINT,
        )
    elif _CONSOLE_EXPORT:
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
        logger.debug("OTel console exporter active (no OTLP package found)")

    return provider


def _build_sdk_meter_provider(*, otlp_available: bool) -> None:
    """Configure the global MeterProvider when SDK is available.

    Args:
        otlp_available: Whether the OTLP gRPC metric exporter is installed.
    """
    try:
        from opentelemetry.sdk.metrics import (  # noqa: PLC0415  # type: ignore[unresolved-import]
            MeterProvider,
        )
        from opentelemetry.sdk.metrics.export import (  # noqa: PLC0415  # type: ignore[unresolved-import]
            PeriodicExportingMetricReader,
        )
        from opentelemetry.sdk.resources import (  # noqa: PLC0415  # type: ignore[unresolved-import]
            Resource,
        )
    except ImportError:
        return

    resource = Resource.create(
        {
            "service.name": _SERVICE_NAME,
            "service.version": _SERVICE_VERSION,
        }
    )
    readers = []

    if otlp_available:
        try:
            from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (  # noqa: PLC0415  # type: ignore[unresolved-import]
                OTLPMetricExporter,
            )

            exporter = OTLPMetricExporter(endpoint=_OTLP_ENDPOINT, insecure=_INSECURE)
            readers.append(PeriodicExportingMetricReader(exporter))
        except ImportError:
            pass

    meter_provider = MeterProvider(resource=resource, metric_readers=readers)
    metrics.set_meter_provider(meter_provider)


def configure_telemetry() -> TelemetryConfig:
    """Set up the global OTel TracerProvider and MeterProvider.

    This function is idempotent — calling it multiple times is safe because
    ``set_tracer_provider`` is a no-op if a non-proxy provider is already set.
    Call once during FastAPI lifespan startup (ADR-007).

    Returns:
        A ``TelemetryConfig`` snapshot describing what was configured.

    Example:
        ```python
        # In FastAPI lifespan:
        from lib.telemetry import configure_telemetry


        @asynccontextmanager
        async def lifespan(app: FastAPI):
            cfg = configure_telemetry()
            logger.info("Telemetry ready: %r", cfg)
            yield
        ```
    """
    sdk_available = _check_sdk()
    otlp_available = _check_otlp() if sdk_available else False
    sdk_enabled = sdk_available and not _SDK_DISABLED

    if sdk_enabled:
        provider = _build_sdk_provider(otlp_available=otlp_available)
        trace.set_tracer_provider(provider)
        _build_sdk_meter_provider(otlp_available=otlp_available)
        logger.info(
            "OTel SDK TracerProvider configured service=%s otlp=%s langsmith=%s",
            _SERVICE_NAME,
            otlp_available,
            _LANGSMITH_ENABLED,
        )
    elif _SDK_DISABLED:
        logger.info("OTel SDK explicitly disabled via OTEL_SDK_DISABLED")
    else:
        logger.info(
            "opentelemetry-sdk not installed — using no-op tracer. "
            "Install 'opentelemetry-sdk' to enable real tracing."
        )

    if _LANGSMITH_ENABLED:
        logger.info(
            "LangSmith tracing enabled via LANGCHAIN_TRACING_V2 project=%r",
            _LANGSMITH_PROJECT,
        )

    return TelemetryConfig(
        sdk_available=sdk_available,
        otlp_available=otlp_available,
        sdk_enabled=sdk_enabled,
        service_name=_SERVICE_NAME,
        otlp_endpoint=_OTLP_ENDPOINT,
        langsmith_enabled=_LANGSMITH_ENABLED,
    )


def get_tracer(name: str) -> trace.Tracer:
    """Return a named tracer from the global provider.

    Works with both the real SDK provider (when configured) and the
    opentelemetry-api no-op provider (when SDK is absent).

    Args:
        name: Tracer name — use ``__name__`` of the calling module.

    Returns:
        An OTel ``Tracer`` instance.

    Example:
        ```python
        from lib.telemetry import get_tracer

        _tracer = get_tracer(__name__)


        async def some_operation() -> None:
            with _tracer.start_as_current_span("operation-name") as span:
                span.set_attribute("key", "value")
        ```
    """
    return trace.get_tracer(name, _SERVICE_VERSION)


def get_meter(name: str) -> metrics.Meter:
    """Return a named meter from the global provider.

    Args:
        name: Meter name — use ``__name__`` of the calling module.

    Returns:
        An OTel ``Meter`` instance.
    """
    return metrics.get_meter(name, _SERVICE_VERSION)

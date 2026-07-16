"""OpenTelemetry TracerProvider and MeterProvider setup for the orchestrator.

OTel is enabled from day one. This module configures the global
TracerProvider and MeterProvider with OTLP export when the optional
``opentelemetry-sdk`` and ``opentelemetry-exporter-otlp-proto-grpc``
packages are installed. Without those packages the opentelemetry-api
no-op implementation is used, so all instrumented code remains functional
with zero overhead.

LangSmith tracing is configured separately via environment variables
(``LANGSMITH_TRACING`` / ``LANGSMITH_API_KEY``) and does not require
any code here — LangChain reads those variables automatically on import.

Credential safety: this module never reads, logs, or forwards
``CLAUDE_CODE_OAUTH_TOKEN``, ``ANTHROPIC_API_KEY``, or any other secret.
The only env vars consumed are the standard OTel and LangSmith vars listed
below.

Environment variables consumed (all read at import time):
    OTEL_SERVICE_NAME: Service name emitted in every span (default: vaultspec-a2a).
    OTEL_SERVICE_VERSION: Version string (default: 0.1.0).
    OTEL_EXPORTER_OTLP_ENDPOINT: gRPC endpoint (default: http://localhost:4317).
    OTEL_EXPORTER_OTLP_INSECURE: Set to "true" to disable TLS (default: true).
    OTEL_SDK_DISABLED: Set to "true" to force no-op mode.
    OTEL_EXPORTER_CONSOLE: Set to "true" to log spans to stdout (dev only).
    LANGSMITH_TRACING: Set to "true" to enable LangSmith tracing.
    LANGSMITH_PROJECT: LangSmith project name.
"""

from __future__ import annotations

import dataclasses
import importlib.util
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

# These module-level env var reads are intentional.  OTel SDK
# configuration must be determined at import time so that ``get_tracer`` and
# ``get_meter`` callers at module scope (e.g. the aggregator) receive a correctly
# configured provider.  Changing telemetry config at runtime is explicitly out of
# scope for this service — operators restart the process to pick up new settings.
#
# _SDK_DISABLED (and other constants below) are evaluated once at import
# time.  Tests that need to vary this behaviour must use subprocess isolation
# (e.g. ``subprocess.run([sys.executable, ...])`` with a custom env dict) rather
# than monkeypatching the env var after import — the constant will not re-evaluate.
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
_LANGSMITH_ENABLED = os.environ.get("LANGSMITH_TRACING", "").lower() in (
    "1",
    "true",
    "yes",
)
_LANGSMITH_PROJECT = os.environ.get("LANGSMITH_PROJECT", "default")


@dataclasses.dataclass(frozen=True)
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

    sdk_available: bool
    otlp_available: bool
    sdk_enabled: bool
    service_name: str
    otlp_endpoint: str
    langsmith_enabled: bool

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
    """Return True — opentelemetry-sdk is a mandatory dependency."""
    return importlib.util.find_spec("opentelemetry.sdk.trace") is not None


def _check_otlp() -> bool:
    """Return True if the OTLP gRPC exporter is importable.

    The OTLP exporter is optional (operators may not run a collector),
    so we retain the availability check here only for the exporter package.
    """
    return (
        importlib.util.find_spec(
            "opentelemetry.exporter.otlp.proto.grpc.trace_exporter"
        )
        is not None
    )


def _build_sdk_provider(
    *, otlp_available: bool, service_name: str | None = None
) -> trace.TracerProvider:
    """Construct a real SDK TracerProvider with resource and optional OTLP export.

    Args:
        otlp_available: Whether the OTLP gRPC exporter package is installed.
        service_name: Override ``service.name`` in the OTel Resource. Defaults
            to ``_SERVICE_NAME`` (resolved from ``OTEL_SERVICE_NAME`` env var).

    Returns:
        A configured SDK ``TracerProvider``.
    """
    from opentelemetry.sdk.resources import (
        Resource,
    )
    from opentelemetry.sdk.trace import (
        TracerProvider as SdkTracerProvider,
    )
    from opentelemetry.sdk.trace.export import (
        BatchSpanProcessor,
        ConsoleSpanExporter,
    )

    resource = Resource.create(
        {
            "service.name": service_name or _SERVICE_NAME,
            "service.version": _SERVICE_VERSION,
        }
    )
    provider = SdkTracerProvider(resource=resource)

    if otlp_available:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
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


def _build_sdk_meter_provider(
    *, otlp_available: bool, service_name: str | None = None
) -> None:
    """Configure the global MeterProvider when SDK is available.

    opentelemetry-sdk is a mandatory dependency — no ImportError guard.

    Args:
        otlp_available: Whether the OTLP gRPC metric exporter is installed.
        service_name: Override ``service.name`` in the OTel Resource. Defaults
            to ``_SERVICE_NAME`` (resolved from ``OTEL_SERVICE_NAME`` env var).
    """
    from opentelemetry.sdk.metrics import (
        MeterProvider,
    )
    from opentelemetry.sdk.metrics.export import (
        PeriodicExportingMetricReader,
    )
    from opentelemetry.sdk.resources import (
        Resource,
    )

    resource = Resource.create(
        {
            "service.name": service_name or _SERVICE_NAME,
            "service.version": _SERVICE_VERSION,
        }
    )
    readers = []

    if otlp_available:
        from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
            OTLPMetricExporter,
        )

        exporter = OTLPMetricExporter(endpoint=_OTLP_ENDPOINT, insecure=_INSECURE)
        readers.append(PeriodicExportingMetricReader(exporter))

    meter_provider = MeterProvider(resource=resource, metric_readers=readers)
    metrics.set_meter_provider(meter_provider)


def configure_telemetry(*, service_name: str | None = None) -> TelemetryConfig:
    """Set up the global OTel TracerProvider and MeterProvider.

    This function is idempotent — calling it multiple times is safe because
    ``set_tracer_provider`` is a no-op if a non-proxy provider is already set.
    Call once during FastAPI lifespan startup.

    Args:
        service_name: Override the OTel ``service.name`` resource attribute.
            Useful when multiple services share the same codebase (e.g. the
            worker calls ``configure_telemetry(service_name="vaultspec-worker")``
            so its spans are attributed separately from the gateway in Jaeger).
            Defaults to the ``OTEL_SERVICE_NAME`` env var (or ``"vaultspec-a2a"``).

    Returns:
        A ``TelemetryConfig`` snapshot describing what was configured.

    Example:
        ```python
        # In FastAPI lifespan:
        from vaultspec_a2a.telemetry import configure_telemetry


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

    effective_service = service_name or _SERVICE_NAME

    if sdk_enabled:
        provider = _build_sdk_provider(
            otlp_available=otlp_available, service_name=effective_service
        )
        trace.set_tracer_provider(provider)
        _build_sdk_meter_provider(
            otlp_available=otlp_available, service_name=effective_service
        )
        logger.info(
            "OTel SDK TracerProvider configured service=%s otlp=%s langsmith=%s",
            effective_service,
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

    # opentelemetry-instrumentation-fastapi is declared as a dependency
    # but FastAPIInstrumentor().instrument() is intentionally NOT called here.
    # Auto-instrumentation via FastAPIInstrumentor conflicts with our custom
    # TelemetryMiddleware which already instruments every HTTP request with
    # W3C traceparent propagation and semantic convention v1.23+ attributes.
    # Using both would create duplicate spans for every request.

    return TelemetryConfig(
        sdk_available=sdk_available,
        otlp_available=otlp_available,
        sdk_enabled=sdk_enabled,
        service_name=effective_service,
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
        from vaultspec_a2a.telemetry import get_tracer

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

"""OpenTelemetry TracerProvider and MeterProvider setup for the orchestrator.

OTel is enabled from day one. This module configures the global
TracerProvider and MeterProvider with OTLP export when the optional
``opentelemetry-sdk`` and ``opentelemetry-exporter-otlp-proto-grpc``
packages are installed. Without those packages the opentelemetry-api
no-op implementation is used, so all instrumented code remains functional
with zero overhead.

LangSmith tracing is not configured here and is not a project setting. Its sole
consumer is the ``langsmith`` SDK, which resolves its own ``LANGSMITH_*`` /
``LANGCHAIN_*`` names out of ``os.environ``. This module only *reports* what that
SDK decided, and it obtains that answer by asking the SDK rather than by
re-deriving it — a second derivation is free to disagree, and did: the SDK accepts
exactly ``"true"`` across four env names, where an open-coded truthiness check
accepted ``1``/``yes`` and saw only one name.

Credential safety: this module never reads, logs, or forwards
``CLAUDE_CODE_OAUTH_TOKEN`` or any other secret. Its configuration is the
``otel_*`` settings, each read under a ``VAULTSPEC_A2A_OTEL_*`` name that wins
over the standard OTel name listed below (all read once, at import time):
    OTEL_SERVICE_NAME: Service name emitted in every span (default: vaultspec-a2a).
    OTEL_SERVICE_VERSION: Version string (default: the installed package version).
    OTEL_EXPORTER_OTLP_ENDPOINT: gRPC endpoint (default: http://localhost:4317).
    OTEL_EXPORTER_OTLP_INSECURE: Set to "true" to disable TLS (default: true).
    OTEL_SDK_DISABLED: Set to "true" to force no-op mode.
    OTEL_TRACES_EXPORTER: Set to "none" to build no span exporter at all.
    OTEL_METRICS_EXPORTER: Set to "none" to build no metric reader at all.
    OTEL_EXPORTER_CONSOLE: Set to "true" to log spans to stdout (dev only).

``OTEL_TRACES_EXPORTER``/``OTEL_METRICS_EXPORTER`` are the specification's own
names for this switch, but the specification assigns them to the SDK's
auto-configuration entrypoint, and this module deliberately builds its providers
by hand instead. They are therefore read HERE, or they would not be read at all:
setting ``OTEL_METRICS_EXPORTER=none`` used to change nothing, leaving a
``PeriodicExportingMetricReader`` running against whatever endpoint was
configured in a process whose operator believed metrics export was off.

A caller with no collector should switch the exporter off rather than aim it at
an address that refuses connections. An unroutable endpoint does not silence
export - the gRPC exporter cannot tell a black hole from a slow collector, so it
keeps retrying on its own deadlines and reports each failure - and it makes a
real transport fault indistinguishable from the arrangement.
"""

from __future__ import annotations

import dataclasses
import importlib
import logging
from typing import TYPE_CHECKING, TypedDict, Unpack, cast, override

from opentelemetry import metrics, trace

from ..control.config import settings
from ..utils.version import package_version

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = [
    "SDK_DISABLED",
    "TelemetryConfig",
    "configure_telemetry",
    "get_meter",
    "get_tracer",
]

logger = logging.getLogger(__name__)

# These module-level settings reads are intentional.  OTel SDK
# configuration must be determined at import time so that ``get_tracer`` and
# ``get_meter`` callers at module scope (e.g. the aggregator) receive a correctly
# configured provider.  Changing telemetry config at runtime is explicitly out of
# scope for this service — operators restart the process to pick up new settings.
#
# SDK_DISABLED (and other constants below) are evaluated once at import
# time.  Tests that need to vary this behaviour must use subprocess isolation
# (e.g. ``subprocess.run([sys.executable, ...])`` with a custom env dict) rather
# than changing the environment after import — the constant will not re-evaluate.
_SERVICE_NAME = settings.otel_service_name
_SERVICE_VERSION = settings.otel_service_version or package_version()
_OTLP_ENDPOINT = settings.otel_exporter_otlp_endpoint
SDK_DISABLED = settings.otel_sdk_disabled
_INSECURE = settings.otel_exporter_otlp_insecure
_CONSOLE_EXPORT = settings.otel_exporter_console


def _signal_export_disabled(selected: str | None) -> bool:
    """Return whether *selected* is the specification's ``none`` exporter.

    Unset is NOT ``none``: the specification's default is the OTLP exporter, and
    an absent value must keep meaning "export normally" so a deployment that
    never heard of this switch is unaffected.
    """
    return (selected or "").strip().lower() == "none"


_TRACES_EXPORT_DISABLED = _signal_export_disabled(settings.otel_traces_exporter)
_METRICS_EXPORT_DISABLED = _signal_export_disabled(settings.otel_metrics_exporter)

_OTLP_EXPORTER_MODULES = (
    "opentelemetry.exporter",
    "opentelemetry.exporter.otlp",
    "opentelemetry.exporter.otlp.proto",
    "opentelemetry.exporter.otlp.proto.grpc",
    "opentelemetry.exporter.otlp.proto.grpc.trace_exporter",
    "opentelemetry.exporter.otlp.proto.grpc.metric_exporter",
)


@dataclasses.dataclass(frozen=True)
class _TelemetryExportState:
    traces_exporting: bool
    metrics_exporting: bool


class _TelemetryConfigOptions(TypedDict, total=False):
    sdk_available: bool
    otlp_available: bool
    sdk_enabled: bool
    service_name: str
    otlp_endpoint: str
    langsmith_enabled: bool
    traces_exporting: bool
    metrics_exporting: bool


_TELEMETRY_CONFIG_FIELDS = (
    "sdk_available",
    "otlp_available",
    "sdk_enabled",
    "service_name",
    "otlp_endpoint",
    "langsmith_enabled",
    "traces_exporting",
    "metrics_exporting",
)
_TELEMETRY_CONFIG_DEFAULTS = (object(),) * 6 + (False, False)


def _bind_telemetry_config_fields(
    args: tuple[object, ...], options: _TelemetryConfigOptions
) -> tuple[object, ...]:
    """Bind the original positional and keyword config fields."""
    field_names = _TELEMETRY_CONFIG_FIELDS
    if len(args) > len(field_names):
        raise TypeError(
            f"expected at most {len(field_names)} positional arguments, got {len(args)}"
        )
    unknown = next((name for name in options if name not in field_names), None)
    if unknown is not None:
        raise TypeError(f"unexpected keyword argument {unknown!r}")
    duplicate = next(
        (name for name in field_names[: len(args)] if name in options),
        None,
    )
    if duplicate is not None:
        raise TypeError(f"multiple values for argument {duplicate!r}")
    return tuple(
        args[index]
        if index < len(args)
        else options.get(name, _TELEMETRY_CONFIG_DEFAULTS[index])
        for index, name in enumerate(field_names)
    )


def _required_telemetry_field(name: str, value: object) -> object:
    if value is _TELEMETRY_CONFIG_DEFAULTS[0]:
        raise TypeError(f"missing required argument {name!r}")
    return value


@dataclasses.dataclass(frozen=True, init=False)
class TelemetryConfig:
    """Runtime snapshot of the active telemetry configuration.

    Attributes:
        sdk_available: True when opentelemetry-sdk is installed.
        otlp_available: True when the OTLP gRPC exporter is installed.
        sdk_enabled: True when SDK is installed and OTEL_SDK_DISABLED is not set.
        service_name: The OTel service name in use.
        otlp_endpoint: The configured OTLP endpoint.
        langsmith_enabled: Whatever the ``langsmith`` SDK reports for its own
            tracing state at the moment ``configure_telemetry`` ran. This is a
            report, not a switch — nothing in this package can turn LangSmith
            tracing on or off.
        traces_exporting: True when a span processor was actually installed.
            Distinct from ``otlp_available``, which only says the package is
            importable: an installed exporter switched off by
            ``OTEL_TRACES_EXPORTER=none`` reports available but not exporting.
        metrics_exporting: The same distinction for the metric reader.
    """

    sdk_available: bool
    otlp_available: bool
    sdk_enabled: bool
    service_name: str
    otlp_endpoint: str
    langsmith_enabled: bool
    _exporting: _TelemetryExportState = dataclasses.field(init=False, repr=False)

    def __init__(
        self,
        *args: object,
        **options: Unpack[_TelemetryConfigOptions],
    ) -> None:
        values = _bind_telemetry_config_fields(args, options)
        object.__setattr__(
            self,
            "sdk_available",
            cast("bool", _required_telemetry_field("sdk_available", values[0])),
        )
        object.__setattr__(
            self,
            "otlp_available",
            cast("bool", _required_telemetry_field("otlp_available", values[1])),
        )
        object.__setattr__(
            self,
            "sdk_enabled",
            cast("bool", _required_telemetry_field("sdk_enabled", values[2])),
        )
        object.__setattr__(
            self,
            "service_name",
            cast("str", _required_telemetry_field("service_name", values[3])),
        )
        object.__setattr__(
            self,
            "otlp_endpoint",
            cast("str", _required_telemetry_field("otlp_endpoint", values[4])),
        )
        object.__setattr__(
            self,
            "langsmith_enabled",
            cast(
                "bool",
                _required_telemetry_field("langsmith_enabled", values[5]),
            ),
        )
        object.__setattr__(
            self,
            "_exporting",
            _TelemetryExportState(
                traces_exporting=cast("bool", values[6]),
                metrics_exporting=cast("bool", values[7]),
            ),
        )

    @property
    def traces_exporting(self) -> bool:
        return self._exporting.traces_exporting

    @property
    def metrics_exporting(self) -> bool:
        return self._exporting.metrics_exporting

    @override
    def __repr__(self) -> str:
        """Return developer-friendly representation."""
        return (
            f"TelemetryConfig("
            f"sdk_enabled={self.sdk_enabled}, "
            f"otlp_available={self.otlp_available}, "
            f"traces_exporting={self.traces_exporting}, "
            f"metrics_exporting={self.metrics_exporting}, "
            f"service={self.service_name!r}, "
            f"langsmith={self.langsmith_enabled})"
        )


def _module_importable(module_name: str) -> bool:
    """Return True if ``module_name`` can actually be imported.

    Deliberately an import rather than a ``find_spec`` probe. A spec probe
    answers "are these files on disk", which is not the question a caller of an
    optional-dependency check is asking, and the two answers come apart in
    exactly the case that matters. ``find_spec`` imports a module's *parents*
    but never executes the leaf, so a present-but-unusable exporter probes as
    available and then raises when something later imports it for real - the OTLP
    exporter's own ``__init__`` pulls symbols from the separate ``grpc``
    distribution, and a partial or mismatched install fails there, not at the
    probe. Importing here collapses that gap: available means importable.

    The module is left in ``sys.modules`` on success, so the caller's subsequent
    import is a cache hit rather than a second execution.
    """
    try:
        importlib.import_module(module_name)
    except Exception:
        # Deliberately broad. This is a availability probe for an OPTIONAL
        # dependency, and a dependency that cannot be imported for any reason -
        # a missing parent, a partial install, a symbol mismatch against a
        # sibling distribution, a failing module-level side effect - is simply
        # unavailable. Narrowing to ImportError would let an unrelated exception
        # in a third-party __init__ abort gateway and worker startup, which is
        # the whole failure class this guard exists to prevent.
        return False
    return True


def _resolve_langsmith() -> tuple[bool, str]:
    """Ask the ``langsmith`` SDK whether it is tracing, and into which project.

    The SDK owns this decision end to end: it reads ``LANGSMITH_TRACING_V2``,
    ``LANGCHAIN_TRACING_V2``, ``LANGSMITH_TRACING`` and ``LANGCHAIN_TRACING`` from
    ``os.environ`` in that order, and honours the context-var and global overrides
    a caller may have installed. Delegating means the reported value cannot drift
    from the real one; re-deriving it here would create a second answer with no
    authority behind it.

    Called from ``configure_telemetry`` rather than at module import so the answer
    reflects the process at startup, not at first import of this module.

    Neither symbol appears in ``langsmith.__all__``, but
    ``langchain_core.tracers.context`` — a first-order dependency here — calls
    these same two at this same path, so a rename breaks langchain-core in the
    same release rather than singling this module out. A telemetry test pins the
    pair so a dependency bump fails there instead of during lifespan startup.

    Returns:
        ``(enabled, project)``. ``enabled`` is True for both remote and local
        tracing modes; ``project`` is the SDK's resolved project name.
    """
    import langsmith.utils as _langsmith_utils

    # langsmith's own signature leaves `tracing_is_enabled`'s parameter partially
    # untyped; the module is bound to `object` and the two functions read off it
    # through explicit `Callable` casts, so the untyped boundary is confined to
    # this one seam rather than spreading into the caller.
    tracing_is_enabled_fn = cast(
        "Callable[[], object]", _langsmith_utils.tracing_is_enabled
    )
    get_tracer_project_fn = cast(
        "Callable[[], object]", _langsmith_utils.get_tracer_project
    )
    project = get_tracer_project_fn() or "default"
    return bool(tracing_is_enabled_fn()), str(project)


def _check_sdk() -> bool:
    """Return True if the mandatory opentelemetry-sdk is importable."""
    return _module_importable("opentelemetry.sdk.trace")


def _check_otlp() -> bool:
    """Return True if the OTLP gRPC exporter is importable.

    The OTLP exporter is optional (operators may not run a collector), so an
    unusable one degrades to no-export rather than failing startup.
    """
    return all(_module_importable(name) for name in _OTLP_EXPORTER_MODULES)


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

    if _TRACES_EXPORT_DISABLED:
        # No processor at all: spans are still created, so instrumentation and
        # the correlation filter keep working, but nothing leaves the process
        # and no export thread is started.
        logger.info("OTel span export disabled via OTEL_TRACES_EXPORTER=none")
    elif otlp_available:
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
        MetricReader,
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
    readers: list[MetricReader] = []

    if _METRICS_EXPORT_DISABLED:
        logger.info("OTel metric export disabled via OTEL_METRICS_EXPORTER=none")
    elif otlp_available:
        from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
            OTLPMetricExporter,
        )

        exporter = OTLPMetricExporter(endpoint=_OTLP_ENDPOINT, insecure=_INSECURE)
        readers.append(PeriodicExportingMetricReader(exporter))

    meter_provider = MeterProvider(resource=resource, metric_readers=readers)
    metrics.set_meter_provider(meter_provider)


def _configure_sdk(
    *,
    sdk_enabled: bool,
    otlp_available: bool,
    effective_service: str,
    langsmith_enabled: bool,
) -> None:
    """Configure SDK providers and report the selected SDK mode."""
    if sdk_enabled:
        provider = _build_sdk_provider(
            otlp_available=otlp_available, service_name=effective_service
        )
        trace.set_tracer_provider(provider)
        _build_sdk_meter_provider(
            otlp_available=otlp_available, service_name=effective_service
        )
        logger.info(
            "OTel SDK TracerProvider configured service=%s otlp=%s traces=%s "
            "metrics=%s langsmith=%s",
            effective_service,
            otlp_available,
            not _TRACES_EXPORT_DISABLED,
            not _METRICS_EXPORT_DISABLED,
            langsmith_enabled,
        )
    elif SDK_DISABLED:
        logger.info("OTel SDK explicitly disabled via OTEL_SDK_DISABLED")
    else:
        logger.info(
            "opentelemetry-sdk not installed — using no-op tracer. "
            "Install 'opentelemetry-sdk' to enable real tracing."
        )


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
    sdk_enabled = sdk_available and not SDK_DISABLED
    langsmith_enabled, langsmith_project = _resolve_langsmith()

    effective_service = service_name or _SERVICE_NAME

    _configure_sdk(
        sdk_enabled=sdk_enabled,
        otlp_available=otlp_available,
        effective_service=effective_service,
        langsmith_enabled=langsmith_enabled,
    )

    if langsmith_enabled:
        logger.info(
            "LangSmith SDK reports tracing enabled project=%r",
            langsmith_project,
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
        langsmith_enabled=langsmith_enabled,
        traces_exporting=(
            sdk_enabled
            and not _TRACES_EXPORT_DISABLED
            and (otlp_available or _CONSOLE_EXPORT)
        ),
        metrics_exporting=(
            sdk_enabled and not _METRICS_EXPORT_DISABLED and otlp_available
        ),
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

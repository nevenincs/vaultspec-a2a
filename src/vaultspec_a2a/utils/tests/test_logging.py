"""Tests for the logging utility — per-kind lane contracts, real seams, no mocks."""

import io
import json
import logging
import logging.handlers
import sys
from collections.abc import Generator
from pathlib import Path

import pytest
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider

from ...control.config import Settings
from ..enums import Environment, LogLevel
from ..logging import (
    JSONFormatter,
    LivenessPollFilter,
    OTelCorrelationFilter,
    _assert_no_stdout_handler,
    _DemoteToWarning,
    configure_logging,
    reconfigure_console_utf8,
)


@pytest.fixture(autouse=True)
def _clean_root_logger() -> Generator[None]:
    """Close and remove all root handlers before and after each test.

    Closing (not just clearing) releases any RotatingFileHandler's file so a
    Windows tmp_path teardown does not fail on an open handle.
    """

    def _reset() -> None:
        root = logging.getLogger()
        for handler in list(root.handlers):
            root.removeHandler(handler)
            handler.close()

    _reset()
    yield
    _reset()


def _settings(*, env: Environment, level: LogLevel, home: Path) -> Settings:
    # a2a_home is keyed by its explicit alias, so it must be passed by alias.
    return Settings(environment=env, log_level=level, VAULTSPEC_A2A_HOME=home)


# --- service kind ----------------------------------------------------------


def test_service_kind_json_to_stderr_and_rotating_file(tmp_path: Path) -> None:
    settings = _settings(
        env=Environment.PRODUCTION, level=LogLevel.DEBUG, home=tmp_path
    )
    configure_logging("service", service_name="gateway", settings_override=settings)

    root = logging.getLogger()
    assert root.level == logging.DEBUG
    stream_handlers = [h for h in root.handlers if isinstance(h, logging.StreamHandler)]
    file_handlers = [
        h for h in root.handlers if isinstance(h, logging.handlers.RotatingFileHandler)
    ]
    assert file_handlers, "service kind must attach a rotating file lane"
    # A stderr JSON stream lane exists; NO handler writes to stdout.
    assert any(
        getattr(h, "stream", None) is sys.stderr
        and isinstance(h.formatter, JSONFormatter)
        for h in stream_handlers
    )
    assert not any(getattr(h, "stream", None) is sys.stdout for h in root.handlers)
    # The file lane exists on disk under the runtime dir.
    assert (tmp_path / "runtime" / "gateway.log").exists()


def test_service_kind_honors_log_level(tmp_path: Path) -> None:
    settings = _settings(
        env=Environment.DEVELOPMENT, level=LogLevel.ERROR, home=tmp_path
    )
    configure_logging("service", service_name="worker", settings_override=settings)
    assert logging.getLogger().level == logging.ERROR


def test_service_kind_attaches_correlation_filter(tmp_path: Path) -> None:
    settings = _settings(env=Environment.PRODUCTION, level=LogLevel.INFO, home=tmp_path)
    configure_logging("service", service_name="gateway", settings_override=settings)
    for handler in logging.getLogger().handlers:
        assert any(isinstance(f, OTelCorrelationFilter) for f in handler.filters)


# --- cli kind --------------------------------------------------------------


def test_cli_kind_stderr_warning_no_stdout(tmp_path: Path) -> None:
    settings = _settings(
        env=Environment.PRODUCTION, level=LogLevel.DEBUG, home=tmp_path
    )
    # Production/non-interactive -> plain stderr StreamHandler at WARNING.
    configure_logging("cli", settings_override=settings)
    root = logging.getLogger()
    assert root.level == logging.WARNING
    assert not any(getattr(h, "stream", None) is sys.stdout for h in root.handlers)
    assert any(getattr(h, "stream", None) is sys.stderr for h in root.handlers)


# --- protocol kind ---------------------------------------------------------


def test_protocol_kind_is_stderr_only(tmp_path: Path) -> None:
    settings = _settings(
        env=Environment.PRODUCTION, level=LogLevel.DEBUG, home=tmp_path
    )
    configure_logging("protocol", settings_override=settings)
    root = logging.getLogger()
    assert root.level == logging.WARNING
    assert root.handlers, "protocol kind must attach a stderr handler"
    assert all(getattr(h, "stream", None) is sys.stderr for h in root.handlers)
    assert not any(getattr(h, "stream", None) is sys.stdout for h in root.handlers)


def test_protocol_no_stdout_assertion_fires() -> None:
    # The construction-time guard must reject a stdout handler on the root.
    root = logging.getLogger()
    root.addHandler(logging.StreamHandler(sys.stdout))
    with pytest.raises(AssertionError, match="stdout"):
        _assert_no_stdout_handler(root)


# --- library kind ----------------------------------------------------------


def test_library_kind_is_noop() -> None:
    sentinel = logging.StreamHandler(io.StringIO())
    root = logging.getLogger()
    root.addHandler(sentinel)
    configure_logging("library")
    assert sentinel in root.handlers  # untouched


# --- utf-8 guard -----------------------------------------------------------


def test_reconfigure_console_utf8_never_raises() -> None:
    # Under pytest capture the streams may not be reconfigurable; must not raise.
    reconfigure_console_utf8()


# --- OTel correlation + JSON formatter (unchanged behaviour) ---------------


def test_otel_correlation_filter_injects_active_span_fields() -> None:
    provider = TracerProvider(resource=Resource.create({"service.name": "svc-test"}))
    tracer = provider.get_tracer(__name__)
    record = logging.LogRecord(
        name="test.logger",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello",
        args=(),
        exc_info=None,
    )
    with tracer.start_as_current_span("span"):
        kept = OTelCorrelationFilter().filter(record)
    assert kept is True
    assert len(record.__dict__["trace_id"]) == 32
    assert len(record.__dict__["span_id"]) == 16
    assert record.__dict__["trace_sampled"] is True
    assert record.__dict__["service_name"] == "svc-test"


def test_otel_correlation_filter_preserves_existing_fields() -> None:
    provider = TracerProvider(resource=Resource.create({"service.name": "svc-test"}))
    tracer = provider.get_tracer(__name__)
    record = logging.LogRecord(
        name="test.logger",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello",
        args=(),
        exc_info=None,
    )
    record.trace_id = "existing-trace-id"
    record.span_id = "existing-span-id"
    record.trace_sampled = "existing-sampled"
    record.service_name = "existing-service"
    with tracer.start_as_current_span("span"):
        kept = OTelCorrelationFilter().filter(record)
    assert kept is True
    assert record.__dict__["trace_id"] == "existing-trace-id"
    assert record.__dict__["span_id"] == "existing-span-id"
    assert record.__dict__["trace_sampled"] == "existing-sampled"
    assert record.__dict__["service_name"] == "existing-service"


def test_json_formatter_outputs_correlation_fields_from_filter() -> None:
    provider = TracerProvider(resource=Resource.create({"service.name": "svc-test"}))
    tracer = provider.get_tracer(__name__)
    stream = io.StringIO()
    logger = logging.getLogger("test.logging.json")
    logger.handlers.clear()
    logger.setLevel(logging.INFO)
    logger.propagate = False
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JSONFormatter())
    handler.addFilter(OTelCorrelationFilter())
    logger.addHandler(handler)
    with tracer.start_as_current_span("span"):
        logger.info("hello", extra={"thread_id": "thread-123"})
    payload = json.loads(stream.getvalue())
    assert payload["message"] == "hello"
    assert payload["thread_id"] == "thread-123"
    assert payload["service_name"] == "svc-test"
    assert len(payload["trace_id"]) == 32
    assert len(payload["span_id"]) == 16
    assert payload["trace_sampled"] is True
    logger.handlers.clear()


def test_otel_correlation_filter_leaves_record_clean_without_active_span() -> None:
    record = logging.LogRecord(
        name="test.logger",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello",
        args=(),
        exc_info=None,
    )
    kept = OTelCorrelationFilter().filter(record)
    assert kept is True
    assert "trace_id" not in record.__dict__
    assert "span_id" not in record.__dict__
    assert "trace_sampled" not in record.__dict__
    assert "service_name" not in record.__dict__


def test_json_formatter_survives_a_computed_false_exc_info() -> None:
    """A falsy ``exc_info`` flag must not cost the record.

    ``Logger._log`` normalises only truthy ``exc_info`` values, so a caller
    passing a computed flag lands ``False`` on the record verbatim. The OTLP
    gRPC exporter does exactly this on every transport error it does not
    classify as unknown, and the formatter used to raise ``TypeError`` on it -
    which discards the record, silencing the very failures the lane exists to
    report.
    """
    logger = logging.getLogger("test.exc_info.false")
    logger.setLevel(logging.WARNING)
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JSONFormatter())
    logger.handlers = [handler]
    logger.propagate = False

    try:
        logger.warning("transport unavailable", exc_info=bool(0))
    finally:
        logger.handlers.clear()

    emitted = stream.getvalue()
    assert "--- Logging error ---" not in emitted, emitted
    payload = json.loads(emitted.strip())
    assert payload["message"] == "transport unavailable"
    assert "exception" not in payload


def test_json_formatter_renders_every_exc_info_shape() -> None:
    """Instance, populated tuple, and an unresolved raw flag all render a traceback."""
    formatter = JSONFormatter()

    def render(exc_info: object) -> dict[str, object]:
        record = logging.LogRecord(
            name="test.exc_info.shapes",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="boom",
            args=(),
            exc_info=exc_info,  # ty: ignore[invalid-argument-type]
        )
        return json.loads(formatter.format(record))

    try:
        raise ValueError("the real cause")
    except ValueError as exc:
        from_instance = render(exc)
        from_tuple = render(sys.exc_info())
        # A record built outside Logger._log keeps the raw flag; the live
        # exception is what Logger._log would have resolved it to.
        from_flag = render(True)

    for payload in (from_instance, from_tuple, from_flag):
        assert "ValueError: the real cause" in str(payload["exception"])


def test_json_formatter_omits_exception_for_an_empty_exc_info_tuple() -> None:
    """``exc_info=True`` raised with no live exception must not invent one."""
    record = logging.LogRecord(
        name="test.exc_info.empty",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="boom",
        args=(),
        exc_info=(None, None, None),
    )
    assert "exception" not in json.loads(JSONFormatter().format(record))


def _access_record(path: str, status: int, *, name: str = "uvicorn.access"):
    """Build a record shaped exactly as uvicorn's access logger emits one.

    uvicorn formats ``'%s - "%s %s HTTP/%s" %d'`` against
    ``(client, method, path_with_query, http_version, status)``; the filter reads
    positions 2 and 4, so the tuple must match that contract rather than a
    convenient stand-in.
    """
    return logging.LogRecord(
        name=name,
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='%s - "%s %s HTTP/%s" %d',
        args=("127.0.0.1:1", "GET", path, "1.1", status),
        exc_info=None,
    )


def test_liveness_poll_filter_drops_only_successful_probe_lines() -> None:
    """The probe is dropped when it is boring and kept when it is not."""
    f = LivenessPollFilter()

    # Boring: a supervisor confirming the process is still alive.
    assert not f.filter(_access_record("/health", 200))
    assert not f.filter(_access_record("/internal/health", 204))
    assert not f.filter(_access_record("/health?probe=1", 200))

    # Not boring: the probe is now telling you something.
    assert f.filter(_access_record("/health", 503))
    assert f.filter(_access_record("/internal/health", 401))

    # Not a probe at all - real traffic must never be silenced to reduce volume.
    assert f.filter(_access_record("/v1/runs", 200))
    assert f.filter(_access_record("/v1/service", 200))


def test_liveness_poll_filter_leaves_application_loggers_alone() -> None:
    """Only uvicorn's access lane is filtered, whatever a record looks like."""
    f = LivenessPollFilter()
    assert f.filter(_access_record("/health", 200, name="vaultspec_a2a.api"))
    assert f.filter(
        logging.LogRecord(
            name="uvicorn.error",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="/health",
            args=(),
            exc_info=None,
        )
    )


def test_liveness_poll_filter_keeps_records_it_cannot_parse() -> None:
    """An unrecognised shape is kept: silence must never be the default."""
    f = LivenessPollFilter()
    for args in ((), ("only", "three", "args"), ("c", "GET", "/health", "1.1", "xx")):
        record = logging.LogRecord(
            name="uvicorn.access",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="%s",
            args=args,
            exc_info=None,
        )
        assert f.filter(record)


def test_export_failures_are_demoted_so_error_keeps_its_meaning() -> None:
    """An absent collector is a deployment condition, reported below ERROR.

    Guards the level, not the message: the record still travels, so a genuinely
    misconfigured collector remains visible.
    """
    f = _DemoteToWarning()
    record = logging.LogRecord(
        name="opentelemetry.exporter.otlp.proto.grpc.exporter",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="Failed to export traces to localhost:4317",
        args=(),
        exc_info=None,
    )
    assert f.filter(record)
    assert record.levelno == logging.WARNING
    assert record.levelname == "WARNING"

    # Anything already below ERROR is untouched.
    warned = logging.LogRecord(
        name="opentelemetry.exporter.otlp.proto.grpc.exporter",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="exporting",
        args=(),
        exc_info=None,
    )
    assert f.filter(warned)
    assert warned.levelno == logging.INFO

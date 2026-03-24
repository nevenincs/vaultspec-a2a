"""Tests for the logging utility."""

import io
import json
import logging
import sys
from collections.abc import Generator

import pytest
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider

from ...control.config import Settings
from ..enums import Environment, LogLevel
from ..logging import JSONFormatter, OTelCorrelationFilter, setup_logging


@pytest.fixture(autouse=True)
def _clean_root_logger() -> Generator[None]:
    """Remove all root logger handlers before and after each test.

    Prevents cross-test pollution from setup_logging adding handlers
    that accumulate across tests (H29 fix).
    """
    root = logging.getLogger()
    root.handlers.clear()
    yield
    root.handlers.clear()


def test_setup_logging_json_format_in_production() -> None:
    """In production, even if interactive, we should force JSON output."""
    settings_override = Settings(
        environment=Environment.PRODUCTION, log_level=LogLevel.DEBUG
    )

    setup_logging(settings_override=settings_override)

    root_logger = logging.getLogger()
    assert root_logger.level == logging.DEBUG

    # Verify we got a stream handler with JSONFormatter
    # since ci_mode / force_json activates
    handlers = root_logger.handlers
    assert len(handlers) == 1
    assert isinstance(handlers[0], logging.StreamHandler)
    assert isinstance(handlers[0].formatter, JSONFormatter)


def test_setup_logging_respects_settings_override() -> None:
    """Ensure logging captures settings correctly."""
    settings_override = Settings(
        environment=Environment.DEVELOPMENT, log_level=LogLevel.ERROR
    )

    setup_logging(settings_override=settings_override)

    root_logger = logging.getLogger()
    assert root_logger.level == logging.ERROR


def test_otel_correlation_filter_injects_active_span_fields() -> None:
    """The correlation filter injects OTel IDs from the active span."""
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
    """Caller-provided correlation fields must not be overwritten."""
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
    """JSON logging includes auto-injected correlation fields and extras."""
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
    """No active span means no auto-injected correlation fields."""
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


def test_setup_logging_attaches_correlation_filter_json_path() -> None:
    """Production-shaped setup attaches the correlation filter to JSON logging."""
    settings_override = Settings(
        environment=Environment.PRODUCTION, log_level=LogLevel.DEBUG
    )

    setup_logging(settings_override=settings_override)

    handler = logging.getLogger().handlers[0]
    assert any(isinstance(f, OTelCorrelationFilter) for f in handler.filters)


def test_setup_logging_attaches_correlation_filter_rich_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Interactive dev setup attaches the correlation filter to Rich logging."""
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(sys.stderr, "isatty", lambda: True)
    settings_override = Settings(
        environment=Environment.DEVELOPMENT,
        log_level=LogLevel.DEBUG,
    )

    setup_logging(settings_override=settings_override)

    handler = logging.getLogger().handlers[0]
    assert handler.__class__.__name__ == "RichHandler"
    assert any(isinstance(f, OTelCorrelationFilter) for f in handler.filters)

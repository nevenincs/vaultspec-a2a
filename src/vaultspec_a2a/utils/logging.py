"""Logging utilities for the VaultSpec A2A project."""

import json
import logging
import sys
from typing import TYPE_CHECKING, Any

from opentelemetry import trace
from opentelemetry.trace.span import format_span_id, format_trace_id

from .enums import LogLevel

__all__ = ["JSONFormatter", "OTelCorrelationFilter", "setup_logging"]


if TYPE_CHECKING:
    from ..core.config import Settings


# Standard LogRecord attributes that should not be included as extra fields.
_STANDARD_LOG_ATTRS: frozenset[str] = frozenset(
    {
        "args",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "thread",
        "threadName",
        "taskName",
    }
)


class OTelCorrelationFilter(logging.Filter):
    """Inject OTel correlation fields into log records when a span is active."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Populate correlation fields without overwriting caller-provided values."""
        span = trace.get_current_span()
        context = span.get_span_context()
        if not context.is_valid:
            return True

        if "trace_id" not in record.__dict__:
            record.trace_id = format_trace_id(context.trace_id)
        if "span_id" not in record.__dict__:
            record.span_id = format_span_id(context.span_id)
        if "trace_sampled" not in record.__dict__:
            record.trace_sampled = bool(context.trace_flags.sampled)

        if "service_name" not in record.__dict__:
            resource = getattr(span, "resource", None)
            attributes = getattr(resource, "attributes", None)
            if attributes is not None:
                service_name = attributes.get("service.name")
                if isinstance(service_name, str) and service_name:
                    record.service_name = service_name

        return True


class JSONFormatter(logging.Formatter):
    """Formatter that outputs JSON strings for structured logging.

    Any extra fields added via ``logging.getLogger(__name__).info(...,
    extra={"thread_id": "...", "agent_id": "..."})`` are automatically
    included in the JSON output, enabling structured correlation context.
    """

    def format(self, record: logging.LogRecord) -> str:
        """Format the log record as a single-line JSON string."""
        log_data: dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "name": record.name,
            "message": record.getMessage(),
        }

        # Include any structured extra fields (e.g. thread_id, agent_id, client_id)
        # that callers pass via logger.info(..., extra={"thread_id": "..."}).
        for key, value in record.__dict__.items():
            if key not in _STANDARD_LOG_ATTRS and not key.startswith("_"):
                log_data[key] = value

        if record.exc_info is not None:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data)


def setup_logging(
    level: LogLevel | str | None = None,
    settings_override: "Settings | None" = None,
) -> None:
    """Configure structured JSON logging or rich terminal logging."""
    from ..core.config import settings as core_settings

    active_settings = settings_override or core_settings

    if level is None:
        level = active_settings.log_level

    # M35: `level` is guaranteed non-None here; `if level else "INFO"` was dead code
    level_str = level.upper() if isinstance(level, str) else level.value.upper()

    numeric_level = getattr(logging, level_str, logging.INFO)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)

    # Remove existing handlers to avoid duplicates
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    is_interactive = sys.stdout.isatty() and sys.stderr.isatty()
    disable_color = active_settings.no_color
    ci_mode = active_settings.ci
    force_json = not active_settings.is_dev

    log_handler: logging.Handler
    if is_interactive and not disable_color and not ci_mode and not force_json:
        from rich.logging import RichHandler

        log_handler = RichHandler(
            level=numeric_level,
            rich_tracebacks=True,
            markup=True,
            show_time=True,
            show_path=True,
        )
    else:
        log_handler = logging.StreamHandler(sys.stdout)
        log_handler.setFormatter(JSONFormatter())

    log_handler.addFilter(OTelCorrelationFilter())
    root_logger.addHandler(log_handler)

    # Override library loggers to use the same handler and disable propagation
    # so log records are not delivered twice (once via the child logger's handler
    # and once via propagation to the root logger).
    # Use handlers.clear() + addHandler() rather than direct list assignment to
    # respect the logging module's internal locking (H23 fix).
    for lib_logger_name in ("uvicorn.access", "uvicorn.error"):
        lib_logger = logging.getLogger(lib_logger_name)
        lib_logger.handlers.clear()
        lib_logger.addHandler(log_handler)
        lib_logger.propagate = False

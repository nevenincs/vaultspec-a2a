"""Logging utilities for the VaultSpec A2A project."""

import json
import logging
import sys

from typing import TYPE_CHECKING, Any

from .enums import LogLevel


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
    from ..core.config import settings as core_settings  # noqa: PLC0415

    active_settings = settings_override or core_settings

    if level is None:
        level = active_settings.log_level

    if isinstance(level, str):
        level = level.upper()
    elif level is not None:
        level = level.value.upper()

    numeric_level = getattr(logging, str(level) if level else "INFO", logging.INFO)

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
        from rich.logging import RichHandler  # noqa: PLC0415

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

    root_logger.addHandler(log_handler)

    # Override library loggers to use the same handler and disable propagation
    # so log records are not delivered twice (once via the child logger's handler
    # and once via propagation to the root logger).
    for lib_logger_name in ("uvicorn.access", "uvicorn.error"):
        lib_logger = logging.getLogger(lib_logger_name)
        lib_logger.handlers = [log_handler]
        lib_logger.propagate = False

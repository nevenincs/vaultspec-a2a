import json
import logging
import os
import sys
from typing import Any

from .enums import LogLevel


class JSONFormatter(logging.Formatter):
    """Formatter that outputs JSON strings for structured logging."""

    def format(self, record: logging.LogRecord) -> str:
        log_data: dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "name": record.name,
            "message": record.getMessage(),
        }

        if record.exc_info is not None:
            log_data["exception"] = self.formatException(record.exc_info)  # type: ignore[arg-type]

        return json.dumps(log_data)


def setup_logging(level: LogLevel | str = LogLevel.INFO) -> None:
    """Configure structured JSON logging or rich terminal logging."""

    if isinstance(level, str):
        level = level.upper()

    numeric_level = getattr(logging, level, logging.INFO)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)

    # Remove existing handlers to avoid duplicates
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    is_interactive = sys.stdout.isatty() and sys.stderr.isatty()
    disable_color = os.environ.get("NO_COLOR", "") != ""
    ci_mode = os.environ.get("CI", "").lower() in ("true", "1")

    log_handler: logging.Handler
    if is_interactive and not disable_color and not ci_mode:
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

    root_logger.addHandler(log_handler)

    # Intercept specific library logs if necessary (e.g., Uvicorn)
    logging.getLogger("uvicorn.access").handlers = [log_handler]
    logging.getLogger("uvicorn.error").handlers = [log_handler]

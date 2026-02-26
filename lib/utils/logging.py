import json
import logging
import sys
from typing import TYPE_CHECKING, Any

from .enums import LogLevel

if TYPE_CHECKING:
    from ..core.config import Settings


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


def setup_logging(
    level: LogLevel | str | None = None,
    settings_override: "Settings | None" = None,
) -> None:
    """Configure structured JSON logging or rich terminal logging."""

    from ..core.config import settings as core_settings

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

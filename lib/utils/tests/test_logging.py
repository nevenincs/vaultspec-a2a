"""Tests for the logging utility."""

import logging

from ...core import Settings
from ..enums import Environment, LogLevel
from ..logging import JSONFormatter, setup_logging


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

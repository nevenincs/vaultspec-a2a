"""Printer utility for user-facing console output."""

import logging
import sys

from typing import Any

from rich.console import Console


__all__ = ["Printer"]

log = logging.getLogger(__name__)

# L18/L19: underscore-prefixed singleton (internal implementation detail).
# Consumers use Printer.success / Printer.error etc., not console directly.
_console = Console(file=sys.stdout)


def _safe_print(*args: Any, **kwargs: Any) -> None:  # noqa: ANN401
    """Print to _console, catching only expected I/O errors.

    Only catches ``UnicodeEncodeError`` (terminal encoding mismatch) and
    ``OSError`` (e.g. EPIPE on broken pipe). All other exceptions propagate.
    Hardcoded ANSI color codes in format strings are intentional for CLI output.
    """
    try:
        _console.print(*args, **kwargs)
    except UnicodeEncodeError as exc:
        log.debug("UnicodeEncodeError in Printer output: %s", exc)
    except OSError as exc:
        log.debug("OSError in Printer output (broken pipe?): %s", exc)


class Printer:
    """Robust console printer for user-facing output.

    This should be used exclusively for semantic UI elements and interactive
    prompts in the terminal. Do not use this for diagnostics; use the standard
    'logging' module which degrades down to JSON in CI environments instead.
    """

    @staticmethod
    def success(msg: str, *args: Any, **kwargs: Any) -> None:  # noqa: ANN401
        """Print a successful action."""
        _safe_print(f"[bold green]✓[/bold green] {msg}", *args, **kwargs)

    @staticmethod
    def error(msg: str, *args: Any, **kwargs: Any) -> None:  # noqa: ANN401
        """Print a user-facing error."""
        _safe_print(f"[bold red]✗[/bold red] {msg}", *args, **kwargs)

    @staticmethod
    def warn(msg: str, *args: Any, **kwargs: Any) -> None:  # noqa: ANN401
        """Print a warning."""
        _safe_print(f"[bold yellow]![/bold yellow] {msg}", *args, **kwargs)

    @staticmethod
    def info(msg: str, *args: Any, **kwargs: Any) -> None:  # noqa: ANN401
        """Print informational output."""
        _safe_print(f"[bold blue]i[/bold blue] {msg}", *args, **kwargs)

    @staticmethod
    def step(msg: str, *args: Any, **kwargs: Any) -> None:  # noqa: ANN401
        """Print a workflow step transition."""
        _safe_print(f"[bold cyan]→[/bold cyan] {msg}", *args, **kwargs)

    @staticmethod
    def debug(msg: str, *args: Any, **kwargs: Any) -> None:  # noqa: ANN401
        """Print debug output."""
        _safe_print(f"[dim]d[/dim] [dim]{msg}[/dim]", *args, **kwargs)

    @staticmethod
    def print(*args: Any, **kwargs: Any) -> None:  # noqa: ANN401
        """Directly expose the rich print functionality for raw styled output."""
        _safe_print(*args, **kwargs)

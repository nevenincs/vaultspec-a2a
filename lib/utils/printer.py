"""Printer utility for user-facing console output."""

import sys

from typing import Any

from rich.console import Console


__all__ = ["Printer"]

# L18/L19: underscore-prefixed singleton (internal implementation detail).
# Consumers use Printer.success / Printer.error etc., not console directly.
_console = Console(file=sys.stdout)


class Printer:
    """Robust console printer for user-facing output.

    This should be used exclusively for semantic UI elements and interactive
    prompts in the terminal. Do not use this for diagnostics; use the standard
    'logging' module which degrades down to JSON in CI environments instead.
    """

    @staticmethod
    def success(msg: str, *args: Any, **kwargs: Any) -> None:  # noqa: ANN401
        """Print a successful action."""
        _console.print(f"[bold green]✓[/bold green] {msg}", *args, **kwargs)

    @staticmethod
    def error(msg: str, *args: Any, **kwargs: Any) -> None:  # noqa: ANN401
        """Print a user-facing error."""
        _console.print(f"[bold red]✗[/bold red] {msg}", *args, **kwargs)

    @staticmethod
    def warn(msg: str, *args: Any, **kwargs: Any) -> None:  # noqa: ANN401
        """Print a warning."""
        _console.print(f"[bold yellow]![/bold yellow] {msg}", *args, **kwargs)

    @staticmethod
    def info(msg: str, *args: Any, **kwargs: Any) -> None:  # noqa: ANN401
        """Print informational output."""
        _console.print(f"[bold blue]i[/bold blue] {msg}", *args, **kwargs)

    @staticmethod
    def step(msg: str, *args: Any, **kwargs: Any) -> None:  # noqa: ANN401
        """Print a workflow step transition."""
        _console.print(f"[bold cyan]→[/bold cyan] {msg}", *args, **kwargs)

    @staticmethod
    def debug(msg: str, *args: Any, **kwargs: Any) -> None:  # noqa: ANN401
        """Print debug output."""
        _console.print(f"[dim]d[/dim] [dim]{msg}[/dim]", *args, **kwargs)

    @staticmethod
    def print(*args: Any, **kwargs: Any) -> None:  # noqa: ANN401
        """Directly expose the rich print functionality for raw styled output."""
        _console.print(*args, **kwargs)

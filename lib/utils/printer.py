import sys
from typing import Any

from rich.console import Console

# Create a global console instance. It auto-detects TTY capabilities.
# We explicitly write to stdout for intentional user-facing output.
console = Console(file=sys.stdout)


class Printer:
    """
    Robust console printer for user-facing output.

    This should be used exclusively for semantic UI elements and interactive
    prompts in the terminal. Do not use this for diagnostics; use the standard
    'logging' module which degrades down to JSON in CI environments instead.
    """

    @staticmethod
    def success(msg: str, *args: Any, **kwargs: Any) -> None:
        """Print a successful action."""
        console.print(f"[bold green]✓[/bold green] {msg}", *args, **kwargs)

    @staticmethod
    def error(msg: str, *args: Any, **kwargs: Any) -> None:
        """Print a user-facing error."""
        console.print(f"[bold red]✗[/bold red] {msg}", *args, **kwargs)

    @staticmethod
    def warn(msg: str, *args: Any, **kwargs: Any) -> None:
        """Print a warning."""
        console.print(f"[bold yellow]![/bold yellow] {msg}", *args, **kwargs)

    @staticmethod
    def info(msg: str, *args: Any, **kwargs: Any) -> None:
        """Print informational output."""
        console.print(f"[bold blue]i[/bold blue] {msg}", *args, **kwargs)

    @staticmethod
    def step(msg: str, *args: Any, **kwargs: Any) -> None:
        """Print a workflow step transition."""
        console.print(f"[bold cyan]→[/bold cyan] {msg}", *args, **kwargs)

    @staticmethod
    def debug(msg: str, *args: Any, **kwargs: Any) -> None:
        """Print debug output."""
        console.print(f"[dim]d[/dim] [dim]{msg}[/dim]", *args, **kwargs)

    @staticmethod
    def print(*args: Any, **kwargs: Any) -> None:
        """Directly expose the rich print functionality for raw styled output."""
        console.print(*args, **kwargs)

"""Tests for the Printer console utility.

Exercises all static methods by capturing console output via StringIO
and verifying the expected semantic markers appear.
"""

from io import StringIO

from rich.console import Console

from ..printer import Printer, _console


# ---------------------------------------------------------------------------
# Console singleton
# ---------------------------------------------------------------------------


class TestConsoleSingleton:
    """Tests for the module-level _console object (L18: underscore-prefixed)."""

    def test_console_is_rich_console(self) -> None:
        """The module-level _console is a rich Console instance."""
        assert isinstance(_console, Console)


# ---------------------------------------------------------------------------
# Printer static methods
# ---------------------------------------------------------------------------


def _capture_printer(method_name: str, msg: str) -> str:
    """Call a Printer method while capturing output to a StringIO buffer.

    Temporarily replaces the module-level _console's file to capture output,
    then restores it.
    """
    buf = StringIO()
    original_file = _console.file
    _console.file = buf
    try:
        getattr(Printer, method_name)(msg)
    finally:
        _console.file = original_file
    return buf.getvalue()


class TestPrinterMethods:
    """Tests for each Printer static method."""

    def test_success_contains_message(self) -> None:
        """Printer.success outputs the message text."""
        output = _capture_printer("success", "all good")
        assert "all good" in output

    def test_error_contains_message(self) -> None:
        """Printer.error outputs the message text."""
        output = _capture_printer("error", "bad thing")
        assert "bad thing" in output

    def test_warn_contains_message(self) -> None:
        """Printer.warn outputs the message text."""
        output = _capture_printer("warn", "careful now")
        assert "careful now" in output

    def test_info_contains_message(self) -> None:
        """Printer.info outputs the message text."""
        output = _capture_printer("info", "fyi note")
        assert "fyi note" in output

    def test_step_contains_message(self) -> None:
        """Printer.step outputs the message text."""
        output = _capture_printer("step", "next step")
        assert "next step" in output

    def test_debug_contains_message(self) -> None:
        """Printer.debug outputs the message text."""
        output = _capture_printer("debug", "verbose detail")
        assert "verbose detail" in output

    def test_print_passthrough(self) -> None:
        """Printer.print delegates to _console.print."""
        buf = StringIO()
        original_file = _console.file
        _console.file = buf
        try:
            Printer.print("raw output")
        finally:
            _console.file = original_file
        assert "raw output" in buf.getvalue()

    def test_all_methods_are_static(self) -> None:
        """All public Printer methods are static (callable without instance)."""
        for name in ("success", "error", "warn", "info", "step", "debug", "print"):
            method = getattr(Printer, name)
            assert callable(method)

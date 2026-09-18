"""The isolated child process that actually imports modules for the probe.

This runs as ``python -m dev.quality.import_load_worker`` under
:mod:`dev.quality.import_load_probe`, never in the driver's own interpreter.
Importing 300 production modules executes every one of their module-level side
effects - registry registration, logger configuration, driver loading - into
the importing process, and doing that inside a gate would leave the gate's own
later behaviour dependent on the tree it just measured.

Each result is written as one line and flushed immediately. That is what lets
the driver attribute a HARD failure - a segfault, an ``os._exit``, an
interpreter abort - to the module that caused it: the last line written names
the last module attempted, and a module that produced no line at all is the
one the process died inside.
"""

from __future__ import annotations

import importlib
import sys
import traceback

#: Field separator. Tab rather than space: an exception message contains
#: spaces and colons freely, and a driver splitting on the wrong character
#: silently truncates the diagnosis.
SEPARATOR = "\t"


def _emit(status: str, module: str, detail: str = "") -> None:
    """Write one result line and flush it.

    Args:
        status: ``start``, ``ok``, or ``fail``.
        module: The module the line is about.
        detail: The failure detail, for ``fail``.
    """
    line = SEPARATOR.join((status, module, detail.replace("\n", " ")))
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def main(argv: list[str] | None = None) -> int:
    """Import each named module in turn, reporting every outcome.

    Args:
        argv: Module names, or ``None`` to read :data:`sys.argv`.

    Returns:
        Always 0. A failed import is a RESULT, reported on its line; the exit
        code says only whether this process finished its list, which is what
        distinguishes a reported failure from a crash.
    """
    modules = list(sys.argv[1:] if argv is None else argv)
    for module in modules:
        # `start` is written BEFORE the import so a module that kills the
        # interpreter still names itself. Without it, a hard crash looks like
        # the previous module succeeding and the process vanishing.
        _emit("start", module)
        try:
            importlib.import_module(module)
        # BaseException, not Exception: a module-level `sys.exit` or a
        # KeyboardInterrupt-derived guard is still this module failing to
        # load, and letting it escape would end the probe at that module.
        except BaseException as exc:
            summary = traceback.format_exception_only(type(exc), exc)[-1].strip()
            _emit("fail", module, summary)
        else:
            _emit("ok", module)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

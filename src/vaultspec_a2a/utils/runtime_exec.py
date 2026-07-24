"""Frozen-aware self-execution authority for every production re-exec.

A source checkout re-invokes this runtime with ``python -m ...``; a frozen
binary (PyInstaller onedir) has no ``-m``, no ``-c``, and no separate
interpreter to borrow - ``sys.executable`` IS the application binary. Every
production subprocess spawn that re-enters this runtime (the gateway's worker
spawn, the authoring stdio bridge, the desktop serve re-exec, and the bundled
``vaultspec_core`` provisioning calls) must therefore render its argv through
this module rather than assembling interpreter flags itself.

Two shapes cover every site:

- :func:`self_command` re-invokes the operator CLI with a subcommand
  (``serve``, ``worker``, ...).
- :func:`module_command` runs an allowlisted module as ``__main__`` inside this
  runtime's dependency closure - the freeze-safe replacement for
  ``python -m <module>``. From source it renders the familiar ``-m`` argv; when
  frozen it renders the CLI's ``run-module`` dispatch verb.

The allowlist is deliberate: ``run-module`` is an execution surface on the
shipped binary, so only the modules the runtime itself spawns are dispatchable.
Anything else fails loud at render time AND at dispatch time.
"""

from __future__ import annotations

import sys

__all__ = [
    "CLI_MODULE",
    "DISPATCHABLE_MODULES",
    "RUN_MODULE_VERB",
    "is_frozen",
    "is_module_invocation",
    "module_command",
    "self_command",
]

CLI_MODULE = "vaultspec_a2a.cli.main"

# The hidden CLI verb that runs an allowlisted module as __main__ when frozen.
RUN_MODULE_VERB = "run-module"

# Every module the runtime legitimately re-executes in a child process. The
# worker is spawned by the gateway's worker management, the authoring stdio
# bridge by the agent CLI's MCP config, and vaultspec_core by workspace
# provisioning/enrollment; nothing else is dispatchable through the binary.
DISPATCHABLE_MODULES = frozenset(
    {
        "vaultspec_a2a.worker",
        "vaultspec_a2a.protocols.mcp.authoring_stdio",
        "vaultspec_core",
    }
)


def is_frozen() -> bool:
    """Whether this process runs from a frozen (PyInstaller) binary."""
    return bool(getattr(sys, "frozen", False))


def self_command(*args: str) -> list[str]:
    """Argv that re-invokes this runtime's operator CLI with *args* appended.

    Frozen: the binary itself already dispatches to the CLI, so the argv is the
    binary plus the subcommand. Source: the current interpreter runs the CLI
    module - the SAME venv interpreter carrying the installed package, never a
    PATH-resolved ``python``.
    """
    if is_frozen():
        return [sys.executable, *args]
    return [sys.executable, "-m", CLI_MODULE, *args]


def module_command(module: str, *args: str) -> list[str]:
    """Argv that runs allowlisted *module* as ``__main__`` in this closure.

    The freeze-safe replacement for ``[sys.executable, "-m", module, *args]``.
    Raises :class:`ValueError` for a module outside
    :data:`DISPATCHABLE_MODULES`, so an unvetted execution surface cannot be
    rendered even from source.
    """
    if module not in DISPATCHABLE_MODULES:
        raise ValueError(
            f"module {module!r} is not dispatchable through the runtime binary; "
            f"allowlisted modules: {sorted(DISPATCHABLE_MODULES)}"
        )
    if is_frozen():
        return [sys.executable, RUN_MODULE_VERB, module, *args]
    return [sys.executable, "-m", module, *args]


def is_module_invocation(args: object, module: str) -> bool:
    """Whether *args* is exactly this runtime's invocation of *module*.

    The shape-integrity check for spec admission (the authoring stdio bridge
    validates the argv it re-emits): accepts precisely the two shapes
    :func:`module_command` renders - ``["-m", module]`` from source and
    ``[RUN_MODULE_VERB, module]`` when frozen - and nothing else.
    """
    return args in (["-m", module], [RUN_MODULE_VERB, module])

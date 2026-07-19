"""Expose lazy entry points for graph construction and compilation.

Build the initial vault index with
:func:`vaultspec_a2a.graph.nodes.vault_reader.build_initial_vault_index`.
Compile a team graph with
:func:`vaultspec_a2a.graph.compiler.compile_team_graph`.

Lazy exports prevent an import cycle among :mod:`vaultspec_a2a.context`,
:mod:`vaultspec_a2a.thread`, and :mod:`vaultspec_a2a.graph.enums`.

Compiled graphs connect :mod:`vaultspec_a2a.team`,
:mod:`vaultspec_a2a.providers`, and :mod:`vaultspec_a2a.authoring` to the
execution context.
"""

import importlib

# Lazy imports to break a circular dependency: the ``.compiler`` tree pulls in
# ``graph.nodes.supervisor``, which imports ``context.token_budget``, which
# imports ``thread.state`` — and ``thread`` (via ``snapshots``/``permission_fsm``)
# imports the Layer-1 leaf ``graph.enums``. Importing that leaf runs this package
# ``__init__``; eagerly loading ``.compiler`` here would therefore close the cycle
# through a partially-initialized ``context.token_budget``. Deferring the compiler
# exports keeps ``graph.enums`` importable without dragging the compiler tree in.
_LAZY_IMPORTS = {
    "build_initial_vault_index": ".compiler",
    "compile_team_graph": ".compiler",
}


def __getattr__(name: str) -> object:
    if name in _LAZY_IMPORTS:
        module = importlib.import_module(_LAZY_IMPORTS[name], __name__)
        value = getattr(module, name)
        globals()[name] = value  # cache for subsequent access
        return value
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)


__all__ = ["build_initial_vault_index", "compile_team_graph"]

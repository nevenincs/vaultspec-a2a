"""Protocol bridges for the Vaultspec A2A Orchestrator.

Sub-modules:
- ``mcp``: FastMCP server exposing team orchestration tools to IDE clients.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .mcp import mcp as mcp

__all__ = ["mcp"]


def __getattr__(name: str) -> object:
    """Lazily resolve the ``mcp`` server on first attribute access (PEP 562).

    Mirrors the lazy re-export in ``protocols.mcp``: importing a lightweight
    submodule under this package must not eagerly load the heavy FastMCP server
    chain. The public ``mcp`` attribute is preserved, resolved on demand.
    """
    if name == "mcp":
        from .mcp import mcp

        return mcp
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

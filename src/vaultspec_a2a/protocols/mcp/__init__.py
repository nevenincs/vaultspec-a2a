"""MCP protocol sub-module for the Vaultspec A2A Orchestrator.

Standalone MCP server that communicates with the gateway over HTTP.
No internal imports from core/ or api/ — all coupling is via the
VAULTSPEC_GATEWAY_URL environment variable.

Run standalone::

    python -m vaultspec_a2a.protocols.mcp                  # stdio
    python -m vaultspec_a2a.protocols.mcp --transport streamable-http
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .server import mcp as mcp

__all__ = ["mcp"]


def __getattr__(name: str) -> object:
    """Lazily resolve the ``mcp`` server on first attribute access (PEP 562).

    Importing a lightweight submodule of this package (e.g. the per-run
    ``authoring_stdio`` bridge) must NOT eagerly pull ``.server`` and its
    FastMCP + thread-lifecycle + langgraph/langchain chain, which dominates the
    bridge's spawn-to-serving latency and pushes it past the CLI's MCP-ready
    window. The public ``mcp`` attribute is preserved for consumers that read it
    off the package, resolved only when actually accessed.
    """
    if name == "mcp":
        from .server import mcp

        return mcp
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

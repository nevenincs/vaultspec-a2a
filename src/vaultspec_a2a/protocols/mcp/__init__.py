"""MCP protocol sub-module for the Vaultspec A2A Orchestrator.

Standalone MCP server that communicates with the gateway over HTTP.
No internal imports from core/ or api/ — all coupling is via the
VAULTSPEC_GATEWAY_URL environment variable.

Run standalone::

    python -m vaultspec_a2a.protocols.mcp                  # stdio
    python -m vaultspec_a2a.protocols.mcp --transport streamable-http
"""

from .server import mcp as mcp

__all__ = ["mcp"]

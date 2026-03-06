"""MCP protocol sub-module for the Vaultspec A2A Orchestrator.

Exposes the FastMCP server instance so the FastAPI app can mount it
at startup. See ADR-003 (Protocol Bridging) and ADR-006 (MCP Tool Mapping).
"""

from .server import mcp as mcp


__all__ = ["mcp"]

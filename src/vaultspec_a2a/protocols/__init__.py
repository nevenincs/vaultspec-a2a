"""Protocol bridges for the Vaultspec A2A Orchestrator.

Sub-modules:
- ``mcp``: FastMCP server exposing team orchestration tools to IDE clients.
"""

from .mcp import mcp as mcp

__all__ = ["mcp"]

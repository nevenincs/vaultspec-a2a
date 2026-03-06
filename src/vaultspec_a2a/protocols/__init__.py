"""Protocol bridges for the Vaultspec A2A Orchestrator.

Sub-modules:
- ``mcp``: FastMCP server exposing team orchestration tools to IDE clients.

See ADR-003 (Protocol Bridging) and ADR-006 (Protocol Ecosystem Bridge).
"""

from .mcp import mcp as mcp


__all__ = ["mcp"]

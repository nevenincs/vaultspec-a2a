"""Bridge the engine's served tool catalog into agent-facing MCP tools.

The engine owns the agent-tool catalog; this module turns a per-run
:class:`~vaultspec_a2a.authoring.catalog.CatalogSnapshot` into a live MCP server
the spawned CLI agent connects to. Because the catalog's tools are dynamic and
carry explicit JSON input schemas, the server is built on the low-level MCP
``Server`` (explicit ``list_tools``/``call_tool``) rather than the
signature-derived ``FastMCP`` surface. Tool calls route back through the
engine's run-scoped execute endpoint via the injected dispatcher.

Only the catalog's tools are surfaced, so the agent gets propose and read tools
and no vault-write path: no filesystem-write tool exists in the engine catalog
by construction, and the ACP fs-write RPC is separately denied.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import mcp.types as types
from mcp.server import Server

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ....authoring.catalog import CatalogSnapshot

__all__ = [
    "McpToolSpec",
    "build_authoring_mcp_server",
    "build_tool_specs",
]

# An MCP tool specification: the minimal advertised shape an MCP client reads.
McpToolSpec = dict[str, Any]


def build_tool_specs(snapshot: CatalogSnapshot) -> list[McpToolSpec]:
    """Map a catalog snapshot to MCP tool specifications in catalog order.

    Each spec carries the engine ``name`` (the higher-level semantic vocabulary,
    not a wire route), its ``description``, and the ``input_schema`` as the MCP
    ``inputSchema``. Risk tier and permission requirement are preserved under an
    ``_engine`` annotation so the session wiring can honour approval gating
    without a second catalog read.
    """
    specs: list[McpToolSpec] = []
    for tool in snapshot.tools:
        specs.append(
            {
                "name": tool.name,
                "description": tool.description,
                "inputSchema": tool.input_schema,
                "_engine": {
                    "risk_tier": tool.risk_tier,
                    "permission_requirement": tool.permission_requirement,
                    "idempotency_required": tool.idempotency_required,
                },
            }
        )
    return specs


def build_authoring_mcp_server(
    snapshot: CatalogSnapshot,
    dispatch: Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]],
    *,
    server_name: str = "vaultspec-authoring",
) -> Server:
    """Build a live MCP server advertising the snapshot's tools.

    ``list_tools`` advertises exactly the catalog's tools with their engine
    input schemas — no filesystem-write tool is present, by construction.
    ``call_tool`` routes to ``dispatch`` and returns the engine result as JSON
    text content; an unknown tool name is a hard error, never a silent no-op.
    """
    server: Server = Server(server_name)
    tools = [
        types.Tool(
            name=tool.name,
            description=tool.description,
            inputSchema=tool.input_schema or {"type": "object"},
        )
        for tool in snapshot.tools
    ]
    known = {tool.name for tool in snapshot.tools}

    @server.list_tools()
    async def _list_tools() -> list[types.Tool]:
        return tools

    @server.call_tool()
    async def _call_tool(
        name: str, arguments: dict[str, Any]
    ) -> list[types.TextContent]:
        if name not in known:
            raise ValueError(f"unknown authoring tool: {name!r}")
        result = await dispatch(name, arguments)
        return [types.TextContent(type="text", text=json.dumps(result, default=str))]

    return server

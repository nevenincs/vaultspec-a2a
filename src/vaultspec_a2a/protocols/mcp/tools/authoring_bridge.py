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

from .schema_normalize import normalize_tool_input_schema

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

# Fields the run dispatcher injects run-scoped (make_tool_dispatch), hidden from
# each tool's advertised schema/guidance so the model never sees them - it must
# not, and cannot, supply an id the dispatcher owns. Keyed by semantic tool name;
# MUST stay consistent with the dispatcher's per-command injection map. Read tools
# (read_context, search_graph) are absent: their target ids are model-owned.
_INJECTED_FIELDS_BY_TOOL: dict[str, frozenset[str]] = {
    "propose_changeset": frozenset({"session_id", "changeset_id"}),
    "validate_proposal": frozenset({"changeset_id", "expected_revision"}),
    "request_approval": frozenset({"changeset_id", "expected_revision"}),
    "cancel": frozenset({"changeset_id", "expected_revision"}),
    "request_apply": frozenset({"changeset_id", "approval_id"}),
}


def build_tool_specs(snapshot: CatalogSnapshot) -> list[McpToolSpec]:
    """Map a catalog snapshot to MCP tool specifications in catalog order.

    Each spec carries the engine ``name`` (the higher-level semantic vocabulary,
    not a wire route), its ``description``, and the ``input_schema`` NORMALIZED to
    valid MCP JSON Schema as the ``inputSchema``. The catalog's schema is a custom
    DSL the pinned CLI would reject and silently drop;
    ``normalize_tool_input_schema`` translates it to a registerable, guiding JSON
    Schema object (hiding the dispatcher-injected id fields) while the engine
    stays the execution authority, and any per-branch/bounds/dropped-keyword
    guidance is appended to the tool description so the model still sees it. The
    catalog snapshot is never mutated - normalization happens here, at serving
    time, only. Risk tier and permission requirement are preserved under an
    ``_engine`` annotation so the session wiring can honour approval gating
    without a second catalog read.

    This is the single normalization seam: :func:`build_authoring_mcp_server`
    advertises the same specs, so the live stdio bridge and the spec path serve
    identical schemas.
    """
    specs: list[McpToolSpec] = []
    for tool in snapshot.tools:
        injected = _INJECTED_FIELDS_BY_TOOL.get(tool.name, frozenset())
        input_schema, guidance = normalize_tool_input_schema(
            tool.input_schema, injected
        )
        description = tool.description
        if guidance:
            description = f"{description}\n\n{guidance}" if description else guidance
        specs.append(
            {
                "name": tool.name,
                "description": description,
                "inputSchema": input_schema,
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

    ``list_tools`` advertises exactly the catalog's tools with their input schemas
    NORMALIZED to valid JSON Schema through :func:`build_tool_specs` (the single
    seam) — so the live bridge serves schemas the pinned CLI keeps rather than
    silently drops. No filesystem-write tool is present, by construction.
    ``call_tool`` routes to ``dispatch`` and returns the engine result as JSON
    text content; an unknown tool name is a hard error, never a silent no-op.
    """
    server: Server = Server(server_name)
    tools = [
        types.Tool(
            name=spec["name"],
            description=spec["description"],
            inputSchema=spec["inputSchema"],
        )
        for spec in build_tool_specs(snapshot)
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

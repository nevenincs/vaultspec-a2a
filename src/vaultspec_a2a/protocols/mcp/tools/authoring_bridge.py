"""Bridge the engine's served tool catalog into agent-facing MCP tools.

The engine owns the agent-tool catalog; this module turns a per-run
:class:`~vaultspec_a2a.authoring.catalog.CatalogSnapshot` into a live MCP server
the spawned CLI agent connects to. Because the catalog's tools are dynamic and
carry explicit JSON input schemas, the server is built on the low-level MCP
``Server`` (explicit ``on_list_tools``/``on_call_tool`` handlers) rather than the
signature-derived ``MCPServer`` surface. Tool calls route back through the
engine's run-scoped execute endpoint via the injected dispatcher.

Only the catalog's tools are surfaced, so the agent gets propose and read tools
and no vault-write path: no filesystem-write tool exists in the engine catalog
by construction, and the ACP fs-write RPC is separately denied.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

import mcp.types as types
from mcp.server import Server
from mcp.shared.tool_name_validation import validate_tool_name

# Narrow module import, not the ``utils`` facade: this module is on the stdio
# bridge's spawn-to-serving path, where the facade's eager logging and process
# helpers are cost with no benefit.
from ....utils.version import package_version
from .schema_normalize import normalize_tool_input_schema

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from mcp.server.context import ServerRequestContext

    from ....authoring.catalog import AgentTool, CatalogSnapshot

__all__ = [
    "McpToolSpec",
    "build_authoring_mcp_server",
    "build_tool_specs",
]

logger = logging.getLogger(__name__)

# An MCP tool specification: the minimal advertised shape an MCP client reads.
McpToolSpec = dict[str, Any]

# The catalog risk tier that maps to the protocol's `destructiveHint`. The other
# tiers are `read_only` and `mutating`; only this one claims destruction.
_DANGEROUS_TIER = "dangerous"

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
                "annotations": _annotations_for(tool),
                "_engine": {
                    "risk_tier": tool.risk_tier,
                    "permission_requirement": tool.permission_requirement,
                    "idempotency_required": tool.idempotency_required,
                },
            }
        )
    return specs


def _annotations_for(tool: AgentTool) -> types.ToolAnnotations:
    """Express the catalog's risk vocabulary as MCP tool annotations.

    The catalog already knows whether a tool mutates, whether the engine gates
    it behind human approval, and whether it is idempotent. MCP 2.0 has a
    standard field for exactly that, so before this the information was carried
    only in the private ``_engine`` key - readable by this repository and by
    nothing else. A client deciding whether to auto-approve a call had to guess
    from the tool name.

    ``read_only_hint`` reuses the catalog's own :attr:`~AgentTool.is_mutating`
    property rather than re-deriving the string comparison, so the annotation
    and the engine's own risk decision cannot drift apart.

    ``destructive_hint`` is set only for the ``dangerous`` tier. The protocol
    defines it as meaningful only when the tool is not read-only, and defaulting
    it true for every mutating tool would flatten the catalog's own distinction
    between an ordinary edit and a destructive one.

    ``open_world_hint`` is deliberately left unset. It asks whether the tool
    reaches an open set of external entities, and these tools address the
    engine's own vault - but "unset" is an honest absence here rather than a
    claim in either direction.
    """
    return types.ToolAnnotations(
        read_only_hint=not tool.is_mutating,
        destructive_hint=tool.risk_tier == _DANGEROUS_TIER,
        idempotent_hint=tool.idempotency_required,
    )


def _warn_on_non_conforming_names(tools: list[types.Tool]) -> None:
    """Log any advertised tool name that violates SEP-986.

    Uses the SDK's own validator rather than a local regex so the rule cannot
    drift from the specification the connecting client enforces.
    """
    for tool in tools:
        result = validate_tool_name(tool.name)
        if not result.is_valid or result.warnings:
            logger.warning(
                "authoring tool name %r does not conform to SEP-986: %s",
                tool.name,
                "; ".join(result.warnings),
            )


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

    Both failure modes are returned as error-flagged tool results rather than
    raised. The handler is registered on the low-level server, which answers a
    raised exception as a top-level JSON-RPC error the calling client raises on -
    the agent would never see the text and so could not self-correct. An
    error-flagged result keeps the message in the model's turn, which is the
    behaviour this bridge depends on for an unknown tool name or a failed engine
    dispatch.

    Tool names arrive from the engine, so they are checked against SEP-986 on
    the way out. The high-level server validates names when it derives them from
    a function; building :class:`~mcp.types.Tool` directly bypasses that, and a
    name the client rejects is the same silent "connected but not exposed"
    failure the schema normalization exists to prevent. A non-conforming name is
    logged and still served - the engine owns the vocabulary, so refusing to
    advertise the tool would be a worse outcome than a warned-about one.
    """
    tools = [
        types.Tool(
            name=spec["name"],
            description=spec["description"],
            input_schema=spec["inputSchema"],
            annotations=spec["annotations"],
        )
        for spec in build_tool_specs(snapshot)
    ]
    _warn_on_non_conforming_names(tools)
    known = {tool.name for tool in snapshot.tools}

    def _error(message: str) -> types.CallToolResult:
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=message)],
            is_error=True,
        )

    async def _on_list_tools(
        _ctx: ServerRequestContext[Any],
        _params: types.PaginatedRequestParams | None,
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=tools)

    async def _on_call_tool(
        _ctx: ServerRequestContext[Any],
        params: types.CallToolRequestParams,
    ) -> types.CallToolResult:
        name = params.name
        if name not in known:
            return _error(f"unknown authoring tool: {name!r}")
        try:
            result = await dispatch(name, params.arguments or {})
        except Exception as exc:
            return _error(f"authoring tool {name!r} failed: {exc}")
        return types.CallToolResult(
            content=[
                types.TextContent(type="text", text=json.dumps(result, default=str))
            ]
        )

    return Server(
        server_name,
        version=package_version(),
        on_list_tools=_on_list_tools,
        on_call_tool=_on_call_tool,
    )

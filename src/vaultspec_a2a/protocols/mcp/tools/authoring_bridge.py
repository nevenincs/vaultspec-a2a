"""Bridge the engine's served tool catalog into agent-facing MCP tools (ADR R4).

The engine owns the agent-tool catalog; this module turns a per-run
:class:`~vaultspec_a2a.authoring.catalog.CatalogSnapshot` into MCP tool
specifications (name, description, input schema) the spawned CLI agent sees.
Execution is not performed here — it routes back through the engine's
run-scoped execute endpoint via
:func:`~vaultspec_a2a.authoring.catalog.execute_agent_tool`; the ACP session
wiring that binds these specs to a live run is S19.

Only the catalog's tools are surfaced: the agent gets propose and read tools
and no vault-write path, because no filesystem-write tool exists in the engine
catalog by construction.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ....authoring.catalog import CatalogSnapshot

__all__ = ["McpToolSpec", "build_tool_specs"]

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

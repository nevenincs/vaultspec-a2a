"""Served agent-tool catalog: fetch, snapshot, and execute routing (ADR R4).

The engine owns the agent-tool catalog and versions it with itself
(``schema_version = authoring.semantic_tools.v1``). Rather than hand-roll
request builders that would silently drift, the bridge fetches the catalog once
per run, snapshots it, and surfaces its tools to the spawned agent session;
tool execution is routed back through the engine's run-scoped execute endpoint
under the calling role's actor token.

This module owns the engine-facing half: parsing the catalog into a typed
snapshot and issuing the ``AgentToolCall`` to ``/v1/runs/{run_id}/agent-tools/
execute``. Turning a snapshot into MCP tool registrations lives in
``protocols/mcp/tools`` and the ACP session wiring in ``providers`` (S19).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ._envelope import AuthoringResponse, Denial
    from .client import AuthoringClient

__all__ = [
    "CATALOG_SCHEMA_VERSION",
    "AgentTool",
    "CatalogSnapshot",
    "execute_agent_tool",
    "fetch_catalog",
]

CATALOG_SCHEMA_VERSION = "authoring.semantic_tools.v1"
_CATALOG_PATH = "/v1/agent-tools"


@dataclass(frozen=True)
class AgentTool:
    """One served agent tool as the bridge needs it (ADR R4).

    The bridge mirrors ``name`` + ``input_schema`` + ``risk_tier`` +
    ``permission_requirement`` — a higher-level vocabulary than the wire route
    names — rather than assuming a 1:1 mapping to routes.
    """

    name: str
    description: str
    input_schema: dict[str, Any]
    risk_tier: str
    permission_requirement: str
    idempotency_required: bool
    commands: tuple[str, ...]

    @property
    def is_mutating(self) -> bool:
        """True when the tool changes state (not a read-only projection)."""
        return self.risk_tier != "read_only"

    @property
    def requires_human_approval(self) -> bool:
        """True when the engine gates the tool behind human approval."""
        return self.permission_requirement == "human_approval_required"


@dataclass(frozen=True)
class CatalogSnapshot:
    """An immutable per-run snapshot of the served agent-tool catalog."""

    schema_version: str
    tools: tuple[AgentTool, ...]

    def tool_names(self) -> tuple[str, ...]:
        """Return the tool names in catalog order."""
        return tuple(tool.name for tool in self.tools)

    def get(self, name: str) -> AgentTool | None:
        """Return the tool with ``name``, or None."""
        return next((tool for tool in self.tools if tool.name == name), None)


def parse_catalog(data: dict[str, Any]) -> CatalogSnapshot:
    """Parse the catalog ``data`` payload into a :class:`CatalogSnapshot`.

    Raises ``ValueError`` on a schema-version mismatch or a malformed tool
    entry, so a drifted engine surface fails loudly rather than silently
    bridging a partial catalog.
    """
    schema_version = data.get("schema_version")
    if schema_version != CATALOG_SCHEMA_VERSION:
        raise ValueError(
            f"unexpected catalog schema_version {schema_version!r}; "
            f"expected {CATALOG_SCHEMA_VERSION!r}"
        )
    raw_tools = data.get("tools")
    if not isinstance(raw_tools, list):
        raise ValueError("catalog payload missing a 'tools' list")
    tools: list[AgentTool] = []
    for entry in raw_tools:
        if not isinstance(entry, dict):
            raise ValueError("catalog tool entry is not an object")
        name = entry.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError("catalog tool entry missing a name")
        input_schema = entry.get("input_schema")
        raw_commands = entry.get("commands")
        commands = (
            tuple(str(c) for c in raw_commands)
            if isinstance(raw_commands, list)
            else ()
        )
        tools.append(
            AgentTool(
                name=name,
                description=str(entry.get("description", "")),
                input_schema=input_schema if isinstance(input_schema, dict) else {},
                risk_tier=str(entry.get("risk_tier", "")),
                permission_requirement=str(entry.get("permission_requirement", "")),
                idempotency_required=bool(entry.get("idempotency_required", False)),
                commands=commands,
            )
        )
    return CatalogSnapshot(schema_version=schema_version, tools=tuple(tools))


async def fetch_catalog(client: AuthoringClient) -> CatalogSnapshot:
    """Fetch and snapshot the served agent-tool catalog for a run."""
    response = await client.get(_CATALOG_PATH)
    if not isinstance(response.data, dict):
        raise ValueError("catalog response data is not an object")
    return parse_catalog(response.data)


async def execute_agent_tool(
    client: AuthoringClient,
    *,
    run_id: str,
    command: str,
    tool_call_id: str,
    name: str,
    tool_input: dict[str, Any],
    idempotency_key: str,
    actor_token: str | None = None,
) -> AuthoringResponse | Denial:
    """Execute a bridged tool through the engine's run-scoped execute endpoint.

    The route deserializes a ``CommandEnvelope<AgentToolCall>``: the envelope
    carries the ``command`` discriminator and idempotency key, the payload is
    the ``AgentToolCall`` (``{tool_call_id, name, input}``). Execution is routed
    to ``/v1/runs/{run_id}/agent-tools/execute`` under the calling role's actor
    token. The engine owns permission gating (mutating tools carry
    ``human_approval_required``); a business denial returns as a
    :class:`Denial` value rather than raising.
    """
    return await client.post_command(
        f"/v1/runs/{run_id}/agent-tools/execute",
        command=command,
        payload={
            "tool_call_id": tool_call_id,
            "name": name,
            "input": tool_input,
        },
        idempotency_key=idempotency_key,
        actor_token=actor_token,
    )

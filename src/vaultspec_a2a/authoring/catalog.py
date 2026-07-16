"""Served agent-tool catalog: fetch, snapshot, and execute routing.

The engine owns the agent-tool catalog and versions it with itself
(``schema_version = authoring.semantic_tools.v1``). Rather than hand-roll
request builders that would silently drift, the bridge fetches the catalog once
per run, snapshots it, and surfaces its tools to the spawned agent session;
tool execution is routed back through the engine's run-scoped execute endpoint
under the calling role's actor token.

This module owns the engine-facing half: parsing the catalog into a typed
snapshot and issuing the ``AgentToolCall`` to ``/v1/runs/{run_id}/agent-tools/
execute``. Turning a snapshot into MCP tool registrations lives in
``protocols/mcp/tools`` and the ACP session wiring in ``providers``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from ._envelope import AuthoringResponse
from ._ids import derive_idempotency_key

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ._envelope import Denial
    from .client import AuthoringClient

__all__ = [
    "CATALOG_SCHEMA_VERSION",
    "AgentTool",
    "CatalogSnapshot",
    "execute_agent_tool",
    "fetch_catalog",
    "make_tool_dispatch",
    "resolve_tool_command",
]

CATALOG_SCHEMA_VERSION = "authoring.semantic_tools.v1"
_CATALOG_PATH = "/v1/agent-tools"


@dataclass(frozen=True)
class AgentTool:
    """One served agent tool as the bridge needs it.

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


def resolve_tool_command(tool: AgentTool, arguments: dict[str, Any]) -> str:
    """Resolve the engine command discriminator for a tool call.

    Single-command tools (e.g. ``read_context`` -> ``read_context``) map
    directly. Multi-command tools carry a discriminator in their arguments:
    ``propose_changeset`` keys on ``operation`` (create -> create_proposal,
    append -> append_draft, replace -> replace_draft) and ``cancel`` keys on
    ``target`` (proposal -> cancel_proposal, run -> cancel_run). The
    discriminator value is matched against the command names the catalog
    declares, so the mapping follows the engine rather than a hardcoded table.
    """
    if len(tool.commands) == 1:
        return tool.commands[0]
    if not tool.commands:
        return tool.name
    discriminator = arguments.get("operation") or arguments.get("target")
    if isinstance(discriminator, str):
        for command in tool.commands:
            if discriminator in command:
                return command
    return tool.commands[0]


def make_tool_dispatch(
    client: AuthoringClient,
    *,
    run_id: str,
    actor_token: str,
    snapshot: CatalogSnapshot,
) -> Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]:
    """Build the dispatcher the authoring MCP server routes tool calls through.

    Each call resolves the command from the catalog, issues the run-scoped
    execute, and returns the engine ``data`` payload (or a denial rendered as a
    value). Idempotency keys are derived from stable run-local material so a
    replayed call dedupes at the engine. Unknown tools fail loudly.
    """

    async def dispatch(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        tool = snapshot.get(name)
        if tool is None:
            raise ValueError(f"tool {name!r} is not in the run's catalog snapshot")
        command = resolve_tool_command(tool, arguments)
        idempotency_key = derive_idempotency_key(run_id, command, uuid4().hex)
        result = await execute_agent_tool(
            client,
            run_id=run_id,
            command=command,
            tool_call_id=uuid4().hex,
            name=name,
            tool_input=arguments,
            idempotency_key=idempotency_key,
            actor_token=actor_token,
        )
        if isinstance(result, AuthoringResponse):
            data = result.data
            return data if isinstance(data, dict) else {"result": data}
        return {
            "status": "denied",
            "denial_kind": result.denial_kind,
            "reason": result.reason,
        }

    return dispatch

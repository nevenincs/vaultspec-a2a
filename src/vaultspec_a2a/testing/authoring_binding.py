"""The one fixture builder for a real :class:`AuthoringToolBinding`.

A binding's catalog is the same two-tool shape everywhere a test needs one
bridged to a model: a read-only ``read_context`` and a mutating
``propose_changeset``, matching the production ``AgentTool`` and
``CatalogSnapshot`` shapes exactly rather than a test-only stand-in. Callers
choose the HTTP transport (``server_url``), the stdio transport
(``engine_base_url`` + ``run_id``), or neither, exactly as
:class:`AuthoringToolBinding` itself allows.
"""

from __future__ import annotations

from ..authoring import AgentTool, CatalogSnapshot
from ..providers._acp_authoring import AuthoringToolBinding

__all__ = ["authoring_tool_binding"]

#: The bearer forwarded to the bridge so it can reach the engine, matching
#: the machine bearer an engine boot mints.
DEFAULT_BEARER_TOKEN = "machine-bearer-xyz"

#: The calling role's per-actor token the bridge routes execution under.
DEFAULT_ACTOR_TOKEN = "actor-token-abc"


def authoring_tool_binding(
    *,
    server_url: str | None = None,
    engine_base_url: str | None = None,
    run_id: str | None = None,
    bearer_token: str = DEFAULT_BEARER_TOKEN,
    actor_token: str = DEFAULT_ACTOR_TOKEN,
) -> AuthoringToolBinding:
    """A real binding over the fixture catalog, for either transport.

    Args:
        server_url: Loopback URL of the HTTP MCP server, for the ACP transport.
        engine_base_url: Loopback origin of the engine, for the stdio transport.
        run_id: The engine run id the stdio bridge routes execution under.
        bearer_token: The machine bearer forwarded to the bridge.
        actor_token: The calling role's per-actor token.

    Returns:
        The binding, carrying whichever transport fields were passed.
    """
    snapshot = CatalogSnapshot(
        schema_version="authoring.semantic_tools.v1",
        tools=(
            AgentTool(
                name="read_context",
                description="read",
                input_schema={"type": "object"},
                risk_tier="read_only",
                permission_requirement="auto_permitted",
                idempotency_required=False,
                commands=("read_context",),
            ),
            AgentTool(
                name="propose_changeset",
                description="propose",
                input_schema={"type": "object"},
                risk_tier="mutating",
                permission_requirement="human_approval_required",
                idempotency_required=True,
                commands=("create_proposal",),
            ),
        ),
    )
    return AuthoringToolBinding(
        snapshot=snapshot,
        bearer_token=bearer_token,
        actor_token=actor_token,
        server_url=server_url,
        engine_base_url=engine_base_url,
        run_id=run_id,
    )

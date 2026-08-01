"""Protocol adaptation for the Vaultspec A2A Orchestrator.

A2A is an agent-to-agent orchestration framework and delivers no MCP server of
its own. What lives here is the outbound direction only: the per-run authoring
bridge the orchestrator spawns as a child of a provider CLI so that agent can
reach the engine's vault-authoring tool catalog. See
:mod:`vaultspec_a2a.protocols.mcp.authoring_stdio`.

Keep protocol adaptation at this boundary. Runtime orchestration remains in
:mod:`vaultspec_a2a.control`.
"""

__all__: list[str] = []

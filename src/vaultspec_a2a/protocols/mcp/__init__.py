"""Per-run MCP bridging for the engine's authoring tools.

This package serves the orchestrator's outbound direction only: it builds and
runs the per-run bridge that advertises the engine's vault-authoring tool
catalog to a coder CLI the orchestrator spawns. A2A delivers no MCP server of
its own, so nothing here is a hosted or long-lived surface.

The bridge is spawned per run as a subprocess of the provider CLI::

    python -m vaultspec_a2a.protocols.mcp.authoring_stdio

Import weight is load-bearing: the bridge must reach serving within the CLI's
MCP-ready window, so this package deliberately holds no eager imports.
"""

__all__: list[str] = []

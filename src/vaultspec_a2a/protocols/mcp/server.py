"""MCP Server tool surface for the Vaultspec A2A Orchestrator.

Exposes the LangGraph orchestrator as standard MCP tools so external IDEs
(Cursor, Windsurf) can trigger agent workflows without custom plugins.

The MCP server must:
- Expose stable, synchronous-looking tools (list_threads, get_thread_status,
  send_message)
- Return immediately rather than blocking the MCP connection for the full
  execution duration
- Not leak LangGraph-specific internals (node IDs, graph state) over the wire

These tools OBSERVE and STEER work that already exists; they do not start it.
Every non-mock preset requires a per-role actor token, the engine is the sole
minter of those tokens, and this server holds only its own gateway bearer, so a
start tool here could reach nothing but acceptance scaffolding. Runs are started
by the engine.

Available tools:
- ``list_threads``:              List existing orchestration threads
- ``get_thread_status``:         Query the status of a specific thread
- ``send_message``:              Send a follow-up message into an existing thread
- ``respond_to_permission``:     Respond to a pending permission request
- ``get_team_status``:           Get agent lifecycle states and active threads
- ``get_pending_permissions``:   List outstanding permission requests
- ``list_team_presets``:         List available team presets with details
- ``delete_thread``:             Permanently delete a thread and its data
- ``archive_thread``:            Archive a completed/failed/cancelled thread
- ``cancel_thread``:             Cancel a running thread
"""

from mcp.server.mcpserver import MCPServer

from ...utils import package_version

__all__ = ["mcp"]

mcp = MCPServer(
    name="vaultspec-orchestrator",
    title="Vaultspec A2A Orchestrator",
    # Served to every client as `serverInfo`. Read from the installed
    # distribution so the wire value cannot drift from the built package.
    version=package_version(),
    instructions=(
        "Vaultspec A2A Orchestrator — tools for observing and steering "
        "multi-agent coding workflows. Runs are started by the engine, not from "
        "here.\n\n"
        "Start from the listing, which is the only source of thread IDs:\n"
        "  1. list_threads() → find the thread and its thread_id\n"
        "  2. get_thread_status(thread_id) → poll until "
        "status is 'completed' or 'failed'; inspect repair status and "
        "execution readiness before assuming a pause is actionable\n"
        "  3. send_message(thread_id, ...) → inject follow-up input\n\n"
        "When a thread pauses for approval:\n"
        "  1. get_pending_permissions() → list request IDs, thread IDs "
        "and option IDs\n"
        "  2. respond_to_permission(thread_id, permission_request_id,"
        " option_id) → unblock thread\n\n"
        "get_team_status() for overall agent health and active thread count."
    ),
)

# Side-effect imports: each module registers @mcp.tool() handlers on import.
from .tools import discovery, messaging, thread_lifecycle, thread_query

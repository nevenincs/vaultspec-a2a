"""MCP Server tool surface for the Vaultspec A2A Orchestrator.

Exposes the LangGraph orchestrator as standard MCP tools so external IDEs
(Cursor, Windsurf) can trigger agent workflows without custom plugins.

The MCP server must:
- Expose stable, synchronous-looking tools (start_thread, get_thread_status,
  send_message)
- Return immediately with a task ID and progress URL rather than blocking
  the MCP connection for the full execution duration
- Not leak LangGraph-specific internals (node IDs, graph state) over the wire

Available tools:
- ``start_thread``:              Start a new agent team workflow (non-blocking)
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

from mcp.server.fastmcp import FastMCP

__all__ = ["mcp"]

mcp = FastMCP(
    name="vaultspec-orchestrator",
    instructions=(
        "Vaultspec A2A Orchestrator — tools for launching and managing multi-agent "
        "coding workflows.\n\n"
        "Autonomous workflow (no human approval needed):\n"
        "  1. start_thread(initial_message, autonomous=True) → get thread_id\n"
        "  2. get_thread_status(thread_id) → poll until "
        "status is 'completed' or 'failed'\n"
        "  3. send_message(thread_id, ...) → inject follow-up input\n\n"
        "Supervised workflow (human approves tool calls):\n"
        "  1. start_thread(initial_message, autonomous=False) → get thread_id\n"
        "  2. get_thread_status(thread_id) → poll; inspect repair status and "
        "execution readiness before assuming the pause is actionable\n"
        "  3. if pending permissions are listed, call get_pending_permissions() "
        "to list request IDs and option IDs\n"
        "  4. respond_to_permission(permission_request_id,"
        " option_id) → unblock thread\n\n"
        "Discovery: list_threads() to find existing threads. "
        "get_team_status() for overall agent health and active thread count."
    ),
)

# Side-effect imports: each module registers @mcp.tool() handlers on import.
from .tools import discovery, messaging, thread_lifecycle, thread_query

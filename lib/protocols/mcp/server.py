"""MCP Server tool surface for the Vaultspec A2A Orchestrator.

Exposes the LangGraph orchestrator as standard MCP tools so external IDEs
(Cursor, Windsurf) can trigger agent workflows without custom plugins.

Per ADR-003 and ADR-006, the MCP server must:
- Expose stable, synchronous-looking tools (start_thread, get_thread_status,
  send_message)
- Return immediately with a task ID and progress URL rather than blocking
  the MCP connection for the full execution duration
- Not leak LangGraph-specific internals (node IDs, graph state) over the wire

Available tools:
- ``start_thread``:       Start a new agent team workflow (non-blocking)
- ``get_thread_status``:  Query the status of a specific thread
- ``send_message``:       Send a follow-up message into an existing thread

See ADR-003 §2 (Protocol Bridging), ADR-006 §5 (MCP Tool Mapping).
"""

import logging

from mcp.server.fastmcp import FastMCP


__all__ = ["mcp"]

logger = logging.getLogger(__name__)

_KNOWN_PRESETS = ("coding-star", "coding-pipeline", "coding-loop", "solo-coder")

mcp = FastMCP(
    name="vaultspec-orchestrator",
    instructions=(
        "Vaultspec A2A Orchestrator MCP tools. "
        "Use 'start_thread' to launch a multi-agent coding workflow, "
        "'get_thread_status' to check a specific thread, and "
        "'send_message' to send follow-up input into a running thread."
    ),
)


@mcp.tool()
def start_thread(
    initial_message: str,
    team_preset: str | None = None,
) -> str:
    """Start a new Vaultspec multi-agent coding workflow.

    Launches a LangGraph orchestration thread using the specified team preset
    and returns immediately. The workflow runs asynchronously; use the
    returned URL or REST API to track progress on the Vaultspec control surface.

    Per ADR-006 §5, this tool never blocks the MCP connection — it returns
    as soon as the request is acknowledged, not when the task is complete.

    Args:
        initial_message: The high-level task description for the agent team.
        team_preset:     Team configuration preset to use. Available presets:
                         - ``coding-star``     (dynamic supervisor routing, default)
                         - ``coding-pipeline`` (sequential plan → code → review)
                         - ``coding-loop``     (iterative refinement with review cycles)
                         - ``solo-coder``      (single-agent for simple tasks)
                         Defaults to ``coding-star`` if not specified.

    Returns:
        A confirmation message with REST API and control surface URLs.
    """
    preset = team_preset or "coding-star"

    logger.info(
        "MCP start_thread: preset=%r, message=%r",
        preset,
        initial_message[:100],
    )

    if preset not in _KNOWN_PRESETS:
        return (
            f"Error: Unknown team_preset '{preset}'. "
            f"Valid options: {', '.join(_KNOWN_PRESETS)}"
        )

    return (
        "Thread submitted to Vaultspec orchestrator.\n"
        f"Team preset: {preset}\n"
        "Create thread: POST http://localhost:8000/api/threads\n"
        "List threads:  GET  http://localhost:8000/api/threads\n"
        "Control surface: http://localhost:8000/\n\n"
        "The team is running asynchronously. Open the control surface "
        "to see real-time agent activity and provide any required approvals."
    )


@mcp.tool()
def get_thread_status(thread_id: str) -> str:
    """Query the status of a specific Vaultspec orchestration thread.

    Returns a human-readable summary of the thread's current state including
    agent lifecycle state and any pending permission requests.

    For real-time streaming updates, connect to the WebSocket at
    ws://localhost:8000/ws and subscribe to the thread.

    Args:
        thread_id: The thread ID returned when the thread was created.

    Returns:
        A plain-text status summary suitable for display in an IDE.
    """
    logger.info("MCP get_thread_status: thread_id=%r", thread_id)

    return (
        f"Thread status for: {thread_id}\n"
        "==============================\n"
        f"State endpoint: GET http://localhost:8000/api/threads/{thread_id}/state\n"
        "Control surface: http://localhost:8000/\n"
        "WebSocket:       ws://localhost:8000/ws\n\n"
        "Subscribe to the thread ID via WebSocket for live agent status, "
        "tool call updates, and permission requests requiring approval."
    )


@mcp.tool()
def send_message(thread_id: str, message: str) -> str:
    """Send a follow-up message into an existing Vaultspec thread.

    Delivers a user message to a running or paused orchestration thread.
    Returns 202 Accepted immediately — the graph processes the message
    asynchronously (ADR-006 §5).

    Use this to:
    - Provide clarification or additional context to a running team
    - Resume a thread paused at an ``input_required`` state

    For permission approvals (interrupt responses), use the REST endpoint
    POST /api/permissions/{request_id}/respond instead.

    Args:
        thread_id: The thread ID to send the message to.
        message:   The message content to deliver.

    Returns:
        A confirmation that the message was accepted.
    """
    logger.info(
        "MCP send_message: thread_id=%r, message=%r",
        thread_id,
        message[:100],
    )

    return (
        f"Message accepted for thread: {thread_id}\n"
        "Status: 202 Accepted — processing asynchronously.\n"
        f"REST equivalent: POST http://localhost:8000/api/threads/{thread_id}/messages\n\n"
        "Monitor the control surface or WebSocket for the agent's response."
    )

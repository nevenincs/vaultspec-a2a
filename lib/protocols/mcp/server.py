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

from pathlib import Path
from urllib.parse import urlparse

import httpx

from mcp.server.fastmcp import FastMCP

from ...core.config import settings


__all__ = ["mcp"]

logger = logging.getLogger(__name__)

# M29: MCP HTTP request timeouts (seconds) — named constants so they can be
# located and adjusted without hunting for magic numbers in each tool function.
_MCP_CREATE_TIMEOUT = 30.0  # POST /api/threads (synchronous setup overhead)
_MCP_QUERY_TIMEOUT = 15.0  # GET /api/threads/{id}/state and POST /api/messages

# M28: derive known presets from the bundled preset TOML files so that adding
# a new preset file automatically makes it available as an MCP option without
# requiring a code change here.
_PRESET_TEAMS_DIR = Path(__file__).parent.parent.parent / "core" / "presets" / "teams"
_KNOWN_PRESETS: frozenset[str] = frozenset(
    p.stem for p in _PRESET_TEAMS_DIR.glob("*.toml")
) or frozenset({"coding-star", "coding-pipeline", "coding-loop", "solo-coder"})

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
async def start_thread(
    initial_message: str,
    team_preset: str | None = None,
) -> str:
    """Start a new Vaultspec agent team workflow. Returns immediately with thread_id.

    Launches a LangGraph orchestration thread using the specified team preset
    and returns immediately with the thread ID.  The workflow runs
    asynchronously in autonomous mode (no human approval interrupts).  Use
    ``get_thread_status`` to check progress or open the control surface for
    live streaming.

    Args:
        initial_message: The high-level task description for the agent team.
        team_preset:     Team configuration preset to use. Available presets:
                         ``coding-star``, ``coding-pipeline``, ``coding-loop``,
                         ``solo-coder``.  Defaults to ``coding-star``.

    Returns:
        A confirmation message with the thread ID and monitoring URLs.
    """
    preset = team_preset or "coding-star"
    if preset not in _KNOWN_PRESETS:
        return (
            f"Error: Unknown preset {preset!r}. "
            f"Valid: {', '.join(sorted(_KNOWN_PRESETS))}"
        )
    try:
        async with httpx.AsyncClient(timeout=_MCP_CREATE_TIMEOUT) as client:
            resp = await client.post(
                f"{settings.api_base_url}/api/threads",
                json={
                    "title": initial_message[:80],
                    "initial_message": initial_message,
                    "team_preset": preset,
                    "autonomous": True,
                },
            )
            resp.raise_for_status()
            data = resp.json()
        thread_id = data["thread_id"]
        return (
            f"Thread started: {thread_id}\n"
            f"Preset: {preset}\n"
            f"Monitor: {settings.api_base_url}/\n"
            f"Status: GET {settings.api_base_url}/api/threads/{thread_id}/state"
        )
    except httpx.HTTPStatusError as exc:
        return f"Error {exc.response.status_code}: {exc.response.text[:200]}"
    except httpx.RequestError as exc:
        return (
            f"Connection error "
            f"(is the server running at {settings.api_base_url}?): {exc}"
        )


@mcp.tool()
async def get_thread_status(thread_id: str) -> str:
    """Query the current status and message count of a thread.

    Returns a human-readable summary of the thread's current state including
    message count and checkpoint ID.  For real-time streaming updates, connect
    to the WebSocket endpoint listed in the response.

    Args:
        thread_id: The thread ID returned by ``start_thread``.

    Returns:
        A plain-text status summary suitable for display in an IDE.
    """
    try:
        async with httpx.AsyncClient(timeout=_MCP_QUERY_TIMEOUT) as client:
            resp = await client.get(
                f"{settings.api_base_url}/api/threads/{thread_id}/state"
            )
            resp.raise_for_status()
            data = resp.json()
        status = data.get("status", "unknown")
        msg_count = len(data.get("messages", []))
        checkpoint = data.get("checkpoint_id") or "none"
        return (
            f"Thread: {thread_id}\n"
            f"Status: {status}\n"
            f"Messages: {msg_count}\n"
            f"Checkpoint: {checkpoint}\n"
            # L16/L18: derive ws/wss scheme from API base URL scheme.
            f"Live: {'wss' if urlparse(settings.api_base_url).scheme == 'https' else 'ws'}"  # noqa: E501
            f"://{urlparse(settings.api_base_url).netloc}/ws"
        )
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:  # noqa: PLR2004
            return f"Thread {thread_id!r} not found."
        return f"Error {exc.response.status_code}: {exc.response.text[:200]}"
    except httpx.RequestError as exc:
        return f"Connection error: {exc}"


@mcp.tool()
async def send_message(thread_id: str, message: str) -> str:
    """Send a follow-up message into an existing thread (async, returns 202).

    Delivers a user message to a running or paused orchestration thread.
    Returns immediately — the graph processes the message asynchronously
    (ADR-006 §5).

    Args:
        thread_id: The thread ID to send the message to.
        message:   The message content to deliver.

    Returns:
        A confirmation that the message was accepted.
    """
    try:
        async with httpx.AsyncClient(timeout=_MCP_QUERY_TIMEOUT) as client:
            resp = await client.post(
                f"{settings.api_base_url}/api/threads/{thread_id}/messages",
                json={"content": message},
            )
            resp.raise_for_status()
        return f"Message delivered to thread {thread_id}."
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:  # noqa: PLR2004
            return f"Thread {thread_id!r} not found."
        return f"Error {exc.response.status_code}: {exc.response.text[:200]}"
    except httpx.RequestError as exc:
        return f"Connection error: {exc}"

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

# MCP-M1: _PRESET_TEAMS_DIR uses Path(__file__)-relative navigation to locate
# preset TOML files in the sibling core/presets/teams/ directory.  This works
# correctly in development (editable installs) but may require adjustment when
# the package is distributed as a wheel if the data files are not included in
# the wheel's source tree.  In that case, use importlib.resources or a
# settings-based override to locate the preset directory.
_PRESET_TEAMS_DIR = Path(__file__).parent.parent.parent / "core" / "presets" / "teams"
_HARDCODED_PRESETS: frozenset[str] = frozenset(
    {"coding-star", "coding-pipeline", "coding-loop", "solo-coder"}
)
_discovered: frozenset[str] = frozenset(
    p.stem for p in _PRESET_TEAMS_DIR.glob("*.toml")
)
# MCP-H2: warn explicitly when falling back to hardcoded presets so that
# packaged deployments notice missing TOML files rather than silently using
# a stale list.
if _discovered:
    _KNOWN_PRESETS: frozenset[str] = _discovered
else:
    logger.warning(
        "Using hardcoded preset fallback — TOML files not found at %s",
        _PRESET_TEAMS_DIR,
    )
    _KNOWN_PRESETS = _HARDCODED_PRESETS

mcp = FastMCP(
    name="vaultspec-orchestrator",
    instructions=(
        "Vaultspec A2A Orchestrator MCP tools. "
        "Use 'start_thread' to launch a multi-agent coding workflow, "
        "'get_thread_status' to check a specific thread, and "
        "'send_message' to send follow-up input into a running thread."
    ),
)


def _ws_url_from_api_base(api_base_url: str) -> str:
    """Derive a WebSocket URL from the REST API base URL.

    MCP-M2: Parse the URL once and reuse the parsed components.  Strip any
    userinfo (credentials) from the netloc before exposing in tool output to
    prevent credential leakage.
    """
    parsed = urlparse(api_base_url)
    ws_scheme = "wss" if parsed.scheme == "https" else "ws"
    # Strip credentials (user:password@host → host)
    netloc_no_creds = parsed.hostname or ""
    if parsed.port:
        netloc_no_creds = f"{netloc_no_creds}:{parsed.port}"
    return f"{ws_scheme}://{netloc_no_creds}/ws"


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
    except httpx.ConnectError as exc:
        # MCP-H1: network-level failure (server not running, DNS error, etc.)
        return (
            f"Network error: could not connect to {settings.api_base_url}. "
            f"Is the server running? Detail: {exc}"
        )
    except httpx.TimeoutException as exc:
        # MCP-H1: request timed out waiting for the server
        return f"Timeout: the server at {settings.api_base_url} did not respond. Detail: {exc}"
    except httpx.HTTPStatusError as exc:
        # MCP-H1: server responded with an HTTP error status
        return f"Server error {exc.response.status_code}: {exc.response.text[:200]}"
    except httpx.RequestError as exc:
        # MCP-H1: other transport-level errors (SSL, proxy, etc.)
        return f"Connection error (is the server running at {settings.api_base_url}?): {exc}"


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
    # MCP-M2: parse URL once and reuse; strip credentials from output.
    ws_live_url = _ws_url_from_api_base(settings.api_base_url)
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
            f"Live: {ws_live_url}"
        )
    except httpx.ConnectError as exc:
        # MCP-H1: network-level failure
        return (
            f"Network error: could not connect to {settings.api_base_url}. "
            f"Is the server running? Detail: {exc}"
        )
    except httpx.TimeoutException as exc:
        # MCP-H1: timeout
        return f"Timeout: the server at {settings.api_base_url} did not respond. Detail: {exc}"
    except httpx.HTTPStatusError as exc:
        # MCP-H1: application-level HTTP error
        if exc.response.status_code == 404:  # noqa: PLR2004
            return f"Thread {thread_id!r} not found."
        return f"Server error {exc.response.status_code}: {exc.response.text[:200]}"
    except httpx.RequestError as exc:
        # MCP-H1: other transport errors
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
    except httpx.ConnectError as exc:
        # MCP-H1: network-level failure
        return (
            f"Network error: could not connect to {settings.api_base_url}. "
            f"Is the server running? Detail: {exc}"
        )
    except httpx.TimeoutException as exc:
        # MCP-H1: timeout
        return f"Timeout: the server at {settings.api_base_url} did not respond. Detail: {exc}"
    except httpx.HTTPStatusError as exc:
        # MCP-H1: application-level HTTP error
        if exc.response.status_code == 404:  # noqa: PLR2004
            return f"Thread {thread_id!r} not found."
        return f"Server error {exc.response.status_code}: {exc.response.text[:200]}"
    except httpx.RequestError as exc:
        # MCP-H1: other transport errors (SSL, proxy, etc.)
        return f"Connection error: {exc}"

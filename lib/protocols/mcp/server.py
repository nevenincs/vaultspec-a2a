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
- ``start_thread``:              Start a new agent team workflow (non-blocking)
- ``list_threads``:              List existing orchestration threads
- ``get_thread_status``:         Query the status of a specific thread
- ``send_message``:              Send a follow-up message into an existing thread
- ``respond_to_permission``:     Respond to a pending permission request
- ``get_team_status``:           Get agent lifecycle states and active threads
- ``get_pending_permissions``:   List outstanding permission requests
- ``list_team_presets``:         List available team presets with details
- ``cancel_thread``:             Cancel a running thread

See ADR-003 §2 (Protocol Bridging), ADR-006 §5 (MCP Tool Mapping).
"""

import logging

from typing import Annotated
from urllib.parse import urlparse

import httpx

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import Field

from ...core.config import settings
from ...core.team_config import discover_team_preset_ids


__all__ = ["mcp"]

logger = logging.getLogger(__name__)

# MCP-05: Shared httpx.AsyncClient — lazily created on first use and reused
# across all tool calls to avoid per-request connection setup overhead.
# The client has no base_url so it works with the runtime settings value.
#
# When the underlying event loop changes (e.g. between test functions), the
# client's transport raises "Event loop is closed".  ``_get_client()`` detects
# this via ``is_closed`` and transparently creates a fresh instance.
_shared_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    """Return the module-level shared httpx.AsyncClient, creating it if needed.

    The client is reused across all MCP tool invocations within the same event
    loop.  If the previous client was closed (e.g. event loop recycled between
    test runs), a new one is created automatically.
    """
    global _shared_client  # noqa: PLW0603
    if _shared_client is None or _shared_client.is_closed:
        _shared_client = httpx.AsyncClient()
    return _shared_client


def _reset_client() -> None:
    """Close and discard the shared client.  Used by test fixtures."""
    global _shared_client  # noqa: PLW0603
    if _shared_client is not None and not _shared_client.is_closed:
        # Synchronous close is fine in test teardown; the transport is idle.
        try:
            _shared_client._transport.__del__()  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001
            pass
    _shared_client = None

# M29: MCP HTTP request timeouts (seconds) — named constants so they can be
# located and adjusted without hunting for magic numbers in each tool function.
_MCP_CREATE_TIMEOUT = 30.0  # POST /api/threads (synchronous setup overhead)
_MCP_QUERY_TIMEOUT = 15.0  # GET /api/threads/{id}/state and POST /api/messages
_HTTP_NOT_FOUND = 404

# MCP-01: cap initial_message to prevent unbounded payloads from filling the
# LLM context window or triggering HTTP 413 errors from the control surface.
_MAX_INITIAL_MESSAGE_CHARS = 32_000  # ~8k tokens at 4 chars/token

# DYN-01: Dynamic preset discovery — delegates to the canonical
# discover_team_preset_ids() in team_config.py so adding/removing a TOML
# file automatically updates all surfaces with no code change required.
_KNOWN_PRESETS: frozenset[str] = discover_team_preset_ids()


mcp = FastMCP(
    name="vaultspec-orchestrator",
    instructions=(
        "Vaultspec A2A Orchestrator — tools for launching and managing multi-agent "
        "coding workflows.\n\n"
        "Autonomous workflow (no human approval needed):\n"
        "  1. start_thread(initial_message, autonomous=True) → get thread_id\n"
        "  2. get_thread_status(thread_id) → poll until status is 'completed' or 'failed'\n"
        "  3. send_message(thread_id, ...) → inject follow-up input\n\n"
        "Supervised workflow (human approves tool calls):\n"
        "  1. start_thread(initial_message, autonomous=False) → get thread_id\n"
        "  2. get_thread_status(thread_id) → poll; when status is 'input_required':\n"
        "  3. get_pending_permissions() → list request IDs and option IDs\n"
        "  4. respond_to_permission(permission_request_id, option_id) → unblock thread\n\n"
        "Discovery: list_threads() to find existing threads. "
        "get_team_status() for overall agent health and active thread count."
    ),
)



def _ws_url_from_api_base(api_base_url: str) -> str:
    """Derive a WebSocket URL from the REST API base URL.

    Converts ``http://host:port`` → ``ws://host:port/ws`` and
    ``https://host:port`` → ``wss://host:port/ws``.  Strips any
    userinfo (credentials) from the netloc to prevent credential leakage
    in tool output.
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
    initial_message: Annotated[str, Field(description="The coding task description for the agent team. Maximum 32,000 characters.")],
    team_preset: Annotated[str | None, Field(description="Team configuration preset ID. Use list_team_presets to discover all available presets. Defaults to 'vaultspec-adaptive-coder'.")] = None,
    autonomous: Annotated[bool, Field(description="If True (default), agents auto-approve all tool calls. Set to False to require manual approval via get_pending_permissions and respond_to_permission.")] = True,
    workspace_root: Annotated[str | None, Field(description="Absolute path to the project directory, e.g. 'C:/projects/myapp'. Enables .vault/ context injection and scopes file operations to this directory.")] = None,
) -> str:
    """Start a new multi-agent coding workflow and return a thread ID for tracking.

    Use this tool when the user wants to delegate a coding task to a team of
    AI agents.  Do NOT use this if there is already an active thread for the
    same task — call ``list_threads`` first to check, then use ``send_message``
    to continue an existing thread instead.

    The workflow runs asynchronously: this tool returns immediately with a
    thread ID and monitoring URLs.  It does NOT wait for agents to finish.
    Poll progress with ``get_thread_status`` or connect to the WebSocket URL
    in the response for real-time streaming.  The initial_message is capped at
    32,000 characters; longer messages are rejected.

    Returns a plain-text block containing:
    - Thread ID (UUID, e.g. '550e8400-e29b-41d4-a716-446655440000')
    - Team preset name used
    - REST monitoring URL
    - State query URL

    Args:
        initial_message: The coding task description for the agent team, e.g.
                         'Refactor the auth module to use JWT tokens'. Maximum
                         32,000 characters.
        team_preset:     Team configuration preset ID. Built-in presets:
                         'vaultspec-adaptive-coder', 'vaultspec-structured-coder',
                         'vaultspec-iterative-coder', 'vaultspec-solo-coder',
                         'vaultspec-continuous-audit'. Use ``list_team_presets``
                         to discover all available presets at runtime.
                         If omitted, defaults to 'vaultspec-adaptive-coder'.
        autonomous:      If True (default), agents auto-approve all tool calls
                         without human review. Set to False to require manual
                         approval — you will then need ``get_pending_permissions``
                         and ``respond_to_permission`` to unblock the workflow.
        workspace_root:  Absolute path to the project directory, e.g.
                         'C:/projects/myapp' or '/home/user/myapp'. Enables
                         automatic .vault/ context injection and scopes agent
                         file operations to this directory. If omitted, agents
                         run without project context.
    """
    # MCP-01: reject oversized payloads before making any HTTP call.
    if len(initial_message) > _MAX_INITIAL_MESSAGE_CHARS:
        raise ToolError(
            f"initial_message too long ({len(initial_message)} chars). "
            f"Maximum allowed: {_MAX_INITIAL_MESSAGE_CHARS} chars."
        )
    preset = team_preset or "vaultspec-adaptive-coder"
    if preset not in _KNOWN_PRESETS:
        raise ToolError(
            f"Unknown preset {preset!r}. "
            f"Valid: {', '.join(sorted(_KNOWN_PRESETS))}"
        )
    try:
        payload: dict[str, object] = {
            "title": initial_message[:80],
            "initial_message": initial_message,
            "team_preset": preset,
            "autonomous": autonomous,
        }
        if workspace_root is not None:
            payload["workspace_root"] = workspace_root
        client = _get_client()
        resp = await client.post(
            f"{settings.api_base_url}/api/threads",
            timeout=_MCP_CREATE_TIMEOUT,
            json=payload,
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
        raise ToolError(
            f"Network error: could not connect to {settings.api_base_url}. "
            f"Is the server running? Detail: {exc}"
        ) from exc
    except httpx.TimeoutException as exc:
        # MCP-H1: request timed out waiting for the server
        raise ToolError(
            f"Timeout: the server at {settings.api_base_url} did not respond. "
            f"Detail: {exc}"
        ) from exc
    except httpx.HTTPStatusError as exc:
        # MCP-H1: server responded with an HTTP error status
        raise ToolError(f"Server error: HTTP {exc.response.status_code}") from exc
    except httpx.RequestError as exc:
        # MCP-H1: other transport-level errors (SSL, proxy, etc.)
        raise ToolError(
            f"Connection error (is the server running at {settings.api_base_url}?): "
            f"{exc}"
        ) from exc


@mcp.tool()
async def list_threads(
    limit: Annotated[int, Field(description="Maximum number of threads to return (1–200). Defaults to 20.", ge=1, le=200)] = 20,
    offset: Annotated[int, Field(description="Number of threads to skip for pagination. Defaults to 0.", ge=0)] = 0,
) -> str:
    """List existing orchestration threads to discover work that can be resumed or monitored.

    Use this tool before calling ``start_thread`` to check whether a thread
    for the same task already exists.  Use ``send_message`` to continue an
    existing thread rather than starting a duplicate.  Do NOT use this tool
    to get detailed status of a single thread — use ``get_thread_status``
    with the specific thread ID instead.

    Results are paginated.  The response includes total count so you can
    request additional pages by increasing the offset.  Threads are returned
    in reverse chronological order (newest first).

    Returns a plain-text listing with one block per thread containing:
    thread_id (UUID), status (one of: 'submitted', 'running', 'input_required',
    'completed', 'failed', 'cancelled'), team preset ID, creation timestamp
    (ISO 8601), and optional nickname/title.
    Returns 'No threads found.' when no threads exist.

    Args:
        limit:  Maximum number of threads to return, between 1 and 200.
                Defaults to 20. Values outside range are clamped.
        offset: Number of threads to skip for pagination. Defaults to 0.
                Use with limit to page through results.
    """
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    try:
        client = _get_client()
        resp = await client.get(
            f"{settings.api_base_url}/api/threads",
            params={"limit": limit, "offset": offset},
            timeout=_MCP_QUERY_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        threads = data.get("threads", [])
        total = data.get("total", 0)
        if not threads:
            return "No threads found."
        lines: list[str] = [f"Threads ({len(threads)} of {total}):\n"]
        for t in threads:
            tid = t.get("thread_id", "?")
            status = t.get("status", "unknown")
            preset = t.get("team_preset") or "—"
            created = t.get("created_at", "?")
            nickname = t.get("nickname")
            title = t.get("title") or ""
            entry = (
                f"  [{status}] {tid}\n"
                f"    preset: {preset}  created: {created}\n"
            )
            if nickname:
                entry += f"    nickname: {nickname}\n"
            if title:
                entry += f"    title: {title}\n"
            lines.append(entry)
        return "".join(lines)
    except httpx.ConnectError as exc:
        raise ToolError(
            f"Network error: could not connect to {settings.api_base_url}. "
            f"Is the server running? Detail: {exc}"
        ) from exc
    except httpx.TimeoutException as exc:
        raise ToolError(
            f"Timeout: the server at {settings.api_base_url} did not respond. "
            f"Detail: {exc}"
        ) from exc
    except httpx.HTTPStatusError as exc:
        raise ToolError(f"Server error: HTTP {exc.response.status_code}") from exc
    except httpx.RequestError as exc:
        raise ToolError(f"Connection error: {exc}") from exc


@mcp.tool()
async def respond_to_permission(
    permission_request_id: Annotated[
        str,
        Field(
            description=(
                "The request ID from get_pending_permissions, in the format "
                "'{thread_id}:{uuid}'."
            ),
        ),
    ],
    option_id: Annotated[
        str,
        Field(
            description=(
                "The chosen option ID from the permission request, "
                "e.g. 'allow', 'deny', 'allow_always'."
            ),
        ),
    ],
) -> str:
    """Submit a response to a pending permission request to unblock a paused thread.

    Use this tool after calling ``get_pending_permissions`` to discover which
    permission requests are waiting.  Each permission request offers a set of
    options (e.g. 'allow', 'deny', 'allow_always'); pass the chosen option_id
    here.  Do NOT use this tool for autonomous threads — they auto-approve all
    permissions and never emit permission requests.

    This tool has a side effect: it resumes the paused graph immediately.  The
    agent that requested the permission will proceed with the approved action.
    If the permission_request_id does not match a known thread, a 404 error is
    returned.

    Returns a plain-text block containing:
    - Whether the response was accepted or rejected
    - The permission request ID echoed back
    - The thread ID extracted from the request

    Args:
        permission_request_id: The request ID from ``get_pending_permissions``,
                               in the format '{thread_id}:{uuid}', e.g.
                               '550e8400-e29b-41d4-a716-446655440000:a1b2c3d4'.
        option_id:             The chosen option ID from the permission request's
                               options list, e.g. 'allow', 'deny', 'allow_always'.
                               Use ``get_pending_permissions`` to see available options.
    """
    try:
        client = _get_client()
        resp = await client.post(
            f"{settings.api_base_url}/api/permissions/{permission_request_id}/respond",
            json={"option_id": option_id},
            timeout=_MCP_QUERY_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        accepted = data.get("accepted", False)
        thread_id = data.get("thread_id", "unknown")
        status = "accepted" if accepted else "rejected"
        return (
            f"Permission response {status}.\n"
            f"Request: {permission_request_id}\n"
            f"Thread: {thread_id}"
        )
    except httpx.ConnectError as exc:
        raise ToolError(
            f"Network error: could not connect to {settings.api_base_url}. "
            f"Is the server running? Detail: {exc}"
        ) from exc
    except httpx.TimeoutException as exc:
        raise ToolError(
            f"Timeout: the server at {settings.api_base_url} did not respond. "
            f"Detail: {exc}"
        ) from exc
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == _HTTP_NOT_FOUND:
            raise ToolError(
                f"Permission request {permission_request_id!r} not found."
            ) from exc
        raise ToolError(f"Server error: HTTP {exc.response.status_code}") from exc
    except httpx.RequestError as exc:
        raise ToolError(f"Connection error: {exc}") from exc


@mcp.tool()
async def get_thread_status(
    thread_id: Annotated[
        str,
        Field(
            description=(
                "The UUID of the thread to query. Obtain from start_thread "
                "or list_threads."
            ),
        ),
    ],
) -> str:
    """Get detailed status of a single thread including agents, plan, and last message.

    Use this tool to check progress on a specific thread after calling
    ``start_thread`` or finding it via ``list_threads``.  Do NOT use this for
    a global overview of all threads — use ``get_team_status`` instead.  Do NOT
    poll this tool rapidly; once every 10-30 seconds is sufficient.  For
    real-time updates, connect to the WebSocket URL included in the response.

    This tool reads the thread's checkpoint state, which may lag slightly
    behind the live execution.  If the thread was just started, some fields
    (agents, plan) may be empty until the first checkpoint is written.
    Returns 404 if the thread_id does not match any known thread.

    Returns a structured plain-text block containing:
    - Thread ID and status (one of: 'submitted', 'running', 'input_required',
      'completed', 'failed', 'cancelled' — 'input_required' means a permission
      response is needed; use ``get_pending_permissions`` to find it)
    - Message count and a preview of the last message (truncated to 200 chars)
    - Agent list with lifecycle states (idle, working, blocked, finished)
    - Plan entries with completion status
    - Pending permission request IDs (if any)
    - WebSocket URL for live streaming

    Args:
        thread_id: The UUID of the thread to query. Obtain this from
                   ``start_thread`` (returned on creation) or ``list_threads``
                   (in the thread listing), e.g.
                   '550e8400-e29b-41d4-a716-446655440000'.
    """
    ws_live_url = _ws_url_from_api_base(settings.api_base_url)
    try:
        client = _get_client()
        resp = await client.get(
            f"{settings.api_base_url}/api/threads/{thread_id}/state",
            timeout=_MCP_QUERY_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()

        status = data.get("status", "unknown")
        messages = data.get("messages", [])
        agents = data.get("agents", [])
        plan = data.get("plan", [])
        pending = data.get("pending_permissions", [])

        lines: list[str] = [
            f"Thread: {thread_id}",
            f"Status: {status}",
            f"Messages: {len(messages)}",
        ]

        # Last message preview (truncated to 200 chars)
        if messages:
            last_msg = messages[-1]
            content = last_msg.get("content", "")
            role = last_msg.get("role", "unknown")
            preview = content[:200] + ("..." if len(content) > 200 else "")
            lines.append(f"Last message ({role}): {preview}")

        # Agent summaries
        if agents:
            lines.append(f"Agents: {len(agents)}")
            for agent in agents:
                name = agent.get("display_name") or agent.get("agent_id", "?")
                state = agent.get("state", "unknown")
                lines.append(f"  - {name}: {state}")

        # Plan entries
        if plan:
            lines.append(f"Plan: {len(plan)} entries")
            for entry in plan:
                entry_status = entry.get("status", "?")
                title = entry.get("title", "untitled")
                lines.append(f"  - [{entry_status}] {title}")

        # Pending permissions
        if pending:
            lines.append(f"Pending permissions: {len(pending)}")
            for perm in pending:
                lines.append(f"  - {perm.get('request_id', '?')}")

        lines.append(f"Live: {ws_live_url}")
        return "\n".join(lines)
    except httpx.ConnectError as exc:
        # MCP-H1: network-level failure
        raise ToolError(
            f"Network error: could not connect to {settings.api_base_url}. "
            f"Is the server running? Detail: {exc}"
        ) from exc
    except httpx.TimeoutException as exc:
        # MCP-H1: timeout
        raise ToolError(
            f"Timeout: the server at {settings.api_base_url} did not respond. "
            f"Detail: {exc}"
        ) from exc
    except httpx.HTTPStatusError as exc:
        # MCP-H1: application-level HTTP error
        if exc.response.status_code == _HTTP_NOT_FOUND:
            raise ToolError(f"Thread {thread_id!r} not found.") from exc
        raise ToolError(f"Server error: HTTP {exc.response.status_code}") from exc
    except httpx.RequestError as exc:
        # MCP-H1: other transport errors
        raise ToolError(f"Connection error: {exc}") from exc


@mcp.tool()
async def send_message(
    thread_id: Annotated[
        str,
        Field(
            description="The UUID of the target thread. Obtain from start_thread or list_threads.",
        ),
    ],
    message: Annotated[
        str,
        Field(
            description=(
                "The message content to deliver to the agent team. "
                "Keep under 32,000 characters."
            ),
            max_length=_MAX_INITIAL_MESSAGE_CHARS,
        ),
    ],
) -> str:
    """Send a follow-up message into an existing thread to provide input or new instructions.

    Use this tool to continue a conversation with an already-running or
    paused thread.  Do NOT use this to start a new workflow — use
    ``start_thread`` instead.  Call ``list_threads`` first if you need to
    find the thread_id.

    This tool is asynchronous: it delivers the message and returns immediately
    without waiting for the agents to process it.  The message is queued and
    will be picked up by the next graph iteration.  Returns 404 if the
    thread_id does not match any known thread.

    Returns a plain-text confirmation that the message was accepted for
    delivery, e.g. 'Message delivered to thread {thread_id}.'

    Args:
        thread_id: The UUID of the target thread. Obtain from ``start_thread``
                   or ``list_threads``, e.g.
                   '550e8400-e29b-41d4-a716-446655440000'.
        message:   The message content to deliver to the agent team, e.g.
                   'Please also add unit tests for the new module'.
                   Keep messages under 32,000 characters; very long inputs
                   should be split across multiple sends.
    """
    try:
        client = _get_client()
        resp = await client.post(
            f"{settings.api_base_url}/api/threads/{thread_id}/messages",
            json={"content": message},
            timeout=_MCP_QUERY_TIMEOUT,
        )
        resp.raise_for_status()
        return f"Message delivered to thread {thread_id}."
    except httpx.ConnectError as exc:
        # MCP-H1: network-level failure
        raise ToolError(
            f"Network error: could not connect to {settings.api_base_url}. "
            f"Is the server running? Detail: {exc}"
        ) from exc
    except httpx.TimeoutException as exc:
        # MCP-H1: timeout
        raise ToolError(
            f"Timeout: the server at {settings.api_base_url} did not respond. "
            f"Detail: {exc}"
        ) from exc
    except httpx.HTTPStatusError as exc:
        # MCP-H1: application-level HTTP error
        if exc.response.status_code == _HTTP_NOT_FOUND:
            raise ToolError(f"Thread {thread_id!r} not found.") from exc
        raise ToolError(f"Server error: HTTP {exc.response.status_code}") from exc
    except httpx.RequestError as exc:
        # MCP-H1: other transport errors (SSL, proxy, etc.)
        raise ToolError(f"Connection error: {exc}") from exc


@mcp.tool()
async def get_team_status() -> str:
    """Get a global overview of the orchestration team: all agents, active threads, and pending permissions.

    Use this tool for a high-level dashboard view of the entire system.  Do
    NOT use this to check the status of a single thread — use
    ``get_thread_status`` with the specific thread ID instead.  Do NOT use
    this to find pending permissions for a specific thread — use
    ``get_pending_permissions`` for a focused permission-only view.

    Agent lifecycle states may lag behind real-time execution because the
    control surface aggregates data relayed from the worker process.  If no
    threads have been started, all lists will be empty.

    Returns a structured plain-text block containing:
    - Count and list of active thread IDs
    - Count and list of agents with their current lifecycle state
      (idle, working, blocked, finished)
    - Count and list of pending permission requests with request IDs and
      descriptions
    """
    try:
        client = _get_client()
        resp = await client.get(
            f"{settings.api_base_url}/api/team/status",
            timeout=_MCP_QUERY_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()

        agents = data.get("agents", [])
        active_threads = data.get("active_threads", [])
        pending = data.get("pending_permissions", [])

        lines: list[str] = ["Team Status"]
        lines.append(f"Active threads: {len(active_threads)}")
        if active_threads:
            for tid in active_threads:
                lines.append(f"  - {tid}")

        lines.append(f"Agents: {len(agents)}")
        for agent in agents:
            name = agent.get("display_name") or agent.get("agent_id", "unknown")
            state = agent.get("state", "unknown")
            lines.append(f"  - {name}: {state}")

        lines.append(f"Pending permissions: {len(pending)}")
        for perm in pending:
            lines.append(
                f"  - {perm.get('request_id', '?')}: {perm.get('description', '')}"
            )

        return "\n".join(lines)
    except httpx.ConnectError as exc:
        raise ToolError(
            f"Network error: could not connect to {settings.api_base_url}. "
            f"Is the server running? Detail: {exc}"
        ) from exc
    except httpx.TimeoutException as exc:
        raise ToolError(
            f"Timeout: the server at {settings.api_base_url} did not respond. "
            f"Detail: {exc}"
        ) from exc
    except httpx.HTTPStatusError as exc:
        raise ToolError(f"Server error: HTTP {exc.response.status_code}") from exc
    except httpx.RequestError as exc:
        raise ToolError(f"Connection error: {exc}") from exc


@mcp.tool()
async def get_pending_permissions() -> str:
    """List all pending permission requests across all active threads that need a response.

    Use this tool to discover which agent actions are blocked waiting for
    human approval.  After reviewing the results, call
    ``respond_to_permission`` with the request ID and chosen option to unblock
    each one.  Do NOT use this tool for autonomous threads — they never emit
    permission requests.

    This tool queries the team status endpoint and extracts only the
    permissions data.  If no threads are running in non-autonomous mode, or if
    all permissions have been resolved, returns 'No pending permission
    requests.'  For a broader system overview that includes agents and threads
    alongside permissions, use ``get_team_status`` instead.

    Returns either 'No pending permission requests.' or a structured list with
    one block per pending request containing:
    - Request ID (format: '{thread_id}:{uuid}')
    - Thread ID the request belongs to
    - Description of the action awaiting approval
    """
    try:
        client = _get_client()
        resp = await client.get(
            f"{settings.api_base_url}/api/team/status",
            timeout=_MCP_QUERY_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()

        pending = data.get("pending_permissions", [])
        if not pending:
            return "No pending permission requests."

        lines = [f"Pending permissions: {len(pending)}"]
        for perm in pending:
            req_id = perm.get("request_id", "?")
            thread_id = perm.get("thread_id", "?")
            desc = perm.get("description", "")
            lines.append(f"  - Request: {req_id}")
            lines.append(f"    Thread: {thread_id}")
            lines.append(f"    Description: {desc}")
        return "\n".join(lines)
    except httpx.ConnectError as exc:
        raise ToolError(
            f"Network error: could not connect to {settings.api_base_url}. "
            f"Is the server running? Detail: {exc}"
        ) from exc
    except httpx.TimeoutException as exc:
        raise ToolError(
            f"Timeout: the server at {settings.api_base_url} did not respond. "
            f"Detail: {exc}"
        ) from exc
    except httpx.HTTPStatusError as exc:
        raise ToolError(f"Server error: HTTP {exc.response.status_code}") from exc
    except httpx.RequestError as exc:
        raise ToolError(f"Connection error: {exc}") from exc


@mcp.tool()
async def list_team_presets() -> str:
    """List all available team configuration presets that can be used with ``start_thread``.

    Use this tool to discover valid ``team_preset`` values before calling
    ``start_thread``.  Do NOT use this to check which preset a running thread
    is using — use ``get_thread_status`` or ``list_threads`` instead.

    Presets are defined as TOML files on the server.  The built-in presets
    are always available; custom presets may also be present depending on
    server configuration.  The list is stable within a server session.

    Returns a plain-text listing with one block per preset containing:
    - Preset ID (pass this as ``team_preset`` to ``start_thread``)
    - Display name and human-readable description
    - Topology type (star, pipeline, etc.) and worker count
    Returns 'No team presets available.' if the server has no presets configured.
    """
    try:
        client = _get_client()
        resp = await client.get(
            f"{settings.api_base_url}/api/teams",
            timeout=_MCP_QUERY_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        presets = data.get("presets", [])
        if not presets:
            return "No team presets available."
        lines: list[str] = [f"Team Presets ({len(presets)}):\n"]
        for p in presets:
            pid = p.get("id", "?")
            name = p.get("display_name", pid)
            desc = p.get("description", "")
            topo = p.get("topology", "?")
            workers = p.get("worker_count", 0)
            lines.append(
                f"  {pid}\n"
                f"    name: {name}\n"
                f"    topology: {topo}  workers: {workers}\n"
                f"    {desc}\n"
            )
        return "".join(lines)
    except httpx.ConnectError as exc:
        raise ToolError(
            f"Network error: could not connect to {settings.api_base_url}. "
            f"Is the server running? Detail: {exc}"
        ) from exc
    except httpx.TimeoutException as exc:
        raise ToolError(
            f"Timeout: the server at {settings.api_base_url} did not respond. "
            f"Detail: {exc}"
        ) from exc
    except httpx.HTTPStatusError as exc:
        raise ToolError(f"Server error: HTTP {exc.response.status_code}") from exc
    except httpx.RequestError as exc:
        raise ToolError(f"Connection error: {exc}") from exc


@mcp.tool()
async def cancel_thread(
    thread_id: Annotated[
        str,
        Field(
            description="The UUID of the thread to cancel. Obtain from start_thread or list_threads.",
        ),
    ],
) -> str:
    """Cancel a running thread and stop all agent work on it.

    Use this tool to abort a workflow that is no longer needed or is stuck.
    Do NOT use this to pause a thread for later resumption — cancellation is
    permanent and the thread cannot be restarted.  Use ``send_message`` if
    you want to redirect an active thread instead.

    This tool has a side effect: it immediately signals the worker to abort
    the in-progress graph execution.  If the thread is already completed,
    failed, or cancelled, the request is accepted but has no effect.
    Returns 404 if the thread_id does not match any known thread.

    Returns a plain-text confirmation with the thread ID and its new status
    ('cancelled'), or an explanation if the thread was already in a terminal
    state.

    Args:
        thread_id: The UUID of the thread to cancel. Obtain from
                   ``start_thread`` or ``list_threads``, e.g.
                   '550e8400-e29b-41d4-a716-446655440000'.
    """
    try:
        client = _get_client()
        resp = await client.post(
            f"{settings.api_base_url}/api/threads/{thread_id}/cancel",
            timeout=_MCP_QUERY_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        cancelled = data.get("cancelled", False)
        status = data.get("status", "unknown")
        if cancelled:
            return f"Thread {thread_id} cancelled (status: {status})."
        return f"Thread {thread_id} not cancelled (current status: {status})."
    except httpx.ConnectError as exc:
        raise ToolError(
            f"Network error: could not connect to {settings.api_base_url}. "
            f"Is the server running? Detail: {exc}"
        ) from exc
    except httpx.TimeoutException as exc:
        raise ToolError(
            f"Timeout: the server at {settings.api_base_url} did not respond. "
            f"Detail: {exc}"
        ) from exc
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == _HTTP_NOT_FOUND:
            raise ToolError(f"Thread {thread_id!r} not found.") from exc
        raise ToolError(f"Server error: HTTP {exc.response.status_code}") from exc
    except httpx.RequestError as exc:
        raise ToolError(f"Connection error: {exc}") from exc

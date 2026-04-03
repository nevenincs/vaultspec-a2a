"""MCP tools for thread querying and status inspection.

Handlers: ``get_thread_status``, ``list_threads``.
"""

from typing import Annotated
from urllib.parse import urlparse

from pydantic import Field

from ....control.config import settings
from .._http import _mcp_request
from ..server import mcp


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
      'completed', 'failed', 'cancelled')
    - Repair status and execution readiness so degraded or non-actionable
      pauses are visible to operators
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
    ws_live_url = _ws_url_from_api_base(settings.gateway_url)
    data = await _mcp_request(
        "GET",
        f"/api/threads/{thread_id}/state",
        timeout=settings.mcp_query_timeout_seconds,
        not_found_msg=f"Thread {thread_id!r} not found.",
    )

    status = data.get("status", "unknown")
    repair_status = data.get("repair_status")
    execution_readiness = data.get("execution_readiness")
    messages = data.get("messages", [])
    agents = data.get("agents", [])
    plan = data.get("plan", [])
    pending = data.get("pending_permissions", [])

    lines: list[str] = [
        f"Thread: {thread_id}",
        f"Status: {status}",
        f"Repair status: {repair_status or 'unknown'}",
        f"Execution readiness: {execution_readiness or 'unknown'}",
        f"Messages: {len(messages)}",
    ]

    # Last message preview
    if messages:
        last_msg = messages[-1]
        content = last_msg.get("content", "")
        role = last_msg.get("role", "unknown")
        ellipsis = "..." if len(content) > settings.mcp_preview_truncate_len else ""
        preview = content[: settings.mcp_preview_truncate_len] + ellipsis
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
            title = entry.get("content", "untitled")
            lines.append(f"  - [{entry_status}] {title}")

    # Pending permissions
    if pending:
        lines.append(f"Pending permissions: {len(pending)}")
        for perm in pending:
            lines.append(f"  - {perm.get('request_id', '?')}")

    lines.append(f"Live: {ws_live_url}")
    return "\n".join(lines)


@mcp.tool()
async def list_threads(
    limit: Annotated[
        int,
        Field(
            description="Maximum number of threads to return (1-200). Defaults to 20.",
            ge=1,
            le=200,
        ),
    ] = 20,
    offset: Annotated[
        int,
        Field(
            description="Number of threads to skip for pagination. Defaults to 0.", ge=0
        ),
    ] = 0,
) -> str:
    """List existing orchestration threads to discover resumable or monitorable work.

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
    data = await _mcp_request(
        "GET",
        "/api/threads",
        params={"limit": limit, "offset": offset},
        timeout=settings.mcp_query_timeout_seconds,
    )
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
        entry = f"  [{status}] {tid}\n    preset: {preset}  created: {created}\n"
        if nickname:
            entry += f"    nickname: {nickname}\n"
        if title:
            entry += f"    title: {title}\n"
        lines.append(entry)
    return "".join(lines)

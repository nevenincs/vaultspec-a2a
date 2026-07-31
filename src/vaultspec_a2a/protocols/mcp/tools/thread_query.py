"""MCP tools for thread querying and status inspection.

Handlers: ``get_thread_status``, ``list_threads``.
"""

from typing import Annotated

from pydantic import Field

from ....control.config import settings
from .._http import _mcp_request, _strip_credentials
from ..server import mcp

# The versioned list verb caps a page at 100 rows, so asking for more is a
# request the gateway refuses outright rather than a larger answer.
_MAX_PAGE = 100


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
    real-time updates, read the progress stream URL included in the response.

    This tool reads the thread's checkpoint state, which may lag slightly
    behind the live execution.  If the thread was just started, some fields
    (agents, plan) may be empty until the first checkpoint is written.
    Terminal and archived threads are readable too.  Returns 404 if the
    thread_id does not match any known thread.

    Returns a structured plain-text block containing:
    - Thread ID and status (one of: 'submitted', 'running', 'input_required',
      'completed', 'failed', 'cancelled')
    - Repair status and execution readiness so degraded or non-actionable
      pauses are visible to operators
    - Message count and a preview of the last message (truncated to 200 chars)
    - Agent list with lifecycle states (idle, working, blocked, finished)
    - Plan entries with completion status
    - Pending permission request IDs (if any)
    - Progress stream URL for live updates

    Args:
        thread_id: The UUID of the thread to query. Obtain this from
                   ``start_thread`` (returned on creation) or ``list_threads``
                   (in the thread listing), e.g.
                   '550e8400-e29b-41d4-a716-446655440000'.
    """
    payload = await _mcp_request(
        "GET",
        f"/v1/runs/{thread_id}/history",
        timeout=settings.mcp_query_timeout_seconds,
        not_found_msg=f"Thread {thread_id!r} not found.",
    )
    # The versioned history verb embeds the state snapshot by reference rather
    # than restating it field by field, so every field below is read from the
    # nested snapshot and cannot drift as that snapshot evolves.
    data = payload.get("state") or {}

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

    stream_base = _strip_credentials(settings.gateway_url)
    lines.append(f"Live: GET {stream_base}/v1/runs/{thread_id}/stream")
    return "\n".join(lines)


@mcp.tool()
async def list_threads(
    limit: Annotated[
        int,
        Field(
            description="Maximum number of threads to return (1-100). Defaults to 20.",
            ge=1,
            le=_MAX_PAGE,
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

    Results are paginated and cover every thread, including terminal and
    archived ones.  The response includes a total count so you can request
    additional pages by increasing the offset.  Threads are returned in reverse
    chronological order (newest first).

    Returns a plain-text listing with one block per thread containing the
    thread_id, its status (one of: 'submitted', 'running', 'input_required',
    'completed', 'failed', 'cancelled', 'archived'), and its target feature tag
    when it has one.  Call ``get_thread_status`` for the full record of any one
    of them.  Returns 'No threads found.' when no threads exist.

    Args:
        limit:  Maximum number of threads to return, between 1 and 100.
                Defaults to 20. Values outside range are clamped.
        offset: Number of threads to skip for pagination. Defaults to 0.
                Use with limit to page through results.
    """
    limit = max(1, min(limit, _MAX_PAGE))
    offset = max(0, offset)
    # ``state=all`` is the history reading of the versioned list verb. The
    # default reading is capped active-run discovery, which by design reports no
    # total and omits every terminal run this tool exists to surface.
    data = await _mcp_request(
        "GET",
        "/v1/runs",
        params={"state": "all", "limit": limit, "offset": offset},
        timeout=settings.mcp_query_timeout_seconds,
    )
    runs = data.get("runs", [])
    total = data.get("total")
    if not runs:
        return "No threads found."
    # The history reading always carries a total; the guard keeps the tool
    # honest rather than printing "of None" if it ever does not.
    counted = f" ({len(runs)} of {total})" if total is not None else ""
    lines: list[str] = [f"Threads{counted}:\n"]
    for run in runs:
        run_id = run.get("run_id", "?")
        status = run.get("status", "unknown")
        feature_tag = run.get("feature_tag")
        entry = f"  [{status}] {run_id}\n"
        if feature_tag:
            entry += f"    feature: {feature_tag}\n"
        lines.append(entry)
    if data.get("truncated"):
        lines.append("  ... more threads remain; increase offset to page on.\n")
    return "".join(lines)

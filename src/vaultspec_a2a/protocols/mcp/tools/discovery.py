"""MCP tools for team and permission discovery.

Handlers: ``get_team_status``, ``get_pending_permissions``,
``respond_to_permission``, ``list_team_presets``.
"""

from typing import Annotated

from pydantic import Field

from ....control.config import settings
from .._http import _mcp_request
from ..server import mcp


@mcp.tool()
async def get_team_status() -> str:
    """Get a global overview of the orchestration team.

    Includes all agents, active threads, and pending
    permissions.

    Use this tool for a high-level dashboard view of the entire system.  Do
    NOT use this to check the status of a single thread — use
    ``get_thread_status`` with the specific thread ID instead.  Do NOT use
    this to find pending permissions for a specific thread — use
    ``get_pending_permissions`` for a focused permission-only view.

    Agent lifecycle states may lag behind real-time execution because the
    gateway aggregates data relayed from the worker process.  If no
    threads have been started, all lists will be empty.

    Returns a structured plain-text block containing:
    - Count and list of active thread IDs
    - Count and list of agents with their current lifecycle state
      (idle, working, blocked, finished)
    - Count and list of pending permission requests with request IDs and
      descriptions
    """
    data = await _mcp_request(
        "GET",
        "/api/team/status",
        timeout=settings.mcp_query_timeout_seconds,
    )

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


@mcp.tool()
async def get_pending_permissions() -> str:
    """List all pending permission requests across active threads that need a response.

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
    data = await _mcp_request(
        "GET",
        "/api/team/status",
        timeout=settings.mcp_query_timeout_seconds,
    )

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
    data = await _mcp_request(
        "POST",
        f"/api/permissions/{permission_request_id}/respond",
        json={"option_id": option_id},
        timeout=settings.mcp_query_timeout_seconds,
        not_found_msg=f"Permission request {permission_request_id!r} not found.",
    )
    accepted = data.get("accepted", False)
    thread_id = data.get("thread_id", "unknown")
    status = "accepted" if accepted else "rejected"
    return (
        f"Permission response {status}.\n"
        f"Request: {permission_request_id}\n"
        f"Thread: {thread_id}"
    )


@mcp.tool()
async def list_team_presets() -> str:
    """List all available team configuration presets usable with ``start_thread``.

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
    data = await _mcp_request(
        "GET",
        "/api/teams",
        timeout=settings.mcp_query_timeout_seconds,
    )
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

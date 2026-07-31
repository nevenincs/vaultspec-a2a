"""MCP tools for team and permission discovery.

Handlers: ``get_team_status``, ``get_pending_permissions``,
``respond_to_permission``, ``list_team_presets``.
"""

from typing import Annotated

from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from ....control.config import settings
from .._http import (
    _HTTP_CONFLICT,
    _HTTP_SERVICE_UNAVAILABLE,
    _PRESETS_PATH,
    HTTPStatusError,
    _mcp_request,
    _response_detail,
)
from ..server import mcp

# The versioned team-status verb: one live operational projection that both the
# overview tool and the permission-only tool read, so they cannot disagree.
_TEAM_STATUS_PATH = "/v1/team/status"


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
    - Count and list of checkpoint-actionable pending permission requests with
      request IDs and descriptions
    """
    data = await _mcp_request(
        "GET",
        _TEAM_STATUS_PATH,
        timeout=settings.mcp_query_timeout_seconds,
    )

    agents = data.get("agents", [])
    active_runs = data.get("active_runs", [])
    pending = data.get("pending_permissions", [])

    lines: list[str] = ["Team Status"]
    lines.append(f"Active threads: {len(active_runs)}")
    for run_id in active_runs:
        lines.append(f"  - {run_id}")

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
    """List all pending permission requests the gateway still considers actionable.

    Use this tool to discover which agent actions are blocked waiting for
    human approval.  After reviewing the results, call
    ``respond_to_permission`` with the request ID and chosen option to unblock
    each one.  Do NOT use this tool for autonomous threads — they never emit
    permission requests.

    This tool queries the team status endpoint and extracts only the
    permissions data.  If no threads are running in non-autonomous mode, if
    all permissions have been resolved, or if a thread has lost
    checkpoint-backed actionability, it returns 'No pending permission
    requests.'  For a broader system overview that includes agents and threads
    alongside permissions, use ``get_team_status`` instead.

    Returns either 'No pending permission requests.' or a structured list with
    one block per pending request containing:
    - Request ID
    - Thread ID the request belongs to — ``respond_to_permission`` needs BOTH,
      because a request is answered within the thread that raised it
    - Description of the action awaiting approval
    - Request status
    """
    data = await _mcp_request(
        "GET",
        _TEAM_STATUS_PATH,
        timeout=settings.mcp_query_timeout_seconds,
    )

    pending = data.get("pending_permissions", [])
    if not pending:
        return "No pending permission requests."

    lines = [f"Pending permissions: {len(pending)}"]
    for perm in pending:
        req_id = perm.get("request_id", "?")
        run_id = perm.get("run_id", "?")
        desc = perm.get("description") or ""
        lines.append(f"  - Request: {req_id}")
        lines.append(f"    Thread: {run_id}")
        lines.append(f"    Description: {desc}")
        lines.append(f"    Status: {perm.get('request_status', 'unknown')}")
    return "\n".join(lines)


@mcp.tool()
async def respond_to_permission(
    thread_id: Annotated[
        str,
        Field(
            description=(
                "The thread ID the permission request belongs to, shown as "
                "'Thread:' beside the request in get_pending_permissions."
            ),
        ),
    ],
    permission_request_id: Annotated[
        str,
        Field(
            description=(
                "The request ID from get_pending_permissions, shown as "
                "'Request:' in its listing."
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
    A request is answered WITHIN the thread that raised it, so both ids are
    required; a request id that belongs to a different thread returns 404 and
    has no effect at all.

    Answering twice is safe: the second answer replays the recorded outcome as
    a duplicate rather than acting again.

    Returns a plain-text block containing:
    - Whether the response was accepted or rejected
    - The permission request ID and thread ID echoed back
    - The resulting action status, which is what distinguishes a fresh
      acceptance from a replayed duplicate, and the approval status

    Args:
        thread_id:             The thread the permission request belongs to,
                               shown as 'Thread:' beside the request in
                               ``get_pending_permissions``.
        permission_request_id: The request ID from ``get_pending_permissions``,
                               shown as 'Request:' in its listing.
        option_id:             The chosen option ID from the permission request's
                               options list, e.g. 'allow', 'deny', 'allow_always'.
                               Use ``get_pending_permissions`` to see available options.
    """
    try:
        data = await _mcp_request(
            "POST",
            f"/v1/runs/{thread_id}/permissions/{permission_request_id}/respond",
            json={"option_id": option_id},
            timeout=settings.mcp_query_timeout_seconds,
            not_found_msg=(
                f"Permission request {permission_request_id!r} not found for "
                f"thread {thread_id!r}."
            ),
        )
    except HTTPStatusError as exc:
        status_code = exc.response.status_code
        detail = _response_detail(exc.response)
        if status_code == _HTTP_CONFLICT:
            raise ToolError(
                f"Cannot respond to permission {permission_request_id}: "
                f"{detail or 'permission request is not in an actionable state'}."
            ) from exc
        if status_code == _HTTP_SERVICE_UNAVAILABLE:
            raise ToolError(
                f"Could not deliver the response to permission "
                f"{permission_request_id}: "
                f"{detail or 'the worker is unreachable'}. Retry later."
            ) from exc
        raise ToolError(f"Server error: HTTP {status_code}") from exc
    outcome = "accepted" if data.get("accepted", False) else "rejected"
    # ``action_status`` is the authoritative vocabulary for what the answer did:
    # a fresh acceptance and a replayed duplicate are both "accepted", and only
    # the action status tells them apart. The response's ``applied`` flag is
    # deliberately NOT reported: it tracks whether the worker has already
    # carried the answer out, which on a fresh acceptance is simply "not yet",
    # and rendering it as prose would read as a failure to a caller.
    lines = [
        f"Permission response {outcome}.",
        f"Request: {permission_request_id}",
        f"Thread: {data.get('run_id', thread_id)}",
        f"Action status: {data.get('action_status', 'unknown')}",
    ]
    approval_status = data.get("approval_status")
    if approval_status:
        lines.append(f"Approval status: {approval_status}")
    return "\n".join(lines)


@mcp.tool()
async def list_team_presets() -> str:
    """List all available team configuration presets usable with ``start_thread``.

    Use this tool to discover valid ``team_preset`` values before calling
    ``start_thread``.  Do NOT use this to check which preset a running thread
    is using — use ``get_thread_status`` or ``list_threads`` instead.

    Presets are defined as TOML files on the server.  The built-in presets
    are always available; custom presets may also be present depending on
    server configuration.  The list is stable within a server session.

    A preset whose definition is missing or invalid is still listed, marked
    unavailable with the reason, so the catalog is the truthful set rather than
    one that silently omits what it could not load.  Required roles are listed
    because a preset that declares them cannot start without one
    engine-provisioned actor token per role.

    Returns a plain-text listing with one block per preset containing:
    - Preset ID (pass this as ``team_preset`` to ``start_thread``)
    - Display name and human-readable description
    - Topology type (star, pipeline, etc.) and worker count
    - Required roles, and whether the preset is loadable
    Returns 'No team presets available.' if the server has no presets configured.
    """
    data = await _mcp_request(
        "GET",
        _PRESETS_PATH,
        timeout=settings.mcp_query_timeout_seconds,
    )
    presets = data.get("presets", [])
    if not presets:
        return "No team presets available."
    lines: list[str] = [f"Team Presets ({len(presets)}):\n"]
    for p in presets:
        pid = p.get("id", "?")
        if not p.get("loadable", True):
            reason = p.get("unavailable_reason") or "unknown reason"
            lines.append(f"  {pid}\n    UNAVAILABLE: {reason}\n")
            continue
        entry = (
            f"  {pid}\n"
            f"    name: {p.get('display_name') or pid}\n"
            f"    topology: {p.get('topology') or '?'}"
            f"  workers: {p.get('worker_count') or 0}\n"
        )
        required_roles = p.get("required_roles") or []
        if required_roles:
            entry += f"    required roles: {', '.join(required_roles)}\n"
        description = p.get("description")
        if description:
            entry += f"    {description}\n"
        lines.append(entry)
    return "".join(lines)

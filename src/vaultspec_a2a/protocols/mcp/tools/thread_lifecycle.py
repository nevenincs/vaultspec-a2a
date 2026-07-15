"""MCP tools for thread lifecycle management.

Handlers: ``start_thread``, ``cancel_thread``, ``delete_thread``,
``archive_thread``.
"""

import contextlib
from typing import Annotated

from mcp.server.fastmcp.exceptions import ToolError
from pydantic import Field

from ....control.config import settings
from ....thread.enums import ThreadStatus
from .._http import (
    _HTTP_CONFLICT,
    HTTPStatusError,
    _get_known_presets,
    _mcp_request,
)
from ..server import mcp


@mcp.tool()
async def start_thread(
    initial_message: Annotated[
        str,
        Field(
            description=(
                "The coding task description for the"
                " agent team. Maximum 32,000 characters."
            )
        ),
    ],
    team_preset: Annotated[
        str | None,
        Field(
            description=(
                "Team configuration preset ID."
                " Use list_team_presets to discover"
                " all available presets."
                " Defaults to"
                " 'vaultspec-adaptive-coder'."
            )
        ),
    ] = None,
    autonomous: Annotated[
        bool,
        Field(
            description=(
                "If True (default), agents auto-approve"
                " all tool calls. Set to False to"
                " require manual approval via"
                " get_pending_permissions and"
                " respond_to_permission."
            )
        ),
    ] = True,
    workspace_root: Annotated[
        str | None,
        Field(
            description=(
                "Absolute path to the project directory,"
                " e.g. 'C:/projects/myapp'. Enables"
                " .vault/ context injection and scopes"
                " file operations to this directory."
            )
        ),
    ] = None,
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
                         'vaultspec-adaptive-coder', 'vaultspec-solo-coder'.
                         Use ``list_team_presets``
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
    if len(initial_message) > settings.mcp_max_initial_message_chars:
        raise ToolError(
            f"initial_message too long ({len(initial_message)} chars). "
            f"Maximum allowed: {settings.mcp_max_initial_message_chars} chars."
        )
    preset = team_preset or "vaultspec-adaptive-coder"
    known = await _get_known_presets()
    if known and preset not in known:
        raise ToolError(f"Unknown preset {preset!r}. Valid: {', '.join(sorted(known))}")
    payload: dict[str, object] = {
        "title": initial_message[:80],
        "initial_message": initial_message,
        "team_preset": preset,
        "autonomous": autonomous,
    }
    if workspace_root is not None:
        payload["metadata"] = {"workspace_root": workspace_root}
    data = await _mcp_request(
        "POST",
        "/api/threads",
        json=payload,
        timeout=settings.mcp_create_timeout_seconds,
    )
    thread_id = data["thread_id"]
    return (
        f"Thread started: {thread_id}\n"
        f"Preset: {preset}\n"
        f"Monitor: {settings.gateway_url}/\n"
        f"Status: GET {settings.gateway_url}/api/threads/{thread_id}/state"
    )


@mcp.tool()
async def cancel_thread(
    thread_id: Annotated[
        str,
        Field(
            description=(
                "The UUID of the thread to cancel."
                " Obtain from start_thread"
                " or list_threads."
            ),
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
    data = await _mcp_request(
        "POST",
        f"/api/threads/{thread_id}/cancel",
        timeout=settings.mcp_query_timeout_seconds,
        not_found_msg=f"Thread {thread_id!r} not found.",
    )
    cancelled = data.get("cancelled", False)
    status = data.get("status", "unknown")
    if cancelled:
        return f"Thread {thread_id} cancelled (status: {status})."
    return f"Thread {thread_id} not cancelled (current status: {status})."


@mcp.tool()
async def delete_thread(
    thread_id: Annotated[
        str,
        Field(
            description=("The UUID of the thread to delete. Obtain from list_threads."),
        ),
    ],
) -> str:
    """Permanently delete a thread and all its associated data.

    Use this tool to remove a thread that is no longer needed.  This is
    irreversible — all messages, artifacts, plan entries, and checkpoints
    are permanently destroyed.  Do NOT use this on non-terminal threads;
    paused, repairing, or otherwise active work must be resolved or cancelled
    before deletion.

    Returns 404 if the thread_id does not match any known thread. Returns 409
    if the thread is still in a non-terminal state.

    Args:
        thread_id: The UUID of the thread to delete, e.g.
                   '550e8400-e29b-41d4-a716-446655440000'.
    """
    try:
        await _mcp_request(
            "DELETE",
            f"/api/threads/{thread_id}",
            timeout=settings.mcp_query_timeout_seconds,
            not_found_msg=f"Thread {thread_id!r} not found.",
        )
    except HTTPStatusError as exc:
        if exc.response.status_code == _HTTP_CONFLICT:
            detail = ""
            with contextlib.suppress(Exception):
                detail = exc.response.json().get("detail", "")
            raise ToolError(
                f"Cannot delete thread {thread_id}: "
                f"{detail or 'thread is not in a terminal state'}."
            ) from exc
        raise ToolError(f"Server error: HTTP {exc.response.status_code}") from exc
    return f"Thread {thread_id} deleted."


@mcp.tool()
async def archive_thread(
    thread_id: Annotated[
        str,
        Field(
            description=(
                "The UUID of the thread to archive. Obtain from list_threads."
            ),
        ),
    ],
) -> str:
    """Archive a completed, failed, or cancelled thread to mark it as historical.

    Use this tool to move a terminal-state thread into the archive.  Archived
    threads remain queryable but are excluded from active listings.  Do NOT
    use this on running threads — they must reach a terminal state first
    (completed, failed, or cancelled).  Already-archived threads are accepted
    idempotently.

    Returns 404 if the thread_id does not match any known thread.  Returns
    409 if the thread is still in a non-terminal state.

    Args:
        thread_id: The UUID of the thread to archive, e.g.
                   '550e8400-e29b-41d4-a716-446655440000'.
    """
    try:
        data = await _mcp_request(
            "POST",
            f"/api/threads/{thread_id}/archive",
            timeout=settings.mcp_query_timeout_seconds,
            not_found_msg=f"Thread {thread_id!r} not found.",
        )
    except HTTPStatusError as exc:
        if exc.response.status_code == _HTTP_CONFLICT:
            detail = ""
            with contextlib.suppress(Exception):
                detail = exc.response.json().get("detail", "")
            raise ToolError(
                f"Cannot archive thread {thread_id}: "
                f"{detail or 'thread is not in a terminal state'}."
            ) from exc
        raise ToolError(f"Server error: HTTP {exc.response.status_code}") from exc
    status = data.get("status", ThreadStatus.ARCHIVED)
    return f"Thread {thread_id} archived (status: {status})."

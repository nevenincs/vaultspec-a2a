"""MCP tools for thread lifecycle management.

Handlers: ``start_thread``, ``cancel_thread``, ``delete_thread``,
``archive_thread``.
"""

import contextlib
from typing import Annotated

from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from ....control.config import settings
from ....thread.enums import ThreadStatus
from .._http import (
    _HTTP_CONFLICT,
    _HTTP_SERVICE_UNAVAILABLE,
    _HTTP_UNPROCESSABLE,
    HTTPStatusError,
    _get_known_presets,
    _mcp_request,
    _response_detail,
)
from ..server import mcp

# Default team preset when the caller omits one. Solo-coder is the retained
# single-role coding preset after the multi-role coder presets were retired.
_DEFAULT_TEAM_PRESET = "vaultspec-solo-coder"


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
                " 'vaultspec-solo-coder'."
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
    feature_tag: Annotated[
        str | None,
        Field(
            description=(
                "Target feature tag (kebab-case) the run"
                " authors documents for. Required by"
                " document-authoring presets; ignored by"
                " coding presets."
            )
        ),
    ] = None,
) -> str:
    """Start a new multi-agent coding workflow and return a run ID for tracking.

    Use this tool when the user wants to delegate a coding task to a team of
    AI agents.  Do NOT use this if there is already an active run for the
    same task — call ``list_threads`` first to check, then use ``send_message``
    to continue an existing run instead.

    The workflow runs asynchronously: this tool returns immediately with a
    run ID and a progress-stream URL.  It does NOT wait for agents to finish.
    Poll progress with ``get_thread_status``, or read the run's progress stream
    at the returned URL.  The initial_message is capped at 32,000 characters;
    longer messages are rejected.

    Presets differ in what they require before a run may dispatch.  A preset
    that arms the engine authoring bridge, and every document-authoring preset,
    needs one engine-minted actor token per role; a document-authoring preset
    additionally needs ``feature_tag``.  Those requirements are refused up front
    rather than mid-run, and this tool reports the refusal verbatim.

    Returns a plain-text block containing:
    - Run ID (e.g. '550e8400e29b41d4a716446655440000')
    - Team preset name used
    - Progress stream URL
    - Status query URL

    Args:
        initial_message: The coding task description for the agent team, e.g.
                         'Refactor the auth module to use JWT tokens'. Maximum
                         32,000 characters.
        team_preset:     Team configuration preset ID. Built-in presets:
                         'vaultspec-solo-coder', 'vaultspec-adr-research'.
                         Use ``list_team_presets``
                         to discover all available presets at runtime.
                         If omitted, defaults to 'vaultspec-solo-coder'.
        autonomous:      If True (default), agents auto-approve all tool calls
                         without human review. Set to False to require manual
                         approval — you will then need ``get_pending_permissions``
                         and ``respond_to_permission`` to unblock the workflow.
        workspace_root:  Absolute path to the project directory, e.g.
                         'C:/projects/myapp' or '/home/user/myapp'. Enables
                         automatic .vault/ context injection and scopes agent
                         file operations to this directory. If omitted, agents
                         run without project context.
        feature_tag:     Target feature tag for a document-authoring preset,
                         e.g. 'editor-demo'. Coding presets ignore it.
    """
    # reject oversized payloads before making any HTTP call.
    if len(initial_message) > settings.mcp_max_initial_message_chars:
        raise ToolError(
            f"initial_message too long ({len(initial_message)} chars). "
            f"Maximum allowed: {settings.mcp_max_initial_message_chars} chars."
        )
    preset = team_preset or _DEFAULT_TEAM_PRESET
    known = await _get_known_presets()
    if known and preset not in known:
        raise ToolError(f"Unknown preset {preset!r}. Valid: {', '.join(sorted(known))}")
    payload: dict[str, object] = {
        "title": initial_message[:80],
        "message": initial_message,
        "team_preset": preset,
        "autonomous": autonomous,
    }
    if workspace_root is not None:
        payload["metadata"] = {"workspace_root": workspace_root}
    if feature_tag is not None:
        payload["feature_tag"] = feature_tag
    try:
        data = await _mcp_request(
            "POST",
            "/v1/runs",
            json=payload,
            timeout=settings.mcp_create_timeout_seconds,
        )
    except HTTPStatusError as exc:
        raise _start_refusal(preset, exc) from exc
    run_id = data["run_id"]
    return (
        f"Thread started: {run_id}\n"
        f"Preset: {preset}\n"
        f"Stream: GET {settings.gateway_url}/v1/runs/{run_id}/stream\n"
        f"Status: GET {settings.gateway_url}/v1/runs/{run_id}"
    )


def _start_refusal(preset: str, exc: HTTPStatusError) -> ToolError:
    """Translate a run-start rejection into an actionable tool error.

    Run-start refuses an ineligible request BEFORE creating durable state, and
    the refusal detail is the only thing that tells the caller what to change —
    which roles lack an engine-minted actor token, or that a document-authoring
    preset was given no target feature. Collapsing that into a bare status code
    would leave the caller retrying an unstartable request forever, so the
    detail is surfaced verbatim.
    """
    status = exc.response.status_code
    detail = _response_detail(exc.response)
    if status == _HTTP_UNPROCESSABLE:
        return ToolError(
            f"Run start refused for preset {preset!r}: "
            f"{detail or 'the request is not eligible to dispatch'}."
        )
    if status == _HTTP_CONFLICT:
        return ToolError(
            f"Run start conflicted for preset {preset!r}: "
            f"{detail or 'a run with this identity already exists'}."
        )
    if status == _HTTP_SERVICE_UNAVAILABLE:
        return ToolError(
            f"Run start is temporarily unavailable for preset {preset!r}: "
            f"{detail or 'the gateway is at capacity or draining'}. Retry later."
        )
    return ToolError(f"Server error: HTTP {status}")


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
        f"/v1/runs/{thread_id}/cancel",
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

    Deletion can also report that it is in progress: cleanup incomplete but
    resumable.  That is not a failure and not a server fault — call this tool
    again with the same thread_id and the same deletion resumes and makes
    progress.  Space those attempts out rather than retrying immediately,
    because each one drives real cleanup work; state that stays unremovable
    across attempts is eventually reported as abandoned instead.

    A deletion is always durable once it reports success, but it can finalize
    over state that no cleanup pass could remove.  The returned text says which
    of the two happened: a clean deletion reports only that, while a deletion
    that stranded state reports the abandonment and names the kinds of item
    left behind, so the caller can surface or remediate them instead of
    reading the thread as cleanly gone.

    Args:
        thread_id: The UUID of the thread to delete, e.g.
                   '550e8400-e29b-41d4-a716-446655440000'.
    """
    try:
        data = await _mcp_request(
            "DELETE",
            f"/v1/runs/{thread_id}",
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
        if exc.response.status_code == _HTTP_SERVICE_UNAVAILABLE:
            # Not a fault.  This status means cleanup is genuinely incomplete
            # but resumable, and repeating the call resumes the same saga and
            # makes progress.  Reporting it as a server error would tell the
            # caller the service is broken, so it would not retry — and the
            # retry is the whole mechanism by which the deletion completes.
            # The pacing is deliberately left to the caller: each attempt
            # drives real cleanup passes and advances an attempt ledger whose
            # ceiling abandons items permanently, so a tight loop here would
            # exhaust that ceiling against an unchanged cause and strand state.
            detail = ""
            with contextlib.suppress(Exception):
                detail = exc.response.json().get("detail", "")
            raise ToolError(
                f"Deletion of thread {thread_id} is in progress: cleanup is "
                f"incomplete but resumable, and this is not a server fault. "
                f"Call delete_thread again with the same thread_id — each "
                f"attempt resumes the same deletion and makes progress. Space "
                f"the attempts out rather than retrying immediately; if "
                f"incompleteness persists, the remaining state is eventually "
                f"reported as abandoned." + (f" Detail: {detail}" if detail else "")
            ) from exc
        raise ToolError(f"Server error: HTTP {exc.response.status_code}") from exc
    # A clean deletion answers with no body at all; a deletion that finalized
    # over permanently unremovable state answers with one naming the kinds it
    # stranded.  Reporting both as a bare "deleted" would erase the very
    # distinction the delete surface exists to carry.  Kinds only — the
    # concrete checkpoint ids and artifact paths are control-plane state and
    # are deliberately absent from the wire.
    abandoned_kinds = [str(kind) for kind in data.get("abandoned_kinds") or []]
    if abandoned_kinds:
        return (
            f"Thread {thread_id} deleted, but cleanup was abandoned: "
            f"state of kind {', '.join(abandoned_kinds)} could not be removed "
            f"and remains behind."
        )
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
            f"/v1/runs/{thread_id}/archive",
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

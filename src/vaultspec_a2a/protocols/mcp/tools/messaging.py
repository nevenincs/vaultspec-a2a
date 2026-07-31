"""MCP tool for sending messages into existing threads.

Handler: ``send_message``.
"""

from typing import Annotated

from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from ....control.config import settings
from .._http import (
    _HTTP_CONFLICT,
    _HTTP_SERVICE_UNAVAILABLE,
    HTTPStatusError,
    _mcp_request,
    _response_detail,
)
from ..server import mcp


@mcp.tool()
async def send_message(
    thread_id: Annotated[
        str,
        Field(
            description=("The UUID of the target thread. Obtain from list_threads."),
        ),
    ],
    message: Annotated[
        str,
        Field(
            description=(
                "The message content to deliver to the agent team. "
                "Keep under 32,000 characters."
            ),
            max_length=settings.mcp_max_initial_message_chars,
        ),
    ],
) -> str:
    """Send a follow-up message into an existing thread.

    Use this tool to continue a conversation with an already-running or
    paused thread.  Call ``list_threads`` first if you need to find the
    thread_id.

    This tool is asynchronous: it hands the message to the worker and returns
    immediately without waiting for the agents to process it.  Acceptance is
    not completion — reconcile progress with ``get_thread_status`` rather than
    from this confirmation.  Returns 404 if the thread_id does not match any
    known thread, and reports a refusal when the thread is in a state that
    takes no follow-up.

    Returns a plain-text confirmation that the message was accepted, naming the
    action status and, when the gateway assigned one, the action id.

    Args:
        thread_id: The UUID of the target thread. Obtain from
                   ``list_threads``, e.g.
                   '550e8400-e29b-41d4-a716-446655440000'.
        message:   The message content to deliver to the agent team, e.g.
                   'Please also add unit tests for the new module'.
                   Keep messages under 32,000 characters; very long inputs
                   should be split across multiple sends.
    """
    try:
        data = await _mcp_request(
            "POST",
            f"/v1/runs/{thread_id}/messages",
            json={"content": message},
            timeout=settings.mcp_query_timeout_seconds,
            not_found_msg=f"Thread {thread_id!r} not found.",
        )
    except HTTPStatusError as exc:
        status = exc.response.status_code
        detail = _response_detail(exc.response)
        if status == _HTTP_CONFLICT:
            raise ToolError(
                f"Cannot send message to thread {thread_id}: "
                f"{detail or 'thread is not accepting follow-up messages'}."
            ) from exc
        if status == _HTTP_SERVICE_UNAVAILABLE:
            # The gateway is draining or at capacity, or the worker circuit is
            # open. The turn was NOT queued, so reporting delivery here would
            # tell the caller its message is on its way when nothing holds it.
            raise ToolError(
                f"Could not deliver the message to thread {thread_id}: "
                f"{detail or 'the gateway is at capacity or draining'}. Retry later."
            ) from exc
        raise ToolError(f"Server error: HTTP {status}") from exc
    # Acceptance is not application: the turn is handed to the worker and the
    # run continues asynchronously, so the confirmation says accepted rather
    # than done and names the action a caller can reconcile against.
    action_status = data.get("action_status", "accepted")
    action_id = data.get("action_id")
    confirmation = f"Message accepted for thread {thread_id} (status: {action_status})."
    if action_id:
        confirmation += f" Action: {action_id}."
    return confirmation

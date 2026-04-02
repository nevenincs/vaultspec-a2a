"""MCP tool for sending messages into existing threads.

Handler: ``send_message``.
"""

import contextlib
from typing import Annotated

from mcp.server.fastmcp.exceptions import ToolError
from pydantic import Field

from ....control.config import settings
from .._http import _HTTP_CONFLICT, HTTPStatusError, _mcp_request
from ..server import mcp


@mcp.tool()
async def send_message(
    thread_id: Annotated[
        str,
        Field(
            description=(
                "The UUID of the target thread."
                " Obtain from start_thread"
                " or list_threads."
            ),
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
        await _mcp_request(
            "POST",
            f"/api/threads/{thread_id}/messages",
            json={"content": message},
            timeout=settings.mcp_query_timeout_seconds,
            not_found_msg=f"Thread {thread_id!r} not found.",
        )
    except HTTPStatusError as exc:
        if exc.response.status_code == _HTTP_CONFLICT:
            detail = ""
            with contextlib.suppress(Exception):
                detail = exc.response.json().get("detail", "")
            raise ToolError(
                f"Cannot send message to thread {thread_id}: "
                f"{detail or 'thread is not accepting follow-up messages'}."
            ) from exc
        raise ToolError(f"Server error: HTTP {exc.response.status_code}") from exc
    return f"Message delivered to thread {thread_id}."

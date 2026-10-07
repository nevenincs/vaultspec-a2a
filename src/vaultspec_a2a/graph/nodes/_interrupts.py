"""Parking a gate until an answer to its own request arrives.

A resume value is handed to whichever ``interrupt()`` asks for one next, which
is not necessarily the one it was written for: an answer delivered to a
checkpoint that has moved on, or that never parked, would otherwise be consumed
as the answer to a question no human was asked. Every gate therefore names the
request it parks on and accepts only an answer bound to it.

A refused answer is met by asking again rather than by raising.
``interrupt()`` records its resume value against the running task before the
node can judge it, so a node that raises leaves that value in place and every
later answer replays the refused one and fails the same way - one bad answer
would end the run's ability to be answered at all. Asking again takes the next
answer at the next position instead, and because the payload is unchanged a
status read still discloses the question the run is waiting on.

The worker's tool-permission callback is the one asker that raises instead: a
replayed provider turn can reach its calls in a different order, and an extra
``interrupt()`` there would shift every later answer onto the wrong call.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from langgraph.types import interrupt

__all__ = [
    "await_request_scoped_resume",
]

_logger = logging.getLogger(__name__)


class _RequestScopedParser[T](Protocol):
    """Read a resume value as the answer to one request, or refuse it."""

    def __call__(self, payload: object, /, *, request_id: str) -> T:
        """Return the typed answer *payload* gives to *request_id*.

        Raises:
            ValueError: *payload* is not an answer this request accepts,
                including one naming another request or none.
        """
        ...


def await_request_scoped_resume[T](
    payload: dict[str, Any],
    request_id: str,
    parse: _RequestScopedParser[T],
) -> T:
    """Park on *payload* until a resume value answers *request_id*.

    Each refusal *parse* raises is logged and the gate parks again on the same
    payload, so the first answer it accepts is the one returned.
    """
    while True:
        resume_value = interrupt(payload)
        try:
            return parse(resume_value, request_id=request_id)
        except ValueError as exc:
            _logger.warning(
                "Answer to %s %r was refused (%s); asking again",
                payload.get("type"),
                request_id,
                exc,
            )

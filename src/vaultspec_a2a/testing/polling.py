"""Run-status polling for tests that wait on a real run.

Every surface that reads a run's served state - the httpx sync client, the
async client, a harness stack's history verb, a database row - differs only in
HOW one body is fetched, so that is the only thing a caller supplies: ``read``,
any callable returning the current body, or ``None`` while it is not readable
yet. The waiting, the terminal vocabulary, and the failure diagnostic live here
once.

A wait fails when the run STOPS MOVING, not when it takes a while. A body whose
status or checkpoint cursor differs from the last one counts as progress and
renews the window, so ``timeout`` bounds a SILENCE rather than the whole run. A
real run on a loaded host is slow in a way no fixed total budget can be written
for; a wedged one repeats one body and fails after a single window with that
body attached.

A predicate may raise ``AssertionError`` to abort a wait whose awaited state
became unreachable (the run settled failed, say) with a message naming why,
rather than burning the window.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from ..thread.enums import TERMINAL_STATUS_VALUES
from .progress import ProgressDeadline, ProgressStalledError, wait_for

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping

    import httpx

__all__ = [
    "is_terminal",
    "ok_body",
    "wait_for_run_status",
    "wait_for_run_status_async",
]


def is_terminal(body: Mapping[str, Any]) -> bool:
    """Whether *body* carries a durable terminal run status."""
    return body.get("status") in TERMINAL_STATUS_VALUES


def ok_body(response: httpx.Response) -> dict[str, Any] | None:
    """The JSON body of a 200 *response*; ``None`` while the read is not served."""
    return response.json() if response.status_code == 200 else None


def _fingerprint(body: Mapping[str, Any] | None) -> object:
    return None if body is None else (body.get("status"), body.get("last_sequence"))


def _unsatisfied(
    label: str, last: Mapping[str, Any] | None, stalled: ProgressStalledError
) -> AssertionError:
    return AssertionError(
        f"{label} never satisfied the awaited status predicate; "
        f"last snapshot: {'never readable' if last is None else last} ({stalled})"
    )


def wait_for_run_status[B: Mapping[str, Any]](
    read: Callable[[], B | None],
    predicate: Callable[[B], bool] = is_terminal,
    *,
    timeout: float = 120.0,
    interval: float = 0.5,
    label: str = "run",
) -> B:
    """Poll *read* until *predicate* holds (default: terminal); return that body.

    *timeout* is the idle window: the longest the observed status and cursor may
    stay unchanged. Failure raises ``AssertionError`` naming *label* and the last
    body read.
    """
    last: B | None = None

    def _poll() -> B | None:
        nonlocal last
        body = read()
        if body is None:
            return None
        last = body
        return body if predicate(body) else None

    try:
        return wait_for(
            _poll,
            deadline=ProgressDeadline(idle_window_s=timeout),
            fingerprint=lambda: _fingerprint(last),
            interval_s=interval,
        )
    except ProgressStalledError as stalled:
        raise _unsatisfied(label, last, stalled) from stalled


async def wait_for_run_status_async[B: Mapping[str, Any]](
    read: Callable[[], Awaitable[B | None]],
    predicate: Callable[[B], bool] = is_terminal,
    *,
    timeout: float = 120.0,
    interval: float = 0.5,
    label: str = "run",
) -> B:
    """Await *read* until *predicate* holds (default: terminal); return that body.

    The same wait as :func:`wait_for_run_status`, for a coroutine reader.
    """
    deadline = ProgressDeadline(idle_window_s=timeout)
    last: B | None = None
    previous: object = object()
    while True:
        body = await read()
        if body is not None:
            last = body
            if predicate(body):
                return body
        current = _fingerprint(last)
        if current != previous:
            previous = current
            deadline.touch()
        try:
            deadline.check()
        except ProgressStalledError as stalled:
            raise _unsatisfied(label, last, stalled) from stalled
        await asyncio.sleep(interval)

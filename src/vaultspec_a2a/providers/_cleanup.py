"""Independent, failure-aggregating cleanup for provider teardown.

A provider's teardown releases several independent resources - a spawned process
tree, background reader tasks, an isolated configuration home holding a copied
credential. Run sequentially with the first failure propagating, one release that
raises skips every later release, leaking the rest (a killed-process failure that
strands a credential home is the concrete hazard). This runs each release
independently so one failure never skips another, collecting the failures for the
caller to surface.
"""

import asyncio
import inspect
import logging
from collections.abc import Callable, Iterable

from ..utils.async_cleanup import complete_cleanup

logger = logging.getLogger(__name__)

__all__ = ["cancel_owned_tasks", "run_independent_cleanups"]

# A named cleanup step. The callable may be sync or async and may return any
# value; an awaitable result is awaited and any other return is ignored, so a
# release that happens to return a handle (e.g. a preserved-record path) fits
# without an adapter.
CleanupStep = tuple[str, Callable[[], object]]


async def cancel_owned_tasks(
    tasks: Iterable[asyncio.Task[None]], *, timeout: float = 15.0
) -> None:
    """Cancel owned handlers, bounding the join even if a handler resists it.

    Callers retain task references and stop resource admission before this call.
    A surviving callback is reported, allowing independent OS releases to run.
    """
    owned = set(tasks)
    if not owned:
        return
    for task in owned:
        task.cancel()
    done, pending = await asyncio.wait(owned, timeout=timeout)
    for task in done:
        if not task.cancelled() and (exc := task.exception()) is not None:
            logger.warning("Provider task failed during teardown", exc_info=exc)
    if pending:
        raise TimeoutError(f"{len(pending)} provider task(s) resisted cancellation")


async def run_independent_cleanups(*steps: CleanupStep) -> list[tuple[str, Exception]]:
    """Run each named cleanup step, isolating failures so one cannot skip the rest.

    Every step runs even if an earlier one raised; each failure is logged with its
    step name and collected. Sync and async steps are both accepted (an awaitable
    result is awaited). Returns the ``(name, exception)`` pairs that failed so the
    caller can decide whether to surface them; best-effort by design, so a
    ``finally`` path releases every resource rather than stopping at the first
    error. Caller cancellation is propagated after all releases finish, including
    repeated cancellation while a release is in flight.
    """
    return await complete_cleanup(_run_steps(steps))


async def _run_steps(steps: tuple[CleanupStep, ...]) -> list[tuple[str, Exception]]:
    failures: list[tuple[str, Exception]] = []
    cancellation: asyncio.CancelledError | None = None
    for name, step in steps:
        try:
            result = step()
            if inspect.isawaitable(result):
                await result
        except asyncio.CancelledError as exc:
            cancellation = exc
        except Exception as exc:
            failures.append((name, exc))
            logger.warning("cleanup step %r failed", name, exc_info=exc)
    if cancellation is not None:
        raise cancellation
    return failures

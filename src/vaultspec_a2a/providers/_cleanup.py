"""Independent, failure-aggregating cleanup for provider teardown.

A provider's teardown releases several independent resources - a spawned process
tree, background reader tasks, an isolated configuration home holding a copied
credential. Run sequentially with the first failure propagating, one release that
raises skips every later release, leaking the rest (a killed-process failure that
strands a credential home is the concrete hazard). This runs each release
independently so one failure never skips another, collecting the failures for the
caller to surface.
"""

import inspect
import logging
from collections.abc import Callable

logger = logging.getLogger(__name__)

__all__ = ["run_independent_cleanups"]

# A named cleanup step. The callable may be sync or async and may return any
# value; an awaitable result is awaited and any other return is ignored, so a
# release that happens to return a handle (e.g. a preserved-record path) fits
# without an adapter.
CleanupStep = tuple[str, Callable[[], object]]


async def run_independent_cleanups(*steps: CleanupStep) -> list[tuple[str, Exception]]:
    """Run each named cleanup step, isolating failures so one cannot skip the rest.

    Every step runs even if an earlier one raised; each failure is logged with its
    step name and collected. Sync and async steps are both accepted (an awaitable
    result is awaited). Returns the ``(name, exception)`` pairs that failed so the
    caller can decide whether to surface them; best-effort by design, so a
    ``finally`` path releases every resource rather than stopping at the first
    error. ``BaseException`` (notably cancellation) is not swallowed - it
    propagates so a cancelling caller is never silently absorbed by cleanup.
    """
    failures: list[tuple[str, Exception]] = []
    for name, step in steps:
        try:
            result = step()
            if inspect.isawaitable(result):
                await result
        except Exception as exc:
            failures.append((name, exc))
            logger.warning("cleanup step %r failed", name, exc_info=exc)
    return failures

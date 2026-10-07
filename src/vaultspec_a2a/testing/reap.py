"""Reap a contained process tree from any calling context.

A leaf of its own so the pytest owner (``runner``), which starts before anything
test-only is imported and is timed, reaps through the same path the rest of the
kit does without paying for the progress and settings machinery ``children``
carries.
"""

from __future__ import annotations

import asyncio
import subprocess
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..utils import ProcessContainment

__all__ = ["reap_contained"]


def reap_contained(
    process: subprocess.Popen[Any],
    containment: ProcessContainment,
    *,
    term_timeout: float = 10.0,
    kill_timeout: float = 5.0,
) -> bool:
    """Reap *process*'s whole tree through *containment*, from any calling context.

    *process* was started inside *containment* by
    :func:`~vaultspec_a2a.utils.spawn_contained`, which held every descendant
    from the root's first instruction, so a root that already exited is no
    obstacle: what it left running is still reaped, and no kill is ever aimed at
    a recycled pid. The root's handle is then waited on. *term_timeout* and
    *kill_timeout* are the graceful and forced phases. Returns ``True`` once the
    tree is gone and the root reaped; a repeat call after that is a no-op.

    Called from a test that is itself running an event loop, ``asyncio.run``
    would refuse and leave the tree alive, so the reap then runs on a thread
    with a loop of its own.
    """

    def _terminate() -> bool:
        return asyncio.run(
            containment.terminate(term_timeout=term_timeout, kill_timeout=kill_timeout)
        )

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        reaped = _terminate()
    else:
        with ThreadPoolExecutor(max_workers=1) as reaper:
            reaped = reaper.submit(_terminate).result()
    try:
        process.wait(timeout=kill_timeout)
    except subprocess.TimeoutExpired:
        return False
    return reaped

"""Owned worker-process shutdown through its OS containment."""

from __future__ import annotations

import asyncio
import logging
import subprocess
from typing import TYPE_CHECKING

from ..utils import ProcessContainmentError
from ..utils.async_cleanup import complete_cleanup

if TYPE_CHECKING:
    from ..lifecycle.shutdown import ShutdownDeadline
    from ..utils import ProcessContainment

__all__ = [
    "_shutdown_worker_process",
    "_stop_worker_tree",
]

logger = logging.getLogger("vaultspec_a2a.control.worker_management")

# The root handle's wait only collects an exit status; the containment already
# bounded the reap of the tree, so this window stays short.
_ROOT_REAP_TIMEOUT = 0.1


async def _stop_worker_tree(
    process: subprocess.Popen[bytes],
    containment: ProcessContainment,
    *,
    term_timeout: float,
    kill_timeout: float = 5.0,
) -> None:
    try:
        if not await containment.terminate(
            term_timeout=term_timeout, kill_timeout=kill_timeout
        ):
            raise ProcessContainmentError(
                f"Worker process tree {process.pid} did not terminate"
            )
    finally:
        await _reap_root_handle(process)


async def _reap_root_handle(process: subprocess.Popen[bytes]) -> None:
    """Collect the root's exit status without replacing the reap's own outcome.

    The containment, not this handle, is authoritative for the tree, so this
    wait exists only to clear the root from the process table. It runs after a
    reap that proved the tree gone, or after one whose
    :class:`ProcessContainmentError` is the diagnostic the caller needs; a root
    can still be in the window in either case (a loaded host, or a tree an
    earlier pass already reaped). Letting ``TimeoutExpired`` out of the
    enclosing ``finally`` would raise on a clean shutdown and discard a real
    failure's cause, so it is logged instead.
    """
    try:
        await asyncio.to_thread(process.wait, _ROOT_REAP_TIMEOUT)
    except subprocess.TimeoutExpired:
        logger.warning(
            "Worker root (PID %d) did not report its exit status within %.1fs",
            process.pid,
            _ROOT_REAP_TIMEOUT,
        )


async def _shutdown_worker_process(
    process: subprocess.Popen[bytes],
    containment: ProcessContainment,
    *,
    deadline: ShutdownDeadline | None = None,
) -> None:
    """Shut down the worker child process and its whole tree.

    The worker was started inside *containment*, so its POSIX process group or
    Windows Job Object is authoritative for the whole tree, including
    descendants that outlive a root which already exited. A repeat call after a
    completed reap is a no-op.
    """
    logger.info(
        "Shutting down worker process (PID %d)",
        process.pid,
    )
    if deadline is None:
        term_timeout = 10.0
        kill_timeout = 5.0
    else:
        remaining = deadline.remaining()
        term_timeout = max((remaining - 0.5) / 2.0, 0.0)
        kill_timeout = max(remaining - term_timeout, 0.1)
    await complete_cleanup(
        _stop_worker_tree(
            process,
            containment,
            term_timeout=term_timeout,
            kill_timeout=kill_timeout,
        )
    )
    logger.info("Worker process stopped")

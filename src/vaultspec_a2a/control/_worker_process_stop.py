"""Owned worker-process shutdown through its OS containment."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from ..utils import ProcessContainmentError
from ..utils.async_cleanup import complete_cleanup

if TYPE_CHECKING:
    import subprocess

    from ..lifecycle.shutdown import ShutdownDeadline
    from ..utils import ProcessContainment

__all__ = [
    "_shutdown_worker_process",
    "_stop_worker_tree",
]

logger = logging.getLogger("vaultspec_a2a.control.worker_management")


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
        await asyncio.to_thread(process.wait, 0.1)


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

"""Exact retained worker-process shutdown and descendant reaping."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import psutil

from ..utils.async_cleanup import complete_cleanup
from ..utils.process import ProcessContainment, ProcessContainmentError

if TYPE_CHECKING:
    import subprocess

    from ..lifecycle.shutdown import ShutdownDeadline

__all__ = [
    "_reap_retained_processes",
    "_shutdown_worker_process",
    "_stop_worker_tree",
]

logger = logging.getLogger("vaultspec_a2a.control.worker_management")


async def _stop_worker_tree(
    process: subprocess.Popen[bytes],
    containment: ProcessContainment | None,
    *,
    term_timeout: float,
    kill_timeout: float = 5.0,
) -> None:
    try:
        if containment is not None and containment.assigned:
            reaped = await containment.terminate(
                term_timeout=term_timeout, kill_timeout=kill_timeout
            )
        else:
            reaped = await _stop_exact_popen_tree(
                process,
                term_timeout=term_timeout,
                kill_timeout=kill_timeout,
            )
        if not reaped:
            raise ProcessContainmentError(
                f"Worker process tree {process.pid} did not terminate"
            )
    finally:
        await asyncio.to_thread(process.wait, 0.1)


def _retained_process_owner(
    process: subprocess.Popen[bytes],
) -> psutil.Process | None:
    """Return a reuse-guarded psutil identity for the exact live ``Popen``."""
    if process.poll() is not None:
        return None
    try:
        owner = psutil.Process(process.pid)
        owner.create_time()
    except psutil.NoSuchProcess:
        return None
    # The first poll proved our retained handle live before lookup; the second
    # rejects an exit/reuse race during lookup. ``owner`` has cached creation
    # identity, so every later signal refuses a reused numeric pid.
    if process.poll() is not None:
        return None
    return owner


def _suspend_owned_tree(owner: psutil.Process) -> list[psutil.Process]:
    owner.suspend()
    retained = [owner]
    for child in owner.children(recursive=True):
        try:
            if child.is_running():
                child.suspend()
                retained.append(child)
        except psutil.NoSuchProcess:
            pass
    return retained


def _signal_retained_processes(targets: list[psutil.Process], *, kill: bool) -> None:
    for target in targets:
        try:
            if target.is_running():
                if kill:
                    target.kill()
                else:
                    target.terminate()
        except psutil.NoSuchProcess:
            pass


async def _stop_exact_popen_tree(
    process: subprocess.Popen[bytes],
    *,
    term_timeout: float,
    kill_timeout: float,
) -> bool:
    """Stop the exact retained root and its observed tree without reopening a pid."""
    owner = _retained_process_owner(process)
    if owner is None:
        return process.poll() is not None
    try:
        retained = _suspend_owned_tree(owner)
        _signal_retained_processes(list(reversed(retained)), kill=False)
        _, alive = await asyncio.to_thread(
            psutil.wait_procs, retained, timeout=term_timeout
        )
        _signal_retained_processes(alive, kill=True)
        if alive:
            _, alive = await asyncio.to_thread(
                psutil.wait_procs, alive, timeout=kill_timeout
            )
        return not alive
    except (psutil.AccessDenied, psutil.NoSuchProcess):
        return process.poll() is not None


async def _shutdown_worker_process(
    process: subprocess.Popen[bytes],
    containment: ProcessContainment | None = None,
    *,
    deadline: ShutdownDeadline | None = None,
) -> None:
    """Shut down the worker child process and its whole tree.

    Assigned containment reaps through a POSIX process group or Windows Job
    Object. Missing or unassigned containment uses exact retained process
    identities, including creation-time reuse guards, and never treats an empty
    containment as authority for a live root.
    """
    if process.poll() is not None and containment is None:
        return
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


async def _reap_retained_processes(
    processes: list[psutil.Process], *, deadline: ShutdownDeadline | None
) -> None:
    """Reap retained process identities without acting on a reused pid."""
    if not processes:
        return
    remaining = deadline.remaining() if deadline is not None else 5.0
    term_timeout = max((remaining - 0.1) / 2.0, 0.0)
    _signal_retained_processes(list(reversed(processes)), kill=False)
    _, alive = await asyncio.to_thread(
        psutil.wait_procs, processes, timeout=term_timeout
    )
    _signal_retained_processes(alive, kill=True)
    if alive:
        remaining = deadline.remaining() if deadline is not None else 2.5
        _, alive = await asyncio.to_thread(psutil.wait_procs, alive, timeout=remaining)
    if alive:
        raise ProcessContainmentError("Retained worker descendants did not terminate")

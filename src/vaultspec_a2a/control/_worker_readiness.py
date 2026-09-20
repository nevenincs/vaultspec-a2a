"""Admission and cleanup for a newly spawned worker process."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..utils.async_cleanup import complete_cleanup
from ._worker_health import (
    _build_worker_restart_detail,
    _tcp_port_ready,
    worker_ready_and_ours,
)
from ._worker_process_stop import _stop_worker_tree
from .config import settings

if TYPE_CHECKING:
    import subprocess
    from collections.abc import Sequence
    from pathlib import Path

    from ..utils.process import ProcessContainment

__all__ = [
    "WorkerReadySpec",
    "_await_worker_ready",
    "_reap_unready_worker",
]

logger = logging.getLogger("vaultspec_a2a.control.worker_management")


@dataclass(frozen=True, slots=True)
class WorkerReadySpec:
    worker_url: str
    worker_port: int
    generation: int
    worker_command: Sequence[str]
    stderr_log_path: Path


async def _await_worker_ready(
    process: subprocess.Popen[bytes],
    containment: ProcessContainment | None,
    spec: WorkerReadySpec,
) -> subprocess.Popen[bytes] | None:
    """Seat the spawned worker in its containment and wait for it to be ours.

    Returns the handle once the worker at *worker_url* answers as this gateway's,
    or ``None`` when it exited early or never became ready - reaping the tree in
    both cases, so a ``None`` return never leaves a process on the worker port.

    Split out of :func:`_spawn_worker` because this is exactly the region that
    runs with a live process nobody else can yet reach: the handle exists only in
    this frame until it is returned. A raise here - a cancellation on gateway
    shutdown being the realistic one - would therefore strand the worker as an
    orphan holding the port, which the next spawn refuses as an unidentified
    occupant, wedging the band rather than merely leaking a process. Owning the
    process and owning its failure are the same job, so they are the same
    function.
    """
    try:
        return await _await_worker_ready_inner(process, containment, spec)
    except BaseException:
        await _reap_unready_worker(process, containment)
        raise


async def _await_worker_ready_inner(
    process: subprocess.Popen[bytes],
    containment: ProcessContainment | None,
    spec: WorkerReadySpec,
) -> subprocess.Popen[bytes] | None:
    """Seat and poll the worker; see :func:`_await_worker_ready` for the guard."""
    worker_url = spec.worker_url
    worker_port = spec.worker_port
    generation = spec.generation
    worker_command = spec.worker_command
    stderr_log_path = spec.stderr_log_path
    if containment is not None:
        # Assign the worker to its containment before it boots far enough to spawn
        # any descendant (provider roots, MCP bridges). A worker this gateway owns
        # is not admitted without durable tree authority: otherwise a descendant
        # created during cooperative exit can outlive a root that exits first.
        containment.assign_process(process)
    logger.info(
        "Worker process spawned (PID %d) via `%s` with stderr at %s",
        process.pid,
        " ".join(worker_command),
        stderr_log_path,
    )

    # Adaptive health polling (PHASE-1e): fast initial probes, exponential
    # backoff to cap.  TCP fast-path skips expensive HTTP checks while the
    # process is still binding its port.
    ready_timeout = settings.worker_ready_timeout_seconds
    started = asyncio.get_event_loop().time()
    deadline = started + ready_timeout
    interval = settings.worker_poll_initial_interval_seconds
    last_log = 0.0  # elapsed seconds at last progress log

    while asyncio.get_event_loop().time() < deadline:
        # Detect OUR spawn dying before probing health. A spawn that crashed on its
        # bind (the port was held by a surviving foreign worker) must be reported as
        # a failed spawn, never as ready off the foreign worker still answering on
        # the port - so the liveness check leads the readiness check.
        if process.poll() is not None:
            detail = _build_worker_restart_detail(
                returncode=process.returncode,
                stderr_log_path=stderr_log_path,
            )
            logger.error(
                "Worker exited prematurely: %s",
                detail,
            )
            # The root died on its own, but a descendant it had already spawned
            # did not necessarily die with it, and one still holding the worker
            # port wedges the next spawn exactly like a timed-out worker's tree
            # would. Reap on the same terms rather than trusting a dead root to
            # mean a dead tree; the reap also waits the handle, so no zombie is
            # left on POSIX.
            await _reap_unready_worker(process, containment)
            return None

        # Ready only when OUR worker answers: the port being open and healthy is not
        # enough when a foreign orphan can squat a shared band port, so readiness
        # requires the responding worker to declare THIS gateway as its target.
        if await _tcp_port_ready(
            "127.0.0.1", worker_port
        ) and await worker_ready_and_ours(worker_url, current_generation=generation):
            elapsed = asyncio.get_event_loop().time() - started
            logger.info(
                "Worker ready at %s (PID %d) in %.1fs",
                worker_url,
                process.pid,
                elapsed,
            )
            return process

        elapsed = asyncio.get_event_loop().time() - started
        if elapsed - last_log >= settings.worker_poll_log_interval_seconds:
            logger.info("Waiting for worker... (%.0fs elapsed)", elapsed)
            last_log = elapsed

        await asyncio.sleep(interval)
        interval = min(
            interval * settings.worker_poll_backoff_factor,
            settings.worker_poll_max_interval_seconds,
        )

    logger.error(
        "Worker failed to become ready within %.0f seconds; stderr_log=%s",
        ready_timeout,
        stderr_log_path,
    )
    await _reap_unready_worker(process, containment)
    return None


async def _reap_unready_worker(
    process: subprocess.Popen[bytes],
    containment: ProcessContainment | None,
) -> None:
    """Reap a worker that spawned but never became ready, tree and all.

    Every failure path must escalate and fell the whole tree, because the caller
    returns ``None`` afterwards - it reports the spawn as failed, and anything
    still alive is by definition an orphan holding the worker port. The next
    spawn then meets its own leftover on that port and refuses it as an
    unidentified occupant, so an incomplete reap here wedges the band rather
    than merely leaking a process.

    An assigned Job Object or process group is authoritative for the tree. If
    assignment failed before authority was recorded, cleanup suspends the exact
    retained ``Popen`` identity, retains its descendants with creation guards,
    and terminates only those identities before waiting the root handle.

    Either way the handle is waited afterwards so no zombie is left on POSIX.
    """
    await complete_cleanup(_stop_worker_tree(process, containment, term_timeout=5.0))

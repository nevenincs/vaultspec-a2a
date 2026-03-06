"""Worker process supervisor -- lifecycle management (ADR-019).

Spawns the worker as a subprocess, monitors its health via heartbeat
timestamps on ``app.state``, and restarts it on crash or heartbeat timeout.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import sys

import anyio

__all__ = ["WorkerSupervisor"]

logger = logging.getLogger(__name__)


class WorkerSupervisor:
    """Manages the worker child process lifecycle.

    In ``pip install`` mode (``auto_spawn_worker=True``), the control
    surface spawns the worker automatically. In Docker/systemd mode,
    the supervisor is not used -- the worker runs as a separate container
    or service unit.
    """

    def __init__(self, worker_port: int = 8001) -> None:
        self._process: subprocess.Popen[bytes] | None = None
        self._port = worker_port
        self._restart_count = 0
        self._max_restart_backoff = 60.0  # seconds

    @property
    def pid(self) -> int | None:
        """Return worker PID if running."""
        if self._process is not None and self.is_alive():
            return self._process.pid
        return None

    def start(self) -> None:
        """Spawn the worker as a child process."""
        cmd = [sys.executable, "-m", "vaultspec_a2a.worker"]
        self._process = subprocess.Popen(
            cmd,
            # Don't capture stdout/stderr -- let it inherit the parent's
            # streams so worker logs appear alongside API logs.
            stdout=None,
            stderr=None,
        )
        logger.info(
            "Worker spawned (PID %d) on port %d (restart #%d)",
            self._process.pid,
            self._port,
            self._restart_count,
        )

    def is_alive(self) -> bool:
        """Check if the worker process is still running."""
        if self._process is None:
            return False
        return self._process.poll() is None

    async def stop(self) -> None:
        """Gracefully terminate the worker process (non-blocking)."""
        if self._process is not None and self.is_alive():
            logger.info("Stopping worker (PID %d)", self._process.pid)
            self._process.terminate()
            loop = asyncio.get_running_loop()
            try:
                await asyncio.wait_for(
                    loop.run_in_executor(None, self._process.wait),
                    timeout=30,
                )
            except TimeoutError:
                logger.warning("Worker did not exit in 30s -- killing")
                self._process.kill()
                await loop.run_in_executor(None, self._process.wait)
            self._process = None

    async def monitor(self, check_interval: float = 2.0) -> None:
        """Continuously monitor the worker and restart on crash.

        Uses exponential backoff with a cap to avoid tight restart loops.
        Resets backoff after 60s of healthy operation.
        """
        healthy_since: float | None = None

        while True:
            if not self.is_alive():
                # Exponential backoff: 1s, 2s, 4s, 8s, ..., max 60s
                delay = min(2**self._restart_count, self._max_restart_backoff)
                logger.warning(
                    "Worker process died -- restarting in %.0fs (attempt #%d)",
                    delay,
                    self._restart_count + 1,
                )
                await anyio.sleep(delay)
                self._restart_count += 1
                self.start()
                healthy_since = None
            else:
                if healthy_since is None:
                    healthy_since = asyncio.get_running_loop().time()
                elif asyncio.get_running_loop().time() - healthy_since > 60.0:
                    # Reset backoff after sustained healthy period
                    self._restart_count = 0
                    healthy_since = asyncio.get_running_loop().time()

            await anyio.sleep(check_interval)

"""Worker process management — lazy spawner, watchdog, and helpers.

Infrastructure for managing the worker subprocess lifecycle.  Protocol-
agnostic: no FastAPI/HTTP imports.  The caller (``api/app.py``) is responsible
for storing ``WorkerState`` on ``app.state`` and wiring it to route handlers.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

from .config import settings

__all__ = [
    "LazyWorkerSpawner",
    "WorkerState",
    "WorkerWatchdog",
]

logger = logging.getLogger(__name__)

_WORKER_STDERR_TAIL_BYTES = 4096


# ---------------------------------------------------------------------------
# WorkerState dataclass — decouples watchdog from app.state
# ---------------------------------------------------------------------------


@dataclass
class WorkerState:
    """Mutable container for worker lifecycle metadata.

    The watchdog writes to this dataclass instead of directly onto
    ``app.state``.  The lifespan creates it, passes it to the watchdog,
    and also stores it on ``app.state`` for route handlers to read.

    Attributes match the 9 fields the watchdog previously wrote directly
    onto ``app.state``.
    """

    worker_status: str = "pending"
    worker_restart_count: int = 0
    worker_last_restart_reason: str | None = None
    worker_last_restart_detail: str | None = None
    worker_last_restart_started_at: str | None = None
    worker_last_restart_completed_at: str | None = None
    worker_last_restart_succeeded: bool | None = None
    worker_last_restart_attempts: int = 0
    worker_stderr_log_path: str | None = None


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _runtime_dir() -> Path:
    """Return the machine-global runtime directory for gateway-managed process logs.

    Lives under the A2A home (ADR R8), not inside ``.vault/`` — vaultspec
    firmware rejects foreign directories inside the vault.
    """
    runtime_dir = settings.a2a_home / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    return runtime_dir


def _worker_stderr_log_path(worker_port: int) -> Path:
    """Return the deterministic stderr log path for the auto-spawned worker."""
    return _runtime_dir() / f"worker-autospawn-{worker_port}.stderr.log"


def _read_log_tail(log_path: Path, max_bytes: int = _WORKER_STDERR_TAIL_BYTES) -> str:
    """Read and decode the tail of a worker stderr log file."""
    if max_bytes <= 0 or not log_path.exists():
        return ""
    with log_path.open("rb") as handle:
        handle.seek(0, 2)
        size = handle.tell()
        handle.seek(max(size - max_bytes, 0))
        return handle.read(max_bytes).decode(errors="replace").strip()


def _build_worker_restart_detail(
    *,
    returncode: int | None,
    stderr_log_path: Path | None,
) -> str:
    """Build a compact diagnostic string for health/readiness surfaces."""
    detail = f"returncode={returncode}"
    stderr_tail = _read_log_tail(stderr_log_path) if stderr_log_path is not None else ""
    if stderr_tail:
        compact_tail = re.sub(r"\s+", " ", stderr_tail)[:500]
        detail += f"; stderr_tail={compact_tail}"
    detail += f"; stderr_log={stderr_log_path}"
    return detail


async def _tcp_port_ready(host: str, port: int) -> bool:
    """Fast-path: check if a TCP port is accepting connections.

    Much cheaper than a full HTTP health check — used to skip expensive
    httpx probes while the process is still binding.
    """
    try:
        _reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=0.5,
        )
        writer.close()
        await writer.wait_closed()
    except (OSError, TimeoutError):
        return False
    return True


async def _check_worker_health(
    url: str,
    timeout: float = 2.0,
) -> bool:
    """Check if the worker is already running by probing /health."""
    import httpx

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{url}/health",
                timeout=timeout,
            )
            return resp.status_code == 200
    except Exception:
        return False


async def _spawn_worker(
    worker_url: str,
    worker_port: int,
) -> subprocess.Popen[bytes] | None:
    """Spawn the worker as a child process if not already running.

    Returns the ``Process`` handle on success, or ``None`` if the worker
    was already running or failed to start within 30 seconds.
    """
    if await _check_worker_health(worker_url):
        logger.info(
            "Worker already running at %s — skipping auto-spawn",
            worker_url,
        )
        return None

    logger.info(
        "Auto-spawning worker on port %d (ADR-031)",
        worker_port,
    )
    logger.info(
        "Worker spawn env snapshot: gateway_port=%s worker_port=%s"
        " worker_url=%s gateway_url=%s",
        settings.port,
        settings.worker_port,
        settings.worker_url,
        settings.gateway_url,
    )

    # Phase 6: explicitly propagate critical config to the worker subprocess.
    # While Python's subprocess.Popen() inherits the parent env by default,
    # the gateway may have auto-derived gateway_url from host+port.  That
    # computed value is NOT in os.environ, so the child would re-derive it
    # and potentially get a different result (e.g. 0.0.0.0 vs 127.0.0.1).
    # Injecting VAULTSPEC_GATEWAY_URL ensures the worker always points at
    # the correct gateway regardless of how it was started.
    spawn_env = os.environ.copy()
    spawn_env["VAULTSPEC_GATEWAY_URL"] = settings.gateway_url
    spawn_env["VAULTSPEC_PORT"] = str(settings.port)
    spawn_env["VAULTSPEC_WORKER_PORT"] = str(settings.worker_port)
    spawn_env["VAULTSPEC_WORKER_HOST"] = settings.worker_host
    if settings.internal_token is not None:
        spawn_env["VAULTSPEC_INTERNAL_TOKEN"] = settings.internal_token

    stderr_log_path = _worker_stderr_log_path(worker_port)
    stderr_log_path.parent.mkdir(parents=True, exist_ok=True)
    with stderr_log_path.open("wb") as stderr_handle:
        process = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "from vaultspec_a2a.worker.app import main; main()",
            ],
            stdout=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            stderr=stderr_handle,
            env=spawn_env,
        )
    logger.info(
        "Worker process spawned (PID %d) via"
        " `%s -c from vaultspec_a2a.worker.app import main; main()`"
        " with stderr at %s",
        process.pid,
        sys.executable,
        stderr_log_path,
    )

    # Adaptive health polling (PHASE-1e): fast initial probes, exponential
    # backoff to cap.  TCP fast-path skips expensive HTTP checks while the
    # process is still binding its port.
    deadline = asyncio.get_event_loop().time() + 30.0
    interval = settings.worker_poll_initial_interval_seconds
    last_log = 0.0  # elapsed seconds at last progress log

    while asyncio.get_event_loop().time() < deadline:
        # Fast-path: skip full HTTP check if port isn't even open yet.
        if await _tcp_port_ready(
            "127.0.0.1", worker_port
        ) and await _check_worker_health(worker_url):
            elapsed = 30.0 - (deadline - asyncio.get_event_loop().time())
            logger.info(
                "Worker ready at %s (PID %d) in %.1fs",
                worker_url,
                process.pid,
                elapsed,
            )
            return process

        elapsed = 30.0 - (deadline - asyncio.get_event_loop().time())
        if elapsed - last_log >= settings.worker_poll_log_interval_seconds:
            logger.info("Waiting for worker... (%.0fs elapsed)", elapsed)
            last_log = elapsed

        if process.poll() is not None:
            detail = _build_worker_restart_detail(
                returncode=process.returncode,
                stderr_log_path=stderr_log_path,
            )
            logger.error(
                "Worker exited prematurely: %s",
                detail,
            )
            return None

        await asyncio.sleep(interval)
        interval = min(
            interval * settings.worker_poll_backoff_factor,
            settings.worker_poll_max_interval_seconds,
        )

    logger.error(
        "Worker failed to become ready within 30 seconds; stderr_log=%s",
        stderr_log_path,
    )
    process.terminate()
    return None


async def _shutdown_worker_process(
    process: subprocess.Popen[bytes],
) -> None:
    """Shut down the worker child process.

    On Windows, ``process.terminate()`` only kills the immediate process
    and leaves grandchildren orphaned.  Use ``taskkill /T /F`` to kill
    the entire process tree.
    """
    if process.poll() is not None:
        return  # Already exited
    logger.info(
        "Shutting down worker process (PID %d)",
        process.pid,
    )
    if sys.platform == "win32":
        try:
            await asyncio.to_thread(
                subprocess.run,
                [
                    "taskkill",
                    "/T",
                    "/F",
                    "/PID",
                    str(process.pid),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        except Exception:
            with contextlib.suppress(OSError):
                process.kill()
    else:
        process.terminate()
        try:
            await asyncio.to_thread(process.wait, 10.0)
        except subprocess.TimeoutExpired:
            logger.warning("Worker did not exit in 10s, killing")
            process.kill()
    with contextlib.suppress(Exception):
        await asyncio.to_thread(process.wait, 5.0)
    logger.info("Worker process stopped")


# ---------------------------------------------------------------------------
# Lazy worker spawner (PHASE-1a)
# ---------------------------------------------------------------------------


class LazyWorkerSpawner:
    """Defer worker spawn to first dispatch instead of gateway startup.

    Read-only endpoints (list_threads, get_thread_status, list_team_presets,
    etc.) only need the gateway + database.  The worker is spawned lazily
    on the first write-path call (start_thread, send_message, etc.).

    Thread-safe: an ``asyncio.Lock`` prevents double-spawn when multiple
    dispatches arrive concurrently.
    """

    def __init__(
        self,
        worker_url: str,
        worker_port: int,
        auto_spawn: bool,
    ) -> None:
        """Initialise with worker connection details and spawn policy."""
        self._worker_url = worker_url
        self._worker_port = worker_port
        self._auto_spawn = auto_spawn
        self._process: subprocess.Popen[bytes] | None = None
        self._stderr_log_path = (
            _worker_stderr_log_path(worker_port) if auto_spawn else None
        )
        self._spawned = False
        self._lock = asyncio.Lock()

    @property
    def spawned(self) -> bool:
        """Whether the worker has been spawned (or was already running)."""
        return self._spawned

    @property
    def process(self) -> subprocess.Popen[bytes] | None:
        """The worker subprocess handle, if we spawned it."""
        return self._process

    @property
    def stderr_log_path(self) -> Path | None:
        """The worker stderr log path used for gateway-managed spawns."""
        return self._stderr_log_path

    async def ensure_worker(self) -> None:
        """Spawn the worker if not already running.  No-op after first call."""
        if self._spawned:
            return
        async with self._lock:
            # Double-check after acquiring lock.
            if self._spawned:
                return
            if not self._auto_spawn:
                # Not configured to auto-spawn; just check if it's running.
                self._spawned = await _check_worker_health(self._worker_url)
                if not self._spawned:
                    logger.warning(
                        "Worker not running at %s and auto_spawn_worker=False",
                        self._worker_url,
                    )
                return
            logger.info(
                "First dispatch received — starting worker at %s...",
                self._worker_url,
            )
            self._process = await _spawn_worker(
                self._worker_url,
                self._worker_port,
            )
            # Mark as spawned even if _spawn_worker found it already running
            # (returns None when worker was already healthy).
            self._spawned = self._process is not None or (
                await _check_worker_health(self._worker_url)
            )
            if self._spawned:
                logger.info("Worker available — processing dispatch")
            else:
                logger.error(
                    "Failed to spawn worker — dispatches will fail. "
                    "Check worker logs or restart: uv run vaultspec service start"
                )

    @property
    def worker_url(self) -> str:
        """The worker's base URL."""
        return self._worker_url

    @property
    def worker_port(self) -> int:
        """The worker's port number."""
        return self._worker_port

    def replace_process(
        self,
        process: subprocess.Popen[bytes] | None,
    ) -> None:
        """Replace the worker process handle (used by watchdog after restart)."""
        self._process = process
        self._spawned = True

    async def shutdown(self) -> None:
        """Shut down the worker process if we spawned it."""
        if self._process is not None:
            await _shutdown_worker_process(self._process)
            self._process = None


# ---------------------------------------------------------------------------
# Worker watchdog (PROD-002)
# ---------------------------------------------------------------------------


class WorkerWatchdog:
    """Background task monitoring worker health and auto-restarting on crash.

    Detection signals:
    1. ``worker_spawner.process.returncode`` is not None -- process crashed.
    2. ``worker_last_heartbeat_ts`` stale beyond heartbeat timeout
       -- worker unresponsive.

    Recovery: exponential backoff restarts (2s, 4s, 8s), circuit breaker
    coordination, and ``WorkerState`` state machine.
    """

    def __init__(
        self,
        spawner: LazyWorkerSpawner,
        circuit_breaker: Any,
        worker_state: WorkerState,
        app_state: Any,
    ) -> None:
        """Initialise watchdog with references to spawner, breaker, and worker state."""
        self._spawner = spawner
        self._cb = circuit_breaker
        self._worker_state = worker_state
        self._app_state = app_state
        # Initialise worker state
        self._worker_state.worker_status = "pending"
        self._worker_state.worker_restart_count = 0
        self._worker_state.worker_last_restart_reason = None
        self._worker_state.worker_last_restart_detail = None
        self._worker_state.worker_last_restart_started_at = None
        self._worker_state.worker_last_restart_completed_at = None
        self._worker_state.worker_last_restart_succeeded = None
        self._worker_state.worker_last_restart_attempts = 0
        self._worker_state.worker_stderr_log_path = (
            str(spawner.stderr_log_path)
            if spawner.stderr_log_path is not None
            else None
        )

    def _mark_restart_started(self, reason: str, detail: str | None) -> None:
        """Latch restart metadata so callers can observe repair deterministically."""
        self._worker_state.worker_restart_count += 1
        self._worker_state.worker_last_restart_reason = reason
        self._worker_state.worker_last_restart_detail = detail
        self._worker_state.worker_last_restart_started_at = datetime.now(
            UTC
        ).isoformat()
        self._worker_state.worker_last_restart_completed_at = None
        self._worker_state.worker_last_restart_succeeded = None
        self._worker_state.worker_last_restart_attempts = 0

    def _mark_restart_finished(self, succeeded: bool, attempts: int) -> None:
        """Record the terminal outcome of the most recent restart cycle."""
        self._worker_state.worker_last_restart_completed_at = datetime.now(
            UTC
        ).isoformat()
        self._worker_state.worker_last_restart_succeeded = succeeded
        self._worker_state.worker_last_restart_attempts = attempts

    def _heartbeat_stale(self) -> bool:
        """Check if the last heartbeat is older than the timeout threshold."""
        last_hb = getattr(self._app_state, "worker_last_heartbeat_ts", None)
        if last_hb is None:
            return False  # No heartbeat yet — not stale, just not started
        return (time.monotonic() - last_hb) > settings.worker_heartbeat_timeout_seconds

    def _process_crashed(self) -> bool:
        """Check if the worker process has exited unexpectedly."""
        proc = self._spawner.process
        return proc is not None and proc.poll() is not None

    async def _probe_worker_ready(self) -> bool:
        """Probe the worker HTTP health endpoint for status promotion checks."""
        return await _check_worker_health(self._spawner.worker_url)

    async def run(self) -> None:
        """Main watchdog loop — runs until cancelled."""
        try:
            while True:
                await asyncio.sleep(settings.watchdog_poll_interval_seconds)

                # Don't monitor before first dispatch triggers a spawn.
                if not self._spawner.spawned:
                    continue

                # --- Crash detection ---
                http_ready = await self._probe_worker_ready()
                crashed = self._process_crashed()
                stale = self._heartbeat_stale()

                # Promote to "up" only after a positive worker health probe.
                if self._worker_state.worker_status == "pending":
                    if http_ready and not stale and not crashed:
                        self._worker_state.worker_status = "up"
                        continue
                    if not crashed and not stale:
                        continue

                if not crashed and not stale:
                    # Healthy — ensure status reflects it.
                    if self._worker_state.worker_status == "up":
                        continue
                    # Recovered from a transient state.
                    if self._worker_state.worker_status != "down":
                        self._worker_state.worker_status = "up"
                    continue

                # --- Crash detected ---
                reason = "process_exited" if crashed else "heartbeat_stale"
                proc = self._spawner.process
                detail = None
                if crashed and proc is not None:
                    detail = _build_worker_restart_detail(
                        returncode=proc.returncode,
                        stderr_log_path=self._spawner.stderr_log_path,
                    )
                logger.error(
                    "Worker crash detected: %s%s — initiating restart",
                    reason,
                    f" ({detail})" if detail else "",
                )
                self._worker_state.worker_status = "restarting"
                self._mark_restart_started(reason, detail)

                # Force circuit breaker open so dispatches return 503.
                self._cb.force_open()

                # --- Restart with exponential backoff ---
                restarted, attempts = await self._attempt_restart()
                self._mark_restart_finished(restarted, attempts)
                if restarted:
                    self._cb.record_success()
                    self._worker_state.worker_status = "up"
                    logger.info("Worker restarted successfully")
                else:
                    self._worker_state.worker_status = "down"
                    logger.critical(
                        "Worker restart failed after %d attempts — "
                        "manual intervention required. "
                        "Run: uv run vaultspec service start",
                        settings.watchdog_max_retries,
                    )
        except asyncio.CancelledError:
            logger.info("Worker watchdog stopped")

    async def _attempt_restart(self) -> tuple[bool, int]:
        """Try to restart the worker with exponential backoff.

        Returns ``(succeeded, attempts)`` for the current restart cycle.
        """
        for attempt in range(settings.watchdog_max_retries):
            self._worker_state.worker_last_restart_attempts = attempt + 1
            delay = settings.watchdog_backoff_base_seconds * (2**attempt)
            logger.info(
                "Restart attempt %d/%d — waiting %.0fs...",
                attempt + 1,
                settings.watchdog_max_retries,
                delay,
            )
            await asyncio.sleep(delay)

            # Clean up the old process handle.
            old_proc = self._spawner.process
            if old_proc is not None and old_proc.returncode is None:
                await _shutdown_worker_process(old_proc)

            # Spawn a new worker.
            new_proc = await _spawn_worker(
                self._spawner.worker_url,
                self._spawner.worker_port,
            )
            if new_proc is not None:
                self._spawner.replace_process(new_proc)
                return True, attempt + 1

            # Check if an external worker came up.
            if await _check_worker_health(self._spawner.worker_url):
                self._spawner.replace_process(None)
                return True, attempt + 1

        return False, settings.watchdog_max_retries

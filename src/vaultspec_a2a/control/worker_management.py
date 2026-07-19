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

    import httpx

from ..utils import kill_pid_tree_async
from .config import GATEWAY_URL_ENV, INTERNAL_TOKEN_ENV, settings

__all__ = [
    "LazyWorkerSpawner",
    "WorkerState",
    "WorkerWatchdog",
    "sweep_orphan_worker_logs",
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

    Lives under the A2A home, not inside ``.vault/`` — vaultspec
    firmware rejects foreign directories inside the vault.
    """
    runtime_dir = settings.a2a_home / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    return runtime_dir


def _worker_stderr_log_path(worker_port: int) -> Path:
    """Return the deterministic stderr log path for the auto-spawned worker."""
    return _runtime_dir() / f"worker-autospawn-{worker_port}.stderr.log"


_WORKER_LOG_NAME_RE = re.compile(r"^worker-autospawn-(\d+)\.stderr\.log$")


def sweep_orphan_worker_logs(
    *, current_worker_port: int, registry_home: Path | None = None
) -> list[Path]:
    """Delete ``worker-autospawn-<port>.stderr.log`` files with no live claim.

    A dev-band worker instance gets a fresh port (hence a fresh log filename)
    every boot, so the runtime dir accumulates one orphaned file per past
    instance forever - no reap ever touched them (research: 15+ accumulated at
    audit time). Meant to run once per gateway boot, before this process spawns
    its own worker: a file's port is kept when it is the port THIS process is
    about to (re)use, or when the dev-process registry (``~/.vaultspec/procs``,
    a separate registry from this gateway's own service discovery) still shows
    a live record on that port; every other file is a stale orphan and removed.
    Best-effort per file and per registry read - neither may abort a real boot.
    """
    from ..lifecycle.registry import StalenessState, classify_record, list_records

    try:
        live_ports = {
            record.port
            for record in list_records(registry_home)
            if classify_record(record, None) is StalenessState.LIVE
        }
    except OSError:
        live_ports = set()

    removed: list[Path] = []
    for path in _runtime_dir().glob("worker-autospawn-*.stderr.log"):
        match = _WORKER_LOG_NAME_RE.match(path.name)
        if match is None:
            continue
        port = int(match.group(1))
        if port == current_worker_port or port in live_ports:
            continue
        with contextlib.suppress(OSError):
            path.unlink()
            removed.append(path)
    return removed


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


def _internal_auth_headers() -> dict[str, str] | None:
    """Return the worker-IPC bearer header when the internal token is configured.

    The gateway-worker pair authenticates every probe and command with the shared
    worker interprocess-communication credential; a DEVELOPMENT gateway with no
    token sends none, matching the bearer rule the worker enforces.
    """
    if settings.internal_token is None:
        return None
    return {"Authorization": f"Bearer {settings.internal_token}"}


async def _check_worker_health(
    url: str,
    timeout: float = 2.0,
    *,
    client: httpx.AsyncClient | None = None,
) -> bool:
    """Probe the worker's ``GET /health``; ``True`` only on an exact ``200``.

    The single worker-health primitive for every caller - the boot/spawn paths,
    the watchdog's authoritative crash check, and ``/api/health``. Request-path
    callers pass the app-pooled *client* to reuse its connection pool (already
    carrying the worker IPC bearer); the watchdog and boot paths pass none and get
    a self-contained one-shot client that presents the same bearer, so a worker
    that enforces the credential on ``/health`` still answers its owner. "Healthy"
    is an exact ``200`` for all of them, so ``/api/health`` can never silently
    disagree with the watchdog's restart decision (a ``204`` fails both, not one).
    """
    import httpx

    async def _probe(active: httpx.AsyncClient) -> bool:
        resp = await active.get(f"{url}/health", timeout=timeout)
        return resp.status_code == 200

    try:
        if client is not None:
            return await _probe(client)
        async with httpx.AsyncClient(headers=_internal_auth_headers()) as owned:
            return await _probe(owned)
    except Exception:
        return False


async def _fetch_worker_health(
    url: str,
    timeout: float = 2.0,
) -> dict[str, Any] | None:
    """Return the worker's ``GET /health`` JSON body, or ``None`` if unhealthy.

    Unlike :func:`_check_worker_health` this hands back the decoded body so the
    spawn path can read the worker's declared heartbeat target (``gateway_url``)
    and decide whether the live worker belongs to *this* gateway or is a stale
    orphan squatting the port.
    """
    import httpx

    try:
        async with httpx.AsyncClient(headers=_internal_auth_headers()) as client:
            resp = await client.get(f"{url}/health", timeout=timeout)
            if resp.status_code != 200:
                return None
            body = resp.json()
    except Exception:
        return None
    return body if isinstance(body, dict) else None


def _same_gateway(worker_target: object, our_gateway: str) -> bool:
    """Whether a worker's declared heartbeat target is *this* gateway.

    A missing/blank target (an older worker whose ``/health`` predates the
    ``gateway_url`` field) is treated as a match so the fix never regresses a
    correctly-wired legacy worker into a needless eviction; only a present,
    differing target marks a stale orphan.
    """
    if not isinstance(worker_target, str) or not worker_target:
        return True
    return worker_target.rstrip("/") == our_gateway.rstrip("/")


async def _evict_stale_worker(
    worker_url: str,
    worker_port: int,
    *,
    timeout: float = 10.0,
) -> bool:
    """Terminate a stale worker and wait for the port to free.

    Posts the worker's bearer-authenticated ``/admin/shutdown`` (an
    ``os.kill(SIGTERM)`` that is an immediate ``TerminateProcess`` on Windows, not
    a graceful run-draining stop) and polls the TCP port until it stops accepting
    connections. Only ever aimed at a foreign-gateway orphan, never at a worker
    serving this gateway's runs, so the abrupt stop cannot drop live work of ours.
    Returns ``True`` once the port is free, ``False`` if it is still bound after
    *timeout* seconds. The internal token is presented so the shutdown is accepted
    only when this gateway is the worker's paired owner.
    """
    import httpx

    with contextlib.suppress(Exception):
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{worker_url}/admin/shutdown",
                headers=_internal_auth_headers(),
                timeout=2.0,
            )

    deadline = asyncio.get_event_loop().time() + timeout
    freed = False
    while asyncio.get_event_loop().time() < deadline:
        if not await _tcp_port_ready("127.0.0.1", worker_port):
            freed = True
            break
        await asyncio.sleep(0.25)
    else:
        freed = not await _tcp_port_ready("127.0.0.1", worker_port)
    if freed:
        # The evicted worker's own stderr log is a dead end from this point:
        # nothing will append to it unless OUR spawn reuses the same port (which
        # truncates it anyway), and an eviction whose follow-up spawn then fails
        # would otherwise leave it behind exactly like the registry orphans this
        # step's kill/reap deletion closes.
        with contextlib.suppress(OSError):
            _worker_stderr_log_path(worker_port).unlink(missing_ok=True)
    return freed


async def _spawn_worker(
    worker_url: str,
    worker_port: int,
) -> subprocess.Popen[bytes] | None:
    """Spawn the worker as a child process if not already running.

    Returns the ``Process`` handle on success, or ``None`` if the worker
    was already running or failed to start within 30 seconds.
    """
    existing = await _fetch_worker_health(worker_url)
    if existing is not None:
        if _same_gateway(existing.get("gateway_url"), settings.gateway_url):
            logger.info(
                "Worker already running at %s targeting this gateway (%s)"
                " — skipping auto-spawn",
                worker_url,
                settings.gateway_url,
            )
            return None
        # A stale orphan from a dead dev-band gateway is squatting the worker
        # port: it heartbeats a gateway that no longer exists and would never be
        # re-pointed. Evict it and spawn a fresh worker wired to THIS gateway.
        logger.warning(
            "Worker at %s targets a foreign gateway (%s != %s) — evicting the"
            " stale orphan before spawning a fresh worker",
            worker_url,
            existing.get("gateway_url"),
            settings.gateway_url,
        )
        if not await _evict_stale_worker(worker_url, worker_port):
            logger.error(
                "Stale worker at %s did not release port %d — new spawn will"
                " likely fail to bind; manual reap may be required",
                worker_url,
                worker_port,
            )

    logger.info(
        "Auto-spawning worker on port %d",
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

    # Explicitly propagate critical config to the worker subprocess.
    # While Python's subprocess.Popen() inherits the parent env by default,
    # the gateway may have auto-derived gateway_url from host+port.  That
    # computed value is NOT in os.environ, so the child would re-derive it
    # and potentially get a different result (e.g. 0.0.0.0 vs 127.0.0.1).
    # Injecting VAULTSPEC_GATEWAY_URL ensures the worker always points at
    # the correct gateway regardless of how it was started.
    spawn_env = os.environ.copy()
    spawn_env[GATEWAY_URL_ENV] = settings.gateway_url
    spawn_env["VAULTSPEC_PORT"] = str(settings.port)
    spawn_env["VAULTSPEC_WORKER_PORT"] = str(settings.worker_port)
    spawn_env["VAULTSPEC_WORKER_HOST"] = settings.worker_host
    if settings.internal_token is not None:
        spawn_env[INTERNAL_TOKEN_ENV] = settings.internal_token

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
    # Shared async tree-kill (Windows taskkill /T /F, POSIX SIGTERM->SIGKILL); the
    # Popen handle is reaped here since the primitive works by pid.
    await kill_pid_tree_async(process.pid, term_timeout=10.0, kill_timeout=5.0)
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
        if auto_spawn:
            # Startup sweep (once per gateway process, before this port's own log
            # is ever (re)opened): clear stale worker-autospawn stderr logs left
            # behind by past dev-band instances. Best-effort - a sweep failure
            # must never block gateway construction.
            with contextlib.suppress(Exception):
                sweep_orphan_worker_logs(current_worker_port=worker_port)

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
    def auto_spawn(self) -> bool:
        """Whether this gateway is configured to spawn/respawn the worker itself.

        ``False`` means the worker is externally managed: the gateway attaches to a
        running worker but must never spawn or restart it (that belongs to whoever
        owns it, e.g. the dev-process registry).
        """
        return self._auto_spawn

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
# Worker watchdog
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
        # Monotonic timestamp of the last restart CYCLE (not attempt), for the
        # global inter-cycle cooldown that rate-limits a persistent crash signal.
        self._last_restart_cycle_ts: float | None = None
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

    @staticmethod
    def _needs_recovery(*, crashed: bool, stale: bool, http_ready: bool) -> bool:
        """Whether the worker genuinely needs recovery.

        A worker answering ``GET /health`` is alive, so heartbeat-PUSH staleness
        alone (with a healthy HTTP endpoint) is degraded telemetry, not a crash -
        treating it as one is what made the watchdog thrash against a healthy,
        externally-managed worker whose heartbeats were failing (e.g. auth). Only a
        crashed process, or staleness AND an unreachable endpoint, is a real crash.
        """
        return crashed or (stale and not http_ready)

    def _owns_worker(self) -> bool:
        """Whether this gateway may restart the worker (it spawned the process).

        The watchdog must never force the breaker open or spawn a competitor for a
        worker it does not own: an externally-managed worker (``process is None``)
        or a gateway configured not to auto-spawn is reconciled from its HTTP probe
        and its lifecycle left to whoever owns it (the dev-process registry).
        """
        return self._spawner.process is not None and self._spawner.auto_spawn

    def _restart_cooldown_elapsed(self, *, now: float | None = None) -> bool:
        """Whether enough time has passed since the last restart cycle to start one."""
        if self._last_restart_cycle_ts is None:
            return True
        current = now if now is not None else time.monotonic()
        return (
            current - self._last_restart_cycle_ts
        ) >= settings.watchdog_restart_cooldown_seconds

    async def run(self) -> None:
        """Main watchdog loop — runs until cancelled."""
        try:
            while True:
                await asyncio.sleep(settings.watchdog_poll_interval_seconds)
                await self._tick()
        except asyncio.CancelledError:
            logger.info("Worker watchdog stopped")

    async def _tick(self) -> None:
        """One watchdog poll: detect, reconcile status, and restart only when owned."""
        # Don't monitor before first dispatch triggers a spawn.
        if not self._spawner.spawned:
            return

        # --- Detection ---
        http_ready = await self._probe_worker_ready()
        crashed = self._process_crashed()
        stale = self._heartbeat_stale()
        needs_recovery = self._needs_recovery(
            crashed=crashed, stale=stale, http_ready=http_ready
        )

        # --- Adopted / externally-managed worker: reconcile purely from the probe ---
        # We hold no process handle (same-gateway adoption returns None, or the worker
        # is owned by the dev-process registry), so there is no restart path that could
        # ever flip a stuck "down" back up. The owned-worker state machine below keeps a
        # "down" worker down until a real restart recovers it - correct for a worker we
        # can restart, but for an adopted one it would freeze a healthy worker's status
        # at "down"/"pending" and make plain /health readiness lie. Track the live HTTP
        # probe every tick instead, so an adopted healthy worker reaches "up".
        if self._spawner.process is None:
            self._worker_state.worker_status = "up" if http_ready else "down"
            return

        # Promote to "up" only after a positive worker health probe.
        if self._worker_state.worker_status == "pending":
            if http_ready and not needs_recovery:
                self._worker_state.worker_status = "up"
                return
            if not needs_recovery:
                return

        # --- Healthy / degraded-but-alive: reconcile status, never restart ---
        if not needs_recovery:
            if self._worker_state.worker_status == "up":
                return
            # Recovered from a transient state (a "down" worker stays down until a
            # real recovery flips it).
            if self._worker_state.worker_status != "down":
                self._worker_state.worker_status = "up"
            return

        # --- Needs recovery ---
        # The gateway only restarts a worker it OWNS. For an external/adopted worker
        # (or a no-auto-spawn deployment) it reports the truth and leaves recovery to
        # the owner - never force-opening the breaker or spawning a competitor.
        if not self._owns_worker():
            self._worker_state.worker_status = "up" if http_ready else "down"
            return

        # Global inter-cycle cooldown: a persistent crash signal cannot spin restart
        # cycles faster than the configured cooldown.
        if not self._restart_cooldown_elapsed():
            return

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
        self._last_restart_cycle_ts = time.monotonic()
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

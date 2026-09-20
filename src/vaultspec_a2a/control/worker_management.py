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
import subprocess
import threading
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import psutil

if TYPE_CHECKING:
    from pathlib import Path

    from ..lifecycle.shutdown import ShutdownDeadline
    from .circuit_breaker import WorkerCircuitBreaker

from ..utils.async_cleanup import complete_cleanup
from ..utils.process import ProcessContainment, ProcessContainmentError
from ..utils.runtime_exec import module_command
from ._worker_health import (
    GATEWAY_LIFETIME_ENV,
    GATEWAY_LIFETIME_ID,
    WORKER_GENERATION_ENV,
    WorkerHealthProbe,
    WorkerLiveness,
    WorkerState,
    _build_worker_restart_detail,
    _desktop_worker_port_clear,
    _evict_stale_worker,
    _internal_auth_headers,
    _read_log_tail,
    _shared_worker_port_clear,
    _worker_stderr_log_path,
    probe_worker_health,
    sweep_orphan_worker_logs,
    worker_liveness,
    worker_ready_and_ours,
)
from ._worker_process_stop import (
    _reap_retained_processes,
    _shutdown_worker_process,
)
from ._worker_readiness import (
    WorkerReadySpec,
    _await_worker_ready,
    _reap_unready_worker,
)
from .config import settings
from .infra_config import GATEWAY_URL_ENV, INTERNAL_TOKEN_ENV
from .worker_status import WorkerConnectionStatus

__all__ = [
    "GATEWAY_LIFETIME_ENV",
    "GATEWAY_LIFETIME_ID",
    "WORKER_GENERATION_ENV",
    "LazyWorkerSpawner",
    "WorkerHealthProbe",
    "WorkerLiveness",
    "WorkerReadySpec",
    "WorkerState",
    "WorkerWatchdog",
    "_await_worker_ready",
    "_build_worker_restart_detail",
    "_evict_stale_worker",
    "_read_log_tail",
    "_reap_unready_worker",
    "_shutdown_worker_process",
    "_worker_stderr_log_path",
    "probe_worker_health",
    "sweep_orphan_worker_logs",
    "worker_liveness",
    "worker_ready_and_ours",
]

logger = logging.getLogger(__name__)


async def _spawn_worker(
    worker_url: str,
    worker_port: int,
    *,
    containment: ProcessContainment | None = None,
    generation: int = 0,
) -> subprocess.Popen[bytes] | None:
    """Spawn the worker as a child process if not already running.

    Returns the ``Process`` handle on success, or ``None`` if the worker was
    already running or failed to become ready within
    ``settings.worker_ready_timeout_seconds``. A worker that spawned but never
    became ready is reaped tree-and-all before returning, so a failed spawn
    never leaves an orphan holding the worker port.

    Gateway-owned workers receive *containment*: a new POSIX session/process
    group or Windows Job Object assigned before descendant work can begin. A
    failed assignment reaps the exact retained process tree and fails the spawn;
    the worker is never admitted without that authority.

    Ownership contract - the caller allocates *containment* and the caller
    releases it. This function never releases it on the caller's behalf, on any
    exit, so there is no exit the caller has to know about: it releases on every
    return that is not a live process, and on a raise. Splitting that duty (some
    exits releasing here, others expecting the caller to) is what previously let
    three exits leak the handle, so it is stated as one rule rather than a list.

    What this function does guarantee is that nothing it spawned outlives a spawn
    it did not report as successful: any process started here is reaped, tree and
    all, before a ``None`` return or a propagating exception leaves the frame.
    Reaping through a containment closes the handle as a side effect, which is
    harmless - :meth:`ProcessContainment.close` is idempotent - but it is the
    caller's release, not that side effect, that makes the release total.

    Use :func:`_spawn_worker_owned` rather than calling this directly; it is the
    single seam that honours the contract for both spawn paths.
    """
    # The armed desktop gateway owns its worker exclusively, but its private
    # worker port can still be occupied - a surviving prior generation after a
    # containment downgrade, or a stranger process. The authenticated pairing
    # verdict rules on ONE health read (adoption and eviction must share one
    # classification): an OWNED current-generation worker is adopted, a
    # PRIOR_GENERATION worker this gateway demonstrably spawned is evicted
    # under the classifier's authorization (a failed eviction is a conflict,
    # never an adoption), and a FOREIGN or UNIDENTIFIED occupant refuses the
    # spawn loudly with no eviction - it may be serving someone else's runs,
    # and silence is not evidence of ownership.
    if settings.desktop_profile_armed:
        if not await _desktop_worker_port_clear(worker_url, worker_port, generation):
            return None
    elif not await _shared_worker_port_clear(worker_url, worker_port):
        return None

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
    spawn_env[GATEWAY_LIFETIME_ENV] = GATEWAY_LIFETIME_ID
    spawn_env[WORKER_GENERATION_ENV] = str(generation)

    stderr_log_path = _worker_stderr_log_path(worker_port)
    stderr_log_path.parent.mkdir(parents=True, exist_ok=True)
    # POSIX containment seats the worker in a new session/process group at fork;
    # passed explicitly (rather than via ``**kwargs``) so the ``Popen[bytes]``
    # overload is preserved. Windows contributes no spawn-time flag - it assigns
    # the job after spawn.
    new_session = containment is not None and bool(
        containment.spawn_kwargs().get("start_new_session")
    )
    # Freeze-safe worker re-exec: rendered by the runtime's command authority
    # (``python -m vaultspec_a2a.worker`` from source; the binary's own
    # ``run-module`` dispatch when frozen), never assembled interpreter flags.
    worker_command = module_command("vaultspec_a2a.worker")
    with stderr_log_path.open("wb") as stderr_handle:
        process = subprocess.Popen(
            worker_command,
            stdout=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            stderr=stderr_handle,
            env=spawn_env,
            start_new_session=new_session,
        )
    return await _await_worker_ready(
        process,
        containment,
        WorkerReadySpec(
            worker_url, worker_port, generation, worker_command, stderr_log_path
        ),
    )


async def _spawn_worker_owned(
    worker_url: str,
    worker_port: int,
    *,
    generation: int,
) -> tuple[subprocess.Popen[bytes] | None, ProcessContainment | None]:
    """Spawn a worker, holding its OS containment only while it owns a live tree.

    The single seam both spawn paths - first dispatch and watchdog restart - go
    through, so the ownership contract is enforced in one place rather than
    re-implemented per caller. Every gateway-owned worker receives containment,
    independent of serving profile. Externally managed workers are attached to,
    never spawned here. The seam releases the handle on every outcome except the
    one that transfers ownership: a live process for the caller to shut down later.

    Returns ``(process, containment)``, where a non-``None`` containment is always
    paired with the live process it contains. A failed spawn returns
    ``(None, None)`` - never a containment without a tree, which is the stale
    handle a caller would otherwise have to remember to drop - and a raised spawn
    propagates with the handle already released.
    """
    containment = ProcessContainment.create()
    owned = False
    try:
        process = await _spawn_worker(
            worker_url,
            worker_port,
            containment=containment,
            generation=generation,
        )
        owned = process is not None
        return (process, containment) if owned else (None, None)
    finally:
        # One statement covers all three exits - failed spawn, raised spawn, and
        # the success that hands ownership on - because "release unless ownership
        # transferred" is the whole rule.
        if not owned:
            containment.close()


# ---------------------------------------------------------------------------
# Lazy worker spawner (PHASE-1a)
# ---------------------------------------------------------------------------


class LazyWorkerSpawner:
    """Defer worker spawn to first dispatch instead of gateway startup.

    Read-only verbs (run listing, run status, preset listing, etc.) only need
    the gateway + database.  The worker is spawned lazily on the first
    write-path call (run start, follow-up message, etc.).

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
        # Every worker spawned by this gateway carries OS containment. ``None``
        # means no owned process or an explicitly restored fallback handle that
        # shutdown must seat before offering a cooperative interval.
        self._containment: ProcessContainment | None = None
        self._stderr_log_path = (
            _worker_stderr_log_path(worker_port) if auto_spawn else None
        )
        self._spawned = False
        # Incremented before each spawn, so the value a worker carries names the
        # attempt that produced it. A restart yields a distinct generation even
        # when the port, the host and the gateway are unchanged.
        self._generation = 0
        # A plain increment is not atomic - it loads, adds and stores - so two
        # callers can read the same value and issue one generation twice. The
        # asyncio lock below does not help: the watchdog reaches this from a
        # worker thread, not the event loop.
        self._generation_lock = threading.Lock()
        self._lock = asyncio.Lock()
        # Optional demand-readiness signal wired by the armed desktop gateway. It
        # is fired once, on the authenticated demand path, after the single-flight
        # worker start reaches readiness, so deferred boot reconciliation runs only
        # after real execution demand. Unset (``None``) for Compose and dev, whose
        # boot reconciliation is eager.
        self.demand_ready_event: asyncio.Event | None = None
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
        """Spawn the worker if not already running.  No-op after first call.

        A spawn that raises leaves this spawner exactly as it found it - no
        process handle, no containment handle, ``spawned`` still ``False`` - and
        leaves nothing of that attempt alive, because the spawn seam reaps its own
        tree and releases its own containment before propagating. The next
        dispatch therefore retries a genuinely fresh spawn, which is the same
        behaviour a spawn that merely returned failure gets. That equivalence is
        the point: ``spawned`` is set after the spawn rather than before it, so it
        can only ever mean "a worker this gateway can use exists", and an
        exception is one of the ways it does not.
        """
        if self._spawned:
            return
        async with self._lock:
            # Double-check after acquiring lock.
            if self._spawned:
                return
            if not self._auto_spawn:
                # Not configured to auto-spawn; attach only to a worker that
                # declares THIS gateway as its target, never a foreign orphan that
                # merely answers /health on the port. Under the armed profile
                # this attach requires the OWNED pairing verdict, which an
                # externally-managed worker can never present - armed without
                # auto-spawn is a misconfiguration and fails closed.
                self._spawned = await worker_ready_and_ours(
                    self._worker_url, current_generation=self._generation
                )
                if not self._spawned:
                    logger.warning(
                        "No worker targeting this gateway at %s and"
                        " auto_spawn_worker=False",
                        self._worker_url,
                    )
                return
            logger.info(
                "First dispatch received — starting worker at %s...",
                self._worker_url,
            )
            # Every gateway-spawned worker is seated inside OS containment and its
            # whole tree is reaped on shutdown. The spawn seam hands containment
            # back only alongside the live tree it contains.
            generation = self.next_generation()
            self._process, self._containment = await _spawn_worker_owned(
                self._worker_url,
                self._worker_port,
                generation=generation,
            )
            # Mark as spawned even if _spawn_worker found it already running
            # (returns None when a same-gateway worker was already healthy). The
            # fallback probe must confirm the running worker is OURS: a bare health
            # check here would let a refused-eviction foreign orphan (spawn returned
            # None) be adopted as this gateway's worker.
            self._spawned = self._process is not None or (
                await worker_ready_and_ours(
                    self._worker_url, current_generation=self._generation
                )
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

    def next_generation(self) -> int:
        """Advance and return the spawn generation for a replacement worker.

        The watchdog restarts the worker without going through the lazy spawn
        path, so it takes its generation from here rather than minting one; two
        counters would let a restarted worker claim a generation the gateway
        never issued.
        """
        with self._generation_lock:
            self._generation += 1
            return self._generation

    @property
    def generation(self) -> int:
        """Return the spawn generation of the worker this spawner last started."""
        return self._generation

    def replace_process(
        self,
        process: subprocess.Popen[bytes] | None,
        containment: ProcessContainment | None = None,
    ) -> None:
        """Replace the worker process handle (used by watchdog after restart).

        The restart supplies the new tree's containment so shutdown reaps the
        replacement worker's tree, not a stale one; an adopted worker (no owned
        process) carries no containment.

        The containment being replaced is released here, because this is the one
        place the spawner's reference to it is dropped. The restart path reaches
        this after shutting the old worker down, which already released it - but
        only when the old worker was still running. The commonest restart trigger
        is the opposite case, a worker that already exited, whose handle nothing
        else would ever close. ``close`` is idempotent, so releasing on both paths
        costs nothing and removes the distinction as a thing to get right.
        """
        outgoing = self._containment
        if outgoing is not None and outgoing is not containment:
            outgoing.close()
        self._process = process
        self._containment = containment
        self._spawned = True

    @property
    def containment(self) -> ProcessContainment | None:
        """The OS containment owning the worker tree, if this gateway spawned it."""
        return self._containment

    async def _cooperative_shutdown(
        self, process: subprocess.Popen[bytes], deadline: ShutdownDeadline
    ) -> None:
        """Ask a contained worker to stop before the forced cleanup window."""
        cooperative_budget = min(deadline.remaining(reserve=3.0), 1.0)
        if cooperative_budget > 0:
            import httpx

            try:
                async with httpx.AsyncClient(
                    headers=_internal_auth_headers(),
                    timeout=cooperative_budget,
                ) as client:
                    response = await client.post(f"{self._worker_url}/admin/shutdown")
                    if response.status_code != 202:
                        logger.warning(
                            "Worker cooperative shutdown refused with HTTP %d",
                            response.status_code,
                        )
            except httpx.HTTPError:
                logger.warning(
                    "Worker cooperative shutdown request failed; escalating",
                    exc_info=True,
                )
        # Containment remains authoritative after the root exits, so the
        # worker can receive a cooperative grace interval without losing
        # descendants it creates while handling the request.
        wait_budget = min(deadline.remaining(reserve=2.0), 5.0)
        if wait_budget > 0 and process.poll() is None:
            with contextlib.suppress(subprocess.TimeoutExpired):
                await asyncio.to_thread(process.wait, wait_budget)

    @staticmethod
    def _live_descendants(process: subprocess.Popen[bytes]) -> list[psutil.Process]:
        try:
            owner = psutil.Process(process.pid)
            return [
                child for child in owner.children(recursive=True) if child.is_running()
            ]
        except psutil.NoSuchProcess:
            return []

    async def _reap_shutdown_process(
        self,
        process: subprocess.Popen[bytes],
        shutdown_containment: ProcessContainment | None,
        transient_containment: ProcessContainment | None,
        retained_descendants: list[psutil.Process],
        deadline: ShutdownDeadline | None,
    ) -> None:
        try:
            if process.poll() is None or shutdown_containment is not None:
                await complete_cleanup(
                    _shutdown_worker_process(
                        process, shutdown_containment, deadline=deadline
                    )
                )
        finally:
            try:
                if retained_descendants:
                    await complete_cleanup(
                        _reap_retained_processes(
                            retained_descendants, deadline=deadline
                        )
                    )
            finally:
                self._process = None
                if self._containment is not None:
                    self._containment.close()
                if transient_containment is not None:
                    transient_containment.close()
                self._containment = None

    async def shutdown(self, *, deadline: ShutdownDeadline | None = None) -> None:
        """Cooperatively stop the owned worker, then reap its tree by deadline."""
        if self._process is None:
            return
        process = self._process
        shutdown_containment = self._containment
        transient_containment: ProcessContainment | None = None
        retained_descendants: list[psutil.Process] = []
        try:
            if shutdown_containment is None and process.poll() is None:
                retained_descendants = self._live_descendants(process)
                try:
                    transient_containment = ProcessContainment.create()
                    transient_containment.assign_process(process)
                    shutdown_containment = transient_containment
                except (OSError, ProcessContainmentError):
                    if transient_containment is not None:
                        transient_containment.close()
                    transient_containment = None
                    logger.warning(
                        "Worker lacked retained containment and could not be seated "
                        "for cooperative shutdown; escalating while its root identity "
                        "is still live",
                        exc_info=True,
                    )
            if (
                deadline is not None
                and process.poll() is None
                and shutdown_containment is not None
            ):
                await self._cooperative_shutdown(process, deadline)
        finally:
            await self._reap_shutdown_process(
                process,
                shutdown_containment,
                transient_containment,
                retained_descendants,
                deadline,
            )


# ---------------------------------------------------------------------------
# Worker watchdog
# ---------------------------------------------------------------------------


class WorkerWatchdog:
    """Background task monitoring worker health and auto-restarting on crash.

    Detection signals:
    1. ``worker_spawner.process.returncode`` is not None -- process crashed.
    2. :meth:`WorkerLiveness.is_stale` -- no contact within the heartbeat
       timeout, so the worker is unresponsive.

    Recovery: exponential backoff restarts (2s, 4s, 8s), circuit breaker
    coordination, and ``WorkerState`` state machine.
    """

    def __init__(
        self,
        spawner: LazyWorkerSpawner,
        circuit_breaker: WorkerCircuitBreaker,
        worker_state: WorkerState,
        app_state: object,
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
        self._worker_state.worker_status = WorkerConnectionStatus.PENDING.value
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
        return worker_liveness(self._app_state).is_stale()

    def _process_crashed(self) -> bool:
        """Check if the worker process has exited unexpectedly."""
        proc = self._spawner.process
        return proc is not None and proc.poll() is not None

    async def _probe_worker_ready(self) -> bool:
        """Probe the worker HTTP health endpoint for status promotion checks."""
        return (await probe_worker_health(self._spawner.worker_url)).healthy

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
        """Main watchdog loop — runs until cancelled.

        A failing tick must not end the supervisor. The loop exists to recover a
        worker that has gone wrong, and the spawn it performs to do that is the
        most likely thing in it to raise - so an unguarded tick made the first
        failed recovery the last one, leaving the worker permanently unsupervised
        with the circuit breaker held open by the cycle that died. The tick is
        contained instead: the failure is logged and the next poll retries it,
        which is the same treatment a restart that merely failed already gets.

        Containment is per tick rather than a restart of the whole loop, because
        the state a retry needs - the restart cooldown, the attempt counters, the
        breaker - lives on this instance and survives a failed tick. Re-running
        the loop from outside would either discard that state or duplicate the
        backoff logic it encodes.

        Cancellation still stops the loop, and it is the only thing that stops it
        quietly. Any other exit is logged as critical before it propagates: a
        watchdog can fail, but it must not fail silently, or the gateway reports a
        supervised worker it is no longer supervising.
        """
        try:
            while True:
                await asyncio.sleep(settings.watchdog_poll_interval_seconds)
                try:
                    await self._tick()
                except Exception:
                    logger.exception(
                        "Worker watchdog tick failed; the watchdog stays active and"
                        " retries on the next poll"
                    )
        except asyncio.CancelledError:
            logger.info("Worker watchdog stopped")
        except BaseException:
            logger.critical(
                "Worker watchdog terminated by an unhandled exception; the worker"
                " is no longer supervised and will not be restarted automatically",
                exc_info=True,
            )
            raise

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
        if self._reconcile_probe(http_ready, needs_recovery):
            return

        reason = "process_exited" if crashed else "heartbeat_stale"
        proc = self._spawner.process
        if proc is None:
            return
        detail = None
        if crashed:
            detail = _build_worker_restart_detail(
                returncode=proc.returncode,
                stderr_log_path=self._spawner.stderr_log_path,
            )
        logger.error(
            "Worker crash detected: %s%s — initiating restart",
            reason,
            f" ({detail})" if detail else "",
        )
        self._worker_state.worker_status = WorkerConnectionStatus.RESTARTING.value
        self._mark_restart_started(reason, detail)

        # Force circuit breaker open so dispatches return 503.
        self._cb.force_open()

        # Stamp the cycle even when restart raises: the cooldown must also
        # throttle failed spawn attempts.
        try:
            restarted, attempts = await self._attempt_restart()
        finally:
            self._last_restart_cycle_ts = time.monotonic()
        self._mark_restart_finished(restarted, attempts)
        if restarted:
            self._cb.record_success()
            self._worker_state.worker_status = WorkerConnectionStatus.UP.value
            logger.info("Worker restarted successfully")
        else:
            self._worker_state.worker_status = WorkerConnectionStatus.DOWN.value
            logger.critical(
                "Worker restart failed after %d attempts — "
                "manual intervention required. "
                "Run: uv run vaultspec service start",
                settings.watchdog_max_retries,
            )

    def _reconcile_probe(self, http_ready: bool, needs_recovery: bool) -> bool:
        """Return whether this poll settles without an owned-worker restart."""

        # --- Adopted / externally-managed worker: reconcile purely from the probe ---
        # We hold no process handle (same-gateway adoption returns None, or the worker
        # is owned by the dev-process registry), so there is no restart path that could
        # ever flip a stuck "down" back up. The owned-worker state machine below keeps a
        # "down" worker down until a real restart recovers it - correct for a worker we
        # can restart, but for an adopted one it would freeze a healthy worker's status
        # at "down"/"pending" and make plain /health readiness lie. Track the live HTTP
        # probe every tick instead, so an adopted healthy worker reaches "up".
        if self._spawner.process is None:
            self._worker_state.worker_status = (
                WorkerConnectionStatus.UP.value
                if http_ready
                else WorkerConnectionStatus.DOWN.value
            )
            return True

        # Promote to "up" only after a positive worker health probe.
        if (
            self._worker_state.worker_status == WorkerConnectionStatus.PENDING
            and not needs_recovery
        ):
            if http_ready:
                self._worker_state.worker_status = WorkerConnectionStatus.UP.value
            return True

        # --- Healthy / degraded-but-alive: reconcile status, never restart ---
        if not needs_recovery:
            # Recovered from a transient state (a "down" worker stays down until a
            # real recovery flips it).
            if self._worker_state.worker_status not in (
                WorkerConnectionStatus.UP,
                WorkerConnectionStatus.DOWN,
            ):
                self._worker_state.worker_status = WorkerConnectionStatus.UP.value
            return True

        # --- Needs recovery ---
        # The gateway only restarts a worker it OWNS. For an external/adopted worker
        # (or a no-auto-spawn deployment) it reports the truth and leaves recovery to
        # the owner - never force-opening the breaker or spawning a competitor.
        if not self._owns_worker():
            self._worker_state.worker_status = (
                WorkerConnectionStatus.UP.value
                if http_ready
                else WorkerConnectionStatus.DOWN.value
            )
            return True

        # Global inter-cycle cooldown: a persistent crash signal cannot spin restart
        # cycles faster than the configured cooldown.
        return not self._restart_cooldown_elapsed()

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

            # Clean up the old process handle and reap its whole tree through the
            # containment it was spawned in (if any).
            old_proc = self._spawner.process
            if old_proc is not None:
                await _shutdown_worker_process(old_proc, self._spawner.containment)

            # Spawn a new worker inside fresh containment,
            # and hand it to the spawner so shutdown reaps the replacement's tree.
            # A restart that fails hands back no containment either, so a retry
            # loop cannot accumulate one handle per attempt.
            new_proc, new_containment = await _spawn_worker_owned(
                self._spawner.worker_url,
                self._spawner.worker_port,
                generation=self._spawner.next_generation(),
            )
            if new_proc is not None:
                self._spawner.replace_process(new_proc, new_containment)
                return True, attempt + 1

            # Check if an external worker came up. Adoption still requires
            # provenance: under the armed profile the authenticated pairing
            # verdict, elsewhere the declared-gateway_url signal - a bare
            # health 200 from a stranger on the port is not an adoptable
            # worker.
            if await worker_ready_and_ours(
                self._spawner.worker_url,
                current_generation=self._spawner.generation,
            ):
                self._spawner.replace_process(None)
                return True, attempt + 1

        return False, settings.watchdog_max_retries

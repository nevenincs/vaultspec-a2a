"""FastAPI application factory -- the gateway entry point (ADR-019).

Creates the ASGI application with:
- Lifespan management (init/close DB, EventAggregator, telemetry)
- CORS middleware (permissive in dev)
- REST router from ``endpoints.py``
- Internal router from ``internal.py`` (worker relay)
- WebSocket route via ``ConnectionManager``
- StaticFiles mount for React SPA build at ``src/ui/build/`` (ADR-007/018)

The gateway NO LONGER runs agent execution locally.  All graph
compilation and ``aggregator.ingest()`` calls are dispatched to the
worker process via HTTP POST to ``/dispatch`` (ADR-019 service separation).

See: ADR-007 (FastAPI serving, SPA)
     ADR-011 (Frontend-Backend Wire Contract)
     ADR-019 (Service Separation)
"""

import asyncio
import contextlib
import json
import logging
import os
import re
import subprocess
import sys
import time
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import httpx
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from opentelemetry import propagate as _otel_propagate
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request as StarletteRequest
from starlette.responses import Response as StarletteResponse
from starlette.websockets import WebSocket

from ..control.config import settings
from ..database.checkpoints import open_checkpointer
from ..database.crud import ThreadStatus, get_thread, list_threads, update_thread_status
from ..database.migrations import backfill_teamstate_sdd_fields
from ..database.reconciliation import reconcile_threads_on_startup
from ..database.session import (
    close_db,
    get_session_factory,
    init_db,
    inspect_sqlite_database,
)
from ..streaming.aggregator import EventAggregator
from ..telemetry import TelemetryMiddleware, configure_telemetry
from ..telemetry.aggregator_hook import OTelAggregatorHook
from ..utils.asyncio_compat import configure_asyncio_runtime
from .endpoints import router
from .internal import internal_router
from .schemas.enums import AgentControlAction
from .schemas.internal import DispatchRequest
from .websocket import ConnectionManager, WebSocketCommandRejectedError

__all__ = [
    "LazyWorkerSpawner",
    "WorkerCircuitBreaker",
    "WorkerWatchdog",
    "create_app",
    "main",
]

logger = logging.getLogger(__name__)

_WORKER_STDERR_TAIL_BYTES = 4096


def _runtime_dir() -> Path:
    """Return the repo-local runtime directory for gateway-managed process logs."""
    runtime_dir = settings.project_root / ".vault" / "runtime"
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


def _build_sqlite_fallback_diagnostics(
    *,
    database_backend: str | None = None,
    checkpoint_backend: str | None = None,
    database_path: Path | None = None,
    checkpoint_path: Path | None = None,
    busy_timeout_ms: int | None = None,
) -> dict[str, object] | None:
    """Build explicit diagnostics for the SQLite fallback path."""
    resolved_database_backend = database_backend or settings.resolved_database_backend
    resolved_checkpoint_backend = (
        checkpoint_backend or settings.resolved_checkpoint_backend
    )
    if (
        resolved_database_backend != "sqlite"
        and resolved_checkpoint_backend != "sqlite"
    ):
        return None

    diagnostics: dict[str, object] = {
        "active": True,
        "busy_timeout_ms": busy_timeout_ms or settings.sqlite_busy_timeout_ms,
        "production_certifying": False,
        "limitations": ["sqlite_fallback_not_production_certifying"],
    }
    if resolved_database_backend == "sqlite":
        diagnostics["database"] = inspect_sqlite_database(
            database_path or settings.database_path
        )
    if resolved_checkpoint_backend == "sqlite":
        diagnostics["checkpoint"] = inspect_sqlite_database(
            checkpoint_path or settings.checkpoint_path
        )
    return diagnostics


# ---------------------------------------------------------------------------
# Worker circuit breaker (PROD-028)
# ---------------------------------------------------------------------------


class WorkerCircuitBreaker:
    """Track worker dispatch health and reject requests when the worker is down.

    States:
    - CLOSED: dispatches flow normally.  Consecutive failures are counted.
    - OPEN: all dispatches are rejected with 503.  After ``_CB_RECOVERY_TIMEOUT``
      seconds, transitions to HALF_OPEN.
    - HALF_OPEN: a single probe dispatch is allowed through.  Success closes
      the circuit; failure re-opens it.
    """

    def __init__(
        self,
        failure_threshold: int,
        recovery_timeout: float,
    ) -> None:
        """Initialise circuit breaker with failure threshold and recovery timeout."""
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._consecutive_failures = 0
        self._state: str = "closed"  # closed | open | half_open
        self._opened_at: float = 0.0

    @property
    def state(self) -> str:
        """Current circuit state, with automatic half-open promotion."""
        if (
            self._state == "open"
            and (time.monotonic() - self._opened_at) >= self._recovery_timeout
        ):
            self._state = "half_open"
        return self._state

    def pre_dispatch(self) -> None:
        """Call before each dispatch.  Raises ``HTTPException(503)`` if open."""
        from fastapi import HTTPException

        current = self.state
        if current == "open":
            raise HTTPException(
                status_code=503,
                detail=(
                    "Worker circuit breaker OPEN — "
                    f"{self._consecutive_failures} consecutive dispatch failures. "
                    f"Retrying in {self._recovery_timeout}s."
                ),
            )
        # half_open: allow one probe through (don't block)

    def record_success(self) -> None:
        """Record a successful dispatch — closes the circuit."""
        if self._state != "closed":
            logger.info("Worker circuit breaker CLOSED (dispatch succeeded)")
        self._consecutive_failures = 0
        self._state = "closed"

    def record_failure(self) -> None:
        """Record a failed dispatch — may open the circuit."""
        self._consecutive_failures += 1
        if self._consecutive_failures >= self._failure_threshold:
            if self._state != "open":
                logger.warning(
                    "Worker circuit breaker OPEN after %d consecutive failures",
                    self._consecutive_failures,
                )
            self._state = "open"
            self._opened_at = time.monotonic()

    def force_open(self) -> None:
        """Force the circuit open immediately (used by watchdog on crash)."""
        if self._state != "open":
            logger.warning("Worker circuit breaker forced OPEN by watchdog")
        self._consecutive_failures = self._failure_threshold
        self._state = "open"
        self._opened_at = time.monotonic()


# React/Vite hashed immutable assets: /_app/immutable/** or /assets/**
_IMMUTABLE_PATTERN = re.compile(r"^/(_app/immutable|assets)/")
_CACHE_IMMUTABLE = "public, max-age=31536000, immutable"
_CACHE_HTML = "no-cache"


class _CacheControlMiddleware(BaseHTTPMiddleware):
    """Set Cache-Control headers for static SPA assets (ADR-007 S5).

    - ``/_app/immutable/**`` or ``/assets/**`` (content-hashed JS/CSS): cache forever
    - HTML responses (``index.html``, SPA fallback): ``no-cache``
    """

    async def dispatch(
        self,
        request: StarletteRequest,
        call_next: RequestResponseEndpoint,
    ) -> StarletteResponse:
        response = await call_next(request)
        path = request.url.path
        if _IMMUTABLE_PATTERN.search(path):
            response.headers["Cache-Control"] = _CACHE_IMMUTABLE
        elif response.headers.get("content-type", "").startswith("text/html"):
            response.headers["Cache-Control"] = _CACHE_HTML
        return response


# ---------------------------------------------------------------------------
# Dispatch handlers -- forward work to the worker process (ADR-019)
# ---------------------------------------------------------------------------


def _trace_headers() -> dict[str, str]:
    """Build W3C trace context headers for WS-path gateway-to-worker calls (TEL-03)."""
    carrier: dict[str, str] = {}
    _otel_propagate.inject(carrier)
    return carrier


async def _classify_missing_ws_thread(
    *,
    thread_id: str,
    session_factory: Any,
    checkpointer: Any,
) -> WebSocketCommandRejectedError:
    """Classify a missing-thread WebSocket command without assuming total absence."""
    from ..database.crud import get_thread_execution_state

    execution_state_present = False
    try:
        async with session_factory() as db:
            execution_state_present = (
                await get_thread_execution_state(db, thread_id)
            ) is not None
    except Exception:
        logger.warning(
            "Could not inspect execution-state projection for websocket thread %s",
            thread_id,
            exc_info=True,
        )

    checkpoint_present = False
    checkpoint_unverified = False
    try:
        config = {"configurable": {"thread_id": thread_id}}
        checkpoint_tuple = await asyncio.wait_for(
            checkpointer.aget_tuple(config),
            timeout=2.0,
        )
        checkpoint_present = checkpoint_tuple is not None
    except TimeoutError:
        checkpoint_unverified = True
    except Exception:
        logger.debug(
            "Could not verify checkpoint for missing thread %s",
            thread_id,
            exc_info=True,
        )
        checkpoint_unverified = True

    metadata = {
        "execution_state_present": execution_state_present,
        "checkpoint_present": checkpoint_present,
        "checkpoint_unverified": checkpoint_unverified,
    }
    if execution_state_present or checkpoint_present:
        return WebSocketCommandRejectedError(
            thread_id=thread_id,
            code="THREAD_STATE_DRIFT",
            message=(
                "Thread is missing from the gateway database, but durable backend "
                "state still exists. Refresh thread state or trigger repair before "
                "sending follow-up commands."
            ),
            recoverable=True,
            metadata=metadata,
        )
    if checkpoint_unverified:
        return WebSocketCommandRejectedError(
            thread_id=thread_id,
            code="THREAD_STATE_UNVERIFIED",
            message=(
                "Thread is missing from the gateway database and checkpoint truth "
                "could not be verified. Retry after the backend is healthy."
            ),
            recoverable=True,
            metadata=metadata,
        )
    return WebSocketCommandRejectedError(
        thread_id=thread_id,
        code="THREAD_NOT_FOUND",
        message="Thread not found.",
        recoverable=True,
        metadata=metadata,
    )


async def _ws_mark_failed_and_broadcast(
    thread_id: str,
    session_factory: Any,
    connection_manager: Any,
    error_detail: str,
) -> None:
    """Mark a thread FAILED and broadcast a terminal WS event.

    Shared by WS dispatch handlers when the worker is unreachable.
    """
    try:
        async with session_factory() as db:
            await update_thread_status(db, thread_id, ThreadStatus.FAILED)
            await db.commit()
    except Exception:
        logger.warning(
            "Could not set thread %s to FAILED after WS dispatch error",
            thread_id,
            exc_info=True,
        )
    terminal_payload = {
        "event_type": "thread_terminal",
        "thread_id": thread_id,
        "status": "failed",
        "error_detail": error_detail,
    }
    try:
        await connection_manager.broadcast_to_thread(thread_id, terminal_payload)
    except Exception:
        logger.warning(
            "Could not broadcast terminal event for thread %s",
            thread_id,
            exc_info=True,
        )


def _create_dispatch_message_handler(
    worker_client: httpx.AsyncClient,
    session_factory: Any,
    checkpointer: Any,
    circuit_breaker: WorkerCircuitBreaker,
    worker_spawner: "LazyWorkerSpawner",
    connection_manager: Any,
    app_state: Any,
) -> Callable:
    """Create message handler that dispatches to the worker process.

    Replaces the old ``_create_message_handler`` which ran
    ``aggregator.ingest()`` locally.  Now sends an HTTP POST to the
    worker's ``/dispatch`` endpoint (ADR-019).

    Looks up the thread to forward ``team_preset`` and ``workspace_root``
    so the worker can recompile the correct graph (T26b).

    WS-G01: On dispatch failure, marks thread as FAILED in the DB and
    broadcasts a ``thread_terminal`` event so UI clients see the failure
    instead of the thread staying stuck in SUBMITTED state forever.
    """

    async def _dispatch_message(
        thread_id: str,
        content: str,
        agent_id: str | None,
    ) -> None:
        await worker_spawner.ensure_worker()
        circuit_breaker.pre_dispatch()

        # Resolve thread-level fields required by the worker.
        team_preset: str | None = None
        workspace_root: str | None = None
        try:
            async with session_factory() as db:
                thread = await get_thread(db, thread_id)
                if thread is None:
                    raise await _classify_missing_ws_thread(
                        thread_id=thread_id,
                        session_factory=session_factory,
                        checkpointer=checkpointer,
                    )
                # WS-G01: Mirror REST 409 guards — reject dispatch to
                # terminal or input-paused threads.
                _terminal_values = (
                    ThreadStatus.COMPLETED.value,
                    ThreadStatus.FAILED.value,
                    ThreadStatus.CANCELLED.value,
                    ThreadStatus.ARCHIVED.value,
                )
                if thread.status in _terminal_values:
                    raise WebSocketCommandRejectedError(
                        thread_id=thread_id,
                        code="THREAD_TERMINAL",
                        message=(
                            f"Cannot send messages to thread in {thread.status!r} state"
                        ),
                        recoverable=False,
                    )
                if thread.status == ThreadStatus.INPUT_REQUIRED.value:
                    raise WebSocketCommandRejectedError(
                        thread_id=thread_id,
                        code="THREAD_INPUT_REQUIRED",
                        message=(
                            "Cannot send a follow-up message while the"
                            " thread is paused for input"
                        ),
                        recoverable=True,
                    )
                team_preset = thread.team_preset
                if thread.thread_metadata:
                    try:
                        meta = json.loads(thread.thread_metadata)
                        workspace_root = meta.get("workspace_root")
                    except (ValueError, AttributeError):
                        pass
        except WebSocketCommandRejectedError:
            raise
        except Exception:
            logger.warning(
                "Could not look up thread %s for WS dispatch — "
                "team_preset/workspace_root will be None",
                thread_id,
                exc_info=True,
            )

        dispatch = DispatchRequest(
            action="ingest",
            thread_id=thread_id,
            agent_id=agent_id or "vaultspec-supervisor",
            content=content,
            team_preset=team_preset,
            workspace_root=workspace_root,
        )

        try:
            resp = await worker_client.post(
                "/dispatch",
                json=dispatch.model_dump(),
                headers=_trace_headers(),
            )
            # PROD-068: worker 429 means alive but at capacity — message dropped.
            if resp.status_code == httpx.codes.TOO_MANY_REQUESTS:
                logger.warning(
                    "Worker at capacity (429) for WS dispatch thread %s"
                    " — message not delivered",
                    thread_id,
                )
                raise WebSocketCommandRejectedError(
                    thread_id=thread_id,
                    code="WORKER_AT_CAPACITY",
                    message="Worker at capacity — try again later",
                    recoverable=True,
                )
            circuit_breaker.record_success()
            app_state.worker_last_heartbeat_ts = time.monotonic()
        except WebSocketCommandRejectedError:
            raise
        except httpx.HTTPError:
            circuit_breaker.record_failure()
            logger.warning(
                "Failed to dispatch message to worker for thread %s",
                thread_id,
                exc_info=True,
            )
            # WS-G01: Mirror REST path — mark thread FAILED and broadcast.
            await _ws_mark_failed_and_broadcast(
                thread_id,
                session_factory,
                connection_manager,
                "Worker unreachable — message not delivered",
            )

    return _dispatch_message


def _create_dispatch_control_handler(
    worker_client: httpx.AsyncClient,
    session_factory: Any,
    checkpointer: Any,
    circuit_breaker: WorkerCircuitBreaker,
    worker_spawner: "LazyWorkerSpawner",
    app_state: Any,
) -> Callable:
    """Create agent control handler that dispatches to the worker.

    Replaces the old ``_create_agent_control_handler`` which ran
    graph operations locally.  Now sends an HTTP POST to the worker's
    ``/dispatch`` endpoint.
    """

    async def _dispatch_control(
        thread_id: str,
        agent_id: str,
        action: AgentControlAction,
    ) -> None:
        match action:
            case AgentControlAction.TERMINATE:
                dispatch_action = "cancel"
            case AgentControlAction.RESUME:
                logger.warning(
                    "WS RESUME without option_id is a no-op;"
                    " use POST /permissions/{id}/respond"
                    " -- thread %s",
                    thread_id,
                )
                return
            case AgentControlAction.PAUSE:
                logger.info("Pause not supported -- ignoring for thread %s", thread_id)
                return

        async with session_factory() as db:
            thread = await get_thread(db, thread_id)
            if thread is None:
                raise await _classify_missing_ws_thread(
                    thread_id=thread_id,
                    session_factory=session_factory,
                    checkpointer=checkpointer,
                )

        await worker_spawner.ensure_worker()
        # PROD-066: Cancel control must bypass circuit breaker so users can
        # always stop a running agent even when the breaker is OPEN.
        try:
            resp = await worker_client.post(
                "/dispatch",
                json={
                    "action": dispatch_action,
                    "thread_id": thread_id,
                    "agent_id": agent_id,
                },
                headers=_trace_headers(),
            )
            if resp.is_success:
                circuit_breaker.record_success()
                app_state.worker_last_heartbeat_ts = time.monotonic()
        except httpx.HTTPError:
            circuit_breaker.record_failure()
            logger.warning(
                "Failed to dispatch control to worker for thread %s",
                thread_id,
                exc_info=True,
            )

    return _dispatch_control


# ---------------------------------------------------------------------------
# Worker auto-spawn helpers (ADR-031 §2.4)
# ---------------------------------------------------------------------------


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
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{url}/health",
                timeout=timeout,
            )
            return resp.status_code == 200
    except (httpx.ConnectError, httpx.TimeoutException):
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
    2. ``worker_last_heartbeat_ts`` stale beyond ``_WORKER_HEARTBEAT_TIMEOUT``
       -- worker unresponsive.

    Recovery: exponential backoff restarts (2s, 4s, 8s), circuit breaker
    coordination, and ``worker_status`` state machine on ``app.state``.
    """

    def __init__(
        self,
        spawner: LazyWorkerSpawner,
        circuit_breaker: WorkerCircuitBreaker,
        app_state: Any,
    ) -> None:
        """Initialise watchdog with references to spawner, breaker, and app state."""
        self._spawner = spawner
        self._cb = circuit_breaker
        self._app_state = app_state
        # State machine: pending → up → restarting → up | down
        self._app_state.worker_status = "pending"
        self._app_state.worker_restart_count = 0
        self._app_state.worker_last_restart_reason = None
        self._app_state.worker_last_restart_detail = None
        self._app_state.worker_last_restart_started_at = None
        self._app_state.worker_last_restart_completed_at = None
        self._app_state.worker_last_restart_succeeded = None
        self._app_state.worker_last_restart_attempts = 0
        self._app_state.worker_stderr_log_path = (
            str(spawner.stderr_log_path)
            if spawner.stderr_log_path is not None
            else None
        )

    def _mark_restart_started(self, reason: str, detail: str | None) -> None:
        """Latch restart metadata so callers can observe repair deterministically."""
        self._app_state.worker_restart_count += 1
        self._app_state.worker_last_restart_reason = reason
        self._app_state.worker_last_restart_detail = detail
        self._app_state.worker_last_restart_started_at = datetime.now(UTC).isoformat()
        self._app_state.worker_last_restart_completed_at = None
        self._app_state.worker_last_restart_succeeded = None
        self._app_state.worker_last_restart_attempts = 0

    def _mark_restart_finished(self, succeeded: bool, attempts: int) -> None:
        """Record the terminal outcome of the most recent restart cycle."""
        self._app_state.worker_last_restart_completed_at = datetime.now(UTC).isoformat()
        self._app_state.worker_last_restart_succeeded = succeeded
        self._app_state.worker_last_restart_attempts = attempts

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
                if self._app_state.worker_status == "pending":
                    if http_ready and not stale and not crashed:
                        self._app_state.worker_status = "up"
                        continue
                    if not crashed and not stale:
                        continue

                if not crashed and not stale:
                    # Healthy — ensure status reflects it.
                    if self._app_state.worker_status == "up":
                        continue
                    # Recovered from a transient state.
                    if self._app_state.worker_status != "down":
                        self._app_state.worker_status = "up"
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
                self._app_state.worker_status = "restarting"
                self._mark_restart_started(reason, detail)

                # Force circuit breaker open so dispatches return 503.
                self._cb.force_open()

                # --- Restart with exponential backoff ---
                restarted, attempts = await self._attempt_restart()
                self._mark_restart_finished(restarted, attempts)
                if restarted:
                    self._cb.record_success()
                    self._app_state.worker_status = "up"
                    logger.info("Worker restarted successfully")
                else:
                    self._app_state.worker_status = "down"
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
            self._app_state.worker_last_restart_attempts = attempt + 1
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


# ---------------------------------------------------------------------------
# Application lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Application lifespan: startup and shutdown hooks.

    ADR-019: The gateway no longer runs agent execution.  All
    graph compilation and ingest calls are dispatched to the worker
    process.  The lifespan sets up:
    1. Database (SQLAlchemy)
    2. Read-only checkpointer (for snapshot queries -- safe under WAL mode)
    3. EventAggregator (lightweight -- for local event relay only)
    4. ConnectionManager
    5. Telemetry
    6. httpx.AsyncClient for worker dispatch
    """
    # --- Startup ---
    logger.info("Starting gateway lifespan (ADR-019)")
    settings.validate_postgres_requirement()

    engine = await init_db(settings.database_url)
    logger.info(
        "Database initialised (%s, migrations applied)",
        settings.resolved_database_backend,
    )
    app.state.sqlite_fallback_diagnostics = _build_sqlite_fallback_diagnostics()

    if settings.resolved_checkpoint_backend == "sqlite":
        backfill_teamstate_sdd_fields(settings.checkpoint_path)

    # LangGraph checkpointer -- READ-ONLY in the gateway (ADR-019).
    async with open_checkpointer() as checkpointer:
        app.state.checkpointer = checkpointer
        logger.info(
            "LangGraph checkpointer initialised (%s)",
            settings.resolved_checkpoint_backend,
        )

        if settings.repair_on_startup:
            session_factory = get_session_factory()
            async with session_factory() as db:
                app.state.repair_summary = await reconcile_threads_on_startup(
                    db, checkpointer, strategy=settings.repair_strategy
                )
                await db.commit()
        else:
            app.state.repair_summary = {
                "repair_backlog": 0,
                "paused_resumable": 0,
                "checkpoint_unavailable": 0,
            }

        # Event aggregator -- lightweight in the gateway.
        # No graphs are registered here; the worker runs ingest.
        aggregator = EventAggregator(telemetry=OTelAggregatorHook())
        app.state.aggregator = aggregator

        # Connection manager (depends on aggregator)
        connection_manager = ConnectionManager(aggregator)
        app.state.connection_manager = connection_manager

        # Store engine ref for shutdown
        app.state.db_engine = engine

        # Telemetry (ADR-010 -- mandatory)
        configure_telemetry()
        logger.info("Telemetry configured")

        # httpx client for dispatching work to the worker process
        worker_client = httpx.AsyncClient(
            base_url=settings.worker_url,
            timeout=httpx.Timeout(30.0, connect=5.0),
            headers=(
                {"Authorization": f"Bearer {settings.internal_token}"}
                if settings.internal_token is not None
                else None
            ),
        )
        app.state.worker_client = worker_client
        logger.info("Worker client configured: %s", settings.worker_url)

        # PHASE-1a: Lazy worker spawn — defer to first dispatch so
        # read-only endpoints (list_threads, get_thread_status, etc.)
        # work instantly without waiting for the worker to start.
        worker_spawner = LazyWorkerSpawner(
            worker_url=settings.worker_url,
            worker_port=settings.worker_port,
            auto_spawn=settings.auto_spawn_worker,
        )
        app.state.worker_spawner = worker_spawner

        # PROD-028: Circuit breaker for worker dispatch
        circuit_breaker = WorkerCircuitBreaker(
            failure_threshold=settings.cb_failure_threshold,
            recovery_timeout=settings.cb_recovery_timeout_seconds,
        )
        app.state.circuit_breaker = circuit_breaker

        # PROD-002: Worker watchdog — auto-restart on crash
        watchdog = WorkerWatchdog(worker_spawner, circuit_breaker, app.state)
        watchdog_task = asyncio.create_task(watchdog.run())

        # Wire dispatch handlers for WebSocket commands
        msg_handler = _create_dispatch_message_handler(
            worker_client,
            get_session_factory(),
            checkpointer,
            circuit_breaker,
            worker_spawner,
            connection_manager,
            app.state,
        )
        connection_manager.set_message_handler(msg_handler)

        ctrl_handler = _create_dispatch_control_handler(
            worker_client,
            get_session_factory(),
            checkpointer,
            circuit_breaker,
            worker_spawner,
            app.state,
        )
        connection_manager.set_agent_control_handler(ctrl_handler)

        # F-36 fix: re-dispatch RECONCILING threads after worker is ready.
        # reconcile_threads_on_startup marks threads but never dispatches them.
        async def _redispatch_reconciling() -> None:
            try:
                await worker_spawner.ensure_worker()
                session_factory = get_session_factory()
                async with session_factory() as db:
                    threads, _ = await list_threads(
                        db, status=ThreadStatus.RECONCILING, limit=100
                    )
                    if not threads:
                        return
                    logger.info("Re-dispatching %d reconciling threads", len(threads))
                    for thread in threads:
                        meta = {}
                        if thread.thread_metadata:
                            try:
                                meta = json.loads(thread.thread_metadata)
                            except Exception:
                                logger.debug(
                                    "Failed to parse thread metadata for %s",
                                    thread.id,
                                    exc_info=True,
                                )
                        dispatch = DispatchRequest(
                            action="ingest",
                            thread_id=thread.id,
                            team_preset=thread.team_preset,
                            workspace_root=meta.get("workspace_root"),
                        )
                        try:
                            if circuit_breaker.state == "open":
                                logger.warning(
                                    "Circuit breaker open, skipping re-dispatch for %s",
                                    thread.id,
                                )
                                continue
                            resp = await worker_client.post(
                                "/dispatch",
                                json=dispatch.model_dump(),
                                headers=_trace_headers(),
                            )
                            if resp.is_success:
                                circuit_breaker.record_success()
                                app.state.worker_last_heartbeat_ts = time.monotonic()
                                logger.info(
                                    "Re-dispatched reconciling thread %s",
                                    thread.id,
                                )
                            else:
                                logger.warning(
                                    "Re-dispatch failed for thread %s: %s",
                                    thread.id,
                                    resp.status_code,
                                )
                        except Exception as exc:
                            logger.warning(
                                "Re-dispatch error for thread %s: %s",
                                thread.id,
                                exc,
                            )
            except Exception as exc:
                logger.error("Reconciling re-dispatch task failed: %s", exc)

        reconcile_task = asyncio.create_task(_redispatch_reconciling())

        logger.info("Gateway startup complete")

        yield

        reconcile_task.cancel()
        await asyncio.gather(reconcile_task, return_exceptions=True)

        # --- Shutdown ---
        logger.info("Shutting down gateway")

        watchdog_task.cancel()
        await asyncio.gather(watchdog_task, return_exceptions=True)

        await worker_spawner.shutdown()
        await worker_client.aclose()
        await connection_manager.shutdown()
        await aggregator.shutdown()
        await close_db()

        logger.info("Gateway shutdown complete")


def main() -> None:
    """Launch the vaultspec-a2a server.

    Entry point for the ``vaultspec`` CLI command defined in
    ``[project.scripts]`` (ADR-015).
    """
    configure_asyncio_runtime()
    uvicorn.run(
        "vaultspec_a2a.api.app:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        log_level="info",
        loop="auto",
    )


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Returns:
        A fully configured ``FastAPI`` instance ready for ``uvicorn.run()``.
    """
    app = FastAPI(
        title="Vaultspec A2A Orchestrator",
        version="0.1.0",
        lifespan=_lifespan,
    )

    # --- CORS Middleware ---
    # Always add CORS so the React SPA can make cross-origin requests in
    # both dev and production (C1 fix).  CORS spec forbids allow_origins=["*"]
    # combined with allow_credentials=True (browsers reject such responses), so
    # we never use wildcard origins.  In dev the extra Vite origins are included;
    # in production the deployer sets VAULTSPEC_CORS_ALLOWED_ORIGINS.
    cors_origins: list[str] = list(settings.cors_allowed_origins)
    app.add_middleware(
        cast("Any", CORSMiddleware),
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # --- Telemetry Middleware (ADR-010) ---
    app.add_middleware(cast("Any", TelemetryMiddleware))

    # --- Cache-Control Middleware (ADR-007 S5) ---
    app.add_middleware(cast("Any", _CacheControlMiddleware))

    # --- REST Router ---
    app.include_router(router, prefix="/api")

    # --- Internal Router (worker relay -- ADR-019) ---
    app.include_router(internal_router)

    # --- Gateway Health (CRIT-03 — MCP startup probe target) ---
    @app.get("/health")
    async def health_endpoint() -> dict[str, object]:
        """Top-level liveness check for external probes.

        `/health` stays green when the gateway process is alive. Aggregate
        dependency readiness is exposed separately via `/api/health`.
        """
        worker_connected = False
        last_hb = getattr(app.state, "worker_last_heartbeat_ts", None)
        if last_hb is not None:
            worker_connected = (
                time.monotonic() - last_hb
            ) < settings.worker_heartbeat_timeout_seconds
        cb: WorkerCircuitBreaker | None = getattr(
            app.state,
            "circuit_breaker",
            None,
        )
        cb_state = cb.state if cb is not None else "unknown"
        spawner: LazyWorkerSpawner | None = getattr(
            app.state,
            "worker_spawner",
            None,
        )
        worker_spawned = spawner.spawned if spawner is not None else False
        worker_pid = (
            spawner.process.pid if spawner is not None and spawner.process else None
        )
        worker_status = getattr(app.state, "worker_status", "unknown")
        worker_restart_count = getattr(app.state, "worker_restart_count", 0)
        worker_last_restart_reason = getattr(
            app.state,
            "worker_last_restart_reason",
            None,
        )
        worker_last_restart_detail = getattr(
            app.state,
            "worker_last_restart_detail",
            None,
        )
        worker_last_restart_started_at = getattr(
            app.state,
            "worker_last_restart_started_at",
            None,
        )
        worker_last_restart_completed_at = getattr(
            app.state,
            "worker_last_restart_completed_at",
            None,
        )
        worker_last_restart_succeeded = getattr(
            app.state,
            "worker_last_restart_succeeded",
            None,
        )
        worker_last_restart_attempts = getattr(
            app.state,
            "worker_last_restart_attempts",
            0,
        )
        worker_stderr_log_path = getattr(
            app.state,
            "worker_stderr_log_path",
            None,
        )
        repair_summary = getattr(
            app.state,
            "repair_summary",
            {
                "repair_backlog": 0,
                "paused_resumable": 0,
                "checkpoint_unavailable": 0,
            },
        )
        sqlite_fallback_diagnostics = getattr(
            app.state, "sqlite_fallback_diagnostics", None
        )
        ready = not (
            cb_state == "open"
            or worker_status in {"down", "restarting"}
            or (worker_spawned and not worker_connected)
        )
        return {
            "status": "ok",
            "service": "gateway",
            "ready": ready,
            "worker_connected": worker_connected,
            "worker_spawned": worker_spawned,
            "worker_pid": worker_pid,
            "worker_status": worker_status,
            "worker_restart_count": worker_restart_count,
            "worker_last_restart_reason": worker_last_restart_reason,
            "worker_last_restart_detail": worker_last_restart_detail,
            "worker_last_restart_started_at": worker_last_restart_started_at,
            "worker_last_restart_completed_at": worker_last_restart_completed_at,
            "worker_last_restart_succeeded": worker_last_restart_succeeded,
            "worker_last_restart_attempts": worker_last_restart_attempts,
            "worker_stderr_log_path": worker_stderr_log_path,
            "circuit_breaker": cb_state,
            "database_backend": settings.resolved_database_backend,
            "checkpoint_backend": settings.resolved_checkpoint_backend,
            "postgres_required": settings.postgres_required,
            # production_certifying is true only when BOTH the application DB
            # and the checkpoint backend resolve to Postgres.  SQLite is a
            # supported fallback for local/CI use but is not the certifying
            # production backend.  Operators should monitor this field and
            # alert when it is false in a production deployment.
            "production_certifying": (
                settings.resolved_database_backend == "postgres"
                and settings.resolved_checkpoint_backend == "postgres"
            ),
            "repair_backlog": repair_summary.get("repair_backlog", 0),
            "paused_resumable": repair_summary.get("paused_resumable", 0),
            "checkpoint_unavailable": repair_summary.get("checkpoint_unavailable", 0),
            "sqlite_fallback": sqlite_fallback_diagnostics,
        }

    # --- WebSocket Route ---
    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        """WebSocket endpoint for multiplexed real-time events."""
        cm: ConnectionManager = app.state.connection_manager
        client_id = await cm.connect(websocket)
        await cm.listen(client_id)

    # --- Static Files (React SPA) ---
    if settings.ui_build_dir.is_dir():
        app.mount(
            "/",
            StaticFiles(directory=str(settings.ui_build_dir), html=True),
            name="ui",
        )
        logger.info("Mounted React SPA from %s", settings.ui_build_dir)
    else:
        logger.warning(
            "SPA build not found at %s -- UI will not be served",
            settings.ui_build_dir,
        )

    return app


if __name__ == "__main__":
    main()

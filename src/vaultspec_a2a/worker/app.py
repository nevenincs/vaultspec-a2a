r"""Worker process -- standalone FastAPI application.

Exposes an internal HTTP dispatch endpoint that the gateway
calls to schedule graph execution.  Manages the ``Executor`` lifecycle
and heartbeat loop.

Run standalone::

    python -m uvicorn vaultspec_a2a.worker.app:create_worker_app \
        --factory --host 127.0.0.1 --port 18001

Or via the ``vaultspec-worker`` console script (once registered in
``pyproject.toml``).
"""

from __future__ import annotations

import logging
import os
import signal
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

from uuid import uuid4

import anyio  # anyio: structured task groups for heartbeat + dispatch.
import anyio.abc
import httpx
import uvicorn
from anyio.to_thread import run_sync
from fastapi import Depends, FastAPI, Header, HTTPException
from opentelemetry import metrics, trace
from opentelemetry.sdk.metrics import MeterProvider as SdkMeterProvider
from opentelemetry.sdk.trace import TracerProvider as SdkTracerProvider

from ..control.config import GATEWAY_URL_ALT_ENV, GATEWAY_URL_ENV, settings
from ..control.worker_management import (
    GATEWAY_LIFETIME_ENV,
    WORKER_GENERATION_ENV,
)
from ..database.checkpoints import open_checkpointer
from ..ipc.schemas import DispatchRequest, DispatchResponse
from ..lifecycle.pairing import DispatchPairingStatus, resolve_worker_gateway_target
from ..lifecycle.registration import deregister_serve, register_serve
from ..providers.warmup import warm_model_imports
from ..telemetry import TelemetryMiddleware, configure_telemetry
from ..utils import (
    BearerVerdict,
    configure_logging,
    package_version,
    reconfigure_console_utf8,
    verify_internal_bearer,
)
from ..utils.asyncio_compat import configure_asyncio_runtime
from .dispatch_ids import DispatchIdAdmission
from .executor import Executor
from .ipc import WorkerBridge

__all__ = ["WorkerApp", "create_worker_app", "main"]

logger = logging.getLogger(__name__)

# Re-export so the facade ``vaultspec_a2a.worker`` can expose ``WorkerApp``
# as the public type alias (matches the placeholder's API contract).
WorkerApp = FastAPI


async def _warm_model_imports() -> None:
    """Load the model stack in the background while the worker serves.

    The compile path offloads this import too, so correctness never depends on
    this task: it only decides whether the FIRST run of a worker's life pays the
    several seconds up front or overlaps them with the idle window before a
    dispatch arrives. Started after the app is serving rather than before,
    because blocking readiness on it would trade a slow first run for a slow
    spawn, and the gateway waits on readiness.

    A failure is logged and dropped HERE only. The compile path performs the same
    import and will raise there, where the run it belongs to can be failed
    truthfully, so nothing is hidden by declining to take the worker down over a
    warm-up.
    """
    try:
        await run_sync(warm_model_imports)
    except Exception:
        logger.warning(
            "Model stack warm-up failed; the first run will load it inline",
            exc_info=True,
            extra={"action": "model_warmup_failed"},
        )


async def _verify_dispatch_token(
    authorization: str | None = Header(None),
) -> None:
    """Verify bearer token for gateway->worker dispatch requests.

    Delegates the rule to the shared IPC bearer verifier; the worker keeps its
    ``WWW-Authenticate`` header on the 401.
    """
    verdict, detail = verify_internal_bearer(
        authorization,
        token=settings.internal_token,
        environment=settings.environment,
    )
    if verdict is BearerVerdict.MISCONFIGURED:
        raise HTTPException(status_code=500, detail=detail)
    if verdict is BearerVerdict.UNAUTHORIZED:
        raise HTTPException(
            status_code=401,
            detail=detail,
            headers={"WWW-Authenticate": "Bearer"},
        )


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Worker lifespan: initialise checkpointer, bridge, executor, heartbeat.

    Startup sequence:
    1. Open the configured backend-selectable checkpointer (SQLite or Postgres) via
       ``open_checkpointer()``.
    2. Create the ``WorkerBridge`` HTTP client.
    3. Instantiate the ``Executor`` with checkpointer + bridge.
    4. Launch the heartbeat loop as a background task.
    5. Launch the model-stack warm-up as a background task, so the first run
       does not pay its import cost inline.

    On shutdown the heartbeat is cancelled and the bridge client closed.
    """
    worker_id = uuid4().hex[:8]
    logger.info("Worker %s starting", worker_id)
    settings.validate_postgres_requirement()

    # Configure OTel with the worker service name so spans are
    # attributed separately from the gateway in Jaeger/OTLP backends.
    configure_telemetry(service_name="vaultspec-worker")
    logger.info("Telemetry configured (service=vaultspec-worker)")

    # Worker -> gateway pairing (the master-bug guard's missing other half): a band
    # worker whose gateway target was never explicitly configured auto-derives the
    # SAME resident default (settings._derive_service_urls) the observed bug hit -
    # it then heartbeats a dead or foreign gateway forever with nothing louder than
    # log noise. Learn a live band gateway when it is unambiguous, and refuse to
    # boot (mirroring the gateway's own dispatch-pairing guard) rather than run
    # broken when the pairing cannot be resolved safely.
    gateway_url_explicit = bool(
        os.environ.get(GATEWAY_URL_ENV) or os.environ.get(GATEWAY_URL_ALT_ENV)
    )
    resolved_gateway_url, pairing_status, pairing_message = (
        resolve_worker_gateway_target(
            settings.gateway_url,
            gateway_url_explicit=gateway_url_explicit,
            worker_port=settings.worker_port,
        )
    )
    if pairing_status is DispatchPairingStatus.MISPAIRED:
        raise RuntimeError(pairing_message)
    app.state.gateway_pairing_warning = None
    if resolved_gateway_url != settings.gateway_url:
        logger.info("Worker gateway pairing: %s", pairing_message)
        settings.gateway_url = resolved_gateway_url
    elif pairing_status is DispatchPairingStatus.UNPAIRED:
        logger.warning("Worker gateway pairing: %s", pairing_message)
        app.state.gateway_pairing_warning = pairing_message

    async with open_checkpointer() as checkpointer:
        bridge = WorkerBridge(
            settings.gateway_url,
            worker_id,
            settings.internal_token,
        )

        # Non-fatal startup probe — verify the gateway is
        # reachable *before* we accept dispatches. Logs ERROR if the
        # gateway cannot be contacted so operators notice immediately.
        try:
            probe = await bridge._client.get("/health")
            if probe.status_code == 200:
                logger.info(
                    "Gateway reachable at %s",
                    settings.gateway_url,
                )
            else:
                logger.error(
                    "Gateway probe returned HTTP %d"
                    " (gateway_url=%s) — IPC events may"
                    " not be delivered",
                    probe.status_code,
                    settings.gateway_url,
                )
        except httpx.HTTPError:
            logger.error(
                "Gateway UNREACHABLE at startup"
                " (gateway_url=%s) — permission requests"
                " and status events will NOT be delivered"
                " until the gateway is available",
                settings.gateway_url,
                exc_info=True,
            )

        executor = Executor(checkpointer, bridge)

        app.state.executor = executor
        app.state.bridge = bridge

        # A worker booted on a band port (worker-dev)
        # self-registers so `procs` can enumerate/reap it; a resident worker on
        # its fixed out-of-band port registers nothing (returns None). worker-dev
        # is a non-heartbeat role, so pid-liveness alone governs its staleness.
        worker_record = register_serve(
            "worker-dev",
            settings.worker_port,
            # Absent is the empty string the registry documents, never the
            # rendering of None: workspace_root carries no default, so
            # stringifying it unconditionally registers the literal "None" as a
            # directory for every process that never had one.
            workspace=""
            if settings.workspace_root is None
            else str(settings.workspace_root),
            command=[
                "python",
                "-m",
                "vaultspec_a2a.worker",
                "--port",
                str(settings.worker_port),
            ],
        )

        async with anyio.create_task_group() as tg:
            app.state.task_group = tg

            # Start the periodic heartbeat loop as a background task.
            tg.start_soon(bridge.heartbeat_loop, 10.0)
            tg.start_soon(_warm_model_imports)

            logger.info("Worker %s ready on port %d", worker_id, settings.worker_port)

            yield

            # Shutdown path
            logger.info("Worker %s shutting down", worker_id)
            deregister_serve(worker_record)
            tg.cancel_scope.cancel()

        await executor.shutdown()
        await bridge.close()

        provider = trace.get_tracer_provider()
        if isinstance(provider, SdkTracerProvider):
            await run_sync(provider.shutdown)
        meter_provider = metrics.get_meter_provider()
        if isinstance(meter_provider, SdkMeterProvider):
            await run_sync(meter_provider.shutdown)


def create_worker_app(lifespan: Any | None = None) -> FastAPI:
    """Create and return the worker FastAPI application.

    Args:
        lifespan: Optional lifespan override for testing. When ``None``
            the production ``_lifespan`` is used.

    Called as a factory by ``uvicorn`` (``--factory`` flag) or directly
    in tests.
    """
    app = FastAPI(
        title="Vaultspec Worker",
        version=package_version(),
        lifespan=lifespan or _lifespan,
    )
    # One process-local, restart-cleared suppression window.  Endpoint admission
    # is synchronous, so duplicate IDs cannot both cross into the task group.
    app.state.dispatch_ids = DispatchIdAdmission()

    # Instrument incoming requests so the worker's spans participate
    # in distributed traces started by the gateway (W3C traceparent extraction).
    app.add_middleware(cast("Any", TelemetryMiddleware))

    @app.post(
        "/dispatch",
        response_model=DispatchResponse,
        dependencies=[Depends(_verify_dispatch_token)],
    )
    async def dispatch_endpoint(req: DispatchRequest) -> DispatchResponse:
        """Accept a work dispatch from the gateway.

        The actual graph execution is scheduled as a background task inside
        the lifespan task group so that this endpoint returns immediately.
        """
        executor: Executor = app.state.executor
        tg = app.state.task_group

        dispatch_ids: DispatchIdAdmission = app.state.dispatch_ids
        if req.dispatch_id in dispatch_ids:
            logger.info(
                "Worker duplicate dispatch suppressed",
                extra={
                    "action": "dispatch_duplicate_suppressed",
                    "dispatch_id": req.dispatch_id,
                    "dispatch_action": req.action,
                    "thread_id": req.thread_id,
                },
            )
            return DispatchResponse(status="dispatched", thread_id=req.thread_id)

        # Reject dispatch when concurrent thread cap is reached.
        if executor.at_capacity():
            raise HTTPException(
                status_code=429,
                detail="Worker at capacity — too many concurrent threads",
            )

        # No await may be inserted between this admission and scheduling: this is
        # the worker's synchronous duplicate-dispatch boundary.
        if not dispatch_ids.admit(req.dispatch_id):
            return DispatchResponse(status="dispatched", thread_id=req.thread_id)

        # Fire-and-forget: the task group keeps the task alive even after
        # this endpoint handler returns.
        tg.start_soon(executor.handle_dispatch, req)
        logger.info(
            "Worker dispatch accepted",
            extra={
                "action": "dispatch_accepted",
                "dispatch_id": req.dispatch_id,
                "dispatch_action": req.action,
                "thread_id": req.thread_id,
            },
        )

        return DispatchResponse(
            status="dispatched",
            thread_id=req.thread_id,
        )

    @app.get("/health", dependencies=[Depends(_verify_dispatch_token)])
    async def health_endpoint() -> dict[str, object]:
        """Worker health check.

        Worker interprocess-communication is private to the gateway-worker pair,
        so ``/health`` requires the same worker IPC credential as dispatch: a
        foreign or unpaired probe is rejected, and only the paired gateway (whose
        probes present the shared bearer) reads the worker's provenance. In a
        DEVELOPMENT gateway with no token the shared bearer rule leaves it open.

        Reports the worker's configured heartbeat target (``gateway_url``) so
        a spawning gateway can tell a worker that points at *this* gateway apart
        from a stale orphan still pointing at a dead dev-band gateway. Without
        this provenance the spawn path would blindly adopt the orphan and it
        would heartbeat a dead port forever.

        ``gateway_pairing_warning`` surfaces the non-fatal half of the worker's
        own boot-time pairing guard (``resolve_worker_gateway_target``): a band
        worker whose target could not be learned unambiguously and fell back to
        the auto-derived default. ``None`` when the target was explicit, learned,
        or the worker is not on a band port.
        """
        return {
            "status": "ok",
            "service": "worker",
            "gateway_url": settings.gateway_url,
            "gateway_pairing_warning": getattr(
                app.state, "gateway_pairing_warning", None
            ),
            "worker_port": settings.worker_port,
            "database_backend": settings.resolved_database_backend,
            "checkpoint_backend": settings.resolved_checkpoint_backend,
            "postgres_required": settings.postgres_required,
            # Pairing identity, reported not asserted. A URL cannot distinguish a
            # gateway from its own restart on the same port, so a worker naming
            # only its target looks correctly paired to a gateway that no longer
            # exists. These two say WHICH gateway incarnation started this worker
            # and which spawn attempt it was. Empty when the worker was started
            # by something other than a gateway spawn - Compose, an operator, or
            # a test - which is itself the honest answer rather than a default.
            "paired_gateway_lifetime": os.environ.get(GATEWAY_LIFETIME_ENV, ""),
            "worker_generation": os.environ.get(WORKER_GENERATION_ENV, ""),
        }

    @app.post(
        "/admin/shutdown",
        status_code=202,
        dependencies=[Depends(_verify_dispatch_token)],
    )
    async def shutdown_endpoint() -> dict[str, str]:
        """Terminate this worker process.

        Bearer-authenticated with the same internal token as ``/dispatch``: this
        endpoint is load-bearing in the gateway's stale-orphan eviction path, so an
        unauthenticated loopback process must not be able to hard-kill the worker.
        ``os.kill(SIGTERM)`` maps to ``TerminateProcess`` on Windows - an immediate
        stop with no run draining, not a graceful drain.
        """
        os.kill(os.getpid(), signal.SIGTERM)
        return {"detail": "shutdown initiated"}

    return app


def main() -> None:
    """Entry point for the ``vaultspec-worker`` console script."""
    reconfigure_console_utf8()
    configure_logging("service", service_name="worker")
    configure_asyncio_runtime()
    logger.info(
        "Worker main config: gateway_port=%d worker_host=%s"
        " worker_port=%d worker_url=%s",
        settings.port,
        settings.worker_host,
        settings.worker_port,
        settings.worker_url,
    )
    uvicorn.run(
        "vaultspec_a2a.worker.app:create_worker_app",
        factory=True,
        host=settings.worker_host,
        port=settings.worker_port,
        log_level=settings.log_level.value,
        access_log=settings.access_log,
        loop="auto",
    )


if __name__ == "__main__":
    main()

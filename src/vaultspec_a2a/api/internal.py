"""Internal endpoints the worker calls on the gateway.

The worker process reaches the gateway over HTTP, through two routes:

1. ``POST /internal/events/batch`` -- the buffered event relay. The body is a
   ``WorkerEventBatch`` of ``WorkerEventEnvelope`` entries, and the
   ``WorkerBridge`` in ``vaultspec_a2a.worker.ipc`` is its only producer.
2. ``POST /internal/heartbeat`` -- worker liveness, a ``HeartbeatRequest``.

The gateway exposes ``/internal/health`` for readiness probes. Request body
size is bounded before routing by ``ipc.body_limit``, not by these routes.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from functools import partial
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.security import HTTPBearer
from pydantic import ValidationError

from ..control._worker_health import worker_liveness
from ..control.config import settings
from ..control.event_handlers import (
    RelayServices,
    _handle_execution_state_event,
    relay_event,
)
from ..ipc.schemas import HeartbeatRequest, WorkerEventBatch
from ..thread.snapshots import is_terminal_event, normalize_wire_event_type
from ..utils import BearerVerdict, verify_internal_bearer
from ._replay_writer_seat import seated_replay_writer

if TYPE_CHECKING:
    from collections.abc import Callable

    from ..streaming import HeldFrame, RelayHub

__all__ = ["internal_router"]

logger = logging.getLogger(__name__)

# Distinguishes "this app declared no database" from "this app declared nothing".
# Both used to arrive as ``None``, and the durable event handlers cannot tell them
# apart from a bare value: the first must skip the write, the second must use the
# process database the gateway opened at boot.
_UNDECLARED = object()


def _app_session_factory(app: Any) -> Any:
    """Resolve the database an app relays durable events into.

    An app that SETS ``db_session_factory`` has declared what it has, including
    ``None`` for "nothing" - a host embedding this router without a store, and the
    reading that makes a skipped projection correct rather than accidental. An app
    that never sets it has declared nothing, which is the gateway's own case: it
    seats no attribute and relays into the process database ``init_db`` opened.

    Reading a bare ``None`` for both is what let an app with no database write into
    whichever database some unrelated component had initialized in the same
    process.
    """
    from ..database import application_session_factory

    declared = getattr(app.state, "db_session_factory", _UNDECLARED)
    if declared is _UNDECLARED:
        return application_session_factory()
    return declared


#: Declares the internal-IPC bearer in the generated OpenAPI document.
#:
#: A SEPARATE scheme from the gateway's ``GatewayServiceToken``, because it is a
#: separate credential: this plane verifies ``app.state.internal_token``, the
#: gateway<->worker IPC secret the gateway seated, not the attach credential that
#: lifecycle discovery publishes for external callers. Declaring both under one
#: scheme would tell a reader the two surfaces accept the same token, which they
#: do not.
#:
#: Declared here rather than beside :func:`verify_internal_bearer`: that module is
#: framework-free by design and leaves transport mapping to each caller, so a
#: FastAPI security object belongs on this side of the boundary.
#:
#: ``auto_error=False`` keeps it inert - the raw header below is still what the
#: verifier compares, and the 401/500 mapping stays in one place.
internal_bearer_scheme = HTTPBearer(
    auto_error=False,
    scheme_name="InternalIpcToken",
    description=(
        "Internal gateway-to-worker IPC token. Not the gateway service token: "
        "these routes are the worker's callback surface, not a client surface."
    ),
)

#: Declaration-only dependency for the router below. Never read; depending on it
#: is what puts the security requirement on these operations in the published
#: contract.
_declare_internal_bearer = Depends(internal_bearer_scheme)


async def _verify_internal_token(
    request: Request,
    authorization: str | None = Header(None, include_in_schema=False),
) -> None:
    """Verify bearer token for internal IPC endpoints.

    The token is the one the gateway seated on ``app.state.internal_token``: the
    secret it minted for this boot under the armed desktop profile, otherwise the
    configured one. It is read off the app that serves the request, so a token
    minted at runtime never has to be written back onto the settings. An app that
    seated nothing raises rather than reading as an unconfigured token, which
    would open the development bypass on state nobody chose.

    Skipped when the seated token is None **and** the environment is DEVELOPMENT.
    In production/staging/testing, a missing token is a configuration error.
    Delegates the rule to the shared IPC bearer verifier.

    Reads the raw header rather than a security object; see
    :data:`internal_bearer_scheme`.
    """
    verdict, detail = verify_internal_bearer(
        authorization,
        token=request.app.state.internal_token,
        environment=settings.environment,
        environment_declared=settings.environment_declared,
    )
    if verdict is BearerVerdict.MISCONFIGURED:
        raise HTTPException(status_code=500, detail=detail)
    if verdict is BearerVerdict.UNAUTHORIZED:
        raise HTTPException(status_code=401, detail=detail)


internal_router = APIRouter(
    prefix="/internal",
    tags=["internal"],
    dependencies=[Depends(_verify_internal_token), _declare_internal_bearer],
    # Both refusals belong to the gate every route here sits behind, not to any
    # one verb. Note the misconfiguration case is a 500 on this plane, where the
    # gateway's attach gate answers 503: an unset internal token outside
    # DEVELOPMENT is this service's own configuration error, not a dependency
    # that might yet become available.
    responses={
        401: {"description": "Missing or invalid internal IPC token."},
        500: {"description": "Internal IPC token is not configured."},
    },
)


def _relay_services(app: Any, relay_hub: RelayHub) -> RelayServices:
    """Read one app's relay collaborators off the state it seated them on."""
    return RelayServices(
        relay_hub=relay_hub,
        session_factory=_app_session_factory(app),
        checkpointer=getattr(app.state, "checkpointer", None),
        # Read, never get-or-created: a gate or a prune registry that was
        # never seated has admitted and started nothing.
        drain_gate=getattr(app.state, "drain_gate", None),
        prune_registry=getattr(app.state, "checkpoint_prunes", None),
    )


async def _relay_single_event(
    thread_id: str,
    payload: dict[str, Any],
    relay_hub: RelayHub,
    services: RelayServices,
) -> None:
    """Relay a single worker event through the gateway's relay hub.

    *services* is the ingest's collaborator bundle. Its run-admission gate is the
    process-wide one seated on ``app.state``; it travels to the terminal handler,
    which releases the run from it, exactly as the relay hub and session factory
    travel to their handlers.

    One frame is relayed differently. A terminal says the RUN ended, and only
    the control plane knows whether it did: a run with a continuation waiting
    takes the next turn instead of settling, and this relay reaches the
    hub first, so it used to show that run a terminal it then kept running
    past. The terminal is therefore NUMBERED here and handed to the control
    plane as a publisher, then fanned out on the far side of the decision.
    Numbering it before the decision rather than at the fan-out is what keeps
    the settled cursor and the terminal frame's own SSE id the same number:
    the settlement records the run's issued mark, and a frame numbered
    afterwards is never in that mark. A decision that does not end the run
    gives the number back, so the run's sequence space stays contiguous.
    Every other frame crosses as it always has.
    """
    payload = normalize_wire_event_type(payload)
    if payload.get("type") == "execution_state_projection":
        await _handle_execution_state_event(
            thread_id, payload, session_factory=services.session_factory
        )
        return
    if payload.get("type") == "dispatch_applied":
        # Application receipts are a private worker->gateway settlement signal.
        # They deliberately bypass the public relay-hub/SSE projection so the
        # stable dispatch identity never becomes a progress-frame field.
        await relay_event(thread_id, payload, services=services)
        return

    held: HeldFrame | None = None
    publish_terminal: Callable[[], None] | None = None
    # Establishes the run's durable numbering before the synchronous
    # chokepoint needs it; a no-op once seeded, and on a gateway that
    # numbers nothing.
    await relay_hub.prepare_run(thread_id)
    if is_terminal_event(payload):
        held = relay_hub.hold_payload(thread_id, payload)
        publish_terminal = partial(relay_hub.publish_held, held)
    else:
        relay_hub.relay_payload(thread_id, payload)
    # Mirrors the event into the relay hub's agent, tool-call and node state
    # before the handlers below, whose settled path purges that state.
    relay_hub.sync_worker_event(thread_id, payload)
    try:
        await relay_event(
            thread_id,
            payload,
            services=replace(services, publish_terminal=publish_terminal),
        )
    finally:
        if held is not None:
            # Unconditional and idempotent: a published terminal keeps its
            # number, and a promoted turn, a refused stale event or a handler
            # that raised gives it back rather than leaving a hole no frame
            # will ever fill.
            relay_hub.release_held(held)


@internal_router.get("/health")
async def internal_health() -> dict[str, str]:
    """Readiness probe -- confirms the internal API is accepting connections."""
    return {"status": "ok", "service": "gateway"}


@internal_router.post("/events/batch")
async def receive_worker_event_batch(request: Request) -> dict[str, str]:
    """Receive a batch of events from the worker.

    The ``WorkerBridge`` accumulates events for a short interval then POSTs
    them as a single ``WorkerEventBatch``. A batch carries many events in one
    request, so the body-limit middleware allows it a larger body than any
    other internal write; the worker sizes its batches against the same figure.
    """
    raw = await request.json()
    try:
        batch = WorkerEventBatch.model_validate(raw)
    except ValidationError as exc:
        raise RequestValidationError(exc.errors(), body=raw) from exc

    # Sort events by worker-side monotonic timestamp to preserve causal order
    # even if the batch was assembled out of order.
    events = sorted(batch.events, key=lambda event: event.ts)

    relay_hub = getattr(request.app.state, "relay_hub", None)
    if relay_hub is None:
        raise HTTPException(
            status_code=503,
            detail="No relay target available -- gateway not ready",
        )

    services = _relay_services(request.app, relay_hub)
    # Resolved once per ingest rather than per event: seating the recorder is
    # also what binds the run-sequence authority, so an ingest that reaches the
    # relay hub has either both or neither.
    replay = seated_replay_writer(request.app, services.session_factory)

    for event in events:
        await _relay_single_event(event.thread_id, event.payload, relay_hub, services)

    # Behind the fan-out, once per ingested batch: every frame above already
    # reached its subscribers, and this is the round trip that makes them
    # durable. A failure here is logged and leaves the frames in the ring.
    if replay is not None:
        await replay.flush()

    return {"status": "ok"}


@internal_router.post("/heartbeat")
async def receive_worker_heartbeat(request: Request) -> dict[str, str]:
    """Receive a heartbeat from the worker.

    Updates ``app.state`` so the gateway can monitor worker liveness.
    """
    raw = await request.json()
    try:
        body = HeartbeatRequest.model_validate(raw)
    except ValidationError as exc:
        raise RequestValidationError(exc.errors(), body=raw) from exc
    worker_liveness(request.app.state).record_contact(
        active_threads=body.active_threads
    )
    logger.debug(
        "Worker heartbeat (HTTP): %d active threads",
        len(body.active_threads),
        extra={
            "message_type": body.type,
            "active_thread_count": len(body.active_threads),
            "transport": "http",
        },
    )
    return {"status": "ok"}

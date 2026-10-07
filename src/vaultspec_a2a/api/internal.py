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
from dataclasses import dataclass
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


@dataclass(frozen=True, slots=True)
class _RelayContext:
    agg: Any
    session_factory: Any
    checkpointer: Any
    drain_gate: Any
    prune_registry: Any
    # The seated replay recorder, resolved once per ingest rather than per
    # event: seating it is also what binds the run-sequence authority, so an
    # ingest that reaches the aggregator has either both or neither.
    replay: Any = None

    @classmethod
    def of(cls, app: Any, agg: Any, *, replay: Any = None) -> _RelayContext:
        """Read one app's relay collaborators off the state it seated them on."""
        return cls(
            agg,
            _app_session_factory(app),
            getattr(app.state, "checkpointer", None),
            # Read, never get-or-created: a gate or a prune registry that was
            # never seated has admitted and started nothing.
            getattr(app.state, "drain_gate", None),
            getattr(app.state, "checkpoint_prunes", None),
            replay,
        )


async def _relay_single_event(
    thread_id: str, payload: dict[str, Any], context: _RelayContext
) -> None:
    """Aggregate and relay a single worker event.

    *drain_gate* is the process-wide run-admission gate seated on ``app.state``;
    it travels to the terminal handler, which releases the run from it, exactly
    as *agg* and *session_factory* travel to their handlers.

    One frame is relayed differently. A terminal says the RUN ended, and only
    the control plane knows whether it did: a run with a continuation waiting
    takes the next turn instead of settling, and this relay reaches the
    aggregator first, so it used to show that run a terminal it then kept
    running past. The terminal is therefore handed to the control plane as a
    publisher rather than fanned out here, and released on the far side of the
    decision. Every other frame crosses as it always has.
    """
    payload = normalize_wire_event_type(payload)
    if payload.get("type") == "execution_state_projection":
        await _handle_execution_state_event(
            thread_id, payload, session_factory=context.session_factory
        )
        return
    if payload.get("type") == "dispatch_applied":
        # Application receipts are a private worker->gateway settlement signal.
        # They deliberately bypass the public aggregator/SSE projection so the
        # stable dispatch identity never becomes a progress-frame field.
        await relay_event(
            thread_id,
            payload,
            services=RelayServices(
                session_factory=context.session_factory,
                checkpointer=context.checkpointer,
                drain_gate=context.drain_gate,
                prune_registry=context.prune_registry,
            ),
        )
        return

    publish_terminal: Callable[[], None] | None = None
    # Establishes the run's durable numbering before the synchronous
    # chokepoint needs it; a no-op once seeded, and on a gateway that
    # numbers nothing.
    await context.agg.prepare_run(thread_id)
    if is_terminal_event(payload):
        publish_terminal = partial(context.agg.relay_payload, thread_id, payload)
    else:
        context.agg.relay_payload(thread_id, payload)
    # Mirrors the event into the aggregator's agent, tool-call and node state
    # before the handlers below, whose settled path purges that state.
    context.agg.sync_worker_event(thread_id, payload)
    await relay_event(
        thread_id,
        payload,
        services=RelayServices(
            aggregator=context.agg,
            session_factory=context.session_factory,
            checkpointer=context.checkpointer,
            drain_gate=context.drain_gate,
            prune_registry=context.prune_registry,
            publish_terminal=publish_terminal,
        ),
    )


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

    agg = getattr(request.app.state, "aggregator", None)
    if agg is None:
        raise HTTPException(
            status_code=503,
            detail="No relay target available -- gateway not ready",
        )

    replay = seated_replay_writer(request.app, _app_session_factory(request.app))
    context = _RelayContext.of(request.app, agg, replay=replay)

    for event in events:
        await _relay_single_event(event.thread_id, event.payload, context)

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

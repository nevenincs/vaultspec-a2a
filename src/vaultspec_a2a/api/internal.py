"""Internal endpoints for worker <-> gateway communication (ADR-031).

The worker process communicates with the gateway via two channels:

1. **WebSocket** (``/internal/ws``) -- legacy streaming path where the worker
   pushes ``WorkerEventEnvelope`` and ``HeartbeatMessage`` JSON frames.
2. **HTTP POST** (``/internal/events``, ``/internal/heartbeat``) -- preferred
   path that avoids the need for a WebSocket client library in the worker.
   The ``WorkerBridge`` in ``vaultspec_a2a.worker.ipc`` uses this approach.

The gateway exposes ``/internal/health`` for readiness probes.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
)

from ..control.config import settings
from ..control.event_handlers import (
    _handle_execution_state_event,
    relay_event,
)

__all__ = ["internal_router"]

logger = logging.getLogger(__name__)


def _normalize_worker_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Mirror ``type``/``event_type`` keys so both legacy and new paths work."""
    normalized = dict(payload)
    payload_type = normalized.get("type")
    event_type = normalized.get("event_type")
    if isinstance(event_type, str) and event_type and not payload_type:
        normalized["type"] = event_type
    if isinstance(payload_type, str) and payload_type and not event_type:
        normalized["event_type"] = payload_type
    return normalized


def _validate_event_envelope(
    thread_id: str,
    payload: dict[str, Any],
    *,
    context: str,
) -> None:
    """Reject malformed worker event payloads with a client-visible error."""
    if not thread_id or not payload:
        raise HTTPException(
            status_code=422,
            detail=f"Malformed {context}: thread_id and payload are required",
        )


async def _verify_internal_token(
    authorization: str | None = Header(None),
) -> None:
    """WPA-002: Verify bearer token for internal IPC endpoints.

    Skipped when settings.internal_token is None **and** the environment
    is DEVELOPMENT.  In production/staging/testing, a missing token is a
    configuration error (PROD-017).
    """
    from ..utils.enums import Environment

    token = settings.internal_token
    if token is None:
        if settings.environment != Environment.DEVELOPMENT:
            raise HTTPException(
                status_code=500,
                detail=(
                    "VAULTSPEC_INTERNAL_TOKEN required in "
                    f"{settings.environment.value} environment"
                ),
            )
        return  # Auth disabled in dev mode
    if authorization != f"Bearer {token}":
        raise HTTPException(status_code=401, detail="Invalid internal token")


internal_router = APIRouter(
    prefix="/internal",
    tags=["internal"],
    dependencies=[Depends(_verify_internal_token)],
)


async def _relay_single_event(
    thread_id: str,
    payload: dict[str, Any],
    *,
    cm: Any,
    agg: Any,
    session_factory: Any,
    transport: str = "http",
) -> None:
    """Broadcast, aggregate, and relay a single worker event.

    Shared by all three ingest paths (WS, HTTP POST, HTTP batch) to
    avoid copy-pasting the broadcast → aggregator sync → relay_event
    sequence.
    """
    payload = _normalize_worker_payload(payload)
    if payload.get("type") == "execution_state_projection":
        await _handle_execution_state_event(
            thread_id, payload, session_factory=session_factory
        )
        return

    if agg is not None:
        agg.relay_payload(thread_id, payload)
        agg.sync_worker_event(thread_id, payload)
    elif cm is not None:
        await cm.broadcast_to_thread(thread_id, payload)
    else:
        logger.warning(
            "No relay target available -- dropping event for %s",
            thread_id,
            extra={
                "thread_id": thread_id,
                "event_type": str(payload.get("event_type", payload.get("type", ""))),
                "transport": transport,
                "action": "relay_drop_event",
            },
        )
    await relay_event(
        thread_id,
        payload,
        aggregator=agg,
        session_factory=session_factory,
    )


async def _relay_worker_event(websocket: WebSocket, msg: dict, raw: str) -> None:
    """Relay a single worker event to WS clients and update aggregator/DB."""
    thread_id = msg.get("thread_id", "")
    payload = msg.get("payload", {})
    if not thread_id or not payload:
        logger.warning(
            "Malformed worker event envelope: %s",
            raw[:200],
            extra={
                "thread_id": thread_id,
                "event_type": "",
                "message_type": str(msg.get("type", "")),
                "transport": "ws",
                "frame_size": len(raw),
            },
        )
        return
    session_factory = getattr(websocket.app.state, "db_session_factory", None)
    cm = getattr(websocket.app.state, "connection_manager", None)
    agg = getattr(websocket.app.state, "aggregator", None)
    await _relay_single_event(
        thread_id,
        payload,
        cm=cm,
        agg=agg,
        session_factory=session_factory,
        transport="ws",
    )


@internal_router.websocket("/ws")
async def worker_ws_endpoint(websocket: WebSocket) -> None:
    """Internal WebSocket -- receives events and heartbeats from the worker."""
    # AUTH-02: WebSocket routes bypass router-level Depends(), so verify
    # the bearer token manually before accepting the connection.
    if settings.internal_token is not None:
        token = websocket.headers.get("authorization", "").removeprefix("Bearer ")
        if token != settings.internal_token:
            await websocket.close(code=1008, reason="Unauthorized")
            return

    await websocket.accept()
    logger.info("Worker connected to internal WS")

    # Store reference so supervisor can check connectivity
    websocket.app.state.worker_ws = websocket
    websocket.app.state.worker_last_heartbeat_ts = time.monotonic()

    try:
        while True:
            raw = await websocket.receive_text()
            # API-02: reject oversized frames (1 MB) to prevent memory exhaustion.
            if len(raw) > settings.internal_max_frame_bytes:
                logger.warning(
                    "Dropping oversized internal WS frame (%d bytes)", len(raw)
                )
                continue
            msg = json.loads(raw)
            msg_type = msg.get("type", "")

            match msg_type:
                case "heartbeat":
                    websocket.app.state.worker_last_heartbeat_ts = time.monotonic()
                    websocket.app.state.worker_active_threads = msg.get(
                        "active_threads", []
                    )
                    logger.debug(
                        "Worker heartbeat: %d active threads",
                        len(msg.get("active_threads", [])),
                        extra={
                            "message_type": msg_type,
                            "active_thread_count": len(msg.get("active_threads", [])),
                            "transport": "ws",
                        },
                    )

                case "event":
                    await _relay_worker_event(websocket, msg, raw)

                case _:
                    logger.warning(
                        "Unknown internal WS message type: %s",
                        msg_type,
                        extra={
                            "message_type": msg_type,
                            "transport": "ws",
                            "frame_size": len(raw),
                        },
                    )

    except WebSocketDisconnect:
        logger.warning("Worker disconnected from internal WS")
        websocket.app.state.worker_ws = None


@internal_router.get("/health")
async def internal_health() -> dict[str, str]:
    """Readiness probe -- confirms the internal API is accepting connections."""
    return {"status": "ok", "service": "gateway"}


# ---------------------------------------------------------------------------
# HTTP POST endpoints -- preferred IPC path (avoids WS client dependency)
# ---------------------------------------------------------------------------


@internal_router.post("/events")
async def receive_worker_event(request: Request) -> dict[str, str]:
    """Receive a single event from the worker and relay to browser clients.

    The ``WorkerBridge`` in the worker process POSTs here instead of
    sending a WebSocket frame.  The payload format matches
    ``WorkerEventEnvelope``.
    """
    # API-03: reject oversized payloads (1 MB) on internal HTTP path.
    content_length = request.headers.get("content-length")
    try:
        if (
            content_length is not None
            and int(content_length) > settings.internal_max_http_body_bytes
        ):
            raise HTTPException(status_code=413, detail="Payload too large (max 1 MB)")
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail="Invalid Content-Length header",
        ) from e

    body: dict[str, Any] = await request.json()
    thread_id: str = body.get("thread_id", "")
    payload: dict[str, Any] = body.get("payload", {})
    _validate_event_envelope(thread_id, payload, context="worker event POST")

    cm = getattr(request.app.state, "connection_manager", None)
    agg = getattr(request.app.state, "aggregator", None)
    if cm is None and agg is None:
        raise HTTPException(
            status_code=503,
            detail="No relay target available -- gateway not ready",
        )

    await _relay_single_event(
        thread_id,
        payload,
        cm=cm,
        agg=agg,
        session_factory=getattr(request.app.state, "db_session_factory", None),
    )
    return {"status": "ok"}


@internal_router.post("/events/batch")
async def receive_worker_event_batch(request: Request) -> dict[str, str]:
    """Receive a batch of events from the worker (CRIT-02).

    The ``WorkerBridge`` accumulates events for a short interval then
    POSTs them as a single ``{"events": [...]}`` payload.  Each entry
    has the same shape as a single-event envelope (``thread_id`` +
    ``payload``).
    """
    content_length = request.headers.get("content-length")
    # Allow larger batches: 4 MB limit for batch payloads.
    try:
        if (
            content_length is not None
            and int(content_length) > settings.internal_max_http_body_bytes * 4
        ):
            raise HTTPException(
                status_code=413,
                detail="Payload too large (max 4 MB)",
            )
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail="Invalid Content-Length header",
        ) from e

    body: dict[str, Any] = await request.json()
    events: list[dict[str, Any]] = body.get("events", [])

    # Sort events by worker-side monotonic timestamp to preserve causal order
    # even if the batch was assembled out of order.
    events.sort(key=lambda e: e.get("ts", 0.0))

    cm = getattr(request.app.state, "connection_manager", None)
    agg = getattr(request.app.state, "aggregator", None)
    if cm is None and agg is None:
        raise HTTPException(
            status_code=503,
            detail="No relay target available -- gateway not ready",
        )

    session_factory = getattr(request.app.state, "db_session_factory", None)

    for idx, evt in enumerate(events):
        thread_id = evt.get("thread_id", "")
        payload = evt.get("payload", {})
        try:
            _validate_event_envelope(
                thread_id, payload, context=f"worker event batch entry {idx}"
            )
        except HTTPException as exc:
            raise HTTPException(status_code=422, detail=exc.detail) from None

    for evt in events:
        thread_id = evt.get("thread_id", "")
        payload = evt.get("payload", {})
        await _relay_single_event(
            thread_id, payload, cm=cm, agg=agg, session_factory=session_factory
        )

    return {"status": "ok"}


@internal_router.post("/heartbeat")
async def receive_worker_heartbeat(request: Request) -> dict[str, str]:
    """Receive a heartbeat from the worker.

    Updates ``app.state`` so the gateway can monitor worker
    liveness without a persistent WebSocket connection.
    """
    body: dict[str, Any] = await request.json()
    request.app.state.worker_last_heartbeat_ts = time.monotonic()
    request.app.state.worker_active_threads = body.get("active_threads", [])
    logger.debug(
        "Worker heartbeat (HTTP): %d active threads",
        len(body.get("active_threads", [])),
        extra={
            "message_type": str(body.get("type", "")),
            "active_thread_count": len(body.get("active_threads", [])),
            "transport": "http",
        },
    )
    return {"status": "ok"}

"""Internal endpoints for worker <-> control surface communication (ADR-019).

The worker process communicates with the control surface via two channels:

1. **WebSocket** (``/internal/ws``) -- legacy streaming path where the worker
   pushes ``WorkerEventEnvelope`` and ``HeartbeatMessage`` JSON frames.
2. **HTTP POST** (``/internal/events``, ``/internal/heartbeat``) -- preferred
   path that avoids the need for a WebSocket client library in the worker.
   The ``WorkerBridge`` in ``lib.worker.ipc`` uses this approach.

The control surface exposes ``/internal/health`` for readiness probes.
"""

from __future__ import annotations

import json
import logging
import time

from typing import Any

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect


__all__ = ["internal_router"]

logger = logging.getLogger(__name__)

# Shared size limit for internal IPC payloads (1 MB).
_MAX_WS_FRAME_BYTES = 1_048_576
_MAX_HTTP_BODY_BYTES = 1_048_576

internal_router = APIRouter(prefix="/internal", tags=["internal"])


@internal_router.websocket("/ws")
async def worker_ws_endpoint(websocket: WebSocket) -> None:
    """Internal WebSocket -- receives events and heartbeats from the worker."""
    await websocket.accept()
    logger.info("Worker connected to internal WS")

    # Store reference so supervisor can check connectivity
    websocket.app.state.worker_ws = websocket
    websocket.app.state.worker_last_heartbeat_ts = time.monotonic()

    try:
        while True:
            raw = await websocket.receive_text()
            # API-02: reject oversized frames (1 MB) to prevent memory exhaustion.
            if len(raw) > _MAX_WS_FRAME_BYTES:
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
                    )

                case "event":
                    thread_id = msg.get("thread_id", "")
                    payload = msg.get("payload", {})
                    if thread_id and payload:
                        cm = getattr(websocket.app.state, "connection_manager", None)
                        if cm is not None:
                            await cm.broadcast_to_thread(thread_id, payload)
                        else:
                            logger.warning(
                                "ConnectionManager not available"
                                " -- dropping event for %s",
                                thread_id,
                            )
                    else:
                        logger.warning("Malformed worker event envelope: %s", raw[:200])

                case _:
                    logger.warning("Unknown internal WS message type: %s", msg_type)

    except WebSocketDisconnect:
        logger.warning("Worker disconnected from internal WS")
        websocket.app.state.worker_ws = None


@internal_router.get("/health")
async def internal_health() -> dict[str, str]:
    """Readiness probe -- confirms the internal API is accepting connections."""
    return {"status": "ok", "service": "control-surface"}


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
    if content_length is not None and int(content_length) > _MAX_HTTP_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Payload too large (max 1 MB)")

    body: dict[str, Any] = await request.json()
    thread_id: str = body.get("thread_id", "")
    payload: dict[str, Any] = body.get("payload", {})

    cm = getattr(request.app.state, "connection_manager", None)
    if cm is None:
        raise HTTPException(
            status_code=503,
            detail="ConnectionManager not available -- control surface not ready",
        )

    if thread_id and payload:
        await cm.broadcast_to_thread(thread_id, payload)
    else:
        logger.warning("Malformed worker event POST: missing thread_id or payload")

    return {"status": "ok"}


@internal_router.post("/heartbeat")
async def receive_worker_heartbeat(request: Request) -> dict[str, str]:
    """Receive a heartbeat from the worker.

    Updates ``app.state`` so the control surface can monitor worker
    liveness without a persistent WebSocket connection.
    """
    body: dict[str, Any] = await request.json()
    request.app.state.worker_last_heartbeat_ts = time.monotonic()
    request.app.state.worker_active_threads = body.get("active_threads", [])
    logger.debug(
        "Worker heartbeat (HTTP): %d active threads",
        len(body.get("active_threads", [])),
    )
    return {"status": "ok"}

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

import contextlib
import json
import logging
import time
from datetime import datetime
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
from .schemas.internal import ExecutionStateProjectionPayload

__all__ = ["internal_router"]

logger = logging.getLogger(__name__)

_PLAN_APPROVAL_PAUSE_CAUSES = {
    "plan_approval_request",
    "plan_approval",
}

# DB-CRIT-01: map aggregator outcome strings to ThreadStatus enum values.
_TERMINAL_STATUS_MAP: dict[str, str] = {
    "completed": "completed",
    "failed": "failed",
    "cancelled": "cancelled",
}


async def _handle_terminal_event(
    thread_id: str,
    payload: dict[str, Any],
    *,
    aggregator: Any | None = None,
    session_factory: Any | None = None,
) -> None:
    """Update thread DB status when a ``thread_terminal`` event arrives.

    Called from both the WS and HTTP POST relay paths.  Imports are kept
    local to avoid circular dependencies at module level.

    When *aggregator* is provided, prune stale permissions and sequence
    counters for the terminated thread (AGG-01/05).
    """
    if payload.get("event_type") != "thread_terminal":
        return
    status_str = _TERMINAL_STATUS_MAP.get(payload.get("status", ""))
    if not status_str:
        return
    try:
        from ..database.crud import (
            ControlActionType,
            InvalidTransitionError,
            RepairStatus,
            ThreadStatus,
            expire_pending_permission_requests,
            get_latest_control_action,
            set_thread_repair_state,
            update_thread_status,
        )

        if session_factory is None:
            from ..database.session import get_session_factory

            factory = get_session_factory()
        else:
            factory = session_factory
        async with factory() as db:
            await update_thread_status(db, thread_id, ThreadStatus(status_str))
            await expire_pending_permission_requests(db, thread_id=thread_id)
            latest_cancel = await get_latest_control_action(
                db, thread_id=thread_id, action_type=ControlActionType.CANCEL
            )
            if latest_cancel is not None and status_str == ThreadStatus.CANCELLED.value:
                latest_cancel.result_status = "applied"
                latest_cancel.applied_at = latest_cancel.applied_at or time_now_utc()
            await set_thread_repair_state(
                db,
                thread_id,
                repair_status=RepairStatus.HEALTHY,
                repair_reason=None,
                execution_readiness=RepairStatus.HEALTHY.value,
                last_applied_action=(
                    ControlActionType.CANCEL
                    if status_str == ThreadStatus.CANCELLED.value
                    else None
                ),
            )
            await db.commit()
        logger.info(
            "Thread %s status updated to %s",
            thread_id,
            status_str,
            extra={
                "thread_id": thread_id,
                "status": status_str,
                "event_type": payload.get("event_type", ""),
                "action": "thread_terminal_status_updated",
            },
        )
    except InvalidTransitionError:
        # BE-37: race condition — cancel endpoint already set terminal status.
        # This is expected and not an error.
        logger.info(
            "Thread %s transition to %s skipped (already terminal)",
            thread_id,
            status_str,
            extra={
                "thread_id": thread_id,
                "status": status_str,
                "event_type": payload.get("event_type", ""),
                "action": "thread_terminal_status_skipped",
            },
        )
    except Exception:
        logger.exception(
            "Failed to update thread %s status to %s",
            thread_id,
            status_str,
            extra={
                "thread_id": thread_id,
                "status": status_str,
                "event_type": payload.get("event_type", ""),
                "action": "thread_terminal_status_update_failed",
            },
        )

    # AGG-01/05: GC aggregator state for the terminated thread.
    if aggregator is not None:
        try:
            aggregator.prune_stale_permissions()
            # Remove the sequence counter for the now-terminal thread.
            active: set[str] = set(
                getattr(aggregator._emitters, "_sequences", {}).keys()
            ) - {thread_id}
            aggregator.prune_sequences(active)
        except Exception:
            logger.warning(
                "Aggregator GC failed for thread %s",
                thread_id,
                extra={
                    "thread_id": thread_id,
                    "action": "aggregator_gc_failed",
                    "event_type": payload.get("event_type", ""),
                },
                exc_info=True,
            )


def time_now_utc() -> Any:
    """Late-bound helper to avoid a top-level datetime import churn in this module."""
    from datetime import UTC, datetime

    return datetime.now(UTC)


async def _handle_permission_event(
    thread_id: str,
    payload: dict[str, Any],
    *,
    session_factory: Any | None = None,
) -> None:
    """Persist worker permission events into the durable journal."""
    event_type = payload.get("type", "")
    if event_type not in {"permission_request", "permission_resolved"}:
        return

    from ..database.crud import (
        ApprovalStatus,
        ControlActionResultStatus,
        ControlActionType,
        PermissionRequestStatus,
        RepairStatus,
        ThreadStatus,
        create_control_action,
        get_permission_request,
        mark_permission_request_applied,
        record_permission_request,
        set_thread_approval_state,
        set_thread_repair_state,
        supersede_permission_requests,
        update_thread_status,
    )

    if session_factory is None:
        from ..database.session import get_session_factory

        factory = get_session_factory()
    else:
        factory = session_factory
    async with factory() as db:
        if event_type == "permission_request":
            request_id = str(payload.get("request_id", ""))
            if not request_id:
                return
            tool_call = payload.get("tool_call")
            pause_reason_type = (
                "plan_approval_request"
                if tool_call == "plan_approval"
                else str(tool_call or "permission_request")
            )
            if pause_reason_type in _PLAN_APPROVAL_PAUSE_CAUSES:
                await supersede_permission_requests(
                    db,
                    thread_id=thread_id,
                    pause_reason_type=pause_reason_type,
                    except_request_id=request_id,
                )
            await record_permission_request(
                db,
                request_id=request_id,
                thread_id=thread_id,
                pause_reason_type=pause_reason_type,
                description=str(payload.get("description", "")),
                allowed_options=list(payload.get("options", [])),
                tool_call=tool_call,
            )
            await create_control_action(
                db,
                thread_id=thread_id,
                action_type=ControlActionType.PERMISSION_REQUEST_CREATED,
                request_id=request_id,
                idempotency_key=f"permission-request:{request_id}",
                payload={"description": payload.get("description", "")},
                result_status=ControlActionResultStatus.APPLIED,
            )
            await update_thread_status(db, thread_id, ThreadStatus.INPUT_REQUIRED)
            await set_thread_repair_state(
                db,
                thread_id,
                repair_status=RepairStatus.PAUSED_RESUMABLE,
                repair_reason="Worker reported a pending permission request",
                execution_readiness=RepairStatus.PAUSED_RESUMABLE.value,
                last_applied_action=ControlActionType.PERMISSION_REQUEST_CREATED,
            )
            if pause_reason_type in _PLAN_APPROVAL_PAUSE_CAUSES:
                await set_thread_approval_state(
                    db,
                    thread_id,
                    approval_status=ApprovalStatus.PENDING,
                    approval_request_id=request_id,
                    approval_reason=str(payload.get("description", "")),
                    approval_response_action_id=None,
                )
        else:
            request_id = str(payload.get("request_id", ""))
            permission = await get_permission_request(db, request_id)
            if permission is not None:
                target_status = PermissionRequestStatus.APPLIED
                if (
                    permission.response_option_id
                    and permission.response_option_id.startswith("reject")
                ):
                    target_status = PermissionRequestStatus.REJECTED
                await mark_permission_request_applied(
                    db, request_id=request_id, status=target_status
                )
                await create_control_action(
                    db,
                    thread_id=thread_id,
                    action_type=ControlActionType.PERMISSION_RESPONSE_APPLIED,
                    request_id=request_id,
                    idempotency_key=f"permission-response-applied:{request_id}",
                    payload={"request_id": request_id},
                    result_status=ControlActionResultStatus.APPLIED,
                )
                await set_thread_repair_state(
                    db,
                    thread_id,
                    repair_status=RepairStatus.HEALTHY,
                    repair_reason=None,
                    execution_readiness=RepairStatus.HEALTHY.value,
                    last_applied_action=ControlActionType.PERMISSION_RESPONSE_APPLIED,
                )
                if permission.pause_reason_type in _PLAN_APPROVAL_PAUSE_CAUSES:
                    await set_thread_approval_state(
                        db,
                        thread_id,
                        approval_status=(
                            ApprovalStatus.REJECTED
                            if target_status == PermissionRequestStatus.REJECTED
                            else ApprovalStatus.APPROVED
                        ),
                        approval_request_id=request_id,
                        approval_reason=permission.description,
                    )
        await db.commit()


async def _handle_progress_event(
    thread_id: str,
    payload: dict[str, Any],
    *,
    session_factory: Any | None = None,
) -> None:
    """Infer permission application from post-resume worker progress."""
    event_type = payload.get("type", "")
    if event_type not in {
        "agent_status",
        "message_chunk",
        "tool_call_start",
        "tool_call_update",
        "plan_update",
        "artifact_update",
    }:
        return

    from ..database.crud import (
        ApprovalStatus,
        ControlActionResultStatus,
        ControlActionType,
        RepairStatus,
        ThreadStatus,
        create_control_action,
        get_pending_permission_requests,
        mark_permission_request_applied,
        set_thread_approval_state,
        set_thread_repair_state,
        update_thread_status,
    )

    if session_factory is None:
        from ..database.session import get_session_factory

        factory = get_session_factory()
    else:
        factory = session_factory
    async with factory() as db:
        pending = await get_pending_permission_requests(db, thread_id=thread_id)
        answered = [
            permission
            for permission in pending
            if permission.request_status == "answered_pending_apply"
        ]
        for permission in answered:
            await mark_permission_request_applied(db, request_id=permission.request_id)
            await create_control_action(
                db,
                thread_id=thread_id,
                action_type=ControlActionType.PERMISSION_RESPONSE_APPLIED,
                request_id=permission.request_id,
                idempotency_key=(
                    f"permission-response-progress-applied:{permission.request_id}"
                ),
                payload={"event_type": event_type},
                result_status=ControlActionResultStatus.APPLIED,
            )
            if permission.pause_reason_type in _PLAN_APPROVAL_PAUSE_CAUSES:
                await set_thread_approval_state(
                    db,
                    thread_id,
                    approval_status=(
                        ApprovalStatus.REJECTED
                        if permission.response_option_id == "reject"
                        else ApprovalStatus.APPROVED
                    ),
                    approval_request_id=permission.request_id,
                    approval_reason=permission.description,
                )
        if answered:
            with contextlib.suppress(Exception):
                await update_thread_status(db, thread_id, ThreadStatus.RUNNING)
            await set_thread_repair_state(
                db,
                thread_id,
                repair_status=RepairStatus.HEALTHY,
                repair_reason=None,
                execution_readiness=RepairStatus.HEALTHY.value,
                last_applied_action=ControlActionType.PERMISSION_RESPONSE_APPLIED,
            )
            await db.commit()


async def _handle_execution_state_event(
    thread_id: str,
    payload: dict[str, Any],
    *,
    session_factory: Any | None = None,
) -> None:
    """Persist worker-owned execution-state projection events."""
    if payload.get("type") != "execution_state_projection":
        return

    from ..database.crud import record_thread_execution_state

    projection = ExecutionStateProjectionPayload.model_validate(payload)
    snapshot_created_at: datetime | None = None
    if projection.snapshot_created_at is not None:
        with contextlib.suppress(ValueError):
            snapshot_created_at = datetime.fromisoformat(projection.snapshot_created_at)

    if session_factory is None:
        from ..database.session import get_session_factory

        factory = get_session_factory()
    else:
        factory = session_factory
    async with factory() as db:
        await record_thread_execution_state(
            db,
            thread_id=thread_id,
            checkpoint_id=projection.checkpoint_id,
            parent_checkpoint_id=projection.parent_checkpoint_id,
            snapshot_created_at=snapshot_created_at,
            task_count=projection.task_count,
            interrupt_count=projection.interrupt_count,
            next_nodes=list(projection.next_nodes),
            interrupt_types=list(projection.interrupt_types),
            tasks=[task.model_dump(mode="json") for task in projection.tasks],
            degraded_reasons=list(projection.degraded_reasons),
        )
        await db.commit()


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
    if payload.get("type") == "execution_state_projection":
        await _handle_execution_state_event(
            thread_id,
            payload,
            session_factory=getattr(websocket.app.state, "db_session_factory", None),
        )
        return
    session_factory = getattr(websocket.app.state, "db_session_factory", None)

    cm = getattr(websocket.app.state, "connection_manager", None)
    if cm is not None:
        await cm.broadcast_to_thread(thread_id, payload)
    else:
        logger.warning(
            "ConnectionManager not available -- dropping event for %s",
            thread_id,
            extra={
                "thread_id": thread_id,
                "event_type": str(payload.get("event_type", payload.get("type", ""))),
                "transport": "ws",
                "action": "relay_drop_event",
            },
        )
    # P8-01: sync into API aggregator state.
    agg = getattr(websocket.app.state, "aggregator", None)
    if agg is not None:
        agg.sync_worker_event(thread_id, payload)
    await _handle_permission_event(
        thread_id,
        payload,
        session_factory=session_factory,
    )
    await _handle_execution_state_event(
        thread_id,
        payload,
        session_factory=session_factory,
    )
    await _handle_progress_event(
        thread_id,
        payload,
        session_factory=session_factory,
    )
    # DB-CRIT-01: terminal status update + AGG-01/05 GC.
    await _handle_terminal_event(
        thread_id,
        payload,
        aggregator=agg,
        session_factory=session_factory,
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
    except ValueError:
        raise HTTPException(  # noqa: B904
            status_code=400,
            detail="Invalid Content-Length header",
        )

    body: dict[str, Any] = await request.json()
    thread_id: str = body.get("thread_id", "")
    payload: dict[str, Any] = body.get("payload", {})
    _validate_event_envelope(thread_id, payload, context="worker event POST")
    session_factory = getattr(request.app.state, "db_session_factory", None)
    if payload.get("type") == "execution_state_projection":
        await _handle_execution_state_event(
            thread_id,
            payload,
            session_factory=session_factory,
        )
        return {"status": "ok"}

    cm = getattr(request.app.state, "connection_manager", None)
    if cm is None:
        raise HTTPException(
            status_code=503,
            detail="ConnectionManager not available -- gateway not ready",
        )

    await cm.broadcast_to_thread(thread_id, payload)
    # P8-01: sync into API aggregator state.
    agg = getattr(request.app.state, "aggregator", None)
    if agg is not None:
        agg.sync_worker_event(thread_id, payload)
    await _handle_permission_event(
        thread_id,
        payload,
        session_factory=session_factory,
    )
    await _handle_execution_state_event(
        thread_id,
        payload,
        session_factory=session_factory,
    )
    await _handle_progress_event(
        thread_id,
        payload,
        session_factory=session_factory,
    )
    # DB-CRIT-01: terminal status update + AGG-01/05 GC.
    await _handle_terminal_event(
        thread_id,
        payload,
        aggregator=agg,
        session_factory=session_factory,
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
    except ValueError:
        raise HTTPException(  # noqa: B904
            status_code=400,
            detail="Invalid Content-Length header",
        )

    body: dict[str, Any] = await request.json()
    events: list[dict[str, Any]] = body.get("events", [])

    # Sort events by worker-side monotonic timestamp to preserve causal order
    # even if the batch was assembled out of order.
    events.sort(key=lambda e: e.get("ts", 0.0))

    cm = getattr(request.app.state, "connection_manager", None)
    if cm is None:
        raise HTTPException(
            status_code=503,
            detail="ConnectionManager not available -- gateway not ready",
        )

    agg = getattr(request.app.state, "aggregator", None)
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
        if payload.get("type") == "execution_state_projection":
            await _handle_execution_state_event(
                thread_id,
                payload,
                session_factory=session_factory,
            )
            continue
        await cm.broadcast_to_thread(thread_id, payload)
        if agg is not None:
            agg.sync_worker_event(thread_id, payload)
        await _handle_permission_event(
            thread_id,
            payload,
            session_factory=session_factory,
        )
        await _handle_execution_state_event(
            thread_id,
            payload,
            session_factory=session_factory,
        )
        await _handle_progress_event(
            thread_id,
            payload,
            session_factory=session_factory,
        )
        await _handle_terminal_event(
            thread_id,
            payload,
            aggregator=agg,
            session_factory=session_factory,
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

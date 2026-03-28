"""POST /threads/{thread_id}/messages -- Send message into thread."""

import hashlib
import json
import logging
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ...control.dispatch import (
    WorkerAtCapacityError,
    WorkerCircuitOpenError,
    WorkerDispatchRejectedError,
    WorkerUnreachableError,
    dispatch_to_worker,
)
from ...database.crud import (
    create_control_action,
    get_control_action_by_idempotency_key,
    get_thread,
    set_thread_repair_state,
    update_thread_status,
)
from ...database.session import get_db
from ...ipc.schemas import DispatchRequest
from ...streaming.aggregator import EventAggregator
from ...thread.enums import (
    ControlActionResultStatus,
    ControlActionType,
    RepairStatus,
    ThreadStatus,
)
from .._utils import mark_worker_connected, trace_headers
from ..dependencies import (
    get_aggregator,
    get_circuit_breaker,
    get_worker_client,
    get_worker_spawner,
)
from ..schemas.rest import SendMessageRequest, SendMessageResponse

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post(
    "/threads/{thread_id}/messages",
    status_code=202,
    response_model=SendMessageResponse,
)
async def send_message_endpoint(
    thread_id: str,
    body: SendMessageRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _aggregator: EventAggregator = Depends(get_aggregator),
    worker_client: httpx.AsyncClient = Depends(get_worker_client),
    circuit_breaker: Any = Depends(get_circuit_breaker),
    worker_spawner: Any = Depends(get_worker_spawner),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> SendMessageResponse:
    """Send a user message into an existing thread.

    Returns 202 Accepted immediately; the message is dispatched to the
    worker process for graph execution (ADR-019).
    """
    thread = await get_thread(db, thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found")

    if thread.status == ThreadStatus.INPUT_REQUIRED.value:
        raise HTTPException(
            status_code=409,
            detail=(
                "Cannot send a follow-up message while the thread is paused for input"
            ),
        )

    terminal_statuses = (
        ThreadStatus.ARCHIVED,
        ThreadStatus.COMPLETED,
        ThreadStatus.FAILED,
        ThreadStatus.CANCELLED,
    )
    if thread.status in terminal_statuses:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot send messages to thread in {thread.status!r} state",
        )

    logger.info(
        "Message received for thread %s: %d chars",
        thread_id,
        len(body.content),
    )

    agent_id = body.agent_id or "vaultspec-supervisor"
    resolved_idempotency_key = (
        idempotency_key
        or hashlib.sha256(
            f"{thread_id}:message:{agent_id}:{body.content}".encode()
        ).hexdigest()
    )
    existing_action = await get_control_action_by_idempotency_key(
        db, thread_id=thread_id, idempotency_key=resolved_idempotency_key
    )
    if existing_action is not None:
        return SendMessageResponse(
            status="accepted",
            thread_id=thread_id,
            accepted=True,
            applied=existing_action.applied_at is not None,
            action_status=existing_action.result_status,
            action_id=existing_action.id,
            idempotency_key=resolved_idempotency_key,
        )

    action = await create_control_action(
        db,
        thread_id=thread_id,
        action_type=ControlActionType.MESSAGE_FOLLOWUP_REQUESTED,
        idempotency_key=resolved_idempotency_key,
        payload={"content": body.content, "agent_id": agent_id},
    )
    await set_thread_repair_state(
        db,
        thread_id,
        repair_status=RepairStatus.HEALTHY,
        execution_readiness=RepairStatus.HEALTHY.value,
        last_requested_action=ControlActionType.MESSAGE_FOLLOWUP_REQUESTED,
    )

    team_preset: str | None = None
    workspace_root: str | None = None
    if thread.team_preset:
        team_preset = thread.team_preset
    if thread.thread_metadata:
        try:
            meta = json.loads(thread.thread_metadata)
            workspace_root = meta.get("workspace_root")
        except (json.JSONDecodeError, AttributeError):
            pass

    dispatch = DispatchRequest(
        action="ingest",
        thread_id=thread_id,
        agent_id=agent_id,
        content=body.content,
        team_preset=team_preset,
        workspace_root=workspace_root,
    )

    logger.info(
        "Dispatching message dispatch_id=%s for thread %s",
        dispatch.dispatch_id,
        thread_id,
        extra={
            "thread_id": thread_id,
            "dispatch_id": dispatch.dispatch_id,
            "action": dispatch.action,
            "agent_id": agent_id,
        },
    )
    try:
        await dispatch_to_worker(
            worker_client,
            dispatch,
            circuit_breaker,
            worker_spawner,
            trace_headers=trace_headers(),
        )
        mark_worker_connected(request)
    except WorkerCircuitOpenError as exc:
        raise HTTPException(status_code=503, detail=exc.detail) from exc
    except WorkerAtCapacityError:
        raise HTTPException(
            status_code=503,
            detail="Worker at capacity — try again later",
        ) from None
    except WorkerUnreachableError:
        await update_thread_status(db, thread_id, ThreadStatus.FAILED)
        await db.commit()
        raise HTTPException(
            status_code=502,
            detail="Worker unreachable — thread marked as failed",
        ) from None
    except WorkerDispatchRejectedError as exc:
        await update_thread_status(db, thread_id, ThreadStatus.FAILED)
        await db.commit()
        raise HTTPException(
            status_code=502,
            detail=f"Worker rejected dispatch (HTTP {exc.status_code})",
        ) from None

    await update_thread_status(db, thread_id, ThreadStatus.RUNNING)
    await set_thread_repair_state(
        db,
        thread_id,
        repair_status=RepairStatus.HEALTHY,
        execution_readiness=RepairStatus.HEALTHY.value,
        last_applied_action=ControlActionType.MESSAGE_FOLLOWUP_REQUESTED,
    )
    await db.commit()

    return SendMessageResponse(
        status="accepted",
        thread_id=thread_id,
        accepted=True,
        applied=False,
        action_status=ControlActionResultStatus.ACCEPTED_NOT_APPLIED.value,
        action_id=action.id,
        idempotency_key=resolved_idempotency_key,
    )

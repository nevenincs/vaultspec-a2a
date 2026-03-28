"""Message follow-up service — business logic extracted from the messages route.

Owns the full send-followup-message workflow (thread lookup, idempotency,
control-action creation, repair-state transitions, dispatch) without any
FastAPI or HTTP coupling.  The route handler remains a thin adapter that
parses the request, calls this service, commits, and maps the result to
an HTTP response.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..control.dispatch import safe_dispatch
from ..control.repair_transitions import (
    mark_message_followup_applied,
    mark_message_followup_requested,
)
from ..database import (
    create_control_action,
    get_control_action_by_idempotency_key,
    get_thread,
    update_thread_status,
)
from ..ipc.schemas import DispatchRequest
from ..thread.enums import (
    NON_ACTIVE_STATUSES,
    ControlActionType,
    ThreadStatus,
)

if TYPE_CHECKING:
    import httpx
    from sqlalchemy.ext.asyncio import AsyncSession

    from ..control.circuit_breaker import WorkerCircuitBreaker
    from ..control.worker_management import LazyWorkerSpawner

__all__ = ["MessageResult", "send_followup_message"]

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class MessageResult:
    """Value object returned by :func:`send_followup_message`."""

    action_id: str
    thread_id: str
    thread_status: str
    dispatched: bool
    error_detail: str | None = None
    circuit_open: bool = False
    failure_type: str | None = None


async def send_followup_message(
    db: AsyncSession,
    thread_id: str,
    content: str,
    agent_id: str,
    idempotency_key: str | None,
    circuit_breaker: WorkerCircuitBreaker,
    worker_spawner: LazyWorkerSpawner,
    worker_client: httpx.AsyncClient,
    recursion_limit: int,
    trace_headers: dict[str, str] | None,
) -> MessageResult:
    """Execute the send-followup-message workflow.

    Returns a :class:`MessageResult` describing the outcome.  Never raises
    HTTP exceptions — the caller is responsible for translating the result
    into an appropriate HTTP response and committing the session.
    """
    # -- Thread lookup & guard -------------------------------------------
    thread = await get_thread(db, thread_id)
    if thread is None:
        return MessageResult(
            action_id="",
            thread_id=thread_id,
            thread_status="",
            dispatched=False,
            error_detail="Thread not found",
        )

    if thread.status == ThreadStatus.INPUT_REQUIRED.value:
        return MessageResult(
            action_id="",
            thread_id=thread_id,
            thread_status=thread.status,
            dispatched=False,
            error_detail=(
                "Cannot send a follow-up message while the thread is paused for input"
            ),
        )

    if thread.status in NON_ACTIVE_STATUSES:
        return MessageResult(
            action_id="",
            thread_id=thread_id,
            thread_status=thread.status,
            dispatched=False,
            error_detail=f"Cannot send messages to thread in {thread.status!r} state",
        )

    logger.info(
        "Message received for thread %s: %d chars",
        thread_id,
        len(content),
    )

    # -- Idempotency deduplication ---------------------------------------
    resolved_idempotency_key = (
        idempotency_key
        or hashlib.sha256(
            f"{thread_id}:message:{agent_id}:{content}".encode()
        ).hexdigest()
    )
    existing_action = await get_control_action_by_idempotency_key(
        db, thread_id=thread_id, idempotency_key=resolved_idempotency_key
    )
    if existing_action is not None:
        return MessageResult(
            action_id=existing_action.id,
            thread_id=thread_id,
            thread_status=thread.status,
            dispatched=False,
        )

    # -- Control action creation -----------------------------------------
    action = await create_control_action(
        db,
        thread_id=thread_id,
        action_type=ControlActionType.MESSAGE_FOLLOWUP_REQUESTED,
        idempotency_key=resolved_idempotency_key,
        payload={"content": content, "agent_id": agent_id},
    )
    await mark_message_followup_requested(db, thread_id)

    # -- Metadata extraction ---------------------------------------------
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

    # -- Dispatch construction & send ------------------------------------
    dispatch = DispatchRequest(
        action="ingest",
        thread_id=thread_id,
        agent_id=agent_id,
        content=content,
        team_preset=team_preset,
        workspace_root=workspace_root,
        recursion_limit=recursion_limit,
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

    outcome = await safe_dispatch(
        worker_client,
        dispatch,
        circuit_breaker,
        worker_spawner,
        trace_headers=trace_headers,
    )

    if not outcome.success:
        if outcome.failure_type == "circuit_open":
            return MessageResult(
                action_id=action.id,
                thread_id=thread_id,
                thread_status=thread.status,
                dispatched=False,
                circuit_open=True,
                error_detail=outcome.detail,
            )

        if outcome.failure_type == "at_capacity":
            await update_thread_status(db, thread_id, ThreadStatus.FAILED)
            return MessageResult(
                action_id=action.id,
                thread_id=thread_id,
                thread_status=ThreadStatus.FAILED.value,
                dispatched=False,
                error_detail="Worker at capacity — try again later",
            )

        # unreachable or rejected
        await update_thread_status(db, thread_id, ThreadStatus.FAILED)
        return MessageResult(
            action_id=action.id,
            thread_id=thread_id,
            thread_status=ThreadStatus.FAILED.value,
            dispatched=False,
            error_detail=outcome.detail or "Worker dispatch failed",
        )

    # -- Success: transition to RUNNING ----------------------------------
    await update_thread_status(db, thread_id, ThreadStatus.RUNNING)
    await mark_message_followup_applied(db, thread_id)

    return MessageResult(
        action_id=action.id,
        thread_id=thread_id,
        thread_status=ThreadStatus.RUNNING.value,
        dispatched=True,
    )

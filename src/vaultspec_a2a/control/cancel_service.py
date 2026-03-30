"""Cancel-thread service logic (Layer 2c — service extraction).

Owns the full cancel workflow: thread validation, idempotency dedup,
control-action creation, repair-state transition, and dispatch.
Does NOT commit, raise HTTPException, or touch FastAPI request state.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..control.dispatch import safe_dispatch
from ..control.repair_transitions import mark_cancel_requested
from ..database import (
    create_control_action,
    get_control_action_by_idempotency_key,
    get_thread,
    update_thread_status,
)
from ..ipc.schemas import DispatchRequest
from ..thread.cancel_policy import can_cancel
from ..thread.dispatch_policy import FailureType, classify_dispatch_failure
from ..thread.enums import (
    ControlActionResultStatus,
    ControlActionType,
    ThreadStatus,
)
from ..thread.idempotency import default_cancel_key

if TYPE_CHECKING:
    import httpx
    from sqlalchemy.ext.asyncio import AsyncSession

    from ..control.circuit_breaker import WorkerCircuitBreaker
    from ..control.worker_management import LazyWorkerSpawner

__all__ = ["CancelResult", "cancel_thread"]

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CancelResult:
    """Outcome of a cancel-thread service call."""

    action_id: str | None
    thread_id: str
    cancelled: bool
    thread_status: str
    error_detail: str | None = None
    accepted: bool = False
    applied: bool = False
    action_status: str = ControlActionResultStatus.REJECTED_INVALID_STATE.value
    idempotency_key: str | None = None
    failure_type: FailureType | None = None


async def cancel_thread(
    db: AsyncSession,
    *,
    thread_id: str,
    idempotency_key: str | None,
    circuit_breaker: WorkerCircuitBreaker,
    worker_spawner: LazyWorkerSpawner,
    worker_client: httpx.AsyncClient,
    recursion_limit: int,
    trace_headers: dict[str, str] | None = None,
) -> CancelResult:
    """Execute the cancel-thread workflow.

    Returns a :class:`CancelResult` describing what happened.  Commits the
    session before returning — the service owns its transaction boundary.
    """
    thread = await get_thread(db, thread_id)
    if thread is None:
        return CancelResult(
            action_id=None,
            thread_id=thread_id,
            cancelled=False,
            thread_status="",
            error_detail="Thread not found",
        )

    eligibility = can_cancel(thread.status)
    if not eligibility.allowed:
        return CancelResult(
            action_id=None,
            thread_id=thread_id,
            cancelled=False,
            thread_status=thread.status,
            accepted=False,
            applied=eligibility.already_cancelled,
            action_status=ControlActionResultStatus.REJECTED_INVALID_STATE.value,
        )

    resolved_idempotency_key = idempotency_key or default_cancel_key(thread_id)
    existing_action = await get_control_action_by_idempotency_key(
        db, thread_id=thread_id, idempotency_key=resolved_idempotency_key
    )
    if existing_action is not None:
        return CancelResult(
            action_id=existing_action.id,
            thread_id=thread_id,
            cancelled=True,
            thread_status=ThreadStatus.CANCELLING.value,
            accepted=True,
            applied=existing_action.applied_at is not None,
            action_status=existing_action.result_status,
            idempotency_key=resolved_idempotency_key,
        )

    action = await create_control_action(
        db,
        thread_id=thread_id,
        action_type=ControlActionType.CANCEL,
        idempotency_key=resolved_idempotency_key,
        payload={"thread_status": thread.status},
    )
    await mark_cancel_requested(db, thread_id)

    dispatch = DispatchRequest(
        action=ControlActionType.CANCEL,  # ty: ignore[invalid-argument-type]
        thread_id=thread_id,
        recursion_limit=recursion_limit,
    )
    logger.info(
        "Dispatching cancel dispatch_id=%s for thread %s",
        dispatch.dispatch_id,
        thread_id,
        extra={
            "thread_id": thread_id,
            "dispatch_id": dispatch.dispatch_id,
            "action": dispatch.action,
        },
    )

    outcome = await safe_dispatch(
        worker_client,
        dispatch,
        circuit_breaker,
        worker_spawner,
        bypass_circuit_breaker=True,
        trace_headers=trace_headers,
    )

    if not outcome.success:
        policy = classify_dispatch_failure(outcome.failure_type)
        typed_failure = (
            FailureType(outcome.failure_type) if outcome.failure_type else None
        )
        logger.warning(
            "Cancel dispatch failed for thread %s — leaving DB status unchanged",
            thread_id,
            extra={
                "thread_id": thread_id,
                "dispatch_id": dispatch.dispatch_id,
                "action": dispatch.action,
            },
        )
        if policy.should_mark_failed:
            action.result_status = (
                ControlActionResultStatus.REJECTED_INVALID_STATE.value
            )
        await db.commit()
        return CancelResult(
            action_id=action.id,
            thread_id=thread_id,
            cancelled=False,
            thread_status=thread.status,
            accepted=False,
            applied=False,
            action_status=ControlActionResultStatus.REJECTED_INVALID_STATE.value,
            idempotency_key=resolved_idempotency_key,
            failure_type=typed_failure,
        )

    await update_thread_status(db, thread_id, ThreadStatus.CANCELLING)
    await db.commit()
    return CancelResult(
        action_id=action.id,
        thread_id=thread_id,
        cancelled=True,
        thread_status=ThreadStatus.CANCELLING.value,
        accepted=True,
        applied=False,
        action_status=ControlActionResultStatus.ACCEPTED_NOT_APPLIED.value,
        idempotency_key=resolved_idempotency_key,
    )

"""Event handlers for worker → gateway relay (D-05).

Business-logic handlers that persist worker events into the database,
manage permission state machines, and perform aggregator GC on thread
termination.  Extracted from ``api/internal.py`` to decouple protocol
translation from domain logic.

The :func:`relay_event` orchestrator consolidates the duplicated 4-handler
call sequence that previously appeared in 3 call sites.
"""

from __future__ import annotations

import contextlib
import logging
from datetime import datetime
from typing import Any

from ..ipc.schemas import ExecutionStateProjectionPayload
from ..thread.permission_fsm import (
    PROGRESS_BATCH_EFFECTS,
    compute_permission_request_effects,
    compute_permission_resolution_effects,
    compute_progress_applied_effects,
)
from ..thread.snapshots import (
    TERMINAL_STATUS_MAP,
    classify_permission_pause_reason,
    is_permission_event,
    is_progress_event,
    is_terminal_event,
)
from ..thread.terminal_effects import compute_terminal_effects

__all__ = [
    "_handle_execution_state_event",
    "_handle_permission_event",
    "_handle_progress_event",
    "_handle_terminal_event",
    "relay_event",
]

logger = logging.getLogger(__name__)

_TERMINAL_STATUS_MAP = TERMINAL_STATUS_MAP


def _time_now_utc() -> Any:
    """Late-bound helper to avoid a top-level datetime import churn."""
    from datetime import UTC
    from datetime import datetime as _datetime

    return _datetime.now(UTC)


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
    if not is_terminal_event(payload):
        return
    status_str = _TERMINAL_STATUS_MAP.get(payload.get("status", ""))
    if not status_str:
        return
    try:
        from ..database import (
            expire_pending_permission_requests,
            get_latest_control_action,
            set_thread_repair_state,
            update_thread_status,
        )
        from ..thread.enums import (
            ControlActionType,
            InvalidTransitionError,
            ThreadStatus,
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
            effects = compute_terminal_effects(
                ThreadStatus(status_str),
                has_cancel_action=latest_cancel is not None,
            )
            if effects.should_finalize_cancel and latest_cancel is not None:
                latest_cancel.result_status = "applied"
                latest_cancel.applied_at = latest_cancel.applied_at or _time_now_utc()
            await set_thread_repair_state(
                db,
                thread_id,
                repair_status=effects.repair_status,
                repair_reason=effects.repair_reason,
                execution_readiness=effects.repair_status.value,
                last_applied_action=effects.last_applied_action,
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


async def _handle_permission_event(
    thread_id: str,
    payload: dict[str, Any],
    *,
    session_factory: Any | None = None,
) -> None:
    """Persist worker permission events into the durable journal."""
    if not is_permission_event(payload):
        return
    event_type = payload.get("type", "")

    from ..database import (
        create_control_action,
        get_permission_request,
        mark_permission_request_applied,
        record_permission_request,
        set_thread_approval_state,
        set_thread_repair_state,
        supersede_permission_requests,
        update_thread_status,
    )
    from ..thread.enums import (
        ApprovalStatus,
        ControlActionResultStatus,
        ControlActionType,
    )

    if session_factory is None:
        from ..database.session import get_session_factory

        factory = get_session_factory()
    else:
        factory = session_factory
    async with factory() as db:
        if event_type in {"permission_request", "plan_approval_request"}:
            request_id = str(payload.get("request_id", ""))
            if not request_id:
                return
            tool_call = payload.get("tool_call")
            pause_reason_type = (
                "plan_approval_request"
                if event_type == "plan_approval_request"
                else classify_permission_pause_reason(tool_call)
            )
            fx = compute_permission_request_effects(pause_reason_type)
            await supersede_permission_requests(
                db,
                thread_id=thread_id,
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
            await update_thread_status(db, thread_id, fx.thread_status)
            await set_thread_repair_state(
                db,
                thread_id,
                repair_status=fx.repair_status,
                repair_reason=fx.repair_reason,
                execution_readiness=fx.repair_status.value,
                last_applied_action=fx.last_applied_action,
            )
            if fx.is_plan_approval:
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
            if (
                permission is not None
                and permission.request_status == "answered_pending_apply"
            ):
                fx_res = compute_permission_resolution_effects(
                    permission.response_option_id,
                    permission.pause_reason_type,
                )
                await mark_permission_request_applied(
                    db, request_id=request_id, status=fx_res.target_status
                )
                await create_control_action(
                    db,
                    thread_id=thread_id,
                    action_type=fx_res.last_applied_action,
                    request_id=request_id,
                    idempotency_key=f"permission-response-applied:{request_id}",
                    payload={"request_id": request_id},
                    result_status=ControlActionResultStatus.APPLIED,
                )
                await set_thread_repair_state(
                    db,
                    thread_id,
                    repair_status=fx_res.repair_status,
                    repair_reason=fx_res.repair_reason,
                    execution_readiness=fx_res.repair_status.value,
                    last_applied_action=fx_res.last_applied_action,
                )
                if fx_res.is_plan_approval:
                    await set_thread_approval_state(
                        db,
                        thread_id,
                        approval_status=fx_res.approval_status,
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
    if not is_progress_event(payload):
        return
    event_type = payload.get("type", "")

    from ..database import (
        create_control_action,
        get_pending_permission_requests,
        mark_permission_request_applied,
        set_thread_approval_state,
        set_thread_repair_state,
        update_thread_status,
    )
    from ..thread.enums import (
        ControlActionResultStatus,
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
            fx = compute_progress_applied_effects(
                permission.response_option_id,
                permission.pause_reason_type,
            )
            await mark_permission_request_applied(db, request_id=permission.request_id)
            await create_control_action(
                db,
                thread_id=thread_id,
                action_type=fx.last_applied_action,
                request_id=permission.request_id,
                idempotency_key=(
                    f"permission-response-progress-applied:{permission.request_id}"
                ),
                payload={"event_type": event_type},
                result_status=ControlActionResultStatus.APPLIED,
            )
            if fx.is_plan_approval:
                await set_thread_approval_state(
                    db,
                    thread_id,
                    approval_status=fx.approval_status,
                    approval_request_id=permission.request_id,
                    approval_reason=permission.description,
                )
        if answered:
            batch = PROGRESS_BATCH_EFFECTS
            with contextlib.suppress(Exception):
                await update_thread_status(db, thread_id, batch.thread_status)
            await set_thread_repair_state(
                db,
                thread_id,
                repair_status=batch.repair_status,
                repair_reason=batch.repair_reason,
                execution_readiness=batch.repair_status.value,
                last_applied_action=batch.last_applied_action,
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

    from ..database import record_thread_execution_state

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


async def relay_event(
    thread_id: str,
    payload: dict[str, Any],
    *,
    aggregator: Any | None = None,
    session_factory: Any | None = None,
) -> None:
    """Consolidated relay: run all 4 event handlers in sequence.

    This replaces the 3x duplicated handler call sequence that previously
    appeared in ``_relay_worker_event``, ``receive_worker_event``, and
    ``receive_worker_event_batch``.

    Callers are responsible for:
    - Early-returning on ``execution_state_projection`` before calling this
    - Broadcasting to WS clients via ConnectionManager
    - Syncing into the aggregator

    This function handles the DB-side event processing:
    permission journal, progress inference, execution state persistence,
    and terminal status updates with aggregator GC.
    """
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
        aggregator=aggregator,
        session_factory=session_factory,
    )

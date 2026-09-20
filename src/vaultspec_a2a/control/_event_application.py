"""Durable permission and dispatch application receipt settlement."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pydantic import ValidationError

from ..ipc.schemas import DispatchApplicationReceiptPayload
from ..thread.enums import ThreadStatus
from ..thread.permission_fsm import compute_permission_resolution_effects

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from ..database.checkpoints import Checkpointer
    from ..thread.action_receipts import GraphActionReceipt

logger = logging.getLogger(__name__)


async def apply_permission_resolution(
    db: AsyncSession,
    thread_id: str,
    payload: dict[str, object],
) -> None:
    """Finalize a worker-applied permission resolution into the journal.

    Only a request still in ``answered_pending_apply`` is settled: its row is
    marked applied and the resolution is projected onto the applied control
    action, repair state, and - for a plan approval - approval state. Any other
    state is a no-op, matching the prior inline guard.
    """
    from ..database import (
        create_control_action,
        get_control_action_by_idempotency_key,
        get_permission_request,
        mark_control_action_applied,
        mark_permission_request_applied,
        set_thread_approval_state,
        set_thread_repair_state,
    )
    from ..thread.enums import ControlActionResultStatus
    from ._permission_response_contract import permission_response_action_key

    request_value = payload.get("request_id")
    request_id = request_value if isinstance(request_value, str) else ""
    permission = await get_permission_request(db, request_id)
    if permission is None or permission.request_status != "answered_pending_apply":
        return
    fx_res = compute_permission_resolution_effects(
        permission.response_option_id,
        permission.pause_reason_type,
        permission.allowed_options_json,
    )
    await mark_permission_request_applied(
        db, request_id=request_id, status=fx_res.target_status
    )
    submitted = await get_control_action_by_idempotency_key(
        db,
        thread_id=thread_id,
        idempotency_key=permission_response_action_key(request_id),
    )
    if submitted is not None and submitted.applied_at is None:
        await mark_control_action_applied(db, submitted.id)
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


def validated_application_receipt(
    thread_id: str, payload: dict[str, object]
) -> DispatchApplicationReceiptPayload | None:
    if payload.get("type") != "dispatch_applied":
        return None
    from ..thread.enums import ControlActionType

    try:
        application = DispatchApplicationReceiptPayload.model_validate(payload)
    except ValidationError:
        logger.warning(
            "Refusing invalid dispatch application receipt for thread %s",
            thread_id,
            extra={"thread_id": thread_id, "action": "invalid_application_receipt"},
        )
        return None
    if application.graph_action_receipt.thread_id != thread_id:
        logger.warning(
            "Refusing cross-thread dispatch application receipt for thread %s",
            thread_id,
            extra={
                "thread_id": thread_id,
                "action": "cross_thread_application_receipt",
            },
        )
        return None
    receipt_action = application.graph_action_receipt.action_type
    expected_transport_action = (
        "ingest"
        if receipt_action
        in {ControlActionType.INGEST, ControlActionType.MESSAGE_FOLLOWUP_REQUESTED}
        else "resume"
    )
    if application.action != expected_transport_action:
        logger.warning(
            "Refusing mismatched dispatch application verb for thread %s",
            thread_id,
            extra={"thread_id": thread_id, "action": "mismatched_application_verb"},
        )
        return None
    return application


async def proven_application_receipt(
    db: AsyncSession,
    thread_id: str,
    application: DispatchApplicationReceiptPayload,
    checkpointer: Checkpointer,
) -> GraphActionReceipt | None:
    from ..database import get_control_action_by_dispatch_id, get_thread
    from ..thread.checkpoint_evidence import read_checkpoint_evidence
    from .dispatch_receipts import validate_current_graph_receipt

    action = await get_control_action_by_dispatch_id(
        db, thread_id=thread_id, dispatch_id=application.dispatch_id
    )
    thread = await get_thread(db, thread_id)
    if action is None or thread is None or action.applied_at is not None:
        return None
    stored_receipt = validate_current_graph_receipt(thread, action)
    if stored_receipt != application.graph_action_receipt:
        logger.warning(
            "Refusing non-current dispatch application receipt for thread %s",
            thread_id,
            extra={
                "thread_id": thread_id,
                "dispatch_id": application.dispatch_id,
                "action": "non_current_application_receipt",
            },
        )
        return None
    if stored_receipt is None:
        return None
    await db.commit()
    from ..domain_config import domain_config

    evidence = await read_checkpoint_evidence(
        checkpointer,
        stored_receipt,
        timeout_seconds=domain_config.aget_state_timeout_seconds,
        checkpoint_id=application.checkpoint_id,
    )
    if not evidence.incorporated:
        logger.warning(
            "Refusing %s dispatch application receipt for thread %s",
            evidence.kind.value,
            thread_id,
            extra={
                "thread_id": thread_id,
                "dispatch_id": application.dispatch_id,
                "checkpoint_id": application.checkpoint_id,
                "condition": evidence.kind.value,
                "action": "unincorporated_application_receipt",
            },
        )
        return None
    return stored_receipt


async def commit_proven_application(
    db: AsyncSession,
    thread_id: str,
    application: DispatchApplicationReceiptPayload,
    stored_receipt: GraphActionReceipt,
) -> str | None:
    from sqlalchemy import select

    from ..database import (
        ControlActionModel,
        ThreadModel,
        mark_control_action_applied,
        update_thread_status,
    )
    from ..thread.enums import ControlActionType
    from .dispatch_receipts import validate_current_graph_receipt
    from .repair_transitions import mark_message_followup_applied

    thread = await db.scalar(
        select(ThreadModel)
        .where(ThreadModel.id == thread_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    action = await db.scalar(
        select(ControlActionModel)
        .where(
            ControlActionModel.thread_id == thread_id,
            ControlActionModel.dispatch_id == application.dispatch_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        action is None
        or thread is None
        or action.applied_at is not None
        or validate_current_graph_receipt(thread, action) != stored_receipt
    ):
        return None
    if action.action_type == ControlActionType.MESSAGE_FOLLOWUP_REQUESTED.value:
        await mark_control_action_applied(db, action.id)
        await mark_message_followup_applied(db, thread_id)
        await db.commit()
        return None
    if (
        action.action_type == ControlActionType.PERMISSION_RESPONSE_SUBMITTED.value
        and action.request_id is not None
    ):
        await apply_permission_resolution(
            db, thread_id, {"request_id": action.request_id}
        )
        await update_thread_status(db, thread_id, ThreadStatus.RUNNING)
        await db.commit()
        return action.request_id
    from .verdict_subscriber import settle_verdict_dispatch_receipt

    if await settle_verdict_dispatch_receipt(db, action):
        await db.commit()
    return None

"""Durable permission and dispatch application receipt settlement."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Final

from pydantic import ValidationError

from ..ipc.schemas import DispatchApplicationReceiptPayload
from ..thread.action_receipts import GRAPH_ACTION_VERB
from ..thread.enums import ControlActionType
from ..thread.idempotency import ResumeIntent, resume_intent
from ..thread.permission_fsm import compute_permission_resolution_effects
from ..thread.repair_policy import RepairPhase, repair_state_for_action
from .permission_options import response_is_rejection

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from ..database import Checkpointer, ControlActionModel
    from ..thread.action_receipts import GraphActionReceipt

__all__ = [
    "commit_proven_application",
    "proven_application_receipt",
    "validated_application_receipt",
]

logger = logging.getLogger(__name__)

#: The repair step recorded when an accepted action is proven applied, for the
#: actions whose settlement is only to mark them applied. A follow-up is
#: journaled as requested and recorded as applied under its own applied type.
_APPLIED_REPAIR_ACTION: Final[dict[str, ControlActionType]] = {
    ControlActionType.INGEST.value: ControlActionType.INGEST,
    ControlActionType.MESSAGE_FOLLOWUP_REQUESTED.value: (
        ControlActionType.MESSAGE_FOLLOWUP_APPLIED
    ),
}


def _accepted_answer_option(submitted: ControlActionModel) -> str | None:
    """The option *submitted* froze as the answer, or ``None`` if it froze none.

    The accepted dispatch envelope of the response action is the one record of
    the answer this settlement may act on, so a payload that is not the current
    accepted shape, or carries no option, settles nothing instead of falling
    back to the request row's own copy of the decision.
    """
    from ._permission_response_contract import accepted_answer_option
    from .accepted_input import read_accepted_input

    try:
        accepted = read_accepted_input(submitted)
    except (ValidationError, ValueError):
        return None
    return accepted_answer_option(accepted.intent)


async def _apply_permission_resolution(
    db: AsyncSession,
    submitted: ControlActionModel,
) -> None:
    """Finalize a worker-applied permission resolution into the journal.

    *submitted* is the accepted ``PERMISSION_RESPONSE_SUBMITTED`` action, and
    its frozen envelope is where the answered option is read from:
    ``permission_logs`` is the single durable record of a permission decision,
    and the request row holds the request's lifecycle and the options it
    offered, never the answer. Only a request still in
    ``answered_pending_apply`` is settled: its row is marked applied and the
    resolution is projected onto the applied control action, repair state, and
    - for a plan approval - approval state. Any other state is a no-op.
    """
    from ..database import (
        create_control_action,
        get_permission_request,
        mark_control_action_applied,
        mark_permission_request_applied,
        set_thread_approval_state,
    )
    from ..thread.enums import ControlActionResultStatus, PermissionRequestStatus
    from ..thread.idempotency import permission_response_applied_action_key
    from .repair_transitions import apply_repair_transition

    request_id = submitted.request_id
    thread_id = submitted.thread_id
    if request_id is None:
        return
    permission = await get_permission_request(db, request_id)
    if (
        permission is None
        or permission.request_status
        != PermissionRequestStatus.ANSWERED_PENDING_APPLY.value
    ):
        return
    option_id = _accepted_answer_option(submitted)
    if option_id is None:
        # Fail closed and leave the action unapplied: the durable recovery
        # owner still holds it, and an answer nobody can read off its own
        # acceptance must not be settled from a second copy of itself.
        logger.warning(
            "Refusing to settle permission %s on thread %s: its accepted action"
            " records no answered option",
            request_id,
            thread_id,
            extra={
                "thread_id": thread_id,
                "request_id": request_id,
                "action": "unreadable_accepted_permission_answer",
            },
        )
        return
    fx_res = compute_permission_resolution_effects(
        permission.pause_reason_type,
        rejected=response_is_rejection(permission.allowed_options_json, option_id),
    )
    await mark_permission_request_applied(
        db, request_id=request_id, status=fx_res.target_status
    )
    if submitted.applied_at is None:
        await mark_control_action_applied(db, submitted.id)
    await create_control_action(
        db,
        thread_id=thread_id,
        action_type=fx_res.last_applied_action,
        request_id=request_id,
        idempotency_key=permission_response_applied_action_key(
            submitted.idempotency_key
        ),
        payload={"request_id": request_id},
        result_status=ControlActionResultStatus.APPLIED,
    )
    await apply_repair_transition(
        db,
        thread_id,
        repair_state_for_action(fx_res.last_applied_action, RepairPhase.APPLIED),
    )
    if fx_res.is_plan_approval:
        await set_thread_approval_state(
            db,
            thread_id,
            approval_status=fx_res.approval_status,
            approval_request_id=request_id,
        )


def validated_application_receipt(
    thread_id: str, payload: dict[str, object]
) -> DispatchApplicationReceiptPayload | None:
    if payload.get("type") != "dispatch_applied":
        return None
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
    if (
        application.action
        != GRAPH_ACTION_VERB[application.graph_action_receipt.action_type]
    ):
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
    from ..database import (
        get_control_action_by_dispatch_id,
        get_thread,
        read_latest_checkpoint,
    )
    from ..thread.checkpoint_evidence import classify_checkpoint_evidence
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
    evidence = classify_checkpoint_evidence(
        await read_latest_checkpoint(
            checkpointer,
            stored_receipt.thread_id,
            checkpoint_id=application.checkpoint_id,
        ),
        stored_receipt,
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
) -> None:
    from ..database import (
        begin_write_transaction,
        get_control_action_by_dispatch_id,
        lock_thread_row,
        mark_control_action_applied,
    )
    from .dispatch_receipts import validate_current_graph_receipt
    from .repair_transitions import apply_repair_transition

    # ``proven_application_receipt`` ends its read transaction before the
    # checkpoint proof, so this settlement owns the whole re-read and write.
    await begin_write_transaction(db)
    thread = await lock_thread_row(db, thread_id)
    action = await get_control_action_by_dispatch_id(
        db, thread_id=thread_id, dispatch_id=application.dispatch_id, lock=True
    )
    if (
        action is None
        or thread is None
        or action.applied_at is not None
        or validate_current_graph_receipt(thread, action) != stored_receipt
    ):
        return
    applied_repair_action = _APPLIED_REPAIR_ACTION.get(action.action_type)
    if applied_repair_action is not None:
        await mark_control_action_applied(db, action.id)
        await apply_repair_transition(
            db,
            thread_id,
            repair_state_for_action(applied_repair_action, RepairPhase.APPLIED),
        )
        await db.commit()
        return
    if (
        action.action_type == ControlActionType.PERMISSION_RESPONSE_SUBMITTED.value
        and action.request_id is not None
    ):
        await _apply_permission_resolution(db, action)
        # The settlement moves no status: the run leaves its pause through the
        # pause recorder, which this receipt prompts once the settlement is
        # committed and which leaves a run whose turn already ended alone.
        await db.commit()
        return
    if await _settle_resume(db, action):
        await db.commit()


async def _settle_resume(db: AsyncSession, action: ControlActionModel) -> bool:
    """Hand one proven resume to the owner its typed intent names.

    Several unrelated answers arrive as the same ``RESUME`` control action, and
    each has exactly one settlement owner. Matching the typed intent is what
    makes this the steady-state owner for all of them: a resume whose intent is
    known is settled here, by its own owner, on the receipt that proved it
    applied, instead of waiting for a recovery sweep to find the unapplied row.
    """
    match resume_intent(action.idempotency_key):
        case ResumeIntent.CLARIFICATION:
            from .clarification_service import settle_clarification_dispatch_receipt

            return await settle_clarification_dispatch_receipt(db, action)
        case ResumeIntent.AUTHORING_VERDICT:
            from .verdict_subscriber import settle_verdict_dispatch_receipt

            return await settle_verdict_dispatch_receipt(db, action)
        case None:
            logger.warning(
                "Refusing to settle %s action %s: its journal key names no resume"
                " this policy owns",
                action.action_type,
                action.idempotency_key,
                extra={
                    "thread_id": action.thread_id,
                    "action": "unowned_resume_settlement",
                },
            )
            return False

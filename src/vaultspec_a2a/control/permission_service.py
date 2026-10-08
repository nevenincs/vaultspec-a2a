"""Permission response orchestration service.

Extracts the state-machine logic from the REST route handler into a
protocol-agnostic service function.  Does NOT raise ``HTTPException`` or import
from ``api/``.  The run's checkpoint says whether a request is pending and which
options it offers; the permission journal keeps the answer's idempotency,
rejection and audit records.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ..database import (
    append_permission_log,
    begin_write_transaction,
    create_control_action,
    get_control_action_by_idempotency_key,
    get_permission_request,
    get_thread,
    read_latest_checkpoint,
    record_permission_response_submission,
    reset_permission_response_submission,
    set_thread_approval_state,
)
from ..thread.dispatch_policy import FailureType
from ..thread.enums import (
    TERMINAL_STATUSES,
    ControlActionResultStatus,
    ControlActionType,
    PermissionRequestStatus,
)
from ..thread.idempotency import (
    default_permission_response_key,
    permission_duplicate_action_key,
    permission_rejection_action_key,
    permission_response_action_key,
)
from ..thread.repair_policy import RepairPhase, repair_state_for_action
from ..thread.resume_values import permission_resume_value
from ..thread.snapshots import (
    LOCALLY_RESPONDABLE_PAUSE_CAUSES,
    PLAN_APPROVAL_PAUSE_CAUSES,
)
from ._permission_response_contract import (
    AuthorizedPermission as _AuthorizedPermission,
)
from ._permission_response_contract import (
    ParkedPermission as _ParkedPermission,
)
from ._permission_response_contract import PermissionAsk, PermissionInput
from ._permission_response_contract import (
    PermissionTransition as _PermissionTransition,
)
from ._permission_response_contract import (
    RejectedResponse as _RejectedResponse,
)
from ._permission_response_contract import (
    audited_tool_name as _audited_tool_name,
)
from ._permission_response_contract import (
    existing_rejection_error as _existing_rejection_error,
)
from ._permission_response_contract import (
    held_interrupt as _held_interrupt,
)
from ._permission_response_contract import (
    journaled_permission_asks as _journaled_permission_asks,
)
from ._permission_response_contract import (
    rejected_payload as _rejected_payload,
)
from ._permission_response_contract import (
    rejected_permission_error as _rejected_permission_error,
)
from ._permission_response_contract import (
    response_payload as _response_payload,
)
from ._permission_transition_context import permission_transition_context
from .accepted_input import freeze_accepted_input
from .action_lease import (
    ControlActionClaimRequest,
    ControlActionOutcome,
    DispatchFailureDisposition,
    prepare_control_action_claim,
)
from .leased_dispatch import DispatchRefusal, build_followon_dispatch, dispatch_leased
from .pause import project_checkpoint_read
from .repair_transitions import (
    apply_repair_transition,
    record_failed_permission_resume,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from ..database import Checkpointer, ThreadModel
    from ..thread import ProjectedInterrupt
    from .leased_dispatch import DispatchTransport, SettledDispatchFailure

__all__ = [
    "respond_to_permission",
]

logger = logging.getLogger(__name__)


async def _journal_rejection(
    db: AsyncSession,
    rejected: _RejectedResponse,
) -> ControlActionOutcome:
    """Journal a rejected permission response durably and report the rejection.

    Every read-side guard that rejects a response records the same entry: a
    ``REJECTED_INVALID_STATE`` control action carrying the original reason, so a
    replay under the same idempotency key reads that reason back instead of
    re-deciding it. The commit is part of the sequence - the action must be
    durable before the rejection is reported, or a replay arriving after the
    reply would find no record of the original decision.

    The row carries no recovery deadline. It is settled the moment it is
    written, so nothing will ever dispatch it, and the ``now + 5 min`` it used
    to invent was a figure no acceptance stood behind.
    """
    request_id = rejected.request_id
    thread_id = rejected.thread_id
    option_id = rejected.option_id
    idempotency_key = rejected.idempotency_key
    approval_status = rejected.approval_status
    error_detail = rejected.error_detail
    error_status_code = rejected.error_status_code
    action = await create_control_action(
        db,
        thread_id=thread_id,
        action_type=ControlActionType.PERMISSION_RESPONSE_SUBMITTED,
        request_id=request_id,
        idempotency_key=permission_rejection_action_key(idempotency_key),
        payload=_rejected_payload(option_id, error_detail),
        result_status=ControlActionResultStatus.REJECTED_INVALID_STATE,
    )
    await db.commit()
    return ControlActionOutcome(
        request_id=request_id,
        thread_id=thread_id,
        action_id=action.id,
        idempotency_key=idempotency_key,
        approval_status=approval_status,
        error_detail=error_detail,
        error_status_code=error_status_code,
    )


def _request_not_found(request_id: str, thread_id: str) -> ControlActionOutcome:
    """Refuse an answer to a request no run holds or journals under this id."""
    return ControlActionOutcome(
        request_id=request_id,
        thread_id=thread_id,
        error_detail=(
            f"Permission request {request_id!r} not found for run {thread_id!r}"
        ),
        error_status_code=404,
    )


async def respond_to_permission(
    db: AsyncSession,
    *,
    thread_id: str,
    response: PermissionInput,
    checkpointer: Checkpointer,
    transport: DispatchTransport,
) -> ControlActionOutcome:
    """Execute the permission-response state machine.

    The run's checkpoint decides whether *response* answers a request the run is
    parked on, and which options that request offers. The request's journal row
    keeps the answer's idempotency, rejection and audit records and never opens,
    closes or answers a pause: a request the checkpoint does not hold is refused,
    except that an answer already accepted for it replays.

    Returns a :class:`ControlActionOutcome` describing the outcome.  Commits the
    session before returning — the service owns its transaction boundary.
    The caller translates errors into protocol-specific responses. ``notes``
    is an optional reviewer comment threaded into the verdict resume payload
    for a locally-respondable verdict-style pause; it is ignored for a plain
    tool-permission response, which resumes on the chosen option and the
    request it answers.
    """
    request_id = response.request_id
    option_id = response.option_id
    logger.info(
        "Permission response: request_id=%s, option_id=%s",
        request_id,
        option_id,
        extra={
            "request_id": request_id,
            "thread_id": thread_id,
            "action": "permission_response",
            "option_id": option_id,
        },
    )

    # An unknown run is refused before the checkpoint round trip below.
    known = await get_thread(db, thread_id) is not None
    await db.rollback()
    if not known:
        return _request_not_found(request_id, thread_id)
    # The checkpoint read is remote I/O, so it happens before the durable
    # transaction opens: holding the write lock across it would block every
    # other writer for the length of a checkpoint round trip.
    checkpoint = await read_latest_checkpoint(checkpointer, thread_id)
    projection = project_checkpoint_read(checkpoint, thread_id)
    held = _held_interrupt(projection, request_id)
    # A checkpoint that did not answer, or answered with something that could not
    # be projected, proves nothing about what the run holds.
    unconfirmed = checkpoint.unreadable or (
        checkpoint.checkpoint_tuple is not None and projection is None
    )

    await begin_write_transaction(db)
    try:
        authorization = await _authorize_permission_response(
            db,
            thread_id,
            response,
            held,
            checkpoint_unconfirmed=unconfirmed,
        )
        if isinstance(authorization, ControlActionOutcome):
            return authorization

        # ------------------------------------------------------------------
        # 5. Record the transition, then 6-7 dispatch the resume
        # ------------------------------------------------------------------
        transition = await _record_permission_transition(
            db, authorized=authorization, response=response
        )
        if isinstance(transition, ControlActionOutcome):
            return transition
        return await _dispatch_permission_resume(
            db,
            authorized=authorization,
            transition=transition,
            response=response,
            transport=transport,
        )
    finally:
        # The service owns its boundary and no caller commits after it, so a
        # transaction still open here holds nothing worth keeping: release the
        # write lock now rather than when the session closes.
        if db.in_transaction():
            await db.rollback()


async def _deduplicate_permission_response(
    db: AsyncSession,
    permission: _ParkedPermission,
    thread_record: ThreadModel,
    response: PermissionInput,
    resolved_idempotency_key: str,
    ask: PermissionAsk,
) -> ControlActionOutcome | _AuthorizedPermission | None:
    request_id = response.request_id
    option_id = response.option_id
    thread_id = thread_record.id
    existing_action = await get_control_action_by_idempotency_key(
        db,
        thread_id=thread_id,
        idempotency_key=permission_rejection_action_key(resolved_idempotency_key),
    )
    if existing_action is not None:
        if (
            existing_action.result_status
            == ControlActionResultStatus.REJECTED_INVALID_STATE.value
        ):
            stored_error_detail = _existing_rejection_error(existing_action)
            error_detail, error_status_code = _rejected_permission_error(
                permission,
                thread_terminal=thread_record.status in TERMINAL_STATUSES,
                option_id=option_id,
            )
            return ControlActionOutcome(
                request_id=request_id,
                thread_id=thread_id,
                action_status=existing_action.result_status,
                action_id=existing_action.id,
                idempotency_key=resolved_idempotency_key,
                approval_status=thread_record.approval_status,
                error_detail=stored_error_detail or error_detail,
                error_status_code=error_status_code,
            )
        return ControlActionOutcome(
            request_id=request_id,
            thread_id=thread_id,
            accepted=True,
            applied=existing_action.applied_at is not None,
            action_status=existing_action.result_status,
            action_id=existing_action.id,
            idempotency_key=resolved_idempotency_key,
            approval_status=thread_record.approval_status,
        )

    # The ASK, not a caller-selected retry header, owns the accepted body.
    # This check deliberately precedes permission-status rejection so an
    # identical retry can replay or redrive an answered/applied request. The
    # claim the transition takes decides which: a competing body conflicts, an
    # applied or freshly leased action replays, and an expired lease redrives.
    # A re-ask has no accepted answer of its own yet, so it falls through to
    # the parked checks instead of replaying the answer to the ask before it.
    if ask.accepted is not None:
        return _AuthorizedPermission(
            permission=permission,
            thread_record=thread_record,
            thread_id=thread_id,
            resolved_idempotency_key=resolved_idempotency_key,
            ask=ask,
        )
    return None


def _document_approval_refusal(
    permission: _ParkedPermission, thread_id: str
) -> ControlActionOutcome | None:
    request_id = permission.request_id
    if (
        permission.pause_reason_type in PLAN_APPROVAL_PAUSE_CAUSES
        and permission.pause_reason_type not in LOCALLY_RESPONDABLE_PAUSE_CAUSES
    ):
        logger.warning(
            "Permission respond refused: request %s pauses on %r, which only "
            "the engine review surface may decide",
            request_id,
            permission.pause_reason_type,
            extra={
                "thread_id": thread_id,
                "request_id": request_id,
                "action": "permission_response",
                "pause_reason_type": permission.pause_reason_type,
            },
        )
        return ControlActionOutcome(
            request_id=request_id,
            thread_id=thread_id,
            error_detail=(
                "Document-approval pauses are decided by the engine review "
                "surface, not this route; the run resumes only through the "
                "verdict subscriber."
            ),
            error_status_code=403,
        )

    return None


async def _parked_permission(
    db: AsyncSession,
    thread_id: str,
    request_id: str,
    held: ProjectedInterrupt | None,
) -> _ParkedPermission | None:
    """Resolve the request a response answers, from the checkpoint first.

    A request the run's checkpoint holds is read off its interrupt, and the
    journal row is consulted only for the description it cached. One the
    checkpoint does not hold is read from this run's journal row, so a replay of
    an answer already accepted for it can still be judged; a run's checkpoint
    and journal that both lack the request leave nothing to answer. A row filed
    under another run is no record of a request on this one.
    """
    journal = await get_permission_request(db, request_id)
    if journal is not None and journal.thread_id != thread_id:
        journal = None
    if held is not None:
        return _ParkedPermission.from_interrupt(
            held, description=journal.description if journal is not None else ""
        )
    return _ParkedPermission.from_journal(journal) if journal is not None else None


async def _authorize_permission_response(
    db: AsyncSession,
    thread_id: str,
    response: PermissionInput,
    held: ProjectedInterrupt | None,
    *,
    checkpoint_unconfirmed: bool,
) -> ControlActionOutcome | _AuthorizedPermission:
    """Authorize a response to a request on a run before any change.

    Runs every read-side guard the state machine imposes - thread resolution,
    idempotency dedup, the checkpoint's pending check, the terminal check, and
    option validation. Returns a :class:`ControlActionOutcome` for any rejection,
    duplicate, or already-applied outcome (committing the rejection journal
    action where the machine records one), or an :class:`_AuthorizedPermission`
    when the response is admitted and the transition may proceed.
    """
    request_id = response.request_id
    # ------------------------------------------------------------------
    # 1. Resolve the thread and the request it is being asked to answer
    # ------------------------------------------------------------------
    thread_record = await get_thread(db, thread_id)
    if thread_record is None:
        return _request_not_found(request_id, thread_id)
    permission = await _parked_permission(db, thread_id, request_id, held)
    if permission is None:
        return _request_not_found(request_id, thread_id)

    # ------------------------------------------------------------------
    # 1.5. Refuse pauses this route has no authority to answer
    # ------------------------------------------------------------------
    # A verdict-style pause (PLAN_APPROVAL_PAUSE_CAUSES) that is not locally
    # respondable is a document-approval pause: the engine review surface is
    # the sole approval authority for it (no second approval authority in
    # A2A). Refusing here, before
    # the idempotency and transition logic runs, means no control action is
    # journalled and no resume value is ever constructed for this call.
    document_refusal = _document_approval_refusal(permission, thread_id)
    if document_refusal is not None:
        return document_refusal

    # ------------------------------------------------------------------
    # 2. Idempotency deduplication
    # ------------------------------------------------------------------
    resolved_idempotency_key = (
        response.idempotency_key
        or default_permission_response_key(request_id, response.option_id)
    )
    # Which ask of the request this answers, read once inside the write
    # transaction: a run still holding the request after an earlier answer
    # landed has asked it again, and that ask takes an identity of its own.
    asks = await _journaled_permission_asks(
        db, thread_id=thread_id, request_id=request_id
    )
    if asks is None:
        return ControlActionOutcome(
            request_id=request_id,
            thread_id=thread_id,
            idempotency_key=resolved_idempotency_key,
            approval_status=thread_record.approval_status,
            error_detail="Permission request has been asked too many times",
            error_status_code=409,
            failure_type=FailureType.INCOMPATIBLE_STATE,
        )
    ask = asks.addressed(held=permission.pending)
    replay = await _deduplicate_permission_response(
        db, permission, thread_record, response, resolved_idempotency_key, ask
    )
    if replay is not None:
        return replay

    return await _authorize_parked_permission(
        db,
        permission,
        thread_record,
        response,
        resolved_idempotency_key,
        ask,
        checkpoint_unconfirmed=checkpoint_unconfirmed,
    )


async def _refuse_unparked_permission(
    db: AsyncSession,
    permission: _ParkedPermission,
    thread_record: ThreadModel,
    response: PermissionInput,
    resolved_idempotency_key: str,
    *,
    checkpoint_unconfirmed: bool,
) -> ControlActionOutcome:
    """Answer a response to a request the run's checkpoint does not hold.

    The checkpoint has already said the request is not pending; the journal row
    only decides how an answer to a finished request is reported. One recorded
    as applied is answered with the duplicate it is. Any other is refused and
    the refusal journalled - unless the checkpoint could not say, because then
    nothing is known about the request and a journalled refusal would replay
    under the same key after the store recovers.
    """
    request_id = response.request_id
    option_id = response.option_id
    thread_id = thread_record.id
    journal = await get_permission_request(db, request_id)
    if (
        journal is not None
        and journal.request_status == PermissionRequestStatus.APPLIED.value
    ):
        action = await create_control_action(
            db,
            thread_id=thread_id,
            action_type=ControlActionType.PERMISSION_RESPONSE_SUBMITTED,
            request_id=request_id,
            idempotency_key=permission_duplicate_action_key(resolved_idempotency_key),
            payload={"option_id": option_id},
            result_status=ControlActionResultStatus.DUPLICATE,
        )
        await db.commit()
        return ControlActionOutcome(
            request_id=request_id,
            thread_id=thread_id,
            accepted=True,
            applied=True,
            action_status=ControlActionResultStatus.DUPLICATE.value,
            action_id=action.id,
            idempotency_key=resolved_idempotency_key,
            approval_status=thread_record.approval_status,
        )

    if checkpoint_unconfirmed:
        return ControlActionOutcome(
            request_id=request_id,
            thread_id=thread_id,
            error_detail="Permission request cannot be confirmed pending",
            error_status_code=409,
        )

    error_detail, error_status_code = _rejected_permission_error(
        permission, thread_terminal=False, option_id=option_id
    )
    return await _journal_rejection(
        db,
        _RejectedResponse(
            request_id,
            thread_id,
            option_id,
            resolved_idempotency_key,
            thread_record.approval_status,
            error_detail,
            error_status_code,
        ),
    )


async def _authorize_parked_permission(
    db: AsyncSession,
    permission: _ParkedPermission,
    thread_record: ThreadModel,
    response: PermissionInput,
    resolved_idempotency_key: str,
    ask: PermissionAsk,
    *,
    checkpoint_unconfirmed: bool,
) -> ControlActionOutcome | _AuthorizedPermission:
    request_id = response.request_id
    thread_id = thread_record.id
    # ------------------------------------------------------------------
    # 3. Pending check: the checkpoint's, never the journal row's
    # ------------------------------------------------------------------
    if not permission.pending:
        return await _refuse_unparked_permission(
            db,
            permission,
            thread_record,
            response,
            resolved_idempotency_key,
            checkpoint_unconfirmed=checkpoint_unconfirmed,
        )

    # ------------------------------------------------------------------
    # 4. Thread terminal status guard
    # ------------------------------------------------------------------
    if thread_record.status in TERMINAL_STATUSES:
        logger.warning(
            "Permission respond rejected: thread %s is no longer active (status=%r)",
            thread_id,
            thread_record.status,
            extra={
                "thread_id": thread_id,
                "request_id": request_id,
                "action": "permission_response",
                "thread_status": thread_record.status,
            },
        )
        return ControlActionOutcome(
            request_id=request_id,
            thread_id=thread_id,
            error_detail="thread is no longer active",
            error_status_code=409,
        )

    option_error = await _validate_permission_option(
        db, permission, thread_record, response, resolved_idempotency_key
    )
    if option_error is not None:
        return option_error

    return _AuthorizedPermission(
        permission=permission,
        thread_record=thread_record,
        thread_id=thread_id,
        resolved_idempotency_key=resolved_idempotency_key,
        ask=ask,
    )


async def _validate_permission_option(
    db: AsyncSession,
    permission: _ParkedPermission,
    thread_record: ThreadModel,
    response: PermissionInput,
    resolved_idempotency_key: str,
) -> ControlActionOutcome | None:
    request_id = response.request_id
    option_id = response.option_id
    thread_id = thread_record.id
    valid_option_ids = permission.option_ids
    if option_id in valid_option_ids:
        return None

    error_detail, error_status_code = _rejected_permission_error(
        permission, thread_terminal=False, option_id=option_id
    )
    if valid_option_ids:
        logger.warning(
            "Permission respond rejected: request %s received unknown option_id=%r",
            request_id,
            option_id,
            extra={
                "thread_id": thread_id,
                "request_id": request_id,
                "action": "permission_response",
                "option_id": option_id,
                "valid_option_ids": sorted(valid_option_ids),
            },
        )
    else:
        logger.warning(
            "Permission respond rejected: request %s offers no valid options",
            request_id,
            extra={
                "thread_id": thread_id,
                "request_id": request_id,
                "action": "permission_response",
            },
        )
    return await _journal_rejection(
        db,
        _RejectedResponse(
            request_id,
            thread_id,
            option_id,
            resolved_idempotency_key,
            thread_record.approval_status,
            error_detail,
            error_status_code,
        ),
    )


async def _record_permission_transition(
    db: AsyncSession,
    *,
    authorized: _AuthorizedPermission,
    response: PermissionInput,
) -> ControlActionOutcome | _PermissionTransition:
    """Write the durable pre-dispatch transition for an authorized response.

    Creates the submitted control action, records the response submission, audits
    the decision, and - for a plan-approval pause - stamps the thread's approval
    state. Returns the claim plus the resume dispatch the dispatch stage carries
    to the worker.

    The transition commits with the claimed acceptance, before any network call,
    so the decision survives a worker that never answers. It is therefore NOT
    rolled back by a failed dispatch: the dispatch stage compensates instead,
    releasing the claim and resetting the response submission so the request can
    be re-answered. The audit row is deliberately left standing by that
    compensation - a decision the operator really made is a fact about the run
    even when its delivery failed, and a re-answer appends a second row rather
    than rewriting the first.
    """
    context = permission_transition_context(authorized, response)

    resume_value = permission_resume_value(
        authorized.permission.pause_reason_type,
        context.option_id,
        context.notes,
        request_id=context.request_id,
    )
    dispatch = await build_followon_dispatch(
        db,
        thread_id=context.thread_id,
        thread_metadata=context.thread_record.thread_metadata,
        action=ControlActionType.RESUME,
        option_id=resume_value,
    )
    if isinstance(dispatch, DispatchRefusal):
        # Nothing was claimed, so the refusal carries its typed failure alone
        # and the one protocol mapping serves it, as it does for every verb.
        return ControlActionOutcome(
            request_id=context.request_id,
            thread_id=context.thread_id,
            idempotency_key=context.resolved_idempotency_key,
            approval_status=context.replay_approval_status,
            error_detail=dispatch.reason,
            failure_type=dispatch.failure_type,
        )

    claim = await prepare_control_action_claim(
        db,
        request=ControlActionClaimRequest(
            write_expectation=context.write_expectation,
            thread_id=context.thread_id,
            action_type=ControlActionType.PERMISSION_RESPONSE_SUBMITTED,
            request_id=context.request_id,
            idempotency_key=permission_response_action_key(
                context.request_id, authorized.ask.generation
            ),
            payload=freeze_accepted_input(
                dispatch, intent=_response_payload(context.option_id, context.notes)
            ),
            dispatch_id=dispatch.dispatch_id,
            recovery_timeout_seconds=(
                dispatch.require_graph_definition().run_timeout_seconds
            ),
        ),
    )
    if not claim.authority_matches:
        return ControlActionOutcome(
            request_id=context.request_id,
            thread_id=context.thread_id,
            idempotency_key=context.resolved_idempotency_key,
            approval_status=context.replay_approval_status,
            error_status_code=409,
            failure_type=FailureType.INCOMPATIBLE_STATE,
            error_detail="Accepted action no longer owns the current run",
        )
    if not claim.payload_matches:
        return ControlActionOutcome(
            request_id=context.request_id,
            thread_id=context.thread_id,
            idempotency_key=context.resolved_idempotency_key,
            approval_status=context.replay_approval_status,
            error_detail="Permission request already has a different response",
            error_status_code=409,
            failure_type=FailureType.CONFLICT,
        )
    if not claim.acquired:
        return ControlActionOutcome(
            request_id=context.request_id,
            thread_id=context.thread_id,
            accepted=True,
            applied=claim.applied,
            action_status=claim.result_status,
            action_id=claim.action_id,
            idempotency_key=context.resolved_idempotency_key,
            approval_status=context.replay_approval_status,
        )

    await record_permission_response_submission(
        db,
        request_id=context.request_id,
        option_id=context.option_id,
        idempotency_key=context.resolved_idempotency_key,
    )
    # The audit entry is written here and nowhere else: this is the one point the
    # response is applied to the pending request, and it sits behind the claim
    # election above, so a retried or losing caller returns before reaching it and
    # one decision produces exactly one row. Writing it at the route would log
    # attempts rather than decisions; writing it after dispatch would lose the
    # record of a decision the operator really made whenever the worker was
    # unreachable. No commit here - the acceptance the dispatch stage finalizes
    # owns it.
    await append_permission_log(
        db,
        thread_id=context.thread_id,
        # Unattributed, deliberately. Neither sense of "who" is knowable at this
        # seam: the agent whose tool call was gated is never captured upstream,
        # and the responder carries no authenticated identity. Recording the
        # decision without the actor beats fabricating one.
        agent_id=None,
        tool_name=_audited_tool_name(authorized.permission),
        action=context.decision_verdict,
        option_id=context.option_id,
    )
    if context.is_locally_respondable:
        await set_thread_approval_state(
            db,
            context.thread_id,
            approval_status=context.submitted_approval_status,
            approval_request_id=context.request_id,
            approval_response_action_id=claim.action_id,
        )
    await apply_repair_transition(
        db,
        context.thread_id,
        repair_state_for_action(
            ControlActionType.PERMISSION_RESPONSE_SUBMITTED, RepairPhase.REQUESTED
        ),
    )

    return _PermissionTransition(
        claim=claim,
        dispatch=dispatch,
        approval_status=context.submitted_approval_status,
    )


async def _failed_permission_dispatch(
    db: AsyncSession,
    authorized: _AuthorizedPermission,
    transition: _PermissionTransition,
    response: PermissionInput,
    failure: SettledDispatchFailure,
) -> ControlActionOutcome:
    request_id = response.request_id
    thread_id = authorized.thread_id
    if failure.disposition is DispatchFailureDisposition.DEFINITE_NON_DELIVERY:
        await reset_permission_response_submission(db, request_id=request_id)
    if failure.should_mark_failed and failure.disposition in {
        DispatchFailureDisposition.DEFINITE_NON_DELIVERY,
        DispatchFailureDisposition.AMBIGUOUS_DELIVERY,
    }:
        await record_failed_permission_resume(db, thread_id, reason=failure.detail)

    await db.commit()
    return ControlActionOutcome(
        request_id=request_id,
        thread_id=thread_id,
        action_id=transition.claim.action_id,
        idempotency_key=authorized.resolved_idempotency_key,
        approval_status=transition.approval_status,
        # No status is chosen here. A dispatch outcome carries its typed failure
        # and nothing else, so the one protocol mapping decides what every verb
        # that met the same outcome serves for it.
        error_detail=failure.detail,
        failure_type=failure.failure_type,
    )


async def _dispatch_permission_resume(
    db: AsyncSession,
    *,
    authorized: _AuthorizedPermission,
    transition: _PermissionTransition,
    response: PermissionInput,
    transport: DispatchTransport,
) -> ControlActionOutcome:
    """Dispatch the resume to the worker and settle the response.

    On dispatch failure the recorded transition is reset and the failure is
    classified into the protocol-facing error and thread state. On success the
    requested projection remains parked until an exact worker application receipt
    settles the request and moves the thread to running.
    """
    request_id = response.request_id
    thread_id = authorized.thread_id
    resolved_idempotency_key = authorized.resolved_idempotency_key
    claim = transition.claim

    logger.info(
        "Dispatching resume dispatch_id=%s for thread %s (request_id=%s)",
        claim.dispatch_id,
        thread_id,
        request_id,
        extra={
            "thread_id": thread_id,
            "dispatch_id": claim.dispatch_id,
            "request_id": request_id,
            "action": transition.dispatch.action,
            "option_id": response.option_id,
        },
    )

    failure = await dispatch_leased(db, claim, transition.dispatch, transport)
    if failure is not None:
        return await _failed_permission_dispatch(
            db, authorized, transition, response, failure
        )

    return ControlActionOutcome(
        request_id=request_id,
        thread_id=thread_id,
        accepted=True,
        action_status=ControlActionResultStatus.ACCEPTED_NOT_APPLIED.value,
        action_id=claim.action_id,
        idempotency_key=resolved_idempotency_key,
        approval_status=transition.approval_status,
        dispatched=True,
    )

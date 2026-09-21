"""Permission response orchestration service.

Extracts the state-machine logic from the REST route handler into a
protocol-agnostic service function.  Does NOT commit the session, raise
``HTTPException``, or import from ``api/``.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from ..database import (
    append_permission_log,
    create_control_action,
    get_control_action_by_idempotency_key,
    get_pending_permission_requests,
    get_permission_request,
    get_thread,
    record_permission_response_submission,
    reset_permission_response_submission,
    set_thread_approval_state,
)
from ..ipc.schemas import DispatchRequest, to_dispatch_action
from ..thread.dispatch_policy import FailureType, evaluate_dispatch_failure
from ..thread.enums import (
    TERMINAL_STATUSES,
    ControlActionResultStatus,
    ControlActionType,
    PermissionRequestStatus,
    ThreadStatus,
)
from ..thread.idempotency import default_permission_response_key
from ..thread.snapshots import (
    LOCALLY_RESPONDABLE_PAUSE_CAUSES,
    PLAN_APPROVAL_PAUSE_CAUSES,
)
from ._permission_response_contract import (
    AuthorizedPermission as _AuthorizedPermission,
)
from ._permission_response_contract import (
    PermissionInput,
    PermissionResult,
    PermissionRuntime,
    permission_response_action_key,
)
from ._permission_response_contract import (
    PermissionTransition as _PermissionTransition,
)
from ._permission_response_contract import (
    RejectedResponse as _RejectedResponse,
)
from ._permission_response_contract import (
    action_payload_matches as _action_payload_matches,
)
from ._permission_response_contract import (
    allowed_option_ids as _allowed_option_ids,
)
from ._permission_response_contract import (
    audited_tool_name as _audited_tool_name,
)
from ._permission_response_contract import (
    existing_rejection_error as _existing_rejection_error,
)
from ._permission_response_contract import (
    permission_rejection_action_key as _permission_rejection_action_key,
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
from ._thread_metadata import dispatchable_workspace_root
from .accepted_input import freeze_accepted_input
from .action_lease import (
    ControlActionClaimRequest,
    DispatchFailureDisposition,
    finalize_control_action_acceptance,
    prepare_control_action_claim,
    record_dispatch_failure,
)
from .dispatch import DispatchOutcome, safe_dispatch
from .dispatch_receipts import bind_graph_action_receipt
from .execution_authority import ExecutionAuthorityError, resolve_execution_authority
from .graph_definition import read_accepted_graph_definition
from .permission_dispatch import (
    permission_dispatch_error as _permission_dispatch_error,
)
from .permission_dispatch import permission_resume_value
from .repair_transitions import (
    apply_dispatch_failure,
    mark_permission_response_requested,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

    from ..database import (
        PermissionRequestModel,
        ThreadModel,
    )

__all__ = [
    "respond_to_permission",
]

logger = logging.getLogger(__name__)


async def _journal_rejection(
    db: AsyncSession,
    rejected: _RejectedResponse,
) -> PermissionResult:
    """Journal a rejected permission response durably and report the rejection.

    Every read-side guard that rejects a response records the same entry: a
    ``REJECTED_INVALID_STATE`` control action carrying the original reason, so a
    replay under the same idempotency key reads that reason back instead of
    re-deciding it. The commit is part of the sequence - the action must be
    durable before the rejection is reported, or a replay arriving after the
    reply would find no record of the original decision.
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
        idempotency_key=_permission_rejection_action_key(idempotency_key),
        payload=_rejected_payload(option_id, error_detail),
        result_status=ControlActionResultStatus.REJECTED_INVALID_STATE,
        recovery_deadline_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    await db.commit()
    return PermissionResult(
        request_id=request_id,
        thread_id=thread_id,
        accepted=False,
        applied=False,
        action_status=ControlActionResultStatus.REJECTED_INVALID_STATE.value,
        action_id=action.id,
        idempotency_key=idempotency_key,
        approval_status=approval_status,
        error_detail=error_detail,
        error_status_code=error_status_code,
    )


async def respond_to_permission(
    db: AsyncSession,
    *,
    response: PermissionInput,
    runtime: PermissionRuntime,
) -> PermissionResult:
    """Execute the permission-response state machine.

    Returns a :class:`PermissionResult` describing the outcome.  Commits the
    session before returning — the service owns its transaction boundary.
    The caller translates errors into protocol-specific responses. ``notes``
    is an optional reviewer comment threaded into the verdict resume payload
    for a locally-respondable verdict-style pause (D6); it is ignored for a
    plain tool-permission response, which resumes on the bare option id.
    """
    request_id = response.request_id
    option_id = response.option_id
    idempotency_key = response.idempotency_key
    notes = response.notes
    logger.info(
        "Permission response: request_id=%s, option_id=%s",
        request_id,
        option_id,
        extra={
            "request_id": request_id,
            "thread_id": (request_id.split(":", 1)[0] if ":" in request_id else None),
            "action": "permission_response",
            "option_id": option_id,
        },
    )

    authorization = await _authorize_permission_response(
        db,
        request_id=request_id,
        option_id=option_id,
        idempotency_key=idempotency_key,
        notes=notes,
    )
    if isinstance(authorization, PermissionResult):
        return authorization

    # ------------------------------------------------------------------
    # 5. Record the transition, then 6-7 dispatch the resume
    # ------------------------------------------------------------------
    transition = await _record_permission_transition(
        db,
        authorized=authorization,
        response=response,
        recursion_limit=runtime.recursion_limit,
    )
    if isinstance(transition, PermissionResult):
        return transition
    return await _dispatch_permission_resume(
        db,
        authorized=authorization,
        transition=transition,
        response=response,
        runtime=runtime,
    )


async def _deduplicate_permission_response(
    db: AsyncSession,
    permission: PermissionRequestModel,
    thread_record: ThreadModel,
    response: PermissionInput,
    resolved_idempotency_key: str,
) -> PermissionResult | _AuthorizedPermission | None:
    request_id = response.request_id
    option_id = response.option_id
    notes = response.notes
    thread_id = thread_record.id
    existing_action = await get_control_action_by_idempotency_key(
        db,
        thread_id=thread_id,
        idempotency_key=_permission_rejection_action_key(resolved_idempotency_key),
    )
    if existing_action is not None:
        if (
            existing_action.result_status
            == ControlActionResultStatus.REJECTED_INVALID_STATE.value
        ):
            stored_error_detail = _existing_rejection_error(existing_action)
            valid_option_ids = _allowed_option_ids(permission)
            error_detail, error_status_code = _rejected_permission_error(
                permission_status=permission.request_status,
                thread_terminal=thread_record.status in TERMINAL_STATUSES,
                option_id=option_id,
                valid_option_ids=valid_option_ids,
            )
            return PermissionResult(
                request_id=request_id,
                thread_id=thread_id,
                accepted=False,
                applied=False,
                action_status=existing_action.result_status,
                action_id=existing_action.id,
                idempotency_key=resolved_idempotency_key,
                approval_status=thread_record.approval_status,
                error_detail=stored_error_detail or error_detail,
                error_status_code=error_status_code,
            )
        return PermissionResult(
            request_id=request_id,
            thread_id=thread_id,
            accepted=True,
            applied=existing_action.applied_at is not None,
            action_status=existing_action.result_status,
            action_id=existing_action.id,
            idempotency_key=resolved_idempotency_key,
            approval_status=thread_record.approval_status,
        )

    # The request, not a caller-selected retry header, owns the accepted body.
    # This check deliberately precedes permission-status rejection so an
    # identical retry can replay or redrive an answered/applied request.
    winning_action = await get_control_action_by_idempotency_key(
        db,
        thread_id=thread_id,
        idempotency_key=permission_response_action_key(request_id),
    )
    if winning_action is not None:
        if not _action_payload_matches(winning_action, option_id, notes):
            return PermissionResult(
                request_id=request_id,
                thread_id=thread_id,
                accepted=False,
                applied=False,
                action_status=ControlActionResultStatus.REJECTED_INVALID_STATE.value,
                idempotency_key=resolved_idempotency_key,
                approval_status=thread_record.approval_status,
                error_detail="Permission request already has a different response",
                error_status_code=409,
                failure_type=FailureType.CONFLICT,
            )
        claim_is_fresh = (
            winning_action.claim_token is not None
            and winning_action.claim_expires_at is not None
            and winning_action.claim_expires_at > datetime.now(UTC)
        )
        if winning_action.applied_at is not None or claim_is_fresh:
            return PermissionResult(
                request_id=request_id,
                thread_id=thread_id,
                accepted=True,
                applied=winning_action.applied_at is not None,
                action_status=winning_action.result_status,
                action_id=winning_action.id,
                idempotency_key=resolved_idempotency_key,
                approval_status=thread_record.approval_status,
            )
        return _AuthorizedPermission(
            permission=permission,
            thread_record=thread_record,
            thread_id=thread_id,
            resolved_idempotency_key=resolved_idempotency_key,
        )
    return None


def _document_approval_refusal(
    permission: PermissionRequestModel, request_id: str, thread_id: str
) -> PermissionResult | None:
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
        return PermissionResult(
            request_id=request_id,
            thread_id=thread_id,
            accepted=False,
            applied=False,
            action_status=ControlActionResultStatus.REJECTED_INVALID_STATE.value,
            error_detail=(
                "Document-approval pauses are decided by the engine review "
                "surface, not this route; the run resumes only through the "
                "verdict subscriber."
            ),
            error_status_code=403,
        )

    return None


async def _authorize_permission_response(
    db: AsyncSession,
    *,
    request_id: str,
    option_id: str,
    idempotency_key: str | None,
    notes: str | None,
) -> PermissionResult | _AuthorizedPermission:
    """Resolve and authorize a permission response before any state change.

    Runs every read-side guard the state machine imposes - request/thread
    resolution, idempotency dedup, permission-status and terminal checks, the
    active-interrupt guard, and option validation. Returns a
    :class:`PermissionResult` for any rejection, duplicate, or already-applied
    outcome (committing the rejection journal action where the machine records
    one), or an :class:`_AuthorizedPermission` when the response is admitted and
    the transition may proceed.
    """
    # ------------------------------------------------------------------
    # 1. Resolve permission request and thread
    # ------------------------------------------------------------------
    permission = await get_permission_request(db, request_id)
    thread_id = permission.thread_id if permission is not None else ""
    if not thread_id and ":" in request_id:
        thread_id, _ = request_id.split(":", 1)
    if not thread_id:
        return PermissionResult(
            request_id=request_id,
            thread_id="",
            accepted=False,
            applied=False,
            action_status=ControlActionResultStatus.REJECTED_INVALID_STATE.value,
        )

    thread_record = await get_thread(db, thread_id)
    if thread_record is None:
        return PermissionResult(
            request_id=request_id,
            thread_id=thread_id,
            accepted=False,
            applied=False,
            action_status=ControlActionResultStatus.REJECTED_INVALID_STATE.value,
            error_detail="Thread not found",
            error_status_code=404,
        )
    if permission is None:
        return PermissionResult(
            request_id=request_id,
            thread_id=thread_id,
            accepted=False,
            applied=False,
            action_status=ControlActionResultStatus.REJECTED_INVALID_STATE.value,
            error_detail="Permission request is not durably pending",
            error_status_code=409,
        )

    # ------------------------------------------------------------------
    # 1.5. Refuse pauses this route has no authority to answer
    # ------------------------------------------------------------------
    # A verdict-style pause (PLAN_APPROVAL_PAUSE_CAUSES) that is not locally
    # respondable is a document-approval pause: the engine review surface is
    # the sole approval authority for it (the amended a2a-orchestration-edge
    # contract — no second approval authority in A2A). Refusing here, before
    # the idempotency and transition logic runs, means no control action is
    # journalled and no resume value is ever constructed for this call.
    document_refusal = _document_approval_refusal(permission, request_id, thread_id)
    if document_refusal is not None:
        return document_refusal

    # ------------------------------------------------------------------
    # 2. Idempotency deduplication
    # ------------------------------------------------------------------
    resolved_idempotency_key = idempotency_key or default_permission_response_key(
        request_id, option_id
    )
    replay = await _deduplicate_permission_response(
        db,
        permission,
        thread_record,
        PermissionInput(request_id, option_id, idempotency_key, notes),
        resolved_idempotency_key,
    )
    if replay is not None:
        return replay

    return await _authorize_pending_permission(
        db,
        permission,
        thread_record,
        PermissionInput(request_id, option_id, idempotency_key, notes),
        resolved_idempotency_key,
    )


def _active_permission_request_id(
    permission: PermissionRequestModel,
    thread_record: ThreadModel,
    pending_permissions: Sequence[PermissionRequestModel],
    request_id: str,
) -> str | None:
    if permission.pause_reason_type in LOCALLY_RESPONDABLE_PAUSE_CAUSES:
        active_plan_permissions = [
            pending.request_id
            for pending in pending_permissions
            if pending.pause_reason_type in LOCALLY_RESPONDABLE_PAUSE_CAUSES
        ]
        return (
            active_plan_permissions[-1]
            if active_plan_permissions
            else thread_record.approval_request_id or request_id
        )
    if pending_permissions:
        return pending_permissions[-1].request_id
    return None


async def _authorize_pending_permission(
    db: AsyncSession,
    permission: PermissionRequestModel,
    thread_record: ThreadModel,
    response: PermissionInput,
    resolved_idempotency_key: str,
) -> PermissionResult | _AuthorizedPermission:
    request_id = response.request_id
    option_id = response.option_id
    thread_id = thread_record.id
    # ------------------------------------------------------------------
    # 3. Permission status checks
    # ------------------------------------------------------------------
    if permission.request_status == PermissionRequestStatus.APPLIED.value:
        action = await create_control_action(
            db,
            thread_id=thread_id,
            action_type=ControlActionType.PERMISSION_RESPONSE_SUBMITTED,
            request_id=request_id,
            idempotency_key=f"permission-duplicate:{resolved_idempotency_key}",
            payload={"option_id": option_id},
            result_status=ControlActionResultStatus.DUPLICATE,
            recovery_deadline_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        await db.commit()
        return PermissionResult(
            request_id=request_id,
            thread_id=thread_id,
            accepted=True,
            applied=True,
            action_status=ControlActionResultStatus.DUPLICATE.value,
            action_id=action.id,
            idempotency_key=resolved_idempotency_key,
            approval_status=thread_record.approval_status,
        )

    if permission.request_status != PermissionRequestStatus.PENDING.value:
        error_detail, error_status_code = _rejected_permission_error(
            permission_status=permission.request_status,
            thread_terminal=False,
            option_id=option_id,
            valid_option_ids=_allowed_option_ids(permission),
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
        return PermissionResult(
            request_id=request_id,
            thread_id=thread_id,
            accepted=False,
            applied=False,
            action_status=ControlActionResultStatus.REJECTED_INVALID_STATE.value,
            error_detail="thread is no longer active",
            error_status_code=409,
        )

    pending_permissions = await get_pending_permission_requests(db, thread_id=thread_id)
    active_request_id = _active_permission_request_id(
        permission, thread_record, pending_permissions, request_id
    )

    if active_request_id is not None and active_request_id != request_id:
        error_detail, error_status_code = _rejected_permission_error(
            permission_status=PermissionRequestStatus.SUPERSEDED.value,
            thread_terminal=False,
            option_id=option_id,
            valid_option_ids=_allowed_option_ids(permission),
        )
        logger.warning(
            "Permission respond rejected: request %s is not the active "
            "interrupt for thread %s (active=%s)",
            request_id,
            thread_id,
            active_request_id,
            extra={
                "thread_id": thread_id,
                "request_id": request_id,
                "active_request_id": active_request_id,
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
    )


async def _validate_permission_option(
    db: AsyncSession,
    permission: PermissionRequestModel,
    thread_record: ThreadModel,
    response: PermissionInput,
    resolved_idempotency_key: str,
) -> PermissionResult | None:
    request_id = response.request_id
    option_id = response.option_id
    thread_id = thread_record.id
    valid_option_ids = _allowed_option_ids(permission)
    if not valid_option_ids:
        error_detail, error_status_code = _rejected_permission_error(
            permission_status=permission.request_status,
            thread_terminal=False,
            option_id=option_id,
            valid_option_ids=set(),
        )
        logger.warning(
            "Permission respond rejected: request %s has no valid durable options",
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

    if option_id not in valid_option_ids:
        error_detail, error_status_code = _rejected_permission_error(
            permission_status=permission.request_status,
            thread_terminal=False,
            option_id=option_id,
            valid_option_ids=valid_option_ids,
        )
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
    return None


async def _record_permission_transition(
    db: AsyncSession,
    *,
    authorized: _AuthorizedPermission,
    response: PermissionInput,
    recursion_limit: int,
) -> PermissionResult | _PermissionTransition:
    """Write the durable pre-dispatch transition for an authorized response.

    Creates the submitted control action, records the response submission, audits
    the decision, and - for a plan-approval pause - stamps the thread's approval
    state. Returns the action plus the resume value and routing fields the
    dispatch stage carries to the worker.

    The transition is committed here, before any network call, so the decision
    survives a worker that never answers. It is therefore NOT rolled back by a
    failed dispatch: the dispatch stage compensates instead, releasing the claim
    and resetting the response submission so the request can be re-answered. The
    audit row is deliberately left standing by that compensation - a decision the
    operator really made is a fact about the run even when its delivery failed,
    and a re-answer appends a second row rather than rewriting the first.
    """
    context = permission_transition_context(authorized, response)

    team_preset: str | None = context.thread_record.team_preset
    # The stored value is validated, not merely fetched. This is the workspace a
    # resumed run executes in, and the sibling that reads it for dispatch records
    # what a bad one costs: degrading it used to dispatch the turn anyway and let
    # the provider layer site the agent - and its filesystem sandbox - in whatever
    # directory the worker happened to start in. The annotation here said
    # ``str | None`` while the read admitted any JSON value, so a stored number or
    # object flowed through untouched and only failed further downstream, if at
    # all.
    workspace_root = dispatchable_workspace_root(context.thread_record.thread_metadata)
    if workspace_root is None:
        return PermissionResult(
            request_id=context.request_id,
            thread_id=context.thread_id,
            accepted=False,
            applied=False,
            action_status=ControlActionResultStatus.REJECTED_INVALID_STATE.value,
            idempotency_key=context.resolved_idempotency_key,
            approval_status=context.replay_approval_status,
            error_detail="The accepted run's project is unavailable",
            error_status_code=409,
            failure_type=FailureType.NO_ACTIVE_PROJECT,
        )

    try:
        graph_definition = await read_accepted_graph_definition(db, context.thread_id)
        team_preset = graph_definition.team_id
        execution_authority = resolve_execution_authority(
            context.thread_record.thread_metadata
        )
    except (ExecutionAuthorityError, ValueError) as exc:
        return PermissionResult(
            request_id=context.request_id,
            thread_id=context.thread_id,
            accepted=False,
            applied=False,
            action_status=ControlActionResultStatus.REJECTED_INVALID_STATE.value,
            idempotency_key=context.resolved_idempotency_key,
            approval_status=context.replay_approval_status,
            error_detail=str(exc),
            error_status_code=409,
            failure_type=FailureType.INCOMPATIBLE_STATE,
        )

    resume_value = permission_resume_value(
        context.permission.pause_reason_type,
        context.option_id,
        context.notes,
    )

    dispatch = DispatchRequest(
        action=to_dispatch_action(ControlActionType.RESUME),
        thread_id=context.thread_id,
        option_id=resume_value,
        team_preset=team_preset,
        graph_definition=graph_definition,
        workspace_root=workspace_root,
        recursion_limit=recursion_limit,
        model_assignment=execution_authority.model_assignment,
    )

    claim = await prepare_control_action_claim(
        db,
        request=ControlActionClaimRequest(
            write_expectation=context.write_expectation,
            thread_id=context.thread_id,
            action_type=ControlActionType.PERMISSION_RESPONSE_SUBMITTED,
            request_id=context.request_id,
            idempotency_key=permission_response_action_key(context.request_id),
            payload=freeze_accepted_input(
                dispatch, intent=_response_payload(context.option_id, context.notes)
            ),
            dispatch_id=dispatch.dispatch_id,
            recovery_timeout_seconds=graph_definition.run_timeout_seconds,
        ),
    )
    if not claim.authority_matches:
        return PermissionResult(
            request_id=context.request_id,
            thread_id=context.thread_id,
            accepted=False,
            applied=False,
            action_status=ControlActionResultStatus.REJECTED_INVALID_STATE.value,
            idempotency_key=context.resolved_idempotency_key,
            approval_status=context.replay_approval_status,
            error_status_code=409,
            failure_type=FailureType.INCOMPATIBLE_STATE,
            error_detail="Accepted action no longer owns the current run",
        )
    if not claim.payload_matches:
        return PermissionResult(
            request_id=context.request_id,
            thread_id=context.thread_id,
            accepted=False,
            applied=False,
            action_status=ControlActionResultStatus.REJECTED_INVALID_STATE.value,
            idempotency_key=context.resolved_idempotency_key,
            approval_status=context.replay_approval_status,
            error_detail="Permission request already has a different response",
            error_status_code=409,
            failure_type=FailureType.CONFLICT,
        )
    if not claim.acquired:
        return PermissionResult(
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
    # unreachable. No commit here - the durability boundary below owns it.
    await append_permission_log(
        db,
        thread_id=context.thread_id,
        # Unattributed, deliberately. Neither sense of "who" is knowable at this
        # seam: the agent whose tool call was gated is never captured upstream,
        # and the responder carries no authenticated identity. Recording the
        # decision without the actor beats fabricating one.
        agent_id=None,
        tool_name=_audited_tool_name(context.permission),
        action=context.decision_verdict,
        option_id=context.option_id,
    )
    if context.is_locally_respondable:
        await set_thread_approval_state(
            db,
            context.thread_id,
            approval_status=context.submitted_approval_status,
            approval_request_id=context.request_id,
            approval_reason=context.permission_description,
            approval_response_action_id=claim.action_id,
        )
    await mark_permission_response_requested(db, context.thread_id)
    await finalize_control_action_acceptance(db, claim)

    return _PermissionTransition(
        claim=claim,
        dispatch=dispatch.model_copy(update={"dispatch_id": claim.dispatch_id}),
        approval_status=context.submitted_approval_status,
    )


async def _failed_permission_dispatch(
    db: AsyncSession,
    authorized: _AuthorizedPermission,
    transition: _PermissionTransition,
    response: PermissionInput,
    outcome: DispatchOutcome,
) -> PermissionResult:
    request_id = response.request_id
    thread_id = authorized.thread_id
    resolved_idempotency_key = authorized.resolved_idempotency_key
    claim = transition.claim
    policy, typed_failure = evaluate_dispatch_failure(outcome.failure_type)
    if typed_failure is None:
        raise RuntimeError("failed dispatch carries no failure type")
    settlement = await record_dispatch_failure(
        db, claim, typed_failure, detail=outcome.detail
    )
    if settlement is DispatchFailureDisposition.DEFINITE_NON_DELIVERY:
        await reset_permission_response_submission(db, request_id=request_id)
    if policy.should_mark_failed and settlement in {
        DispatchFailureDisposition.DEFINITE_NON_DELIVERY,
        DispatchFailureDisposition.AMBIGUOUS_DELIVERY,
    }:
        await apply_dispatch_failure(
            db,
            thread_id,
            failed_status=ThreadStatus.INPUT_REQUIRED,
            reason=outcome.detail or "Worker dispatch failed",
        )

    error_detail, error_status_code = _permission_dispatch_error(
        outcome,
        is_circuit_open=policy.is_circuit_open,
        should_mark_failed=policy.should_mark_failed,
    )

    await db.commit()
    return PermissionResult(
        request_id=request_id,
        thread_id=thread_id,
        accepted=False,
        applied=False,
        action_status=ControlActionResultStatus.REJECTED_INVALID_STATE.value,
        action_id=claim.action_id,
        idempotency_key=resolved_idempotency_key,
        approval_status=transition.approval_status,
        circuit_open=policy.is_circuit_open,
        error_detail=error_detail,
        error_status_code=error_status_code,
        failure_type=typed_failure,
    )


async def _dispatch_permission_resume(
    db: AsyncSession,
    *,
    authorized: _AuthorizedPermission,
    transition: _PermissionTransition,
    response: PermissionInput,
    runtime: PermissionRuntime,
) -> PermissionResult:
    """Dispatch the resume to the worker and settle the response.

    On dispatch failure the recorded transition is reset and the failure is
    classified into the protocol-facing error and thread state. On success the
    requested projection remains parked until an exact worker application receipt
    resolves the aggregator and moves the thread to running.
    """
    request_id = response.request_id
    option_id = response.option_id
    thread_id = authorized.thread_id
    resolved_idempotency_key = authorized.resolved_idempotency_key
    claim = transition.claim

    dispatch = transition.dispatch

    logger.info(
        "Dispatching resume dispatch_id=%s for thread %s (request_id=%s)",
        dispatch.dispatch_id,
        thread_id,
        request_id,
        extra={
            "thread_id": thread_id,
            "dispatch_id": dispatch.dispatch_id,
            "request_id": request_id,
            "action": dispatch.action,
            "option_id": option_id,
        },
    )

    dispatch = await bind_graph_action_receipt(db, dispatch)
    outcome = await safe_dispatch(
        runtime.worker_client,
        dispatch,
        runtime.circuit_breaker,
        runtime.worker_spawner,
        trace_headers=runtime.trace_headers,
    )

    if not outcome.success:
        return await _failed_permission_dispatch(
            db, authorized, transition, response, outcome
        )

    return PermissionResult(
        request_id=request_id,
        thread_id=thread_id,
        accepted=True,
        applied=False,
        action_status=ControlActionResultStatus.ACCEPTED_NOT_APPLIED.value,
        action_id=claim.action_id,
        idempotency_key=resolved_idempotency_key,
        approval_status=transition.approval_status,
        dispatched=True,
    )

"""Durable leased orchestration for clarification resolutions.

The checkpoint owns whether a questionnaire is parked and whether its resolution
was applied.  The control journal owns the accepted payload, stable dispatch
identity, and renewable dispatcher election.  This service is the only place
that combines those two authorities and constructs a clarification resume.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from inspect import Parameter, Signature
from typing import TYPE_CHECKING, Any, cast, override

from ..database import (
    CheckpointRead,
    ControlActionModel,
    ThreadModel,
    begin_write_transaction,
    get_control_action,
    get_control_action_by_idempotency_key,
    get_thread,
    get_unapplied_control_actions,
    mark_control_action_applied,
    read_latest_checkpoint,
    settle_control_action_lease,
    thread_write_expectation,
)
from ..thread.clarification import (
    ClarificationAnswers,
    ClarificationRequest,
    ClarificationResolution,
    clarification_resolution_fingerprint,
    parse_clarification_resolution,
    pending_clarification,
    validate_clarification_answers,
)
from ..thread.dispatch_policy import FailureType
from ..thread.enums import (
    NON_ACTIVE_STATUSES,
    ControlActionResultStatus,
    ControlActionType,
)
from ..thread.idempotency import (
    CLARIFICATION_RESPONSE_KEY_PREFIX,
    clarification_response_action_key,
)
from .accepted_input import AcceptedActionInput, freeze_accepted_input
from .action_lease import (
    ControlActionClaim,
    ControlActionClaimRequest,
    DispatchFailureDisposition,
    prepare_control_action_claim,
)
from .leased_dispatch import DispatchRefusal, build_followon_dispatch, dispatch_leased
from .pause import project_checkpoint_read, reconcile_run_pause
from .repair_transitions import record_undelivered_dispatch

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from ..database.checkpoints import Checkpointer
    from ..ipc.schemas import DispatchRequest
    from .leased_dispatch import DispatchTransport

__all__ = [
    "ClarificationRuntime",
    "redrive_clarification_actions",
    "respond_to_clarification",
]

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _ClarificationResultIdentity:
    request_id: str
    thread_id: str
    action_id: str | None
    idempotency_key: str | None


@dataclass(frozen=True, slots=True)
class _ClarificationResultOutcome:
    accepted: bool
    applied: bool
    action_status: str
    dispatched: bool
    error_detail: str | None
    error_status_code: int | None
    failure_type: FailureType | None


_CLARIFICATION_RESULT_SIGNATURE = Signature(
    [
        Parameter("request_id", Parameter.POSITIONAL_OR_KEYWORD),
        Parameter("thread_id", Parameter.POSITIONAL_OR_KEYWORD),
        Parameter("accepted", Parameter.POSITIONAL_OR_KEYWORD),
        Parameter("applied", Parameter.POSITIONAL_OR_KEYWORD),
        Parameter("action_status", Parameter.POSITIONAL_OR_KEYWORD),
        Parameter("action_id", Parameter.POSITIONAL_OR_KEYWORD, default=None),
        Parameter("idempotency_key", Parameter.POSITIONAL_OR_KEYWORD, default=None),
        Parameter("dispatched", Parameter.POSITIONAL_OR_KEYWORD, default=False),
        Parameter("error_detail", Parameter.POSITIONAL_OR_KEYWORD, default=None),
        Parameter("error_status_code", Parameter.POSITIONAL_OR_KEYWORD, default=None),
        Parameter("failure_type", Parameter.POSITIONAL_OR_KEYWORD, default=None),
    ]
)
_CLARIFICATION_RESULT_FIELDS = tuple(_CLARIFICATION_RESULT_SIGNATURE.parameters)


def _split_clarification_result_args(
    args: tuple[object, ...], kwargs: dict[str, object]
) -> tuple[_ClarificationResultIdentity, _ClarificationResultOutcome]:
    bound = _CLARIFICATION_RESULT_SIGNATURE.bind(*args, **kwargs)
    bound.apply_defaults()
    values = bound.arguments
    return (
        _ClarificationResultIdentity(
            cast("str", values["request_id"]),
            cast("str", values["thread_id"]),
            cast("str | None", values.get("action_id")),
            cast("str | None", values.get("idempotency_key")),
        ),
        _ClarificationResultOutcome(
            cast("bool", values["accepted"]),
            cast("bool", values["applied"]),
            cast("str", values["action_status"]),
            cast("bool", values.get("dispatched", False)),
            cast("str | None", values.get("error_detail")),
            cast("int | None", values.get("error_status_code")),
            cast("FailureType | None", values.get("failure_type")),
        ),
    )


@dataclass(frozen=True, slots=True, init=False, repr=False)
class ClarificationResult:
    """Protocol-neutral outcome of resolving one questionnaire."""

    _identity: _ClarificationResultIdentity
    _outcome: _ClarificationResultOutcome
    __signature__ = _CLARIFICATION_RESULT_SIGNATURE
    __match_args__ = _CLARIFICATION_RESULT_FIELDS

    def __init__(self, *args: object, **kwargs: object) -> None:
        identity, outcome = _split_clarification_result_args(args, kwargs)
        object.__setattr__(self, "_identity", identity)
        object.__setattr__(self, "_outcome", outcome)

    @property
    def request_id(self) -> str:
        return self._identity.request_id

    @property
    def thread_id(self) -> str:
        return self._identity.thread_id

    @property
    def accepted(self) -> bool:
        return self._outcome.accepted

    @property
    def applied(self) -> bool:
        return self._outcome.applied

    @property
    def action_status(self) -> str:
        return self._outcome.action_status

    @property
    def action_id(self) -> str | None:
        return self._identity.action_id

    @property
    def idempotency_key(self) -> str | None:
        return self._identity.idempotency_key

    @property
    def dispatched(self) -> bool:
        return self._outcome.dispatched

    @property
    def error_detail(self) -> str | None:
        return self._outcome.error_detail

    @property
    def error_status_code(self) -> int | None:
        return self._outcome.error_status_code

    @property
    def failure_type(self) -> FailureType | None:
        return self._outcome.failure_type

    @override
    def __repr__(self) -> str:
        values = ", ".join(
            f"{name}={getattr(self, name)!r}" for name in _CLARIFICATION_RESULT_FIELDS
        )
        return f"ClarificationResult({values})"


@dataclass(frozen=True, slots=True)
class ClarificationRecoverySummary:
    """Counts from one restart recovery pass over clarification actions."""

    examined: int = 0
    applied: int = 0
    dispatched: int = 0
    deferred: int = 0
    conflicted: int = 0


@dataclass(frozen=True, slots=True)
class ClarificationRuntime:
    checkpointer: Checkpointer
    transport: DispatchTransport


@dataclass(frozen=True, slots=True)
class _DispatchContext:
    runtime: ClarificationRuntime
    fingerprint: str
    thread_id: str


@dataclass(frozen=True, slots=True)
class _ClaimContext:
    runtime: ClarificationRuntime
    fingerprint: str
    payload: dict[str, Any]
    idempotency_key: str
    thread_id: str
    request_id: str
    parked_matches: bool


@dataclass(frozen=True, slots=True)
class _ResultError:
    detail: str
    # Named only by a guard about this request; a dispatch outcome carries its
    # typed failure alone and the protocol mapping chooses its status.
    status_code: int | None = None
    failure_type: FailureType | None = None


def _checkpoint_receipt(checkpoint: CheckpointRead, request_id: str) -> str | None:
    """Read one application receipt from checkpoint channel values."""
    receipts = checkpoint.channel_values.get("clarification_resolution_receipts")
    if not isinstance(receipts, dict):
        return None
    fingerprint = cast("dict[str, object]", receipts).get(request_id)
    return fingerprint if isinstance(fingerprint, str) else None


def _stored_resolution(
    action: ControlActionModel,
) -> ClarificationResolution | None:
    if not action.payload_json or action.request_id is None:
        return None
    try:
        accepted = AcceptedActionInput.model_validate_json(action.payload_json)
        return parse_clarification_resolution(
            accepted.intent, request_id=action.request_id
        )
    except (json.JSONDecodeError, ValueError):
        return None


async def _settle_from_receipt(
    db: AsyncSession,
    action: ControlActionModel,
    *,
    fingerprint: str,
    checkpoint: CheckpointRead,
) -> bool:
    """Settle only when checkpoint truth carries this request and fingerprint."""
    if _checkpoint_receipt(checkpoint, action.request_id or "") != fingerprint:
        return False
    if action.applied_at is not None:
        return True
    settled = False
    if action.claim_token:
        settled = await settle_control_action_lease(
            db,
            action.id,
            claim_token=action.claim_token,
        )
    else:
        settled = await mark_control_action_applied(db, action.id) is not None
    if settled:
        await db.commit()
    return settled


def _result(
    action: ControlActionModel,
    *,
    accepted: bool = True,
    applied: bool | None = None,
    dispatched: bool = False,
    error: _ResultError | None = None,
) -> ClarificationResult:
    return ClarificationResult(
        request_id=action.request_id or "",
        thread_id=action.thread_id,
        accepted=accepted,
        applied=action.applied_at is not None if applied is None else applied,
        action_status=action.result_status,
        action_id=action.id,
        idempotency_key=action.idempotency_key,
        dispatched=dispatched,
        error_detail=error.detail if error else None,
        error_status_code=error.status_code if error else None,
        failure_type=error.failure_type if error else None,
    )


async def _replay_existing_action(
    db: AsyncSession,
    existing: ControlActionModel,
    fingerprint: str,
    checkpoint: CheckpointRead,
    parked_matches: bool,
) -> ClarificationResult | None:
    stored = _stored_resolution(existing)
    if stored is None or clarification_resolution_fingerprint(stored) != fingerprint:
        return _result(
            existing,
            accepted=False,
            error=_ResultError(
                "A different clarification resolution is already accepted", 409
            ),
        )
    if await _settle_from_receipt(
        db,
        existing,
        fingerprint=fingerprint,
        checkpoint=checkpoint,
    ):
        await db.refresh(existing)
        return _result(existing, applied=True)
    if existing.applied_at is not None:
        return _result(existing, applied=True)
    if not parked_matches:
        # The exact resolution already owns this durable idempotency key.
        # A fast worker may have consumed the interrupt before its receipt
        # becomes visible; replay returns that accepted action rather than
        # pretending the now-absent questionnaire invalidates the write.
        return _result(existing)
    return None


def _invalid_parked_answers(
    parked: ClarificationRequest | None,
    resolution: ClarificationResolution,
    thread_id: str,
    request_id: str,
) -> ClarificationResult | None:
    if (
        parked is None
        or parked.request_id != request_id
        or not isinstance(resolution, ClarificationAnswers)
    ):
        return None
    violations = validate_clarification_answers(parked, resolution.answers)
    if not violations:
        return None
    return ClarificationResult(
        request_id=request_id,
        thread_id=thread_id,
        accepted=False,
        applied=False,
        action_status=ControlActionResultStatus.REJECTED_INVALID_STATE.value,
        error_detail="; ".join(violations),
        error_status_code=422,
    )


def _run_not_found(request_id: str, thread_id: str) -> ClarificationResult:
    return ClarificationResult(
        request_id=request_id,
        thread_id=thread_id,
        accepted=False,
        applied=False,
        action_status=ControlActionResultStatus.REJECTED_INVALID_STATE.value,
        error_detail="Run not found",
        error_status_code=404,
    )


async def respond_to_clarification(
    db: AsyncSession,
    *,
    thread_id: str,
    request_id: str,
    resolution: ClarificationResolution,
    runtime: ClarificationRuntime,
) -> ClarificationResult:
    """Reserve, lease, and dispatch one typed clarification resolution.

    The service owns its transaction boundary.  A fresh competing dispatcher
    replays the durable outcome without dispatch; an expired lease is acquired by
    one redriver.  Worker success is not application proof: only the request-scoped
    checkpoint receipt settles the journal row.
    """
    checkpointer = runtime.checkpointer
    # An unknown run is refused before the checkpoint round trip below.
    known = await get_thread(db, thread_id) is not None
    await db.rollback()
    if not known:
        return _run_not_found(request_id, thread_id)
    # The checkpoint read is remote I/O, so it happens before the durable
    # transaction opens: holding the write lock across it would block every
    # other writer for the length of a checkpoint round trip.
    checkpoint = await read_latest_checkpoint(checkpointer, thread_id)
    # A checkpoint that cannot be projected reads as no pending clarification,
    # as an absent one does, so the answer path refuses rather than failing.
    parked = pending_clarification(project_checkpoint_read(checkpoint, thread_id))
    attempt = _ClarificationAttempt(
        thread_id=thread_id,
        request_id=request_id,
        resolution=resolution,
        runtime=runtime,
        checkpoint=checkpoint,
        parked=parked,
    )

    await begin_write_transaction(db)
    try:
        return await _respond_under_write_lock(db, attempt)
    finally:
        # The service owns its boundary and no caller commits after it, so a
        # transaction still open here holds nothing worth keeping: release the
        # write lock now rather than when the session closes.
        if db.in_transaction():
            await db.rollback()


@dataclass(frozen=True, slots=True)
class _ClarificationAttempt:
    """One response, with the checkpoint facts read before the write lock."""

    thread_id: str
    request_id: str
    resolution: ClarificationResolution
    runtime: ClarificationRuntime
    checkpoint: CheckpointRead
    parked: ClarificationRequest | None

    @property
    def is_parked(self) -> bool:
        """Whether the run is parked on exactly this request."""
        return self.parked is not None and self.parked.request_id == self.request_id


async def _respond_under_write_lock(
    db: AsyncSession, attempt: _ClarificationAttempt
) -> ClarificationResult:
    thread = await get_thread(db, attempt.thread_id)
    if thread is None:
        return _run_not_found(attempt.request_id, attempt.thread_id)

    fingerprint = clarification_resolution_fingerprint(attempt.resolution)
    idempotency_key = clarification_response_action_key(attempt.request_id)
    existing = await get_control_action_by_idempotency_key(
        db,
        thread_id=attempt.thread_id,
        idempotency_key=idempotency_key,
    )
    if existing is None and not attempt.is_parked:
        return ClarificationResult(
            request_id=attempt.request_id,
            thread_id=attempt.thread_id,
            accepted=False,
            applied=False,
            action_status=ControlActionResultStatus.REJECTED_INVALID_STATE.value,
            error_detail="Clarification request is not pending for this run",
            error_status_code=404,
        )

    invalid_answers = _invalid_parked_answers(
        attempt.parked, attempt.resolution, attempt.thread_id, attempt.request_id
    )
    if invalid_answers is not None:
        return invalid_answers

    if existing is not None:
        replay = await _replay_existing_action(
            db,
            existing,
            fingerprint,
            attempt.checkpoint,
            attempt.is_parked,
        )
        if replay is not None:
            return replay

    return await _claim_and_dispatch(
        db,
        thread,
        _ClaimContext(
            attempt.runtime,
            fingerprint,
            attempt.resolution.as_resume_value(),
            idempotency_key,
            attempt.thread_id,
            attempt.request_id,
            attempt.is_parked,
        ),
    )


async def _claim_and_dispatch(
    db: AsyncSession, thread: ThreadModel, context: _ClaimContext
) -> ClarificationResult:
    # ``prepare_control_action_claim`` rolls back the caller's session when this request
    # loses a concurrent insert.  SQLAlchemy expires every loaded ORM instance
    # on that rollback, so all thread fields needed after the election must be
    # copied first; reading an expired attribute here would attempt implicit
    # async I/O and raise MissingGreenlet.
    thread_status = thread.status
    write_expectation = thread_write_expectation(thread)
    worker_generation = thread.repair_generation
    dispatch = await build_followon_dispatch(
        db,
        thread_id=context.thread_id,
        thread_metadata=thread.thread_metadata,
        action=ControlActionType.RESUME,
        option_id=context.payload,
    )
    if isinstance(dispatch, DispatchRefusal):
        # Nothing was claimed, so the refusal carries its typed failure alone
        # and the one protocol mapping serves it, as it does for every verb.
        return ClarificationResult(
            request_id=context.request_id,
            thread_id=context.thread_id,
            accepted=False,
            applied=False,
            action_status=ControlActionResultStatus.REJECTED_INVALID_STATE.value,
            error_detail=dispatch.reason,
            failure_type=dispatch.failure_type,
        )

    claim = await prepare_control_action_claim(
        db,
        request=ControlActionClaimRequest(
            write_expectation=write_expectation,
            thread_id=context.thread_id,
            action_type=ControlActionType.RESUME,
            idempotency_key=context.idempotency_key,
            request_id=context.request_id,
            payload=freeze_accepted_input(dispatch, intent=context.payload),
            dispatch_id=dispatch.dispatch_id,
            worker_generation=worker_generation,
            recovery_timeout_seconds=(
                dispatch.require_graph_definition().run_timeout_seconds
            ),
        ),
    )
    if not claim.authority_matches:
        return ClarificationResult(
            request_id=context.request_id,
            thread_id=context.thread_id,
            accepted=False,
            applied=False,
            action_status=ControlActionResultStatus.REJECTED_INVALID_STATE.value,
            error_status_code=409,
            failure_type=FailureType.INCOMPATIBLE_STATE,
            error_detail="Accepted action no longer owns the current run",
        )
    action = await get_control_action(db, claim.action_id, refresh=True)
    if action is None:
        raise RuntimeError("claimed clarification action disappeared")
    result = await _claimed_action_result(db, action, claim, context, thread_status)
    if result is not None:
        return result

    return await _dispatch_claimed(
        db,
        action,
        claim,
        dispatch,
        _DispatchContext(context.runtime, context.fingerprint, context.thread_id),
    )


async def _claimed_action_result(
    db: AsyncSession,
    action: ControlActionModel,
    claim: ControlActionClaim,
    context: _ClaimContext,
    thread_status: str,
) -> ClarificationResult | None:
    if not claim.payload_matches:
        return _result(
            action,
            accepted=False,
            error=_ResultError(
                "A different clarification resolution is already accepted", 409
            ),
        )

    if claim.applied or action.applied_at is not None:
        return _result(action, applied=True)

    if not context.parked_matches:
        result = _result(
            action,
            accepted=False,
            error=_ResultError("Clarification application cannot be confirmed", 409),
        )
        await db.rollback()
        return result
    if thread_status in NON_ACTIVE_STATUSES:
        result = _result(
            action,
            accepted=False,
            error=_ResultError("Run is not active", 409),
        )
        await db.rollback()
        return result

    if not claim.acquired:
        return _result(action)

    return None


async def _dispatch_claimed(
    db: AsyncSession,
    action: ControlActionModel,
    claim: ControlActionClaim,
    dispatch: DispatchRequest,
    context: _DispatchContext,
) -> ClarificationResult:
    failure = await dispatch_leased(db, claim, dispatch, context.runtime.transport)
    if failure is not None:
        if failure.disposition is DispatchFailureDisposition.DEFINITE_NON_DELIVERY:
            # A released claim means the worker certainly scheduled no task, so
            # the answer demonstrably did not reach the parked node. The run is
            # untouched by that - it is still parked on the same questionnaire,
            # still alive, and still answerable - so the account goes on the
            # repair reason and never on the failure columns, which describe a
            # run that failed. An ambiguous failure keeps its lease because
            # delivery is undecided, and says nothing.
            await record_undelivered_dispatch(
                db,
                context.thread_id,
                reason=f"Clarification resume not delivered: {failure.detail}",
            )
        await db.commit()
        # No status is chosen here. A dispatch outcome carries its typed failure
        # and nothing else, so the one protocol mapping decides what every verb
        # that met the same outcome serves for it.
        return _result(
            action,
            error=_ResultError(failure.detail, failure_type=failure.failure_type),
        )

    # A very fast worker may already have checkpointed the receipt before its HTTP
    # acknowledgement reaches us. Settle opportunistically, but never infer
    # application merely from the acknowledgement.
    latest_checkpoint = await read_latest_checkpoint(
        context.runtime.checkpointer, context.thread_id
    )
    applied = await _settle_from_receipt(
        db,
        action,
        fingerprint=context.fingerprint,
        checkpoint=latest_checkpoint,
    )
    if applied:
        await db.refresh(action)
    return _result(action, applied=applied, dispatched=True)


async def redrive_clarification_actions(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    runtime: ClarificationRuntime,
) -> ClarificationRecoverySummary:
    """Settle receipted actions and redrive expired parked leases after restart."""
    async with session_factory() as db:
        rows = await get_unapplied_control_actions(
            db, idempotency_key_prefix=CLARIFICATION_RESPONSE_KEY_PREFIX
        )

    applied = dispatched = deferred = conflicted = 0
    for row in rows:
        resolution = _stored_resolution(row)
        if resolution is None or row.request_id is None:
            conflicted += 1
            continue
        async with session_factory() as db:
            result = await respond_to_clarification(
                db,
                thread_id=row.thread_id,
                request_id=row.request_id,
                resolution=resolution,
                runtime=runtime,
            )
            # The receipt that would have resumed the status may have been lost
            # with the previous process, so restart re-projects the pause too.
            await reconcile_run_pause(
                db, thread_id=row.thread_id, checkpointer=runtime.checkpointer
            )
        if result.applied:
            applied += 1
        elif result.dispatched:
            dispatched += 1
        elif result.error_status_code is not None or result.failure_type is not None:
            conflicted += 1
        else:
            deferred += 1
    summary = ClarificationRecoverySummary(
        examined=len(rows),
        applied=applied,
        dispatched=dispatched,
        deferred=deferred,
        conflicted=conflicted,
    )
    logger.info("Clarification recovery pass complete: %s", summary)
    return summary

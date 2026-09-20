"""Startup redelivery for durable direct control-action leases."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import select

from ..database import (
    ControlActionModel,
    ThreadModel,
    ThreadStatusElectionOutcome,
    elect_thread_status,
    get_control_action_by_dispatch_id,
    get_thread,
    mark_control_action_applied,
    release_control_action_lease,
    set_thread_repair_state,
    successor_thread_write_authority,
    thread_write_expectation,
)
from ..thread.dispatch_policy import FailureType, evaluate_dispatch_failure
from ..thread.enums import (
    NON_ACTIVE_STATUSES,
    ControlActionResultStatus,
    ControlActionType,
    RecoveryCondition,
    RepairStatus,
    ThreadStatus,
)
from .accepted_input import (
    AcceptedActionInput,
    ActorCredentialsRequiredError,
    restore_accepted_dispatch,
)
from .action_lease import (
    CONTROL_ACTION_LEASE_TTL,
    ControlActionClaim,
    ControlActionClaimRequest,
    finalize_control_action_acceptance,
    prepare_control_action_claim,
)
from .dispatch import DispatchOutcome, safe_dispatch
from .dispatch_receipts import bind_graph_action_receipt
from .recovery import (
    RecoveryAttemptClaim,
    acquire_due_recovery_attempts,
    record_recovery_deadline,
    release_recovery_attempt,
    reschedule_recovery_attempt,
    seed_recovery_attempts,
    settle_recovery_attempt,
)

if TYPE_CHECKING:
    import httpx
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from ..database.models import RunWriteAuthority
    from ..ipc.schemas import DispatchRequest
    from .circuit_breaker import WorkerCircuitBreaker
    from .worker_management import LazyWorkerSpawner

__all__ = ["DirectControlRecoverySummary", "redrive_direct_control_actions"]

logger = logging.getLogger(__name__)
_JSON_OBJECT = TypeAdapter(dict[str, object])
_RECOVERABLE_TYPES = frozenset(
    {
        ControlActionType.INGEST.value,
        ControlActionType.RESUME.value,
        ControlActionType.PERMISSION_RESPONSE_SUBMITTED.value,
        ControlActionType.MESSAGE_FOLLOWUP_REQUESTED.value,
        ControlActionType.CANCEL.value,
    }
)
_RECOVERY_PAGE_SIZE = 64
_RECOVERY_CLAIM_TTL = timedelta(seconds=45)


class _RecoveryOutcome(StrEnum):
    DISPATCHED = "dispatched"
    DEFERRED = "deferred"
    CONFLICTED = "conflicted"
    REFUSED = "refused"
    APPLIED = "applied"


@dataclass(frozen=True, slots=True)
class _RecoveryRuntime:
    worker_client: httpx.AsyncClient
    circuit_breaker: WorkerCircuitBreaker
    worker_spawner: LazyWorkerSpawner
    trace_headers: dict[str, str] | None


@dataclass(frozen=True, slots=True)
class _PreparedRecovery:
    action: _StoredAction
    claim: ControlActionClaim
    claim_started: datetime


def _retry_delay(attempt_count: int) -> timedelta:
    return timedelta(seconds=min(2 ** min(attempt_count, 6), 60))


async def _expire_overdue_actions(
    db: AsyncSession,
    *,
    observed_at: datetime,
) -> int:
    rows = (
        await db.execute(
            select(ControlActionModel, ThreadModel)
            .join(ThreadModel, ThreadModel.id == ControlActionModel.thread_id)
            .where(
                ControlActionModel.action_type.in_(_RECOVERABLE_TYPES),
                ControlActionModel.applied_at.is_(None),
                ControlActionModel.recovery_deadline_at.is_not(None),
                ControlActionModel.recovery_deadline_at <= observed_at,
                ThreadModel.is_active.is_(True),
                ThreadModel.writer_action_type == ControlActionModel.action_type,
                ThreadModel.writer_action_receipt_id == ControlActionModel.dispatch_id,
            )
            .order_by(ControlActionModel.recovery_deadline_at)
            .limit(_RECOVERY_PAGE_SIZE)
        )
    ).all()
    expired = 0
    for row, _thread in rows:
        if row.dispatch_id is None or row.recovery_deadline_at is None:
            continue
        stored = _StoredAction(
            identity=_StoredActionIdentity(
                dispatch_id=row.dispatch_id,
                request_id=row.request_id,
                idempotency_key=row.idempotency_key,
            ),
            thread_id=row.thread_id,
            action_type=row.action_type,
            payload=_decode_payload(row.payload_json) or {},
            worker_generation=row.worker_generation,
            recovery_deadline_at=row.recovery_deadline_at,
        )
        refusal = _Refusal(
            FailureType.DEADLINE_EXCEEDED,
            "accepted run deadline expired before application",
        )
        if not await _settle_permanent_refusal(
            db,
            stored,
            refusal,
            deadline_observed_at=observed_at,
        ):
            await db.rollback()
            continue
        expired += 1
    await db.commit()
    return expired


@dataclass(frozen=True, slots=True)
class DirectControlRecoverySummary:
    examined: int
    dispatched: int
    deferred: int
    conflicted: int
    #: Actions this pass declined to reconstruct at all, each for a typed
    #: reason. Separate from ``conflicted`` (a competing payload under the same
    #: idempotency key) because nothing about a refusal is a race: the stored
    #: action simply cannot become a dispatch, and counting the two together hid
    #: which one a restart had actually met.
    refused: int = 0


@dataclass(frozen=True, slots=True)
class _Refusal:
    """A stored action that must not be dispatched, and the typed reason why.

    Recovery reconstructs a dispatch from durable rows, so every way that can
    fail is a property of what was stored - never a transport outcome. Returning
    this instead of a bare ``None`` keeps the reason typed at the point it is
    known, which is what lets an absent active project be reported as itself
    rather than folded into a generic rejection at the provider seam.
    """

    failure_type: FailureType
    reason: str


@dataclass(frozen=True, slots=True)
class _StoredActionIdentity:
    dispatch_id: str
    request_id: str | None
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class _StoredAction:
    identity: _StoredActionIdentity
    thread_id: str
    action_type: str
    payload: dict[str, object]
    worker_generation: int
    recovery_deadline_at: datetime


def _decode_payload(encoded: str | None) -> dict[str, object] | None:
    if encoded is None:
        return None
    try:
        return _JSON_OBJECT.validate_json(encoded)
    except ValidationError:
        return None


async def _reconstruct_dispatch(
    db: AsyncSession,
    action: _StoredAction,
    *,
    dispatch_id: str,
) -> DispatchRequest | _Refusal:
    thread = await get_thread(db, action.thread_id)
    if thread is None:
        return _Refusal(FailureType.NOT_FOUND, "the accepted run no longer exists")
    try:
        accepted = AcceptedActionInput.model_validate(action.payload)
        dispatch = restore_accepted_dispatch(accepted, dispatch_id=dispatch_id)
    except ActorCredentialsRequiredError as exc:
        return _Refusal(FailureType.CREDENTIALS_REQUIRED, str(exc))
    except ValueError as exc:
        return _Refusal(FailureType.INCOMPATIBLE_STATE, str(exc))
    expected_action = {
        ControlActionType.INGEST.value: "ingest",
        ControlActionType.MESSAGE_FOLLOWUP_REQUESTED.value: "ingest",
        ControlActionType.RESUME.value: "resume",
        ControlActionType.PERMISSION_RESPONSE_SUBMITTED.value: "resume",
        ControlActionType.CANCEL.value: "cancel",
    }.get(action.action_type)
    if dispatch.thread_id != action.thread_id or dispatch.action != expected_action:
        return _Refusal(
            FailureType.INCOMPATIBLE_STATE, "accepted input identity mismatch"
        )
    if dispatch.action != "cancel" and (
        dispatch.workspace_root is None or not Path(dispatch.workspace_root).is_dir()
    ):
        return _Refusal(
            FailureType.NO_ACTIVE_PROJECT, "accepted project is unavailable"
        )
    return dispatch


async def _restore_requested_state(
    db: AsyncSession,
    action: _StoredAction,
    *,
    action_receipt_id: str,
) -> bool:
    thread = await get_thread(db, action.thread_id)
    if thread is None:
        return False
    expectation = thread_write_expectation(thread)
    action_type = ControlActionType(action.action_type)
    if action_type is ControlActionType.MESSAGE_FOLLOWUP_REQUESTED:
        target = ThreadStatus.RUNNING
    elif action_type is ControlActionType.CANCEL:
        target = ThreadStatus.CANCELLING
    else:
        target = expectation.status
    return (
        target is expectation.status
        and action_type is expectation.authority.action_type
        and action_receipt_id == expectation.authority.action_receipt_id
    )


async def _settle_permanent_refusal(
    db: AsyncSession,
    action: _StoredAction,
    refusal: _Refusal,
    *,
    deadline_observed_at: datetime | None = None,
) -> bool:
    """Quarantine one impossible accepted action under exact current authority."""
    thread = await db.scalar(
        select(ThreadModel)
        .where(ThreadModel.id == action.thread_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    row = await db.scalar(
        select(ControlActionModel)
        .where(
            ControlActionModel.thread_id == action.thread_id,
            ControlActionModel.dispatch_id == action.identity.dispatch_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        thread is None
        or row is None
        or row.applied_at is not None
        or ThreadStatus(thread.status) in NON_ACTIVE_STATUSES
    ):
        return False
    expectation = thread_write_expectation(thread)
    action_type = ControlActionType(action.action_type)
    if (
        expectation.authority.action_type is not action_type
        or expectation.authority.action_receipt_id != action.identity.dispatch_id
    ):
        return False
    if deadline_observed_at is not None:
        await record_recovery_deadline(
            db,
            thread_id=action.thread_id,
            authority=expectation.authority,
            observed_at=deadline_observed_at,
            deadline_at=action.recovery_deadline_at,
        )
    if expectation.status is not ThreadStatus.RECONCILING:
        election = await elect_thread_status(
            db,
            action.thread_id,
            expectation=expectation,
            status=ThreadStatus.RECONCILING,
            successor=successor_thread_write_authority(
                expectation,
                action_type=action_type,
                action_receipt_id=action.identity.dispatch_id,
            ),
        )
        if election.outcome is not ThreadStatusElectionOutcome.WON:
            return False
    await mark_control_action_applied(
        db,
        row.id,
        result_status=ControlActionResultStatus.REJECTED_INVALID_STATE,
    )
    await set_thread_repair_state(
        db,
        action.thread_id,
        repair_status=RepairStatus.OPERATOR_INTERVENTION_REQUIRED,
        repair_reason=f"{refusal.failure_type.value}: {refusal.reason}",
        execution_readiness=RepairStatus.OPERATOR_INTERVENTION_REQUIRED.value,
    )
    return True


async def _settle_orphaned_refusal(
    db: AsyncSession,
    *,
    thread_id: str,
    authority: RunWriteAuthority,
    refusal: _Refusal,
) -> bool:
    """Quarantine exact authority whose accepted action row disappeared."""
    thread = await db.scalar(
        select(ThreadModel)
        .where(ThreadModel.id == thread_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if thread is None or ThreadStatus(thread.status) in NON_ACTIVE_STATUSES:
        return False
    expectation = thread_write_expectation(thread)
    if expectation.authority != authority:
        return False
    if expectation.status is not ThreadStatus.RECONCILING:
        election = await elect_thread_status(
            db,
            thread_id,
            expectation=expectation,
            status=ThreadStatus.RECONCILING,
            successor=successor_thread_write_authority(
                expectation,
                action_type=authority.action_type,
                action_receipt_id=authority.action_receipt_id,
            ),
        )
        if election.outcome not in {
            ThreadStatusElectionOutcome.WON,
            ThreadStatusElectionOutcome.RECEIPT_MISMATCH,
        }:
            return False
    await set_thread_repair_state(
        db,
        thread_id,
        repair_status=RepairStatus.OPERATOR_INTERVENTION_REQUIRED,
        repair_reason=f"{refusal.failure_type.value}: {refusal.reason}",
        execution_readiness=RepairStatus.OPERATOR_INTERVENTION_REQUIRED.value,
    )
    return True


async def _settle_action_refusal(
    db: AsyncSession,
    recovery_claim: RecoveryAttemptClaim,
    action: _StoredAction,
    refusal: _Refusal,
    condition: RecoveryCondition,
) -> _RecoveryOutcome:
    if await _settle_permanent_refusal(db, action, refusal):
        await settle_recovery_attempt(
            db,
            recovery_claim,
            settled_at=datetime.now(UTC),
            condition=condition,
            detail=refusal.reason,
        )
        await db.commit()
        return _RecoveryOutcome.REFUSED
    await db.rollback()
    return _RecoveryOutcome.CONFLICTED


async def _settle_missing_action(
    db: AsyncSession,
    recovery_claim: RecoveryAttemptClaim,
    row: ControlActionModel | None,
    payload: dict[str, object] | None,
) -> _RecoveryOutcome:
    refusal = _Refusal(
        FailureType.INCOMPATIBLE_STATE,
        "accepted recovery input is absent or inconsistent",
    )
    if (
        row is not None
        and row.action_type == recovery_claim.authority.action_type.value
    ):
        quarantined = await _settle_permanent_refusal(
            db,
            _StoredAction(
                identity=_StoredActionIdentity(
                    dispatch_id=recovery_claim.authority.action_receipt_id,
                    request_id=row.request_id,
                    idempotency_key=row.idempotency_key,
                ),
                thread_id=recovery_claim.thread_id,
                action_type=recovery_claim.authority.action_type.value,
                payload=payload or {},
                worker_generation=row.worker_generation,
                recovery_deadline_at=recovery_claim.deadline_at,
            ),
            refusal,
        )
    else:
        quarantined = await _settle_orphaned_refusal(
            db,
            thread_id=recovery_claim.thread_id,
            authority=recovery_claim.authority,
            refusal=refusal,
        )
    if quarantined:
        await settle_recovery_attempt(
            db,
            recovery_claim,
            settled_at=datetime.now(UTC),
            condition=RecoveryCondition.INCOMPATIBLE_STATE,
            detail=refusal.reason,
        )
        await db.commit()
        return _RecoveryOutcome.REFUSED
    await db.rollback()
    return _RecoveryOutcome.CONFLICTED


async def _settle_delivery_failure(
    db: AsyncSession,
    recovery_claim: RecoveryAttemptClaim,
    prepared: _PreparedRecovery,
    outcome: DispatchOutcome,
) -> _RecoveryOutcome:
    action = prepared.action
    claim = prepared.claim
    _policy, failure_type = evaluate_dispatch_failure(outcome.failure_type)
    if failure_type is None:
        raise RuntimeError("failed dispatch carries no failure type")
    if failure_type is FailureType.INCOMPATIBLE_STATE:
        refusal = _Refusal(
            failure_type,
            outcome.detail or "worker refused dispatch authority",
        )
        return await _settle_action_refusal(
            db,
            recovery_claim,
            action,
            refusal,
            RecoveryCondition.INCOMPATIBLE_STATE,
        )
    if claim.claim_token is None:
        raise RuntimeError("recovery dispatch lost its action claim")
    if failure_type in {
        FailureType.CIRCUIT_OPEN,
        FailureType.AT_CAPACITY,
        FailureType.REJECTED,
    }:
        await release_control_action_lease(
            db,
            claim.action_id,
            claim_token=claim.claim_token,
        )
    failure_observed_at = datetime.now(UTC)
    if failure_observed_at >= recovery_claim.deadline_at:
        await release_recovery_attempt(
            db, recovery_claim, released_at=failure_observed_at
        )
        await db.commit()
        return _RecoveryOutcome.DEFERRED
    retry_at = failure_observed_at + _retry_delay(recovery_claim.attempt_count)
    retry_at = min(retry_at, recovery_claim.deadline_at)
    await reschedule_recovery_attempt(
        db,
        recovery_claim,
        condition=RecoveryCondition(failure_type.value),
        observed_at=failure_observed_at,
        next_eligible_at=retry_at,
        detail=outcome.detail,
    )
    await db.commit()
    return _RecoveryOutcome.DEFERRED


async def _dispatch_prepared_claim(
    db: AsyncSession,
    recovery_claim: RecoveryAttemptClaim,
    prepared: _PreparedRecovery,
    runtime: _RecoveryRuntime,
) -> _RecoveryOutcome:
    action = prepared.action
    claim = prepared.claim
    claim_started = prepared.claim_started
    dispatch = await _reconstruct_dispatch(
        db,
        action,
        dispatch_id=claim.dispatch_id,
    )
    if isinstance(dispatch, _Refusal):
        # Refusal aborts this prepared acceptance. The durable retry
        # coordinator owns classification and later scheduling.
        logger.warning(
            "Direct control recovery refused %s on thread %s (%s): %s",
            action.action_type,
            action.thread_id,
            dispatch.failure_type.value,
            dispatch.reason,
            extra={
                "thread_id": action.thread_id,
                "action": action.action_type,
                "failure_type": dispatch.failure_type.value,
            },
        )
        return await _settle_action_refusal(
            db,
            recovery_claim,
            action,
            dispatch,
            RecoveryCondition(dispatch.failure_type.value),
        )
    owns_projection = await _restore_requested_state(
        db,
        action,
        action_receipt_id=claim.dispatch_id,
    )
    if not owns_projection:
        await settle_recovery_attempt(db, recovery_claim, settled_at=datetime.now(UTC))
        await db.commit()
        return _RecoveryOutcome.CONFLICTED
    await finalize_control_action_acceptance(db, claim)
    dispatch = await bind_graph_action_receipt(db, dispatch)
    outcome = await safe_dispatch(
        runtime.worker_client,
        dispatch,
        runtime.circuit_breaker,
        runtime.worker_spawner,
        trace_headers=runtime.trace_headers,
    )
    if not outcome.success:
        return await _settle_delivery_failure(db, recovery_claim, prepared, outcome)
    delivered_at = datetime.now(UTC)
    if delivered_at >= recovery_claim.deadline_at:
        await release_recovery_attempt(db, recovery_claim, released_at=delivered_at)
        await db.commit()
        return _RecoveryOutcome.DISPATCHED
    await reschedule_recovery_attempt(
        db,
        recovery_claim,
        condition=RecoveryCondition.DISPATCH_PENDING,
        observed_at=delivered_at,
        next_eligible_at=min(
            max(
                delivered_at,
                claim_started + CONTROL_ACTION_LEASE_TTL,
            ),
            recovery_claim.deadline_at,
        ),
        detail="worker accepted dispatch; application receipt pending",
    )
    await db.commit()
    return _RecoveryOutcome.DISPATCHED


async def _prepare_recovery_action(
    db: AsyncSession,
    recovery_claim: RecoveryAttemptClaim,
    row: ControlActionModel,
    payload: dict[str, object],
) -> _PreparedRecovery | _RecoveryOutcome:
    action = _StoredAction(
        identity=_StoredActionIdentity(
            dispatch_id=recovery_claim.authority.action_receipt_id,
            request_id=row.request_id,
            idempotency_key=row.idempotency_key,
        ),
        thread_id=recovery_claim.thread_id,
        action_type=recovery_claim.authority.action_type.value,
        payload=payload,
        worker_generation=row.worker_generation,
        recovery_deadline_at=recovery_claim.deadline_at,
    )
    action_claim_expires_at = row.claim_expires_at
    claim_started = datetime.now(UTC)
    claim = await prepare_control_action_claim(
        db,
        request=ControlActionClaimRequest(
            thread_id=action.thread_id,
            action_type=action.action_type,
            request_id=action.identity.request_id,
            idempotency_key=action.identity.idempotency_key,
            payload=action.payload,
            dispatch_id=action.identity.dispatch_id,
            worker_generation=action.worker_generation,
            recovery_deadline_at=action.recovery_deadline_at,
            now=claim_started,
        ),
    )
    if not claim.authority_matches:
        authority_checked_at = datetime.now(UTC)
        if authority_checked_at >= recovery_claim.deadline_at:
            await release_recovery_attempt(
                db, recovery_claim, released_at=authority_checked_at
            )
            outcome = _RecoveryOutcome.DEFERRED
        else:
            await settle_recovery_attempt(
                db, recovery_claim, settled_at=authority_checked_at
            )
            outcome = _RecoveryOutcome.CONFLICTED
        await db.commit()
        return outcome
    if not claim.payload_matches:
        refusal = _Refusal(
            FailureType.INCOMPATIBLE_STATE,
            "accepted recovery payload changed after acceptance",
        )
        return await _settle_action_refusal(
            db,
            recovery_claim,
            action,
            refusal,
            RecoveryCondition.INCOMPATIBLE_STATE,
        )
    if not claim.acquired:
        deferred_at = datetime.now(UTC)
        if deferred_at >= recovery_claim.deadline_at:
            await release_recovery_attempt(db, recovery_claim, released_at=deferred_at)
        else:
            await reschedule_recovery_attempt(
                db,
                recovery_claim,
                condition=recovery_claim.condition,
                observed_at=deferred_at,
                next_eligible_at=min(
                    max(deferred_at, action_claim_expires_at or deferred_at),
                    recovery_claim.deadline_at,
                ),
                detail="accepted action lease remains owned",
            )
        await db.commit()
        return _RecoveryOutcome.DEFERRED
    return _PreparedRecovery(action, claim, claim_started)


async def _redrive_one_claim(
    session_factory: async_sessionmaker[AsyncSession],
    recovery_claim: RecoveryAttemptClaim,
    runtime: _RecoveryRuntime,
) -> _RecoveryOutcome:
    async with session_factory() as db:
        row = await get_control_action_by_dispatch_id(
            db,
            thread_id=recovery_claim.thread_id,
            dispatch_id=recovery_claim.authority.action_receipt_id,
        )
        payload = _decode_payload(row.payload_json) if row is not None else None
        if (
            row is None
            or payload is None
            or row.recovery_deadline_at != recovery_claim.deadline_at
        ):
            return await _settle_missing_action(db, recovery_claim, row, payload)
        if row.applied_at is not None:
            await settle_recovery_attempt(
                db, recovery_claim, settled_at=datetime.now(UTC)
            )
            await db.commit()
            return _RecoveryOutcome.APPLIED
        prepared = await _prepare_recovery_action(db, recovery_claim, row, payload)
        if isinstance(prepared, _RecoveryOutcome):
            return prepared
        return await _dispatch_prepared_claim(db, recovery_claim, prepared, runtime)


async def redrive_direct_control_actions(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    worker_client: httpx.AsyncClient,
    circuit_breaker: WorkerCircuitBreaker,
    worker_spawner: LazyWorkerSpawner,
    trace_headers: dict[str, str] | None,
) -> DirectControlRecoverySummary:
    """Claim due durable recovery records and resend their stable dispatch."""
    instant = datetime.now(UTC)
    async with session_factory() as db:
        expired = await _expire_overdue_actions(db, observed_at=instant)
    async with session_factory() as db:
        await seed_recovery_attempts(
            db,
            observed_at=instant,
            limit=_RECOVERY_PAGE_SIZE,
        )
        recovery_claims = await acquire_due_recovery_attempts(
            db,
            acquired_at=instant,
            claim_expires_at=instant + _RECOVERY_CLAIM_TTL,
            limit=_RECOVERY_PAGE_SIZE,
        )
        await db.commit()

    runtime = _RecoveryRuntime(
        worker_client=worker_client,
        circuit_breaker=circuit_breaker,
        worker_spawner=worker_spawner,
        trace_headers=trace_headers,
    )
    outcomes: dict[_RecoveryOutcome, int] = {}
    for recovery_claim in recovery_claims:
        outcome = await _redrive_one_claim(session_factory, recovery_claim, runtime)
        outcomes[outcome] = outcomes.get(outcome, 0) + 1

    summary = DirectControlRecoverySummary(
        examined=expired + len(recovery_claims),
        dispatched=outcomes.get(_RecoveryOutcome.DISPATCHED, 0),
        deferred=outcomes.get(_RecoveryOutcome.DEFERRED, 0),
        conflicted=outcomes.get(_RecoveryOutcome.CONFLICTED, 0),
        refused=expired + outcomes.get(_RecoveryOutcome.REFUSED, 0),
    )
    logger.info("Direct control recovery pass complete: %s", summary)
    return summary

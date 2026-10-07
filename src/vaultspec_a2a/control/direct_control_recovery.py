"""Startup redelivery for durable direct control-action leases."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from ..database import (
    CONTROL_ACTION_LEASE_TTL,
    RECOVERY_CLAIM_TTL,
    ControlActionModel,
    ThreadStatusElectionOutcome,
    begin_write_transaction,
    elect_thread_status,
    get_control_action_by_dispatch_id,
    get_thread,
    lease_free_from,
    lock_thread_row,
    mark_control_action_applied,
    overdue_recovery_actions,
    release_control_action_lease,
    thread_write_expectation,
)
from ..domain_config import domain_config
from ..thread.action_receipts import GRAPH_ACTION_VERB
from ..thread.dispatch_policy import FailureType
from ..thread.enums import (
    NON_ACTIVE_STATUSES,
    ControlActionResultStatus,
    ControlActionType,
    RecoveryCondition,
    ThreadStatus,
)
from ..thread.repair_policy import ACTION_QUARANTINED_TRANSITION
from ..utils.coercion import decode_json_object
from .accepted_input import (
    AcceptedActionInput,
    ActorCredentialsRequiredError,
    restore_accepted_dispatch,
)
from .action_lease import (
    DEFINITE_NON_DELIVERY,
    ControlActionClaim,
    ControlActionClaimRequest,
    prepare_control_action_claim,
)
from .leased_dispatch import DispatchRefusal, DispatchTransport, deliver_leased
from .recovery import (
    RecoveryAttemptClaim,
    acquire_due_recovery_attempts,
    record_recovery_deadline,
    release_recovery_attempt,
    reschedule_recovery_attempt,
    seed_recovery_attempts,
    settle_recovery_attempt,
)
from .repair_transitions import apply_repair_transition
from .workspace import WorkspaceUnavailableError

if TYPE_CHECKING:
    import httpx
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from ..ipc.schemas import DispatchRequest
    from ..thread import RunWriteAuthority
    from .circuit_breaker import WorkerCircuitBreaker
    from .leased_dispatch import DispatchFailure
    from .worker_management import LazyWorkerSpawner

__all__ = ["DirectControlRecoverySummary", "redrive_direct_control_actions"]

logger = logging.getLogger(__name__)


class _RecoveryOutcome(StrEnum):
    DISPATCHED = "dispatched"
    DEFERRED = "deferred"
    CONFLICTED = "conflicted"
    REFUSED = "refused"
    APPLIED = "applied"


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
    page_size: int,
) -> int:
    rows = await overdue_recovery_actions(db, observed_at=observed_at, limit=page_size)
    # Every overdue row is snapshotted before the first settlement, because a
    # refused item rolls the session back and a rollback expires every loaded
    # row: reading one afterwards would attempt implicit async I/O. Each
    # settlement then owns its own transaction, so one refusal discards its own
    # work and never the items already settled in this pass.
    overdue = [
        _StoredAction(
            identity=_StoredActionIdentity(
                dispatch_id=row.dispatch_id,
                request_id=row.request_id,
                idempotency_key=row.idempotency_key,
            ),
            thread_id=row.thread_id,
            action_type=row.action_type,
            payload=decode_json_object(row.payload_json) or {},
            worker_generation=row.worker_generation,
            recovery_deadline_at=row.recovery_deadline_at,
        )
        for row in rows
        if row.dispatch_id is not None and row.recovery_deadline_at is not None
    ]
    await db.rollback()
    refusal = DispatchRefusal(
        FailureType.DEADLINE_EXCEEDED,
        "accepted run deadline expired before application",
    )
    expired = 0
    for stored in overdue:
        await begin_write_transaction(db)
        if not await _settle_permanent_refusal(
            db,
            stored,
            refusal,
            deadline_observed_at=observed_at,
        ):
            await db.rollback()
            continue
        await db.commit()
        expired += 1
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


async def _reconstruct_dispatch(
    db: AsyncSession,
    action: _StoredAction,
    *,
    dispatch_id: str,
) -> DispatchRequest | DispatchRefusal:
    thread = await get_thread(db, action.thread_id)
    if thread is None:
        return DispatchRefusal(
            FailureType.NOT_FOUND, "the accepted run no longer exists"
        )
    try:
        accepted = AcceptedActionInput.model_validate(action.payload)
        dispatch = restore_accepted_dispatch(accepted, dispatch_id=dispatch_id)
    except ActorCredentialsRequiredError as exc:
        return DispatchRefusal(FailureType.CREDENTIALS_REQUIRED, str(exc))
    except WorkspaceUnavailableError:
        return DispatchRefusal(
            FailureType.NO_ACTIVE_PROJECT, "accepted project is unavailable"
        )
    except ValueError as exc:
        return DispatchRefusal(FailureType.INCOMPATIBLE_STATE, str(exc))
    action_type = ControlActionType(action.action_type)
    expected_action = (
        "cancel"
        if action_type is ControlActionType.CANCEL
        else GRAPH_ACTION_VERB.get(action_type)
    )
    if dispatch.thread_id != action.thread_id or dispatch.action != expected_action:
        return DispatchRefusal(
            FailureType.INCOMPATIBLE_STATE, "accepted input identity mismatch"
        )
    if dispatch.requires_graph_receipt and (
        dispatch.workspace_root is None or not Path(dispatch.workspace_root).is_dir()
    ):
        return DispatchRefusal(
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
        target = (
            expectation.status
            if expectation.status in {ThreadStatus.CANCELLING, ThreadStatus.RECONCILING}
            else ThreadStatus.CANCELLING
        )
    else:
        target = expectation.status
    return target is expectation.status and expectation.authority.owned_by(
        action_type, action_receipt_id
    )


async def _quarantine_for_operator(
    db: AsyncSession, thread_id: str, refusal: DispatchRefusal
) -> None:
    """Hand a run whose accepted action was refused for good to an operator."""
    await apply_repair_transition(
        db,
        thread_id,
        ACTION_QUARANTINED_TRANSITION,
        reason=f"{refusal.failure_type.value}: {refusal.reason}",
    )


async def _settle_permanent_refusal(
    db: AsyncSession,
    action: _StoredAction,
    refusal: DispatchRefusal,
    *,
    deadline_observed_at: datetime | None = None,
) -> bool:
    """Quarantine one impossible accepted action under exact current authority."""
    thread = await lock_thread_row(db, action.thread_id)
    row = await get_control_action_by_dispatch_id(
        db,
        thread_id=action.thread_id,
        dispatch_id=action.identity.dispatch_id,
        lock=True,
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
    if not expectation.authority.owned_by(action_type, action.identity.dispatch_id):
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
            action_type=action_type,
            action_receipt_id=action.identity.dispatch_id,
        )
        if election.outcome is not ThreadStatusElectionOutcome.WON:
            return False
    await mark_control_action_applied(
        db,
        row.id,
        result_status=ControlActionResultStatus.REJECTED_INVALID_STATE,
    )
    await _quarantine_for_operator(db, action.thread_id, refusal)
    return True


async def _settle_orphaned_refusal(
    db: AsyncSession,
    *,
    thread_id: str,
    authority: RunWriteAuthority,
    refusal: DispatchRefusal,
) -> bool:
    """Quarantine exact authority whose accepted action row disappeared."""
    thread = await lock_thread_row(db, thread_id)
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
            action_type=authority.action_type,
            action_receipt_id=authority.action_receipt_id,
        )
        if election.outcome not in {
            ThreadStatusElectionOutcome.WON,
            ThreadStatusElectionOutcome.RECEIPT_MISMATCH,
        }:
            return False
    await _quarantine_for_operator(db, thread_id, refusal)
    return True


async def _settle_action_refusal(
    db: AsyncSession,
    recovery_claim: RecoveryAttemptClaim,
    action: _StoredAction,
    refusal: DispatchRefusal,
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
    refusal = DispatchRefusal(
        FailureType.INCOMPATIBLE_STATE,
        "accepted recovery input is absent or inconsistent",
    )
    if row is not None and recovery_claim.authority.owned_by(
        row.action_type, row.dispatch_id
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
    failure: DispatchFailure,
) -> _RecoveryOutcome:
    action = prepared.action
    claim = prepared.claim
    failure_type = failure.failure_type
    await begin_write_transaction(db)
    if failure_type is FailureType.INCOMPATIBLE_STATE:
        refusal = DispatchRefusal(failure_type, failure.detail)
        return await _settle_action_refusal(
            db,
            recovery_claim,
            action,
            refusal,
            RecoveryCondition.INCOMPATIBLE_STATE,
        )
    if claim.claim_token is None:
        raise RuntimeError("recovery dispatch lost its action claim")
    if failure_type in DEFINITE_NON_DELIVERY:
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
    # The worker's own Retry-After, when it gave one, is better information than
    # the backoff curve: it comes from the side that knows when it expects room.
    # The later of the two wins, so the hint can bring a retry no earlier than
    # the curve already allows and can only hold one back.
    delay = _retry_delay(recovery_claim.attempt_count)
    if failure.retry_after_seconds is not None:
        delay = max(delay, timedelta(seconds=failure.retry_after_seconds))
    retry_at = failure_observed_at + delay
    retry_at = min(retry_at, recovery_claim.deadline_at)
    await reschedule_recovery_attempt(
        db,
        recovery_claim,
        condition=RecoveryCondition(failure_type.value),
        observed_at=failure_observed_at,
        next_eligible_at=retry_at,
        detail=failure.detail,
    )
    await db.commit()
    return _RecoveryOutcome.DEFERRED


async def _dispatch_prepared_claim(
    db: AsyncSession,
    recovery_claim: RecoveryAttemptClaim,
    prepared: _PreparedRecovery,
    transport: DispatchTransport,
) -> _RecoveryOutcome:
    action = prepared.action
    claim = prepared.claim
    claim_started = prepared.claim_started
    dispatch = await _reconstruct_dispatch(
        db,
        action,
        dispatch_id=claim.dispatch_id,
    )
    if isinstance(dispatch, DispatchRefusal):
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
    failure = await deliver_leased(db, claim, dispatch, transport)
    if failure is not None:
        return await _settle_delivery_failure(db, recovery_claim, prepared, failure)
    await begin_write_transaction(db)
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
            lease_free_from(claim_started + CONTROL_ACTION_LEASE_TTL, delivered_at),
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
        refusal = DispatchRefusal(
            FailureType.INCOMPATIBLE_STATE,
            "accepted recovery payload changed after acceptance",
        )
        if not db.in_transaction():
            # A losing claim already rolled the acceptance back; the refusal
            # below reads before it writes and needs the lock from the start.
            await begin_write_transaction(db)
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
                    lease_free_from(action_claim_expires_at, deferred_at),
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
    transport: DispatchTransport,
) -> _RecoveryOutcome:
    async with session_factory() as db:
        await begin_write_transaction(db)
        row = await get_control_action_by_dispatch_id(
            db,
            thread_id=recovery_claim.thread_id,
            dispatch_id=recovery_claim.authority.action_receipt_id,
        )
        payload = decode_json_object(row.payload_json) if row is not None else None
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
        return await _dispatch_prepared_claim(db, recovery_claim, prepared, transport)


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
    # Paging by the service-wide continuation cap lets one pass reach every
    # continuation the service could have admitted, whatever the operator set.
    page_size = domain_config.run_continuation_service_queue_cap
    async with session_factory() as db:
        expired = await _expire_overdue_actions(
            db, observed_at=instant, page_size=page_size
        )
    async with session_factory() as db:
        await begin_write_transaction(db)
        await seed_recovery_attempts(
            db,
            observed_at=instant,
            limit=page_size,
        )
        recovery_claims = await acquire_due_recovery_attempts(
            db,
            acquired_at=instant,
            claim_expires_at=instant + RECOVERY_CLAIM_TTL,
            limit=page_size,
        )
        await db.commit()

    transport = DispatchTransport(
        worker_client=worker_client,
        circuit_breaker=circuit_breaker,
        worker_spawner=worker_spawner,
        trace_headers=trace_headers,
    )
    outcomes: dict[_RecoveryOutcome, int] = {}
    for recovery_claim in recovery_claims:
        outcome = await _redrive_one_claim(session_factory, recovery_claim, transport)
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

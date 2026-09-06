"""Startup redelivery for durable direct control-action leases."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import select

from ..database import (
    ControlActionModel,
    get_thread,
    thread_write_expectation,
)
from ..thread.dispatch_policy import FailureType, evaluate_dispatch_failure
from ..thread.enums import ControlActionType, ThreadStatus
from .accepted_input import (
    AcceptedActionInput,
    ActorCredentialsRequiredError,
    restore_accepted_dispatch,
)
from .action_lease import (
    finalize_control_action_acceptance,
    prepare_control_action_claim,
    release_definite_non_delivery,
)
from .dispatch import safe_dispatch
from .dispatch_receipts import bind_graph_action_receipt

if TYPE_CHECKING:
    import httpx
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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
class _StoredAction:
    dispatch_id: str
    thread_id: str
    action_type: str
    request_id: str | None
    idempotency_key: str
    payload: dict[str, object]
    worker_generation: int


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


async def redrive_direct_control_actions(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    worker_client: httpx.AsyncClient,
    circuit_breaker: WorkerCircuitBreaker,
    worker_spawner: LazyWorkerSpawner,
    trace_headers: dict[str, str] | None,
) -> DirectControlRecoverySummary:
    """Reacquire expired direct-control leases and resend their stable dispatch."""
    async with session_factory() as db:
        rows = (
            (
                await db.execute(
                    select(ControlActionModel).where(
                        ControlActionModel.action_type.in_(_RECOVERABLE_TYPES),
                        ControlActionModel.applied_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        stored = [
            _StoredAction(
                dispatch_id=row.dispatch_id,
                thread_id=row.thread_id,
                action_type=row.action_type,
                request_id=row.request_id,
                idempotency_key=row.idempotency_key,
                payload=payload,
                worker_generation=row.worker_generation,
            )
            for row in rows
            if row.dispatch_id
            and (payload := _decode_payload(row.payload_json)) is not None
        ]

    dispatched = deferred = refused = 0
    conflicted = len(rows) - len(stored)
    for action in stored:
        async with session_factory() as db:
            claim = await prepare_control_action_claim(
                db,
                thread_id=action.thread_id,
                action_type=action.action_type,
                request_id=action.request_id,
                idempotency_key=action.idempotency_key,
                payload=action.payload,
                dispatch_id=action.dispatch_id,
                worker_generation=action.worker_generation,
            )
            if not claim.authority_matches:
                conflicted += 1
                continue
            if not claim.payload_matches:
                conflicted += 1
                continue
            if not claim.acquired:
                deferred += 1
                continue
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
                await db.rollback()
                refused += 1
                continue
            owns_projection = await _restore_requested_state(
                db,
                action,
                action_receipt_id=claim.dispatch_id,
            )
            if not owns_projection:
                await db.rollback()
                conflicted += 1
                continue
            await finalize_control_action_acceptance(db, claim)
            dispatch = await bind_graph_action_receipt(db, dispatch)
            outcome = await safe_dispatch(
                worker_client,
                dispatch,
                circuit_breaker,
                worker_spawner,
                bypass_circuit_breaker=(
                    action.action_type == ControlActionType.CANCEL.value
                ),
                trace_headers=trace_headers,
            )
            if not outcome.success:
                _policy, failure_type = evaluate_dispatch_failure(outcome.failure_type)
                released = await release_definite_non_delivery(
                    db,
                    claim,
                    failure_type,
                )
                if not released:
                    await db.commit()
                deferred += 1
                continue
            await db.commit()
            dispatched += 1

    summary = DirectControlRecoverySummary(
        examined=len(rows),
        dispatched=dispatched,
        deferred=deferred,
        conflicted=conflicted,
        refused=refused,
    )
    logger.info("Direct control recovery pass complete: %s", summary)
    return summary

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
from typing import TYPE_CHECKING, cast

from sqlalchemy import select

from ..database import (
    get_control_action_by_idempotency_key,
    get_thread,
    mark_control_action_applied,
    settle_control_action_lease,
)
from ..database.models import ControlActionModel
from ..ipc.schemas import DispatchRequest, to_dispatch_action
from ..thread.clarification import (
    ClarificationAnswers,
    ClarificationResolution,
    clarification_resolution_fingerprint,
    parse_clarification_resolution,
    pending_clarification,
    validate_clarification_answers,
)
from ..thread.dispatch_policy import FailureType, evaluate_dispatch_failure
from ..thread.enums import (
    NON_ACTIVE_STATUSES,
    ControlActionResultStatus,
    ControlActionType,
)
from .action_lease import claim_control_action, release_definite_non_delivery
from .dispatch import safe_dispatch
from .repair_transitions import record_undelivered_dispatch
from .thread_state_service import read_run_snapshot

if TYPE_CHECKING:
    import httpx
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from ..database.checkpoints import Checkpointer
    from .circuit_breaker import WorkerCircuitBreaker
    from .worker_management import LazyWorkerSpawner

__all__ = [
    "ClarificationRecoverySummary",
    "ClarificationResult",
    "redrive_clarification_actions",
    "respond_to_clarification",
]

logger = logging.getLogger(__name__)

_IDEMPOTENCY_PREFIX = "clarification-response:"


@dataclass(frozen=True, slots=True)
class ClarificationResult:
    """Protocol-neutral outcome of resolving one questionnaire."""

    request_id: str
    thread_id: str
    accepted: bool
    applied: bool
    action_status: str
    action_id: str | None = None
    idempotency_key: str | None = None
    dispatched: bool = False
    error_detail: str | None = None
    error_status_code: int | None = None
    failure_type: FailureType | None = None


@dataclass(frozen=True, slots=True)
class ClarificationRecoverySummary:
    """Counts from one restart recovery pass over clarification actions."""

    examined: int = 0
    applied: int = 0
    dispatched: int = 0
    deferred: int = 0
    conflicted: int = 0


def _idempotency_key(request_id: str) -> str:
    return f"{_IDEMPOTENCY_PREFIX}{request_id}"


def _workspace_root(metadata_json: str | None) -> str | None:
    if not metadata_json:
        return None
    try:
        decoded: object = json.loads(metadata_json)
    except json.JSONDecodeError:
        return None
    if not isinstance(decoded, dict):
        return None
    root = cast("dict[str, object]", decoded).get("workspace_root")
    return root if isinstance(root, str) and root else None


def _checkpoint_receipt(checkpoint_tuple: object | None, request_id: str) -> str | None:
    """Read one application receipt from checkpoint channel values."""
    checkpoint_value: object = getattr(checkpoint_tuple, "checkpoint", None)
    if not isinstance(checkpoint_value, dict):
        return None
    checkpoint = cast("dict[str, object]", checkpoint_value)
    values = checkpoint.get("channel_values")
    if not isinstance(values, dict):
        return None
    receipts = cast("dict[str, object]", values).get(
        "clarification_resolution_receipts"
    )
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
        payload: object = json.loads(action.payload_json)
        return parse_clarification_resolution(payload, request_id=action.request_id)
    except (json.JSONDecodeError, ValueError):
        return None


async def _settle_from_receipt(
    db: AsyncSession,
    action: ControlActionModel,
    *,
    fingerprint: str,
    checkpoint_tuple: object | None,
) -> bool:
    """Settle only when checkpoint truth carries this request and fingerprint."""
    if _checkpoint_receipt(checkpoint_tuple, action.request_id or "") != fingerprint:
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
    error_detail: str | None = None,
    error_status_code: int | None = None,
    failure_type: FailureType | None = None,
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
        error_detail=error_detail,
        error_status_code=error_status_code,
        failure_type=failure_type,
    )


async def respond_to_clarification(
    db: AsyncSession,
    *,
    thread_id: str,
    request_id: str,
    resolution: ClarificationResolution,
    checkpointer: Checkpointer,
    worker_client: httpx.AsyncClient,
    circuit_breaker: WorkerCircuitBreaker,
    worker_spawner: LazyWorkerSpawner,
    recursion_limit: int,
    trace_headers: dict[str, str] | None,
) -> ClarificationResult:
    """Reserve, lease, and dispatch one typed clarification resolution.

    The service owns its transaction boundary.  A fresh competing dispatcher
    replays the durable outcome without dispatch; an expired lease is acquired by
    one redriver.  Worker success is not application proof: only the request-scoped
    checkpoint receipt settles the journal row.
    """
    thread = await get_thread(db, thread_id)
    if thread is None:
        return ClarificationResult(
            request_id=request_id,
            thread_id=thread_id,
            accepted=False,
            applied=False,
            action_status=ControlActionResultStatus.REJECTED_INVALID_STATE.value,
            error_detail="Run not found",
            error_status_code=404,
        )

    fingerprint = clarification_resolution_fingerprint(resolution)
    payload = resolution.as_resume_value()
    idempotency_key = _idempotency_key(request_id)
    checkpoint_snapshot = await read_run_snapshot(checkpointer, thread_id)
    parked = pending_clarification(checkpoint_snapshot, thread_id=thread_id)

    existing = await get_control_action_by_idempotency_key(
        db,
        thread_id=thread_id,
        idempotency_key=idempotency_key,
    )
    if existing is None and (parked is None or parked.request_id != request_id):
        return ClarificationResult(
            request_id=request_id,
            thread_id=thread_id,
            accepted=False,
            applied=False,
            action_status=ControlActionResultStatus.REJECTED_INVALID_STATE.value,
            error_detail="Clarification request is not pending for this run",
            error_status_code=404,
        )

    if (
        parked is not None
        and parked.request_id == request_id
        and isinstance(resolution, ClarificationAnswers)
    ):
        violations = validate_clarification_answers(parked, resolution.answers)
        if violations:
            return ClarificationResult(
                request_id=request_id,
                thread_id=thread_id,
                accepted=False,
                applied=False,
                action_status=ControlActionResultStatus.REJECTED_INVALID_STATE.value,
                error_detail="; ".join(violations),
                error_status_code=422,
            )

    if existing is not None:
        stored = _stored_resolution(existing)
        if (
            stored is None
            or clarification_resolution_fingerprint(stored) != fingerprint
        ):
            return _result(
                existing,
                accepted=False,
                error_detail=(
                    "A different clarification resolution is already accepted"
                ),
                error_status_code=409,
            )
        if await _settle_from_receipt(
            db,
            existing,
            fingerprint=fingerprint,
            checkpoint_tuple=checkpoint_snapshot,
        ):
            await db.refresh(existing)
            return _result(existing, applied=True)
        if existing.applied_at is not None:
            return _result(existing, applied=True)

    # ``claim_control_action`` rolls back the caller's session when this request
    # loses a concurrent insert.  SQLAlchemy expires every loaded ORM instance
    # on that rollback, so all thread fields needed after the election must be
    # copied first; reading an expired attribute here would attempt implicit
    # async I/O and raise MissingGreenlet.
    thread_status = thread.status
    worker_generation = thread.repair_generation
    team_preset = thread.team_preset
    workspace_root = _workspace_root(thread.thread_metadata)

    claim = await claim_control_action(
        db,
        thread_id=thread_id,
        action_type=ControlActionType.RESUME,
        idempotency_key=idempotency_key,
        request_id=request_id,
        payload=payload,
        worker_generation=worker_generation,
    )
    action = await db.get(ControlActionModel, claim.action_id, populate_existing=True)
    if action is None:
        raise RuntimeError("claimed clarification action disappeared")
    if not claim.payload_matches:
        return _result(
            action,
            accepted=False,
            error_detail="A different clarification resolution is already accepted",
            error_status_code=409,
        )

    if claim.applied or action.applied_at is not None:
        return _result(action, applied=True)

    if parked is None or parked.request_id != request_id:
        return _result(
            action,
            accepted=False,
            error_detail="Clarification application cannot be confirmed",
            error_status_code=409,
        )
    if thread_status in NON_ACTIVE_STATUSES:
        return _result(
            action,
            accepted=False,
            error_detail="Run is not active",
            error_status_code=409,
        )

    if not claim.acquired:
        return _result(action)

    dispatch = DispatchRequest(
        dispatch_id=claim.dispatch_id,
        action=to_dispatch_action(ControlActionType.RESUME),
        thread_id=thread_id,
        option_id=payload,
        team_preset=team_preset,
        workspace_root=workspace_root,
        recursion_limit=recursion_limit,
    )
    outcome = await safe_dispatch(
        worker_client,
        dispatch,
        circuit_breaker,
        worker_spawner,
        trace_headers=trace_headers,
    )
    if not outcome.success:
        _policy, failure_type = evaluate_dispatch_failure(outcome.failure_type)
        detail = outcome.detail or "Worker dispatch failed"
        if await release_definite_non_delivery(db, claim, failure_type):
            # A released claim means the worker certainly scheduled no task, so
            # the answer demonstrably did not reach the parked node. The run is
            # untouched by that - it is still parked on the same questionnaire,
            # still alive, and still answerable - so the account goes on the
            # repair reason and never on the failure columns, which describe a
            # run that failed. An ambiguous failure keeps its lease because
            # delivery is undecided, and says nothing.
            await record_undelivered_dispatch(
                db,
                thread_id,
                reason=f"Clarification resume not delivered: {detail}",
            )
            await db.commit()
        return _result(
            action,
            error_detail=detail,
            error_status_code=(
                503 if failure_type is FailureType.CIRCUIT_OPEN else 502
            ),
            failure_type=failure_type,
        )

    # A very fast worker may already have checkpointed the receipt before its HTTP
    # acknowledgement reaches us. Settle opportunistically, but never infer
    # application merely from the acknowledgement.
    latest_checkpoint = await read_run_snapshot(checkpointer, thread_id)
    applied = await _settle_from_receipt(
        db,
        action,
        fingerprint=fingerprint,
        checkpoint_tuple=latest_checkpoint,
    )
    if applied:
        await db.refresh(action)
    return _result(action, applied=applied, dispatched=True)


async def redrive_clarification_actions(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    checkpointer: Checkpointer,
    worker_client: httpx.AsyncClient,
    circuit_breaker: WorkerCircuitBreaker,
    worker_spawner: LazyWorkerSpawner,
    recursion_limit: int,
    trace_headers: dict[str, str] | None,
) -> ClarificationRecoverySummary:
    """Settle receipted actions and redrive expired parked leases after restart."""
    async with session_factory() as db:
        rows = (
            (
                await db.execute(
                    select(ControlActionModel).where(
                        ControlActionModel.idempotency_key.like(
                            f"{_IDEMPOTENCY_PREFIX}%"
                        ),
                        ControlActionModel.applied_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
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
                checkpointer=checkpointer,
                worker_client=worker_client,
                circuit_breaker=circuit_breaker,
                worker_spawner=worker_spawner,
                recursion_limit=recursion_limit,
                trace_headers=trace_headers,
            )
        if result.applied:
            applied += 1
        elif result.dispatched:
            dispatched += 1
        elif result.error_status_code is not None:
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

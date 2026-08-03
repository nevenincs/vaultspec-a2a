"""Startup redelivery for durable direct control-action leases."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import select

from ..database import (
    ControlActionModel,
    get_permission_request,
    get_thread,
    update_thread_status,
)
from ..ipc.schemas import DispatchRequest, canonical_project_root, to_dispatch_action
from ..thread.constants import DEFAULT_SUPERVISOR_ID
from ..thread.dispatch_policy import FailureType, evaluate_dispatch_failure
from ..thread.enums import ControlActionType, ThreadStatus
from .action_lease import claim_control_action, release_definite_non_delivery
from .dispatch import safe_dispatch
from .permission_dispatch import permission_resume_value
from .repair_transitions import (
    mark_cancel_requested,
    mark_message_followup_requested,
    mark_permission_response_requested,
)

if TYPE_CHECKING:
    import httpx
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from .circuit_breaker import WorkerCircuitBreaker
    from .worker_management import LazyWorkerSpawner

__all__ = ["DirectControlRecoverySummary", "redrive_direct_control_actions"]

logger = logging.getLogger(__name__)
_JSON_OBJECT = TypeAdapter(dict[str, object])
_RECOVERABLE_TYPES = frozenset(
    {
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


def _active_project(metadata_json: str | None) -> str | None:
    """Return the run's canonical active project from its stored thread metadata.

    ``None`` when the metadata is unreadable, names no ``workspace_root``, or
    names one that cannot be minted into the run's canonical spelling. All three
    are the same thing - the stored run names no active project - and none of
    them is a project that may be degraded to "wherever the worker started".

    Minting through the shared canonical form rather than returning the stored
    string is what makes a recovered dispatch key the same compiled graph the
    original run compiled, instead of a second entry for one directory.
    """
    if metadata_json is None:
        return None
    try:
        metadata = _JSON_OBJECT.validate_json(metadata_json)
    except ValidationError:
        return None
    value = metadata.get("workspace_root")
    if not isinstance(value, str) or not value:
        return None
    try:
        return canonical_project_root(value)
    except ValueError:
        return None


async def _reconstruct_dispatch(
    db: AsyncSession,
    action: _StoredAction,
    *,
    dispatch_id: str,
    recursion_limit: int,
) -> DispatchRequest | _Refusal:
    thread = await get_thread(db, action.thread_id)
    if thread is None:
        return _Refusal(
            FailureType.NOT_FOUND,
            "the thread this action belongs to no longer exists",
        )

    if action.action_type == ControlActionType.CANCEL.value:
        # A cancel names no active project by design: it tears a run down rather
        # than siting one, so it is reconstructed before the project gate below.
        return DispatchRequest(
            dispatch_id=dispatch_id,
            action=to_dispatch_action(ControlActionType.CANCEL),
            thread_id=action.thread_id,
            recursion_limit=recursion_limit,
        )

    # Both remaining actions re-enter graph execution, and a recovery pass runs
    # after the worker that held the run is gone: there is no live graph still
    # carrying the project, so a resume needs it named as much as a follow-up
    # does. Refuse here, typed, the way the follow-up path refuses - rather than
    # dispatching with nothing and letting the provider seam site the agent and
    # its sandbox roots in whatever directory the worker was started in.
    workspace_root = _active_project(thread.thread_metadata)
    if workspace_root is None:
        return _Refusal(
            FailureType.NO_ACTIVE_PROJECT,
            "run carries no active project: its stored metadata names no usable "
            "workspace_root, so a recovered dispatch cannot be sited. "
            "Start a new run.",
        )

    if action.action_type == ControlActionType.MESSAGE_FOLLOWUP_REQUESTED.value:
        content = action.payload.get("content")
        agent_value = action.payload.get("agent_id")
        if not isinstance(content, str):
            return _Refusal(
                FailureType.REJECTED,
                "the stored follow-up carries no message content",
            )
        agent_id = (
            agent_value
            if isinstance(agent_value, str) and agent_value
            else DEFAULT_SUPERVISOR_ID
        )
        return DispatchRequest(
            dispatch_id=dispatch_id,
            action=to_dispatch_action(ControlActionType.INGEST),
            thread_id=action.thread_id,
            agent_id=agent_id,
            content=content,
            team_preset=thread.team_preset,
            workspace_root=workspace_root,
            recursion_limit=recursion_limit,
        )
    if (
        action.action_type == ControlActionType.PERMISSION_RESPONSE_SUBMITTED.value
        and action.request_id is not None
    ):
        permission = await get_permission_request(db, action.request_id)
        option_value = action.payload.get("option_id")
        notes_value = action.payload.get("notes")
        if permission is None or not isinstance(option_value, str):
            return _Refusal(
                FailureType.REJECTED,
                "the permission request this response answers is unreadable",
            )
        notes = notes_value if isinstance(notes_value, str) else None
        return DispatchRequest(
            dispatch_id=dispatch_id,
            action=to_dispatch_action(ControlActionType.RESUME),
            thread_id=action.thread_id,
            option_id=permission_resume_value(
                permission.pause_reason_type,
                option_value,
                notes,
            ),
            team_preset=thread.team_preset,
            workspace_root=workspace_root,
            recursion_limit=recursion_limit,
        )
    return _Refusal(
        FailureType.REJECTED,
        f"stored action type {action.action_type!r} has no recoverable dispatch",
    )


async def _restore_requested_state(
    db: AsyncSession,
    action: _StoredAction,
) -> None:
    if action.action_type == ControlActionType.MESSAGE_FOLLOWUP_REQUESTED.value:
        await mark_message_followup_requested(db, action.thread_id)
        await update_thread_status(db, action.thread_id, ThreadStatus.RUNNING)
    elif action.action_type == ControlActionType.CANCEL.value:
        await mark_cancel_requested(db, action.thread_id)
        await update_thread_status(db, action.thread_id, ThreadStatus.CANCELLING)
    elif action.action_type == ControlActionType.PERMISSION_RESPONSE_SUBMITTED.value:
        await mark_permission_response_requested(db, action.thread_id)


async def redrive_direct_control_actions(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    worker_client: httpx.AsyncClient,
    circuit_breaker: WorkerCircuitBreaker,
    worker_spawner: LazyWorkerSpawner,
    recursion_limit: int,
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
                thread_id=row.thread_id,
                action_type=row.action_type,
                request_id=row.request_id,
                idempotency_key=row.idempotency_key,
                payload=payload,
                worker_generation=row.worker_generation,
            )
            for row in rows
            if (payload := _decode_payload(row.payload_json)) is not None
        ]

    dispatched = deferred = refused = 0
    conflicted = len(rows) - len(stored)
    for action in stored:
        async with session_factory() as db:
            claim = await claim_control_action(
                db,
                thread_id=action.thread_id,
                action_type=action.action_type,
                request_id=action.request_id,
                idempotency_key=action.idempotency_key,
                payload=action.payload,
                worker_generation=action.worker_generation,
            )
            if not claim.payload_matches:
                conflicted += 1
                continue
            if not claim.acquired:
                if not claim.applied:
                    await _restore_requested_state(db, action)
                    await db.commit()
                deferred += 1
                continue
            dispatch = await _reconstruct_dispatch(
                db,
                action,
                dispatch_id=claim.dispatch_id,
                recursion_limit=recursion_limit,
            )
            if isinstance(dispatch, _Refusal):
                # No worker was contacted, so the lease release is offered with
                # the refusal's own type: a definite non-delivery hands the
                # action straight back for redrive, while a refusal that can
                # never succeed on its own - an absent active project - is not in
                # that set and keeps its lease until the TTL, so a permanently
                # unsatisfiable action backs off instead of spinning.
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
                await release_definite_non_delivery(
                    db,
                    claim,
                    dispatch.failure_type,
                )
                refused += 1
                continue
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
                    await _restore_requested_state(db, action)
                    await db.commit()
                deferred += 1
                continue
            await _restore_requested_state(db, action)
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

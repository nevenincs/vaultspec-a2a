"""Message follow-up service — business logic extracted from the messages route.

Owns the full send-followup-message workflow (thread lookup, idempotency,
control-action creation, repair-state transitions, dispatch) without any
FastAPI or HTTP coupling.  The route handler remains a thin adapter that
parses the request, calls this service, commits, and maps the result to
an HTTP response.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..control.action_lease import (
    claim_control_action,
    release_definite_non_delivery,
)
from ..control.dispatch import safe_dispatch
from ..control.repair_transitions import (
    mark_message_followup_requested,
    record_undelivered_dispatch,
)
from ..database import (
    get_thread,
)
from ..ipc.schemas import DispatchRequest, to_dispatch_action
from ..thread.dispatch_policy import FailureType, evaluate_dispatch_failure
from ..thread.enums import ControlActionType, ThreadStatus
from ..thread.idempotency import default_message_key
from ..thread.message_policy import can_send_followup

if TYPE_CHECKING:
    import httpx
    from sqlalchemy.ext.asyncio import AsyncSession

    from ..control.circuit_breaker import WorkerCircuitBreaker
    from ..control.worker_management import LazyWorkerSpawner

__all__ = ["MessageResult", "send_followup_message"]

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class MessageResult:
    """Value object returned by :func:`send_followup_message`."""

    action_id: str
    thread_id: str
    thread_status: str
    dispatched: bool
    error_detail: str | None = None
    circuit_open: bool = False
    failure_type: FailureType | None = None


async def send_followup_message(
    db: AsyncSession,
    *,
    thread_id: str,
    content: str,
    agent_id: str,
    idempotency_key: str | None,
    circuit_breaker: WorkerCircuitBreaker,
    worker_spawner: LazyWorkerSpawner,
    worker_client: httpx.AsyncClient,
    recursion_limit: int,
    trace_headers: dict[str, str] | None,
) -> MessageResult:
    """Execute the send-followup-message workflow.

    Returns a :class:`MessageResult` describing the outcome.  Never raises
    HTTP exceptions — the caller is responsible for translating the result
    into an appropriate HTTP response.  Commits the session before returning.
    """
    # -- Thread lookup & guard -------------------------------------------
    thread = await get_thread(db, thread_id)
    if thread is None:
        return MessageResult(
            action_id="",
            thread_id=thread_id,
            thread_status="",
            dispatched=False,
            error_detail="Thread not found",
            failure_type=FailureType.NOT_FOUND,
        )

    eligibility = can_send_followup(thread.status)
    if not eligibility.allowed:
        # Distinguish INPUT_REQUIRED from generic terminal-state rejection
        domain_failure = (
            FailureType.INPUT_REQUIRED
            if thread.status == ThreadStatus.INPUT_REQUIRED.value
            else FailureType.TERMINAL
        )
        return MessageResult(
            action_id="",
            thread_id=thread_id,
            thread_status=thread.status,
            dispatched=False,
            error_detail=eligibility.reason,
            failure_type=domain_failure,
        )

    logger.info(
        "Message received for thread %s: %d chars",
        thread_id,
        len(content),
    )

    # The losing claim path rolls its transaction back, which expires ORM state.
    # Snapshot every value needed after election before entering the shared lease
    # primitive so a concurrent replay/conflict never triggers implicit async I/O.
    thread_status = thread.status
    team_preset = thread.team_preset
    thread_metadata = thread.thread_metadata

    # -- Durable reservation and dispatch election -----------------------
    resolved_idempotency_key = idempotency_key or default_message_key(
        thread_id, agent_id, content
    )
    claim = await claim_control_action(
        db,
        thread_id=thread_id,
        action_type=ControlActionType.MESSAGE_FOLLOWUP_REQUESTED,
        idempotency_key=resolved_idempotency_key,
        payload={"content": content, "agent_id": agent_id},
    )
    if not claim.payload_matches:
        return MessageResult(
            action_id=claim.action_id,
            thread_id=thread_id,
            thread_status=thread_status,
            dispatched=False,
            error_detail="Idempotency key is already bound to a different message",
            failure_type=FailureType.CONFLICT,
        )
    if not claim.acquired:
        return MessageResult(
            action_id=claim.action_id,
            thread_id=thread_id,
            thread_status=thread_status,
            dispatched=False,
        )

    await mark_message_followup_requested(db, thread_id)
    await db.commit()

    # -- Metadata extraction ---------------------------------------------
    workspace_root: str | None = None
    if thread_metadata:
        try:
            meta = json.loads(thread_metadata)
            workspace_root = meta.get("workspace_root")
        except (json.JSONDecodeError, AttributeError):
            pass

    # -- Dispatch construction & send ------------------------------------
    dispatch = DispatchRequest(
        dispatch_id=claim.dispatch_id,
        action=to_dispatch_action(ControlActionType.INGEST),
        thread_id=thread_id,
        agent_id=agent_id,
        content=content,
        team_preset=team_preset,
        workspace_root=workspace_root,
        recursion_limit=recursion_limit,
    )

    logger.info(
        "Dispatching message dispatch_id=%s for thread %s",
        dispatch.dispatch_id,
        thread_id,
        extra={
            "thread_id": thread_id,
            "dispatch_id": dispatch.dispatch_id,
            "action": dispatch.action,
            "agent_id": agent_id,
        },
    )

    outcome = await safe_dispatch(
        worker_client,
        dispatch,
        circuit_breaker,
        worker_spawner,
        trace_headers=trace_headers,
    )

    if not outcome.success:
        policy, typed_failure = evaluate_dispatch_failure(outcome.failure_type)
        detail = outcome.detail or "Worker dispatch failed"
        released = await release_definite_non_delivery(db, claim, typed_failure)
        if released:
            # The lease is released only where the worker certainly scheduled no
            # task, so this is the one arm that KNOWS the message never arrived,
            # and the only one entitled to say so durably. An ambiguous failure
            # keeps its lease for redrive precisely because delivery is
            # undecided; recording a non-delivery there would assert something
            # the gateway cannot observe. Neither arm touches the run's status:
            # the run is alive, and the message is what failed.
            await record_undelivered_dispatch(
                db,
                thread_id,
                reason=f"Follow-up message not delivered: {detail}",
            )
        await db.commit()
        return MessageResult(
            action_id=claim.action_id,
            thread_id=thread_id,
            thread_status=thread_status,
            dispatched=False,
            circuit_open=policy.is_circuit_open,
            error_detail=detail,
            failure_type=typed_failure,
        )

    # Worker acknowledgement proves scheduling only. The exact internal
    # ``dispatch_applied`` receipt settles the journal action and repair state.
    return MessageResult(
        action_id=claim.action_id,
        thread_id=thread_id,
        thread_status=thread_status,
        dispatched=True,
    )

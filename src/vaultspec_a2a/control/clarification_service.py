"""Mid-run clarification response orchestration service (agent-flow ADR D5(c)).

The structural sibling of ``control/permission_service.py``'s
``respond_to_permission``, but self-contained rather than reusing its
``permission_requests`` durable table: a pending clarification's authority is
the checkpoint itself (mirroring how ``run-status`` discloses it —
:func:`vaultspec_a2a.thread.snapshots.clarification_data_from_interrupt` over
:func:`vaultspec_a2a.thread.snapshots.project_checkpoint_tuple`), never a side
table. This service reads the SAME checkpoint to locate and validate the
pending request, so disclosure and response never drift onto two sources of
truth. Idempotency and the resume dispatch reuse the same generic primitives
every other resume path uses (the ``control_actions`` journal, ``safe_dispatch``
+ ``DispatchRequest``), so this is a sibling of proven code, not a new
mechanism (agent-flow ADR D5(c) rationale).

Per the engine-side contract (already committed): the engine forwards the
``{"answers": {question_id: value}}`` envelope verbatim and validates only its
own bounds (ids, entry count, value length/single-line); it judges no answer
CONTENT. Option-id existence, per-question satisfaction, and required-question
completeness are this service's authority.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ..database import (
    create_control_action,
    get_control_action_by_idempotency_key,
    get_thread,
    update_thread_status,
)
from ..ipc.schemas import DispatchRequest, to_dispatch_action
from ..thread.dispatch_policy import evaluate_dispatch_failure
from ..thread.enums import (
    TERMINAL_STATUSES,
    ControlActionResultStatus,
    ControlActionType,
    ThreadStatus,
)
from ..thread.snapshots import (
    CLARIFICATION_REQUEST_INTERRUPT_TYPE,
    ClarificationRequestData,
    clarification_data_from_interrupt,
    project_checkpoint_tuple,
)
from .dispatch import safe_dispatch
from .repair_transitions import apply_dispatch_failure

if TYPE_CHECKING:
    import httpx
    from langchain_core.runnables import RunnableConfig
    from sqlalchemy.ext.asyncio import AsyncSession

    from ..database.checkpoints import Checkpointer
    from ..thread.dispatch_policy import FailureType
    from .circuit_breaker import WorkerCircuitBreaker
    from .worker_management import LazyWorkerSpawner

__all__ = [
    "ClarificationResult",
    "respond_to_clarification",
]

logger_name = __name__


@dataclass(frozen=True, slots=True)
class ClarificationResult:
    """Outcome of a clarification response operation.

    The route handler translates this into an HTTP response or exception —
    mirrors :class:`control.permission_service.PermissionResult`.
    """

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
    circuit_open: bool = False
    failure_type: "FailureType | None" = None


def _workspace_root(thread_metadata: str | None) -> str | None:
    if not thread_metadata:
        return None
    try:
        meta = json.loads(thread_metadata)
    except (json.JSONDecodeError, TypeError):
        return None
    if isinstance(meta, dict):
        root = meta.get("workspace_root")
        return root if isinstance(root, str) else None
    return None


async def _pending_clarification(
    checkpointer: Checkpointer, thread_id: str
) -> ClarificationRequestData | None:
    """Read the run's current pending clarification straight from its checkpoint.

    The same read the run-status disclosure uses — there is exactly one
    authority for "what is this run currently asking", and this is it.
    """
    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
    checkpoint_tuple = await checkpointer.aget_tuple(config)
    if checkpoint_tuple is None:
        return None
    projection = project_checkpoint_tuple(checkpoint_tuple, thread_id=thread_id)
    for interrupt in projection.pending_interrupts:
        if interrupt.interrupt_type == CLARIFICATION_REQUEST_INTERRUPT_TYPE:
            clarification = clarification_data_from_interrupt(interrupt)
            if clarification is not None:
                return clarification
    return None


def _validate_answers(
    clarification: ClarificationRequestData, answers: dict[str, str]
) -> tuple[dict[str, str], str | None]:
    """Validate *answers* against the pending question set.

    Returns ``(resume_answers, error_detail)``. ``resume_answers`` is the
    answer map filtered to known question ids only — an answer key naming no
    declared question is dropped rather than forwarded into the resume, so a
    stale or malformed key can never reach the graph. ``error_detail`` is
    ``None`` on success; when set, the response is a 409 (a business-state
    conflict, not a wire-shape violation the request schema already refused).

    Three checks, in the order named by the engine contract: option-id
    existence (a ``choice`` question's answer must be one of its declared
    options), per-question satisfaction (an answered ``choice`` question's
    value is meaningful only if it names an option), and required-question
    completeness (every ``required`` question has a non-empty answer).
    """
    resume_answers: dict[str, str] = {}
    for question in clarification.questions:
        raw_answer = answers.get(question.id)
        if raw_answer is None:
            if question.required:
                return {}, f"question {question.id!r} is required but was not answered"
            continue
        answer = raw_answer.strip()
        if not answer:
            if question.required:
                return {}, f"question {question.id!r} is required but was not answered"
            continue
        if question.kind == "choice" and answer not in question.options:
            return (
                {},
                f"question {question.id!r} received unknown option {answer!r}; "
                f"valid options are {question.options!r}",
            )
        resume_answers[question.id] = answer
    return resume_answers, None


async def respond_to_clarification(
    db: AsyncSession,
    *,
    run_id: str,
    request_id: str,
    answers: dict[str, str],
    idempotency_key: str | None,
    checkpointer: Checkpointer,
    circuit_breaker: WorkerCircuitBreaker,
    worker_spawner: LazyWorkerSpawner,
    worker_client: httpx.AsyncClient,
    recursion_limit: int,
    trace_headers: dict[str, str] | None,
) -> ClarificationResult:
    """Answer a pending clarification and resume the run it belongs to.

    Commits the session before returning — the service owns its transaction
    boundary, mirroring ``respond_to_permission``.
    """
    thread = await get_thread(db, run_id)
    if thread is None:
        return ClarificationResult(
            request_id=request_id,
            thread_id=run_id,
            accepted=False,
            applied=False,
            action_status=ControlActionResultStatus.REJECTED_INVALID_STATE.value,
            error_detail="Run not found",
            error_status_code=404,
        )

    resolved_idempotency_key = idempotency_key or hashlib.sha256(
        f"{request_id}:{json.dumps(answers, sort_keys=True)}".encode()
    ).hexdigest()
    existing_action = await get_control_action_by_idempotency_key(
        db, thread_id=run_id, idempotency_key=resolved_idempotency_key
    )
    if existing_action is not None:
        return ClarificationResult(
            request_id=request_id,
            thread_id=run_id,
            accepted=True,
            applied=existing_action.applied_at is not None,
            action_status=existing_action.result_status,
            action_id=existing_action.id,
            idempotency_key=resolved_idempotency_key,
        )

    if thread.status in {status.value for status in TERMINAL_STATUSES}:
        return ClarificationResult(
            request_id=request_id,
            thread_id=run_id,
            accepted=False,
            applied=False,
            action_status=ControlActionResultStatus.REJECTED_INVALID_STATE.value,
            error_detail="thread is no longer active",
            error_status_code=409,
        )

    clarification = await _pending_clarification(checkpointer, run_id)
    if clarification is None or clarification.request_id != request_id:
        return ClarificationResult(
            request_id=request_id,
            thread_id=run_id,
            accepted=False,
            applied=False,
            action_status=ControlActionResultStatus.REJECTED_INVALID_STATE.value,
            error_detail=(
                f"Clarification request {request_id!r} is not the run's "
                "current pending question (already answered, superseded, or "
                "the run is not parked at a clarification)"
            ),
            error_status_code=409,
        )

    resume_answers, validation_error = _validate_answers(clarification, answers)
    if validation_error is not None:
        return ClarificationResult(
            request_id=request_id,
            thread_id=run_id,
            accepted=False,
            applied=False,
            action_status=ControlActionResultStatus.REJECTED_INVALID_STATE.value,
            error_detail=validation_error,
            error_status_code=409,
        )

    action = await create_control_action(
        db,
        thread_id=run_id,
        action_type=ControlActionType.PERMISSION_RESPONSE_SUBMITTED,
        request_id=request_id,
        idempotency_key=resolved_idempotency_key,
        payload={"answers": resume_answers},
    )

    dispatch = DispatchRequest(
        action=to_dispatch_action(ControlActionType.RESUME),
        thread_id=run_id,
        option_id=resume_answers,
        team_preset=thread.team_preset,
        workspace_root=_workspace_root(thread.thread_metadata),
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
        policy, typed_failure = evaluate_dispatch_failure(outcome.failure_type)
        action.idempotency_key = f"{resolved_idempotency_key}:dispatch-failed:{action.id}"
        if policy.should_mark_failed:
            await apply_dispatch_failure(
                db, run_id, failed_status=ThreadStatus.INPUT_REQUIRED
            )
        else:
            action.result_status = ControlActionResultStatus.REJECTED_INVALID_STATE.value
        error_detail: str | None = outcome.detail or "Worker dispatch failed"
        error_status_code: int | None = None
        if policy.is_circuit_open:
            error_detail = outcome.detail or "Circuit breaker open"
            error_status_code = 503
        else:
            exc = outcome.exception
            http_code = getattr(exc, "status_code", 0)
            if http_code:
                error_detail = f"Worker dispatch failed (HTTP {http_code})"
            error_status_code = 502
        await db.commit()
        return ClarificationResult(
            request_id=request_id,
            thread_id=run_id,
            accepted=False,
            applied=False,
            action_status=ControlActionResultStatus.REJECTED_INVALID_STATE.value,
            action_id=action.id,
            idempotency_key=resolved_idempotency_key,
            circuit_open=policy.is_circuit_open,
            error_detail=error_detail,
            error_status_code=error_status_code,
            failure_type=typed_failure,
        )

    await update_thread_status(db, run_id, ThreadStatus.RUNNING)
    await db.commit()
    return ClarificationResult(
        request_id=request_id,
        thread_id=run_id,
        accepted=True,
        applied=False,
        action_status=ControlActionResultStatus.ACCEPTED_NOT_APPLIED.value,
        action_id=action.id,
        idempotency_key=resolved_idempotency_key,
        dispatched=True,
    )

"""Thread creation and dispatch orchestration service.

Encapsulates the business logic for creating a thread, building the
dispatch payload, and dispatching to the worker.  The route handler
delegates here and retains only request parsing, DB commit, and HTTP
response formatting.
"""

from __future__ import annotations

import contextlib
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..context.preamble import build_context_preamble
from ..control.dispatch import safe_dispatch
from ..control.repair_transitions import mark_ingest_applied, mark_ingest_requested
from ..database import create_control_action, create_thread, update_thread_status
from ..graph.compiler import build_initial_vault_index
from ..ipc.schemas import DispatchRequest
from ..team.team_config import load_team_config
from ..thread.creation import requires_dispatch, resolve_autonomous
from ..thread.dispatch_policy import classify_dispatch_failure
from ..thread.enums import ControlActionType, ThreadStatus
from ..thread.errors import ConfigError, TeamConfigNotFoundError

if TYPE_CHECKING:
    from pathlib import Path

    import httpx
    from sqlalchemy.ext.asyncio import AsyncSession

    from ..context.metadata import ThreadMetadata
    from .circuit_breaker import WorkerCircuitBreaker
    from .worker_management import LazyWorkerSpawner

__all__ = [
    "ThreadCreationRequest",
    "ThreadCreationResult",
    "create_and_dispatch_thread",
]

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ThreadCreationRequest:
    """Bundled request fields for :func:`create_and_dispatch_thread`."""

    thread_id: str
    title: str | None
    initial_message: str | None
    team_preset: str | None
    autonomous: bool | None
    nickname: str | None
    metadata: ThreadMetadata | None
    metadata_json: str | None
    workspace_root: Path | None


@dataclass(frozen=True, slots=True)
class ThreadCreationResult:
    """Outcome of :func:`create_and_dispatch_thread`."""

    thread_id: str
    status: str
    nickname: str | None
    dispatched: bool
    error_detail: str | None


async def create_and_dispatch_thread(
    db: AsyncSession,
    req: ThreadCreationRequest,
    *,
    circuit_breaker: WorkerCircuitBreaker,
    worker_spawner: LazyWorkerSpawner,
    worker_client: httpx.AsyncClient,
    recursion_limit: int,
    trace_headers: dict[str, str] | None,
) -> ThreadCreationResult:
    """Create a thread row, build dispatch payload, and dispatch to worker.

    Does **not** call ``db.commit()`` -- the caller owns the transaction
    boundary.  Does **not** raise ``HTTPException`` -- returns a result
    that the caller translates into HTTP status codes.

    Raises:
        NicknameConflictError: If the requested nickname is already taken.
    """
    thread = await create_thread(
        db,
        title=req.title,
        status=ThreadStatus.SUBMITTED,
        metadata=req.metadata_json,
        nickname=req.nickname,
        thread_id=req.thread_id,
        team_preset=req.team_preset,
    )

    logger.info(
        "Created thread %s (title=%s, preset=%s, nickname=%s)",
        thread.id,
        req.title,
        req.team_preset,
        req.nickname,
        extra={
            "thread_id": thread.id,
            "action": "create_thread",
            "team_preset": req.team_preset,
            "thread_title": req.title,
            "thread_nickname": req.nickname,
        },
    )

    await create_control_action(
        db,
        thread_id=thread.id,
        action_type=ControlActionType.INGEST,
        idempotency_key=f"thread-create:{thread.id}",
        payload={
            "title": req.title,
            "team_preset": req.team_preset,
            "autonomous": req.autonomous,
        },
    )
    await mark_ingest_requested(db, thread.id)

    if not requires_dispatch(req.team_preset):
        return ThreadCreationResult(
            thread_id=thread.id,
            status=thread.status,
            nickname=req.nickname,
            dispatched=False,
            error_detail=None,
        )

    # -- Build context preamble ------------------------------------------------
    context_preamble: str | None = None
    if req.metadata is not None:
        preamble_msg = build_context_preamble(req.metadata)
        context_preamble = (
            preamble_msg.content
            if isinstance(preamble_msg.content, str)
            else str(preamble_msg.content)
        )

    # -- Resolve autonomous flag -----------------------------------------------
    team_config = None
    if req.team_preset:
        with contextlib.suppress(ConfigError, TeamConfigNotFoundError):
            team_config = load_team_config(
                req.team_preset, workspace_root=req.workspace_root
            )
    effective_autonomous = resolve_autonomous(req.autonomous, team_config)

    # -- Build vault index -----------------------------------------------------
    feature_tag = req.metadata.feature_tag if req.metadata else None
    vault_index = (
        build_initial_vault_index(req.workspace_root, req.metadata.feature_tag)
        if (req.metadata and req.metadata.feature_tag)
        else {}
    )

    # -- Construct dispatch request --------------------------------------------
    dispatch = DispatchRequest(
        action=ControlActionType.INGEST,  # ty: ignore[invalid-argument-type]
        thread_id=thread.id,
        team_preset=req.team_preset,
        workspace_root=str(req.workspace_root) if req.workspace_root else None,
        autonomous=effective_autonomous,
        metadata_json=req.metadata_json,
        content=req.initial_message,
        context_preamble=context_preamble,
        recursion_limit=recursion_limit,
        active_feature=feature_tag,
        pipeline_phase=None,
        vault_index=vault_index,
        validation_errors=[],
    )

    logger.info(
        "Dispatching ingest dispatch_id=%s for thread %s",
        dispatch.dispatch_id,
        thread.id,
        extra={
            "thread_id": thread.id,
            "dispatch_id": dispatch.dispatch_id,
            "action": dispatch.action,
            "team_preset": dispatch.team_preset,
            "autonomous": dispatch.autonomous,
        },
    )

    # -- Dispatch via safe_dispatch (non-raising) ------------------------------
    outcome = await safe_dispatch(
        worker_client,
        dispatch,
        circuit_breaker,
        worker_spawner,
        trace_headers=trace_headers,
    )

    if not outcome.success:
        policy = classify_dispatch_failure(outcome.failure_type)
        if policy.should_mark_failed:
            await update_thread_status(db, thread.id, ThreadStatus.FAILED)
        return ThreadCreationResult(
            thread_id=thread.id,
            status=(
                ThreadStatus.FAILED.value
                if policy.should_mark_failed
                else thread.status
            ),
            nickname=req.nickname,
            dispatched=False,
            error_detail=f"{outcome.failure_type}:{outcome.detail}",
        )

    # -- Success ---------------------------------------------------------------
    await update_thread_status(db, thread.id, ThreadStatus.RUNNING)
    await mark_ingest_applied(db, thread.id)

    return ThreadCreationResult(
        thread_id=thread.id,
        status=ThreadStatus.RUNNING.value,
        nickname=req.nickname,
        dispatched=True,
        error_detail=None,
    )

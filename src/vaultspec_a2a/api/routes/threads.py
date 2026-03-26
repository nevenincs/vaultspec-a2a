"""Thread CRUD routes: POST /threads, GET /threads, DELETE, archive, metadata."""

import json
import logging
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ...context.metadata import ThreadMetadata, discover_context_refs, generate_nickname
from ...context.preamble import build_context_preamble
from ...control.config import settings
from ...control.dispatch import (
    WorkerAtCapacityError,
    WorkerCircuitOpenError,
    WorkerDispatchRejectedError,
    WorkerUnreachableError,
    dispatch_to_worker,
)
from ...database.checkpoints import Checkpointer
from ...database.crud import (
    ControlActionType,
    RepairStatus,
    ThreadStatus,
    create_control_action,
    create_thread,
    delete_thread,
    get_thread,
    get_thread_metadata,
    list_threads,
    set_thread_repair_state,
    update_thread_status,
)
from ...database.session import get_db
from ...graph.compiler import build_initial_vault_index
from ...ipc.schemas import DispatchRequest
from ...streaming.aggregator import EventAggregator
from ...team.team_config import load_team_config
from ...thread.errors import (
    ConfigError,
    NicknameConflictError,
    TeamConfigNotFoundError,
)
from .._utils import mark_worker_connected, trace_headers
from ..dependencies import (
    get_circuit_breaker,
    get_services,
    get_worker_spawner,
)
from ..schemas.rest import (
    CreateThreadRequest,
    CreateThreadResponse,
    ThreadListResponse,
    ThreadSummary,
)

router = APIRouter()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _process_metadata(
    body: CreateThreadRequest,
    thread_id: str,
) -> tuple[Path | None, str | None, str | None]:
    """Validate and enrich thread metadata (ADR-014).

    Returns (workspace_root, nickname, metadata_json).

    Raises:
        HTTPException: If ``workspace_root`` is not an existing directory (422).
    """
    metadata = body.metadata
    if metadata is None:
        return None, None, None

    ws_root = Path(metadata.workspace_root).resolve()
    if not ws_root.is_dir():
        raise HTTPException(
            status_code=422,
            detail=(
                "workspace_root is not an existing directory: "
                f"{metadata.workspace_root!r}"
            ),
        )

    if metadata.feature_tag and not metadata.context_refs:
        metadata.context_refs = discover_context_refs(ws_root, metadata.feature_tag)

    topology = "default"
    if body.team_preset:
        try:
            tc = load_team_config(body.team_preset, workspace_root=ws_root)
            topology = tc.topology.type
        except (ConfigError, TeamConfigNotFoundError):
            pass
    nickname = metadata.nickname or generate_nickname(
        metadata.feature_tag, topology, thread_id
    )
    metadata.nickname = nickname

    return ws_root, nickname, metadata.model_dump_json()


# ---------------------------------------------------------------------------
# POST /threads
# ---------------------------------------------------------------------------


@router.post("/threads", response_model=CreateThreadResponse, status_code=201)
async def create_thread_endpoint(
    request: Request,
    body: CreateThreadRequest,
    services: tuple[
        AsyncSession,
        EventAggregator,
        Checkpointer,
        httpx.AsyncClient,
    ] = Depends(get_services),
    circuit_breaker: Any = Depends(get_circuit_breaker),
    worker_spawner: Any = Depends(get_worker_spawner),
) -> CreateThreadResponse:
    """Create a new orchestration thread and dispatch to the worker."""
    try:
        db, _aggregator, _checkpointer, worker_client = services
        thread_id = uuid4().hex

        ws_root, nickname, metadata_json = _process_metadata(body, thread_id)

        if nickname is None and body.nickname is not None:
            nickname = body.nickname

        try:
            thread = await create_thread(
                db,
                title=body.title,
                status=ThreadStatus.SUBMITTED,
                metadata=metadata_json,
                nickname=nickname,
                thread_id=thread_id,
                team_preset=body.team_preset,
            )
        except NicknameConflictError as exc:
            raise HTTPException(
                status_code=409,
                detail=f"Thread nickname already exists: {exc.nickname!r}",
            ) from exc

        logger.info(
            "Created thread %s (title=%s, preset=%s, nickname=%s)",
            thread.id,
            body.title,
            body.team_preset,
            nickname,
            extra={
                "thread_id": thread.id,
                "action": "create_thread",
                "team_preset": body.team_preset,
                "thread_title": body.title,
                "thread_nickname": nickname,
            },
        )
        await create_control_action(
            db,
            thread_id=thread.id,
            action_type=ControlActionType.INGEST,
            idempotency_key=f"thread-create:{thread.id}",
            payload={
                "title": body.title,
                "team_preset": body.team_preset,
                "autonomous": body.autonomous,
            },
        )
        await set_thread_repair_state(
            db,
            thread.id,
            repair_status=RepairStatus.HEALTHY,
            execution_readiness=RepairStatus.HEALTHY.value,
            last_requested_action=ControlActionType.INGEST,
        )

        if body.team_preset:
            context_preamble: str | None = None
            if body.metadata is not None:
                preamble_msg = build_context_preamble(body.metadata)
                context_preamble = (
                    preamble_msg.content
                    if isinstance(preamble_msg.content, str)
                    else str(preamble_msg.content)
                )

            effective_autonomous: bool = False
            if body.autonomous is not None:
                effective_autonomous = body.autonomous
            else:
                try:
                    _tc = load_team_config(body.team_preset, workspace_root=ws_root)
                    effective_autonomous = _tc.permissions.auto_approve
                except (ConfigError, TeamConfigNotFoundError):
                    pass

            metadata = body.metadata
            feature_tag = metadata.feature_tag if metadata else None
            vault_index = (
                build_initial_vault_index(ws_root, metadata.feature_tag)
                if (metadata and metadata.feature_tag)
                else {}
            )

            dispatch = DispatchRequest(
                action="ingest",
                thread_id=thread.id,
                team_preset=body.team_preset,
                workspace_root=str(ws_root) if ws_root else None,
                autonomous=effective_autonomous,
                metadata_json=metadata_json,
                content=body.initial_message,
                context_preamble=context_preamble,
                recursion_limit=settings.graph_recursion_limit,
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
            try:
                await dispatch_to_worker(
                    worker_client,
                    dispatch,
                    circuit_breaker,
                    worker_spawner,
                    trace_headers=trace_headers(),
                )
                mark_worker_connected(request)
            except WorkerCircuitOpenError as exc:
                raise HTTPException(status_code=503, detail=exc.detail) from exc
            except WorkerAtCapacityError:
                await update_thread_status(db, thread.id, ThreadStatus.FAILED)
                await db.commit()
                raise HTTPException(
                    status_code=503,
                    detail="Worker at capacity — try again later",
                ) from None
            except WorkerUnreachableError:
                await update_thread_status(db, thread.id, ThreadStatus.FAILED)
                await db.commit()
                raise HTTPException(
                    status_code=502,
                    detail="Worker unreachable — thread marked as failed",
                ) from None
            except WorkerDispatchRejectedError as exc:
                await update_thread_status(db, thread.id, ThreadStatus.FAILED)
                await db.commit()
                raise HTTPException(
                    status_code=502,
                    detail=f"Worker rejected dispatch (HTTP {exc.status_code})",
                ) from None
            await update_thread_status(db, thread.id, ThreadStatus.RUNNING)
            await set_thread_repair_state(
                db,
                thread.id,
                repair_status=RepairStatus.HEALTHY,
                execution_readiness=RepairStatus.HEALTHY.value,
                last_applied_action=ControlActionType.INGEST,
            )

        await db.commit()

        return CreateThreadResponse(
            thread_id=thread.id,
            status=thread.status,
            nickname=nickname,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unhandled exception while creating thread")
        raise


# ---------------------------------------------------------------------------
# GET /threads
# ---------------------------------------------------------------------------


@router.get("/threads", response_model=ThreadListResponse)
async def list_threads_endpoint(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    status: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> ThreadListResponse:
    """List orchestration threads with pagination and optional status filter."""
    status_filter: ThreadStatus | None = None
    if status is not None:
        try:
            status_filter = ThreadStatus(status)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid status filter: {status!r}",
            ) from None
    threads, total = await list_threads(
        db, offset=offset, limit=limit, status=status_filter
    )
    summaries: list[ThreadSummary] = []
    for t in threads:
        nickname: str | None = t.nickname
        feature_tag: str | None = None
        source_branch: str | None = None
        callee: str | None = None
        if t.thread_metadata:
            try:
                meta_dict = json.loads(t.thread_metadata)
                feature_tag = meta_dict.get("feature_tag") or None
                source_branch = meta_dict.get("source_branch") or None
                callee = meta_dict.get("callee") or None
            except (json.JSONDecodeError, TypeError):
                pass

        summaries.append(
            ThreadSummary(
                thread_id=t.id,
                title=t.title,
                status=t.status,
                repair_status=t.repair_status,
                execution_readiness=t.execution_readiness,
                approval_status=t.approval_status,
                approval_request_id=t.approval_request_id,
                team_preset=t.team_preset,
                created_at=t.created_at,
                updated_at=t.updated_at,
                nickname=nickname,
                feature_tag=feature_tag,
                source_branch=source_branch,
                callee=callee,
            )
        )
    return ThreadListResponse(threads=summaries, total=total)


# ---------------------------------------------------------------------------
# GET /threads/{thread_id}/metadata
# ---------------------------------------------------------------------------


@router.get("/threads/{thread_id}/metadata", response_model=ThreadMetadata)
async def get_thread_metadata_endpoint(
    thread_id: str,
    db: AsyncSession = Depends(get_db),
) -> ThreadMetadata:
    """Return the full ThreadMetadata object for a thread."""
    meta_json = await get_thread_metadata(db, thread_id)
    if meta_json is None:
        raise HTTPException(status_code=404, detail="Thread or metadata not found")
    return ThreadMetadata.model_validate_json(meta_json)


# ---------------------------------------------------------------------------
# DELETE /threads/{thread_id}
# ---------------------------------------------------------------------------


@router.delete("/threads/{thread_id}", status_code=204)
async def delete_thread_endpoint(
    thread_id: str,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Hard-delete a thread and all cascading artifacts."""
    thread = await get_thread(db, thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found")
    if thread.status == ThreadStatus.RUNNING.value:
        raise HTTPException(
            status_code=409,
            detail="Cannot delete a RUNNING thread — cancel it first",
        )
    deleted = await delete_thread(db, thread_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Thread not found")
    await db.commit()


# ---------------------------------------------------------------------------
# POST /threads/{thread_id}/archive
# ---------------------------------------------------------------------------


@router.post("/threads/{thread_id}/archive", status_code=200)
async def archive_thread_endpoint(
    thread_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Transition a thread to ARCHIVED status."""
    thread = await get_thread(db, thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found")

    if thread.status == ThreadStatus.ARCHIVED:
        return {"thread_id": thread_id, "status": ThreadStatus.ARCHIVED}

    if thread.status not in (
        ThreadStatus.COMPLETED,
        ThreadStatus.FAILED,
        ThreadStatus.CANCELLED,
    ):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot archive thread in {thread.status!r} state",
        )

    await update_thread_status(db, thread_id, ThreadStatus.ARCHIVED)
    await db.commit()
    return {"thread_id": thread_id, "status": ThreadStatus.ARCHIVED}

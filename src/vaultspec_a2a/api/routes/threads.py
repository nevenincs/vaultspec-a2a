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
from ...control.thread_service import ThreadCreationRequest, create_and_dispatch_thread
from ...database import (
    delete_thread,
    get_thread,
    get_thread_metadata,
    list_threads,
    update_thread_status,
)
from ...database.checkpoints import Checkpointer
from ...database.session import get_db
from ...domain_config import domain_config
from ...streaming.aggregator import EventAggregator
from ...team.team_config import load_team_config
from ...thread.enums import (
    TERMINAL_STATUSES,
    ThreadStatus,
)
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
            creation_req = ThreadCreationRequest(
                thread_id=thread_id,
                title=body.title,
                initial_message=body.initial_message,
                team_preset=body.team_preset,
                autonomous=body.autonomous,
                nickname=nickname,
                metadata=body.metadata,
                metadata_json=metadata_json,
                workspace_root=ws_root,
            )
            result = await create_and_dispatch_thread(
                db,
                creation_req,
                circuit_breaker=circuit_breaker,
                worker_spawner=worker_spawner,
                worker_client=worker_client,
                recursion_limit=domain_config.graph_recursion_limit,
                trace_headers=trace_headers(),
            )
        except NicknameConflictError as exc:
            raise HTTPException(
                status_code=409,
                detail=f"Thread nickname already exists: {exc.nickname!r}",
            ) from exc

        await db.commit()

        if result.dispatched:
            mark_worker_connected(request)

        if result.error_detail:
            if result.error_detail.startswith("circuit_open:"):
                raise HTTPException(
                    status_code=503,
                    detail=result.error_detail.removeprefix("circuit_open:"),
                )
            if result.error_detail.startswith("at_capacity:"):
                raise HTTPException(
                    status_code=503,
                    detail="Worker at capacity \u2014 try again later",
                )
            if result.error_detail.startswith("unreachable:"):
                raise HTTPException(
                    status_code=502,
                    detail="Worker unreachable \u2014 thread marked as failed",
                )
            if result.error_detail.startswith("rejected:"):
                raise HTTPException(
                    status_code=502,
                    detail=result.error_detail.removeprefix("rejected:"),
                )

        return CreateThreadResponse(
            thread_id=result.thread_id,
            status=result.status,
            nickname=result.nickname,
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

    if thread.status not in TERMINAL_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot archive thread in {thread.status!r} state",
        )

    await update_thread_status(db, thread_id, ThreadStatus.ARCHIVED)
    await db.commit()
    return {"thread_id": thread_id, "status": ThreadStatus.ARCHIVED}

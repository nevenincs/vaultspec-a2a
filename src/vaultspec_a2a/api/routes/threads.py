"""Thread CRUD routes: POST /threads, GET /threads, DELETE, archive, metadata."""

import json
import logging
from typing import Any
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ...context.metadata import ThreadMetadata
from ...control.thread_service import (
    ThreadCreationRequest,
    archive_thread,
    create_and_dispatch_thread,
    delete_thread_service,
    process_metadata,
)
from ...database import (
    get_thread_metadata,
    list_threads,
)
from ...database.checkpoints import Checkpointer
from ...database.session import get_db
from ...domain_config import domain_config
from ...streaming.aggregator import EventAggregator
from ...thread.dispatch_policy import FailureType
from ...thread.enums import ThreadStatus
from ...thread.errors import NicknameConflictError
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


def _parse_thread_summary_metadata(
    raw_json: str | None,
) -> tuple[str | None, str | None, str | None]:
    """Extract display fields from thread_metadata JSON.

    Returns ``(feature_tag, source_branch, callee)``.
    """
    if not raw_json:
        return None, None, None
    try:
        meta = json.loads(raw_json)
        return (
            meta.get("feature_tag") or None,
            meta.get("source_branch") or None,
            meta.get("callee") or None,
        )
    except (json.JSONDecodeError, TypeError):
        return None, None, None


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

        try:
            ws_root, nickname, metadata_json = process_metadata(
                body.metadata, thread_id, body.team_preset
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

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

        if result.dispatched:
            mark_worker_connected(request)

        if result.failure_type is not None:
            if result.failure_type == FailureType.CIRCUIT_OPEN:
                raise HTTPException(
                    status_code=503,
                    detail=result.error_detail or "Circuit breaker open",
                )
            if result.failure_type == FailureType.AT_CAPACITY:
                raise HTTPException(
                    status_code=503,
                    detail="Worker at capacity \u2014 try again later",
                )
            if result.failure_type == FailureType.UNREACHABLE:
                raise HTTPException(
                    status_code=502,
                    detail="Worker unreachable \u2014 thread marked as failed",
                )
            if result.failure_type == FailureType.REJECTED:
                raise HTTPException(
                    status_code=502,
                    detail=result.error_detail or "Worker dispatch rejected",
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
        feature_tag, source_branch, callee = _parse_thread_summary_metadata(
            t.thread_metadata
        )
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
                nickname=t.nickname,
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
    result = await delete_thread_service(db, thread_id)
    if result.not_found:
        raise HTTPException(status_code=404, detail="Thread not found")
    if not result.deleted:
        raise HTTPException(status_code=409, detail=result.error_detail)


# ---------------------------------------------------------------------------
# POST /threads/{thread_id}/archive
# ---------------------------------------------------------------------------


@router.post("/threads/{thread_id}/archive", status_code=200)
async def archive_thread_endpoint(
    thread_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Transition a thread to ARCHIVED status."""
    result = await archive_thread(db, thread_id)
    if result.not_found:
        raise HTTPException(status_code=404, detail="Thread not found")
    if not result.archived:
        raise HTTPException(status_code=409, detail=result.error_detail)
    return {"thread_id": thread_id, "status": ThreadStatus.ARCHIVED}

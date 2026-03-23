"""REST API endpoints for the A2A Orchestrator (ADR-019 refactored).

Implements the REST routes from ADR-011 section 2.2 plus health:
- GET  /health             -> aggregated health (gateway, worker, database)
- POST /threads            -> CreateThreadResponse
- GET  /threads            -> ThreadListResponse (paginated)
- GET  /threads/{id}/state -> ThreadStateSnapshot (reconnection)
- POST /threads/{id}/messages -> 202 Accepted
- GET  /team/status        -> TeamStatusResponse
- POST /permissions/{id}/respond -> PermissionResponseResult

ADR-019: Graph compilation and ``aggregator.ingest()`` no longer run in
the gateway.  All work is dispatched to the worker process via
HTTP POST to ``/dispatch``.  The ``GraphRegistry`` has been removed; the
worker owns graph lifecycle.

See: ADR-007 (FastAPI, SPA mount)
     ADR-011 (Frontend-Backend Wire Contract)
     ADR-019 (Service Separation)
"""

import asyncio
import contextlib
import hashlib
import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import StateSnapshot
from opentelemetry import propagate as _otel_propagate
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..core import (
    EventAggregator,
    ThreadMetadata,
    build_context_preamble,
    build_initial_vault_index,
    discover_context_refs,
    discover_team_preset_ids,
    generate_nickname,
    load_team_config,
    settings,
)
from ..core.aggregator import classify_tool_kind
from ..database.checkpoints import Checkpointer
from ..database.crud import (
    ApprovalStatus,
    ControlActionResultStatus,
    ControlActionType,
    PermissionRequestStatus,
    RepairStatus,
    ThreadStatus,
    create_control_action,
    create_thread,
    delete_thread,
    get_control_action_by_idempotency_key,
    get_pending_permission_requests,
    get_permission_request,
    get_thread,
    get_thread_metadata,
    list_threads,
    record_permission_response_submission,
    set_thread_approval_state,
    set_thread_repair_state,
    update_thread_status,
)
from ..database.session import get_db
from ..thread.errors import (
    ConfigError,
    NicknameConflictError,
    TeamConfigNotFoundError,
)
from .projection import (
    apply_checkpoint_projection,
    enrich_snapshot_from_durable_state,
    enrich_snapshot_from_execution_state,
    project_checkpoint_tuple,
)
from .schemas.enums import AgentLifecycleState, PermissionType, ToolCallStatus, ToolKind
from .schemas.events import PlanEntry
from .schemas.internal import DispatchRequest
from .schemas.rest import (
    AgentStatusEntry,
    CancelThreadResponse,
    CreateThreadRequest,
    CreateThreadResponse,
    PendingPermission,
    PermissionResponseRequest,
    PermissionResponseResult,
    SendMessageRequest,
    SendMessageResponse,
    TeamPresetsResponse,
    TeamPresetSummary,
    TeamStatusResponse,
    ThreadListResponse,
    ThreadSummary,
)
from .schemas.snapshots import (
    ArtifactSnapshot,
    MessageSnapshot,
    ThreadStateSnapshot,
    ToolCallSnapshot,
    _AgentSnapshot,
    _PermissionOptionSnapshot,
    _PermissionSnapshot,
)

__all__ = [
    "get_aggregator",
    "get_checkpointer",
    "get_circuit_breaker",
    "get_worker_client",
    "get_worker_spawner",
    "router",
]


logger = logging.getLogger(__name__)

_PLAN_APPROVAL_PAUSE_CAUSES = {
    PermissionType.PLAN_APPROVAL.value,
    "plan_approval_request",
}

router = APIRouter()


def _trace_headers() -> dict[str, str]:
    """Build W3C trace context headers for gateway-to-worker HTTP calls (TEL-03).

    Injects the current OTel span context (``traceparent`` / ``tracestate``)
    into a headers dict so distributed traces continue from gateway to worker.
    Returns an empty dict when no active span is present (no-op mode).
    """
    carrier: dict[str, str] = {}
    _otel_propagate.inject(carrier)
    return carrier


def _mark_worker_connected(request: Request) -> None:
    """Update the gateway heartbeat timestamp after a confirmed worker dispatch.

    Sets ``worker_last_heartbeat_ts`` to the current monotonic clock value so
    that the ``/health`` endpoint reports ``worker_connected: true`` immediately
    after the first successful dispatch rather than waiting for the worker's
    next periodic heartbeat (F-23 fix).

    The value written here is identical in shape to the timestamp written by
    ``POST /internal/heartbeat``, so existing liveness logic is reused without
    any new state fields.
    """
    request.app.state.worker_last_heartbeat_ts = time.monotonic()


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------
# Injected at lifespan startup via app.state; the dependencies just read it.


def get_aggregator(request: Request) -> EventAggregator:
    """FastAPI dependency for the EventAggregator singleton."""
    aggregator: EventAggregator | None = getattr(request.app.state, "aggregator", None)
    if aggregator is None:
        raise RuntimeError("EventAggregator not initialised in app state")
    return aggregator


def get_checkpointer(request: Request) -> Checkpointer:
    """FastAPI dependency for the LangGraph checkpointer (read-only, ADR-019)."""
    checkpointer: Checkpointer | None = getattr(request.app.state, "checkpointer", None)
    if checkpointer is None:
        raise RuntimeError("LangGraph checkpointer not initialised in app state")
    return checkpointer


def get_worker_client(request: Request) -> httpx.AsyncClient:
    """FastAPI dependency for the httpx client pointing at the worker."""
    client: httpx.AsyncClient | None = getattr(request.app.state, "worker_client", None)
    if client is None:
        raise RuntimeError("Worker httpx client not initialised in app state")
    return client


def get_circuit_breaker(request: Request) -> Any:
    """FastAPI dependency for the WorkerCircuitBreaker (PROD-028)."""
    cb = getattr(request.app.state, "circuit_breaker", None)
    if cb is None:
        raise RuntimeError("WorkerCircuitBreaker not initialised in app state")
    return cb


def get_worker_spawner(request: Request) -> Any:
    """FastAPI dependency for the LazyWorkerSpawner (PHASE-1a)."""
    spawner = getattr(request.app.state, "worker_spawner", None)
    if spawner is None:
        raise RuntimeError("LazyWorkerSpawner not initialised in app state")
    return spawner


async def get_services(
    db: AsyncSession = Depends(get_db),
    aggregator: EventAggregator = Depends(get_aggregator),
    checkpointer: Checkpointer = Depends(get_checkpointer),
    worker_client: httpx.AsyncClient = Depends(get_worker_client),
) -> tuple[AsyncSession, EventAggregator, Checkpointer, httpx.AsyncClient]:
    """Dependency for bundling all required services into a single injection point.

    ADR-019: No longer includes GraphRegistry or TaskGroup -- the worker owns
    graph lifecycle, and the gateway does not run background agent tasks.
    """
    return db, aggregator, checkpointer, worker_client


# ---------------------------------------------------------------------------
# GET /health -- Aggregated health check
# ---------------------------------------------------------------------------


@router.get("/health")
async def health(
    request: Request,
    db: AsyncSession = Depends(get_db),
    worker_client: httpx.AsyncClient = Depends(get_worker_client),
    circuit_breaker: Any = Depends(get_circuit_breaker),
    worker_spawner: Any = Depends(get_worker_spawner),
) -> dict:
    """Public health endpoint aggregating gateway, worker, and database status."""
    checks: dict[str, dict[str, str]] = {}

    # Gateway -- always ok if we're responding
    checks["gateway"] = {"status": "ok"}

    # Database -- execute a trivial query
    try:
        await db.execute(text("SELECT 1"))
        checks["database"] = {
            "status": "ok",
            "backend": settings.resolved_database_backend,
            "postgres_required": "yes" if settings.postgres_required else "no",
        }
    except Exception:
        logger.exception("Health check: database probe failed")
        checks["database"] = {
            "status": "error",
            "backend": settings.resolved_database_backend,
            "detail": "database probe failed",
            "postgres_required": "yes" if settings.postgres_required else "no",
        }

    checkpointer_status_builder = getattr(
        request.app,
        "state",
        None,
    )
    checkpointer_present = (
        getattr(checkpointer_status_builder, "checkpointer", None) is not None
        if checkpointer_status_builder is not None
        else False
    )
    checks["checkpoint"] = {
        "status": "ok" if checkpointer_present else "error",
        "backend": settings.resolved_checkpoint_backend,
        "postgres_required": "yes" if settings.postgres_required else "no",
    }

    # Worker -- ping its /health endpoint
    try:
        resp = await worker_client.get("/health", timeout=5.0)
        resp.raise_for_status()
        checks["worker"] = {"status": "ok"}
    except Exception:
        logger.exception("Health check: worker probe failed")
        checks["worker"] = {"status": "error", "detail": "worker probe failed"}

    # Circuit breaker + lazy spawner state (informational)
    checks["circuit_breaker"] = {"status": circuit_breaker.state}
    checks["worker_spawned"] = {"status": "yes" if worker_spawner.spawned else "no"}
    worker_last_restart_detail = getattr(
        request.app.state,
        "worker_last_restart_detail",
        None,
    )
    worker_stderr_log_path = getattr(
        request.app.state,
        "worker_stderr_log_path",
        None,
    )
    if worker_stderr_log_path is not None:
        checks["worker_stderr_log"] = {"status": "configured"}

    ready = (
        checks["gateway"]["status"] == "ok"
        and checks["database"]["status"] == "ok"
        and checks["checkpoint"]["status"] == "ok"
        and checks["worker"]["status"] == "ok"
        and checks["circuit_breaker"]["status"] == "closed"
    )
    repair_summary = getattr(request.app.state, "repair_summary", {})
    sqlite_fallback_diagnostics = getattr(
        request.app.state, "sqlite_fallback_diagnostics", None
    )
    return {
        "status": "ok" if ready else "degraded",
        "checks": checks,
        "database_backend": settings.resolved_database_backend,
        "checkpoint_backend": settings.resolved_checkpoint_backend,
        "postgres_required": settings.postgres_required,
        "worker_last_restart_detail": worker_last_restart_detail,
        "worker_stderr_log_path": worker_stderr_log_path,
        "repair_backlog": repair_summary.get("repair_backlog", 0),
        "paused_resumable": repair_summary.get("paused_resumable", 0),
        "checkpoint_unavailable": repair_summary.get("checkpoint_unavailable", 0),
        "sqlite_fallback": sqlite_fallback_diagnostics,
    }


# ---------------------------------------------------------------------------
# POST /threads -- Create a new orchestration thread
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

    # API-H6: resolve() prevents symlink traversal attacks
    ws_root = Path(metadata.workspace_root).resolve()
    if not ws_root.is_dir():
        raise HTTPException(
            status_code=422,
            detail=(
                "workspace_root is not an existing directory: "
                f"{metadata.workspace_root!r}"
            ),
        )

    # Auto-discover .vault/ documents if feature_tag set and context_refs empty
    if metadata.feature_tag and not metadata.context_refs:
        metadata.context_refs = discover_context_refs(ws_root, metadata.feature_tag)

    # Generate nickname if not provided
    topology = "default"
    if body.team_preset:
        try:
            tc = load_team_config(body.team_preset, workspace_root=ws_root)
            topology = tc.topology.type
        except (ConfigError, TeamConfigNotFoundError):
            pass  # non-critical: fall back to "default" topology for nickname
    nickname = metadata.nickname or generate_nickname(
        metadata.feature_tag, topology, thread_id
    )
    metadata.nickname = nickname

    return ws_root, nickname, metadata.model_dump_json()


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
    """Create a new orchestration thread and dispatch to the worker.

    If ``team_preset`` is set in the request, the work is dispatched to the
    worker process which handles graph compilation and ``ingest()`` execution
    (ADR-019).

    When ``metadata`` is provided (ADR-014), the endpoint:
    - Validates ``workspace_root`` as an existing directory (422 if not)
    - Auto-discovers ``.vault/`` documents when ``feature_tag`` is set
    - Generates a nickname if not explicitly provided
    - Sends context preamble content to the worker for injection
    - Threads ``workspace_root`` to the worker for config resolution
    """
    try:
        db, _aggregator, _checkpointer, worker_client = services
        thread_id = uuid4().hex

        # --- ADR-014: Metadata processing ---
        ws_root, nickname, metadata_json = _process_metadata(body, thread_id)

        # ADR-034: top-level nickname overrides metadata-derived nickname when
        # metadata is absent (CLI users without full metadata can still name threads).
        if nickname is None and body.nickname is not None:
            nickname = body.nickname

        # Create thread in DB
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

        # Dispatch to worker if a team preset was requested (ADR-019)
        if body.team_preset:
            # Build context preamble content if metadata provided (ADR-014 S2.3)
            context_preamble: str | None = None
            if body.metadata is not None:
                preamble_msg = build_context_preamble(body.metadata)
                context_preamble = (
                    preamble_msg.content
                    if isinstance(preamble_msg.content, str)
                    else str(preamble_msg.content)
                )

            # Resolve autonomous: explicit request value overrides team default.
            # None = defer to team preset's auto_approve setting (TOML-04).
            effective_autonomous: bool = False
            if body.autonomous is not None:
                effective_autonomous = body.autonomous
            else:
                try:
                    _tc = load_team_config(body.team_preset, workspace_root=ws_root)
                    effective_autonomous = _tc.permissions.auto_approve
                except (ConfigError, TeamConfigNotFoundError):
                    pass  # fall back to False (supervised)

            # ADR-019: SDD blackboard fields
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
            await worker_spawner.ensure_worker()
            circuit_breaker.pre_dispatch()
            try:
                resp = await worker_client.post(
                    "/dispatch",
                    json=dispatch.model_dump(),
                    headers=_trace_headers(),
                )
                # PROD-067: worker 429 means it is alive but at capacity.
                # Do NOT record CB success — the thread never executed.
                if resp.status_code == httpx.codes.TOO_MANY_REQUESTS:
                    logger.warning(
                        "Worker at capacity (429) for dispatch_id=%s thread %s"
                        " — thread marked as failed",
                        dispatch.dispatch_id,
                        thread.id,
                        extra={
                            "thread_id": thread.id,
                            "dispatch_id": dispatch.dispatch_id,
                            "action": dispatch.action,
                            "http_status_code": resp.status_code,
                        },
                    )
                    await update_thread_status(db, thread.id, ThreadStatus.FAILED)
                    await db.commit()
                    raise HTTPException(
                        status_code=503,
                        detail="Worker at capacity — try again later",
                    ) from None
                circuit_breaker.record_success()
                _mark_worker_connected(request)
            except httpx.HTTPError:
                circuit_breaker.record_failure()
                logger.warning(
                    "Failed to dispatch ingest dispatch_id=%s for thread %s",
                    dispatch.dispatch_id,
                    thread.id,
                    extra={
                        "thread_id": thread.id,
                        "dispatch_id": dispatch.dispatch_id,
                        "action": dispatch.action,
                    },
                    exc_info=True,
                )
                # PROD-012: Mark thread as FAILED so it doesn't stay SUBMITTED
                # forever when the worker is unreachable.
                await update_thread_status(db, thread.id, ThreadStatus.FAILED)
                await db.commit()
                raise HTTPException(
                    status_code=502,
                    detail="Worker unreachable — thread marked as failed",
                ) from None
            # PROD-015 parity: advance to RUNNING after successful dispatch so
            # the thread does not stay SUBMITTED while the worker executes.
            # Mirrors the identical pattern in send_message and permission-resume.
            await update_thread_status(db, thread.id, ThreadStatus.RUNNING)
            await set_thread_repair_state(
                db,
                thread.id,
                repair_status=RepairStatus.HEALTHY,
                execution_readiness=RepairStatus.HEALTHY.value,
                last_applied_action=ControlActionType.INGEST,
            )

        # Commit only after all synchronous setup succeeds -- prevents orphaned
        # thread rows when metadata processing fails (H9 fix).
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
# GET /threads -- List threads (paginated)
# ---------------------------------------------------------------------------


@router.get("/threads", response_model=ThreadListResponse)
async def list_threads_endpoint(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    status: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> ThreadListResponse:
    """List orchestration threads with pagination and optional status filter.

    Enriches each thread summary with metadata fields (ADR-014) when
    available. Legacy threads without metadata gracefully omit these fields.
    """
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
        # Parse metadata JSON for summary fields (graceful fallback for legacy threads)
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
                pass  # graceful fallback for legacy threads with invalid metadata

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
# GET /threads/{thread_id}/metadata -- Thread metadata (ADR-014)
# ---------------------------------------------------------------------------


@router.get("/threads/{thread_id}/metadata", response_model=ThreadMetadata)
async def get_thread_metadata_endpoint(
    thread_id: str,
    db: AsyncSession = Depends(get_db),
) -> ThreadMetadata:
    """Return the full ThreadMetadata object for a thread.

    Used by the inspector panel for detailed provenance display.
    Returns 404 if the thread does not exist or has no metadata.
    """
    meta_json = await get_thread_metadata(db, thread_id)
    if meta_json is None:
        raise HTTPException(status_code=404, detail="Thread or metadata not found")
    return ThreadMetadata.model_validate_json(meta_json)


# ---------------------------------------------------------------------------
# GET /threads/{thread_id}/state -- Thread state snapshot (reconnection)
# ---------------------------------------------------------------------------


def _enrich_snapshot_from_state(
    snapshot: ThreadStateSnapshot,
    state: StateSnapshot,
    aggregator: EventAggregator | None = None,
) -> ThreadStateSnapshot:
    """Populate snapshot fields from LangGraph checkpointer state.

    Maps LangChain ``BaseMessage`` objects to ``MessageSnapshot`` and
    extracts ``checkpoint_id``, plan, artifacts from the state config.
    Populates agents and pending permissions from the aggregator.
    """
    msgs: list[MessageSnapshot] = []
    for m in state.values.get("messages", []):
        if isinstance(m, HumanMessage):
            role = "user"
        elif isinstance(m, AIMessage):
            role = "assistant"
        elif isinstance(m, ToolMessage):
            role = "tool"
        else:
            role = "system"

        content = m.content if isinstance(m.content, str) else str(m.content)

        # Prefer actual message timestamp from response_metadata or additional_kwargs;
        # fall back to now() only if the provider did not populate a timestamp.
        ts: datetime | None = None
        for meta_src in (
            getattr(m, "response_metadata", None) or {},
            getattr(m, "additional_kwargs", None) or {},
        ):
            raw_ts = meta_src.get("created_at") or meta_src.get("timestamp")
            if isinstance(raw_ts, datetime):
                ts = raw_ts
                break
            if isinstance(raw_ts, str):
                with contextlib.suppress(ValueError):
                    ts = datetime.fromisoformat(raw_ts)
                if ts is not None:
                    break
        if ts is None:
            ts = datetime.now(UTC)

        # Stable fallback: deterministic hash of role+content so repeated
        # snapshot fetches return the same message_id (uuid4 would change each
        # call, breaking client-side deduplication for messages without a
        # persisted LangChain message id).
        stored_id: str | None = getattr(m, "id", None)
        message_id = (
            stored_id or hashlib.sha256(f"{role}:{content}".encode()).hexdigest()[:32]
        )

        msgs.append(
            MessageSnapshot(
                message_id=message_id,
                role=role,
                content=content,
                agent_id=getattr(m, "name", None),
                timestamp=ts,
            )
        )

    checkpoint_id: str | None = None
    if hasattr(state, "config") and state.config:
        checkpoint_id = state.config.get("configurable", {}).get("checkpoint_id")

    # Extract plan entries from checkpoint channel_values
    plan_raw = state.values.get("current_plan", [])
    plan_entries: list[PlanEntry] = []
    for entry in plan_raw:
        if isinstance(entry, dict):
            plan_entries.append(
                PlanEntry(
                    content=entry.get("content", ""),
                    status=entry.get("status", "pending"),
                    priority=entry.get("priority", "medium"),
                )
            )
        elif isinstance(entry, PlanEntry):
            plan_entries.append(entry)

    # Extract artifacts from checkpoint channel_values
    artifacts_raw = state.values.get("artifacts", [])
    artifact_snapshots: list[ArtifactSnapshot] = []
    for art in artifacts_raw:
        if isinstance(art, dict):
            artifact_snapshots.append(
                ArtifactSnapshot(
                    artifact_id=art.get("artifact_id", ""),
                    filename=art.get("filename", ""),
                    content=art.get("content", ""),
                    complete=art.get("complete", True),
                )
            )

    # Populate agents from aggregator node summaries + agent states
    agent_snapshots: list[_AgentSnapshot] = []
    if aggregator is not None:
        node_summaries = aggregator.get_node_summaries()
        agent_states = aggregator.get_agent_states()
        for node in node_summaries:
            agent_id = node.get("agent_id", node.get("node_name", ""))
            agent_snapshots.append(
                _AgentSnapshot(
                    agent_id=agent_id,
                    node_name=node.get("node_name", ""),
                    state=agent_states.get(agent_id, AgentLifecycleState.IDLE),
                    role=node.get("role", ""),
                    display_name=node.get("display_name", ""),
                    description=node.get("description", ""),
                )
            )

    # Populate pending permissions from aggregator
    perm_snapshots: list[_PermissionSnapshot] = []
    if aggregator is not None:
        thread_id = snapshot.thread_id
        for perm in aggregator.get_pending_permissions(thread_id):
            perm_snapshots.append(
                _PermissionSnapshot(
                    request_id=perm.request_id,
                    description=perm.description,
                    tool_call=perm.tool_call,
                    options=[
                        _PermissionOptionSnapshot(
                            option_id=opt.option_id,
                            name=opt.name,
                            kind=opt.kind,
                        )
                        for opt in perm.options
                    ],
                )
            )

    # Extract tool calls from AIMessage.tool_calls, cross-reference with
    # ToolMessage to determine completion status.
    answered_tool_ids: set[str] = {
        m.tool_call_id
        for m in state.values.get("messages", [])
        if isinstance(m, ToolMessage) and hasattr(m, "tool_call_id")
    }
    tool_call_snapshots: list[ToolCallSnapshot] = []
    checkpoint_tc_ids: set[str] = set()
    for m in state.values.get("messages", []):
        if isinstance(m, AIMessage) and m.tool_calls:
            for tc in m.tool_calls:
                tc_id = tc.get("id", "")
                tc_name = tc.get("name", "unknown_tool")
                checkpoint_tc_ids.add(tc_id)
                tool_call_snapshots.append(
                    ToolCallSnapshot(
                        tool_call_id=tc_id,
                        title=tc_name,
                        kind=classify_tool_kind(tc_name),
                        status=(
                            ToolCallStatus.COMPLETED
                            if tc_id in answered_tool_ids
                            else ToolCallStatus.PENDING
                        ),
                    )
                )

    # F-38: Merge tool calls from aggregator in-memory state for tool calls
    # not present in the checkpoint.  This covers cases where: (a) the
    # checkpoint is stale / not yet written, (b) the gateway restarted but
    # the worker relayed tool_call events that the aggregator tracked, or
    # (c) the checkpoint's channel_values are not deserialized objects.
    if aggregator is not None:
        thread_id = snapshot.thread_id
        aggregator_tc_states = aggregator.get_tool_call_states(thread_id)
        for tc_id, tc_state in aggregator_tc_states.items():
            if tc_id in checkpoint_tc_ids:
                continue
            try:
                kind = ToolKind(tc_state.get("kind", ToolKind.OTHER.value))
            except ValueError:
                kind = ToolKind.OTHER
            try:
                status = ToolCallStatus(
                    tc_state.get("status", ToolCallStatus.PENDING.value)
                )
            except ValueError:
                status = ToolCallStatus.PENDING
            tool_call_snapshots.append(
                ToolCallSnapshot(
                    tool_call_id=tc_id,
                    title=tc_state.get("title", "unknown_tool"),
                    kind=kind,
                    status=status,
                )
            )

    return snapshot.model_copy(
        update={
            "messages": msgs,
            "checkpoint_id": checkpoint_id,
            "plan": plan_entries,
            "artifacts": artifact_snapshots,
            "agents": agent_snapshots,
            "pending_permissions": perm_snapshots,
            "tool_calls": tool_call_snapshots,
        }
    )


class _MinimalState:
    """Minimal adapter for `_enrich_snapshot_from_state()` reuse."""

    def __init__(self, values: dict, cfg: dict | None = None) -> None:
        self.values = values
        self.config = cfg


async def _load_checkpoint_history_depth(
    checkpointer: Checkpointer,
    config: RunnableConfig,
    *,
    limit: int = 2,
) -> int | None:
    """Return recent checkpoint history depth when the saver supports listing."""
    count = 0
    async for _item in checkpointer.alist(config, limit=limit):
        count += 1
    return count


def _finalize_snapshot_replay_status(
    snapshot: ThreadStateSnapshot,
    *,
    checkpoint_loaded: bool,
    checkpoint_present: bool,
    checkpoint_error: bool,
    thread_status: str,
) -> ThreadStateSnapshot:
    """Apply the reconnect snapshot replay/degradation contract."""
    if checkpoint_loaded:
        snapshot.replay_status = "durable"
    elif checkpoint_error:
        snapshot.snapshot_complete = False
        snapshot.replay_status = "unknown"
    elif checkpoint_present:
        snapshot.snapshot_complete = False
        snapshot.replay_status = "best_effort"
    elif thread_status == ThreadStatus.SUBMITTED.value:
        snapshot.snapshot_complete = True
        snapshot.replay_status = "unknown"
    else:
        snapshot.snapshot_complete = False
        if "checkpoint_missing" not in snapshot.degraded_reasons:
            snapshot.degraded_reasons.append("checkpoint_missing")
        snapshot.replay_status = "gap_detected"
    return snapshot


@router.get("/threads/{thread_id}/state", response_model=ThreadStateSnapshot)
async def get_thread_state_endpoint(
    thread_id: str,
    db: AsyncSession = Depends(get_db),
    aggregator: EventAggregator = Depends(get_aggregator),
    checkpointer: Checkpointer = Depends(get_checkpointer),
) -> ThreadStateSnapshot:
    """Return a complete thread state snapshot for client reconnection.

    The ``last_sequence`` field enables gap detection: the client discards
    any subsequent WebSocket events with ``sequence <= last_sequence``
    (ADR-011 section 2.3).

    ADR-019: The graph is no longer registered locally.  Snapshot enrichment
    reads directly from the shared SQLite checkpointer (read-only in the
    gateway, safe under WAL mode).  If checkpointer data is not
    available (e.g. worker hasn't written yet), a basic snapshot is returned.
    """
    thread = await get_thread(db, thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found")

    last_seq = aggregator.get_sequence(thread_id)

    snapshot = ThreadStateSnapshot(
        thread_id=thread.id,
        status=thread.status,
        last_sequence=last_seq,
        repair_status=thread.repair_status,
        execution_readiness=thread.execution_readiness,
        approval_status=thread.approval_status,
        approval_request_id=thread.approval_request_id,
    )
    snapshot = await enrich_snapshot_from_durable_state(
        db, thread=thread, snapshot=snapshot
    )
    checkpoint_loaded = False
    checkpoint_present = False
    checkpoint_error = False

    # ADR-019: Try to enrich from checkpointer directly.
    # aget_tuple() returns a CheckpointTuple with the checkpoint dict
    # containing channel_values (messages, plan, artifacts, etc.).
    try:
        config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
        checkpoint_tuple = await asyncio.wait_for(
            checkpointer.aget_tuple(config),
            timeout=10.0,
        )
        if checkpoint_tuple is not None:
            checkpoint_present = True
            history_depth: int | None = None
            try:
                history_depth = await asyncio.wait_for(
                    _load_checkpoint_history_depth(checkpointer, config),
                    timeout=10.0,
                )
            except TimeoutError:
                if "checkpoint_history_timeout" not in snapshot.degraded_reasons:
                    snapshot.degraded_reasons.append("checkpoint_history_timeout")
            except Exception:
                if "checkpoint_history_unavailable" not in snapshot.degraded_reasons:
                    snapshot.degraded_reasons.append("checkpoint_history_unavailable")
            projection = project_checkpoint_tuple(
                checkpoint_tuple,
                thread_id=thread_id,
                history_depth=history_depth,
            )

            minimal_state = _MinimalState(
                values=projection.channel_values,
                cfg=projection.config,
            )
            snapshot = _enrich_snapshot_from_state(
                snapshot,
                minimal_state,  # type: ignore[arg-type]
                aggregator=aggregator,
            )
            snapshot = apply_checkpoint_projection(snapshot, projection)
            checkpoint_loaded = True
    except TimeoutError:
        logger.warning(
            "Timed out loading checkpoint for thread %s after 10s; "
            "returning partial snapshot",
            thread_id,
        )
        checkpoint_error = True
        snapshot.snapshot_complete = False
        snapshot.degraded_reasons.append("checkpoint_timeout")
        snapshot.replay_status = "unknown"
        snapshot.repair_status = RepairStatus.CHECKPOINT_UNAVAILABLE.value
    except Exception:
        logger.warning(
            "Could not load checkpoint for thread %s; returning partial snapshot",
            thread_id,
            exc_info=True,
        )
        checkpoint_error = True
        snapshot.snapshot_complete = False
        snapshot.degraded_reasons.append("checkpoint_unavailable")
        snapshot.replay_status = "unknown"
        snapshot.repair_status = RepairStatus.CHECKPOINT_UNAVAILABLE.value

    snapshot = await enrich_snapshot_from_execution_state(
        db,
        thread=thread,
        snapshot=snapshot,
        checkpoint_present=checkpoint_present,
        checkpoint_id=snapshot.checkpoint_id,
    )

    return _finalize_snapshot_replay_status(
        snapshot,
        checkpoint_loaded=checkpoint_loaded,
        checkpoint_present=checkpoint_present,
        checkpoint_error=checkpoint_error,
        thread_status=thread.status,
    )


# ---------------------------------------------------------------------------
# POST /threads/{thread_id}/messages -- Send message into thread
# ---------------------------------------------------------------------------


@router.post(
    "/threads/{thread_id}/messages",
    status_code=202,
    response_model=SendMessageResponse,
)
async def send_message_endpoint(
    thread_id: str,
    body: SendMessageRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _aggregator: EventAggregator = Depends(get_aggregator),
    worker_client: httpx.AsyncClient = Depends(get_worker_client),
    circuit_breaker: Any = Depends(get_circuit_breaker),
    worker_spawner: Any = Depends(get_worker_spawner),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> SendMessageResponse:
    """Send a user message into an existing thread.

    Returns 202 Accepted immediately; the message is dispatched to the
    worker process for graph execution (ADR-019).
    """
    thread = await get_thread(db, thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found")

    if thread.status == ThreadStatus.INPUT_REQUIRED.value:
        raise HTTPException(
            status_code=409,
            detail=(
                "Cannot send a follow-up message while the thread is paused for input"
            ),
        )

    terminal_statuses = (
        ThreadStatus.ARCHIVED,
        ThreadStatus.COMPLETED,
        ThreadStatus.FAILED,
        ThreadStatus.CANCELLED,
    )
    if thread.status in terminal_statuses:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot send messages to thread in {thread.status!r} state",
        )

    logger.info(
        "Message received for thread %s: %d chars",
        thread_id,
        len(body.content),
    )

    agent_id = body.agent_id or "vaultspec-supervisor"
    resolved_idempotency_key = (
        idempotency_key
        or hashlib.sha256(
            f"{thread_id}:message:{agent_id}:{body.content}".encode()
        ).hexdigest()
    )
    existing_action = await get_control_action_by_idempotency_key(
        db, thread_id=thread_id, idempotency_key=resolved_idempotency_key
    )
    if existing_action is not None:
        return SendMessageResponse(
            status="accepted",
            thread_id=thread_id,
            accepted=True,
            applied=existing_action.applied_at is not None,
            action_status=existing_action.result_status,
            action_id=existing_action.id,
            idempotency_key=resolved_idempotency_key,
        )

    action = await create_control_action(
        db,
        thread_id=thread_id,
        action_type=ControlActionType.MESSAGE_FOLLOWUP_REQUESTED,
        idempotency_key=resolved_idempotency_key,
        payload={"content": body.content, "agent_id": agent_id},
    )
    await set_thread_repair_state(
        db,
        thread_id,
        repair_status=RepairStatus.HEALTHY,
        execution_readiness=RepairStatus.HEALTHY.value,
        last_requested_action=ControlActionType.MESSAGE_FOLLOWUP_REQUESTED,
    )

    # Look up team_preset and workspace_root from DB for lazy recompile
    # (same pattern as respond_to_permission_endpoint, T22).
    team_preset: str | None = None
    workspace_root: str | None = None
    if thread.team_preset:
        team_preset = thread.team_preset
    if thread.thread_metadata:
        try:
            meta = json.loads(thread.thread_metadata)
            workspace_root = meta.get("workspace_root")
        except (json.JSONDecodeError, AttributeError):
            pass

    # Dispatch to worker (ADR-019)
    dispatch = DispatchRequest(
        action="ingest",
        thread_id=thread_id,
        agent_id=agent_id,
        content=body.content,
        team_preset=team_preset,
        workspace_root=workspace_root,
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
    await worker_spawner.ensure_worker()
    circuit_breaker.pre_dispatch()
    try:
        resp = await worker_client.post(
            "/dispatch",
            json=dispatch.model_dump(),
            headers=_trace_headers(),
        )
        # PROD-068: worker 429 means alive but at capacity — message not queued.
        if resp.status_code == httpx.codes.TOO_MANY_REQUESTS:
            logger.warning(
                "Worker at capacity (429) for dispatch_id=%s thread %s"
                " — message rejected",
                dispatch.dispatch_id,
                thread_id,
                extra={
                    "thread_id": thread_id,
                    "dispatch_id": dispatch.dispatch_id,
                    "action": dispatch.action,
                    "agent_id": agent_id,
                    "http_status_code": resp.status_code,
                },
            )
            raise HTTPException(
                status_code=503,
                detail="Worker at capacity — try again later",
            ) from None
        circuit_breaker.record_success()
        _mark_worker_connected(request)
    except httpx.HTTPError:
        circuit_breaker.record_failure()
        logger.warning(
            "Failed to dispatch message dispatch_id=%s for thread %s",
            dispatch.dispatch_id,
            thread_id,
            extra={
                "thread_id": thread_id,
                "dispatch_id": dispatch.dispatch_id,
                "action": dispatch.action,
                "agent_id": agent_id,
            },
            exc_info=True,
        )
        # PROD-015: Set thread to FAILED on dispatch error instead of
        # leaving it in a stale RUNNING state.
        await update_thread_status(db, thread_id, ThreadStatus.FAILED)
        await db.commit()
        raise HTTPException(
            status_code=502,
            detail="Worker unreachable — thread marked as failed",
        ) from None

    # PROD-015: Only set RUNNING after successful dispatch.
    await update_thread_status(db, thread_id, ThreadStatus.RUNNING)
    await set_thread_repair_state(
        db,
        thread_id,
        repair_status=RepairStatus.HEALTHY,
        execution_readiness=RepairStatus.HEALTHY.value,
        last_applied_action=ControlActionType.MESSAGE_FOLLOWUP_REQUESTED,
    )
    await db.commit()

    return SendMessageResponse(
        status="accepted",
        thread_id=thread_id,
        accepted=True,
        applied=False,
        action_status=ControlActionResultStatus.ACCEPTED_NOT_APPLIED.value,
        action_id=action.id,
        idempotency_key=resolved_idempotency_key,
    )


# ---------------------------------------------------------------------------
# GET /team/status -- Team status snapshot
# ---------------------------------------------------------------------------


@router.get("/team/status", response_model=TeamStatusResponse)
async def get_team_status_endpoint(
    request: Request,
    aggregator: EventAggregator = Depends(get_aggregator),
    db: AsyncSession = Depends(get_db),
) -> TeamStatusResponse:
    """Return current team status: agents, active threads, pending permissions.

    ADR-019 NOTE: The gateway aggregator is lightweight.  Agent
    summaries come from node metadata registered via the worker relay.
    Pending permissions are tracked by the aggregator (MCP-R5).
    """
    heartbeat_threads = getattr(request.app.state, "worker_active_threads", [])
    active_threads = sorted(
        set(heartbeat_threads) | set(aggregator.get_active_thread_ids())
    )
    node_summaries = aggregator.get_node_summaries()
    agent_states = aggregator.get_agent_states()

    agents = [
        AgentStatusEntry(
            agent_id=s["agent_id"],
            node_name=s["node_name"],
            state=agent_states.get(s["agent_id"], AgentLifecycleState.IDLE),
            role=s.get("role", ""),
            display_name=s.get("display_name", ""),
            description=s.get("description", ""),
        )
        for s in node_summaries
    ]

    durable_pending = await get_pending_permission_requests(db)
    pending = [
        PendingPermission(
            request_id=permission.request_id,
            thread_id=permission.thread_id,
            description=permission.description,
            request_status=permission.request_status,
        )
        for permission in durable_pending
    ]
    known_request_ids = {permission.request_id for permission in pending}
    pending.extend(
        PendingPermission(
            request_id=event.request_id,
            thread_id=event.thread_id,
            description=event.description,
        )
        for event in aggregator.get_pending_permissions()
        if event.request_id not in known_request_ids
    )

    return TeamStatusResponse(
        agents=agents,
        active_threads=active_threads,
        pending_permissions=pending,
    )


# ---------------------------------------------------------------------------
# GET /teams -- List available team presets (ADR-013 S6)
# ---------------------------------------------------------------------------


@router.get("/teams", response_model=TeamPresetsResponse)
async def list_team_presets_endpoint() -> TeamPresetsResponse:
    """Return all available team presets for the team picker UI.

    Dynamically discovers presets by globbing
    ``src/vaultspec_a2a/core/presets/teams/*.toml``.
    Workspace-local overrides are not included in this listing (they
    shadow individual presets but are not auto-discovered in v1).
    """
    summaries: list[TeamPresetSummary] = []
    for preset_id in sorted(discover_team_preset_ids()):
        try:
            tc = load_team_config(preset_id)
        except TeamConfigNotFoundError:
            logger.warning("Bundled team preset not found: %s", preset_id)
            continue

        summaries.append(
            TeamPresetSummary(
                id=tc.id,
                display_name=tc.display_name,
                description=tc.description,
                topology=tc.topology.type,
                worker_count=len(tc.workers),
            )
        )

    return TeamPresetsResponse(presets=summaries)


# ---------------------------------------------------------------------------
# POST /permissions/{request_id}/respond -- Permission response (REST)
# ---------------------------------------------------------------------------


@router.post(
    "/permissions/{request_id}/respond",
    response_model=PermissionResponseResult,
)
async def respond_to_permission_endpoint(
    request_id: str,
    body: PermissionResponseRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    worker_client: httpx.AsyncClient = Depends(get_worker_client),
    aggregator: EventAggregator = Depends(get_aggregator),
    circuit_breaker: Any = Depends(get_circuit_breaker),
    worker_spawner: Any = Depends(get_worker_spawner),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> PermissionResponseResult:
    """Submit a permission response via REST for guaranteed delivery.

    Permission responses are handled via REST rather than WebSocket
    to ensure guaranteed delivery (ADR-011 S3.1).

    ADR-019: The resume is dispatched to the worker which owns the graph
    and calls ``Command(resume=option_id)`` on the interrupted graph.

    The DB is queried for ``team_preset`` and ``workspace_root`` so the
    worker can lazily recompile the graph if it was evicted or the worker
    restarted since the thread was created (ADR-019 lazy recompile path).
    """
    logger.info(
        "Permission response: request_id=%s, option_id=%s",
        request_id,
        body.option_id,
        extra={
            "request_id": request_id,
            "thread_id": request_id.split(":", 1)[0] if ":" in request_id else None,
            "action": "permission_response",
            "option_id": body.option_id,
        },
    )

    permission = await get_permission_request(db, request_id)
    thread_id = permission.thread_id if permission is not None else ""
    if not thread_id and ":" in request_id:
        thread_id, _ = request_id.split(":", 1)
    if not thread_id:
        return PermissionResponseResult(
            request_id=request_id,
            accepted=False,
            applied=False,
            action_status=ControlActionResultStatus.REJECTED_INVALID_STATE.value,
            thread_id="",
        )

    thread_record = await get_thread(db, thread_id)
    if thread_record is None:
        raise HTTPException(status_code=404, detail="Thread not found")
    if permission is None:
        raise HTTPException(
            status_code=409,
            detail="Permission request is not durably pending",
        )

    resolved_idempotency_key = (
        idempotency_key
        or hashlib.sha256(f"{request_id}:{body.option_id}".encode()).hexdigest()
    )
    existing_action = await get_control_action_by_idempotency_key(
        db, thread_id=thread_id, idempotency_key=resolved_idempotency_key
    )
    if existing_action is not None:
        return PermissionResponseResult(
            request_id=request_id,
            accepted=True,
            applied=existing_action.applied_at is not None,
            action_status=existing_action.result_status,
            thread_id=thread_id,
            action_id=existing_action.id,
            idempotency_key=resolved_idempotency_key,
            approval_status=thread_record.approval_status,
        )

    if permission.request_status == PermissionRequestStatus.APPLIED.value:
        action = await create_control_action(
            db,
            thread_id=thread_id,
            action_type=ControlActionType.PERMISSION_RESPONSE_SUBMITTED,
            request_id=request_id,
            idempotency_key=resolved_idempotency_key,
            payload={"option_id": body.option_id},
            result_status=ControlActionResultStatus.DUPLICATE,
        )
        await db.commit()
        return PermissionResponseResult(
            request_id=request_id,
            accepted=True,
            applied=True,
            action_status=ControlActionResultStatus.DUPLICATE.value,
            thread_id=thread_id,
            action_id=action.id,
            idempotency_key=resolved_idempotency_key,
            approval_status=thread_record.approval_status,
        )

    if permission.request_status != PermissionRequestStatus.PENDING.value:
        action = await create_control_action(
            db,
            thread_id=thread_id,
            action_type=ControlActionType.PERMISSION_RESPONSE_SUBMITTED,
            request_id=request_id,
            idempotency_key=resolved_idempotency_key,
            payload={"option_id": body.option_id},
            result_status=ControlActionResultStatus.REJECTED_INVALID_STATE,
        )
        await db.commit()
        return PermissionResponseResult(
            request_id=request_id,
            accepted=False,
            applied=False,
            action_status=ControlActionResultStatus.REJECTED_INVALID_STATE.value,
            thread_id=thread_id,
            action_id=action.id,
            idempotency_key=resolved_idempotency_key,
            approval_status=thread_record.approval_status,
        )

    permission_terminal_statuses = {
        ThreadStatus.COMPLETED,
        ThreadStatus.FAILED,
        ThreadStatus.CANCELLED,
    }
    if thread_record.status in permission_terminal_statuses:
        logger.warning(
            "Permission respond rejected: thread %s is no longer active (status=%r)",
            thread_id,
            thread_record.status,
            extra={
                "thread_id": thread_id,
                "request_id": request_id,
                "action": "permission_response",
                "thread_status": thread_record.status,
            },
        )
        raise HTTPException(
            status_code=409,
            detail="thread is no longer active",
        )

    team_preset: str | None = thread_record.team_preset
    workspace_root: str | None = None
    if thread_record.thread_metadata:
        try:
            meta = json.loads(thread_record.thread_metadata)
            workspace_root = meta.get("workspace_root")
        except (json.JSONDecodeError, AttributeError):
            pass

    resume_value: str | dict[str, bool] = body.option_id
    if permission.pause_reason_type in _PLAN_APPROVAL_PAUSE_CAUSES:
        resume_value = {"approved": body.option_id == "approve"}

    action = await create_control_action(
        db,
        thread_id=thread_id,
        action_type=ControlActionType.PERMISSION_RESPONSE_SUBMITTED,
        request_id=request_id,
        idempotency_key=resolved_idempotency_key,
        payload={"option_id": body.option_id},
    )
    await record_permission_response_submission(
        db,
        request_id=request_id,
        option_id=body.option_id,
        idempotency_key=resolved_idempotency_key,
    )
    if permission.pause_reason_type in _PLAN_APPROVAL_PAUSE_CAUSES:
        await set_thread_approval_state(
            db,
            thread_id,
            approval_status=ApprovalStatus.PENDING,
            approval_request_id=request_id,
            approval_reason=permission.description,
            approval_response_action_id=action.id,
        )
    await set_thread_repair_state(
        db,
        thread_id,
        repair_status=RepairStatus.PAUSED_RESUMABLE,
        execution_readiness=RepairStatus.PAUSED_RESUMABLE.value,
        last_requested_action=ControlActionType.PERMISSION_RESPONSE_SUBMITTED,
    )

    dispatch = DispatchRequest(
        action="resume",
        thread_id=thread_id,
        option_id=resume_value,
        team_preset=team_preset,
        workspace_root=workspace_root,
    )

    logger.info(
        "Dispatching resume dispatch_id=%s for thread %s (request_id=%s)",
        dispatch.dispatch_id,
        thread_id,
        request_id,
        extra={
            "thread_id": thread_id,
            "dispatch_id": dispatch.dispatch_id,
            "request_id": request_id,
            "action": dispatch.action,
            "option_id": body.option_id,
        },
    )
    await worker_spawner.ensure_worker()
    circuit_breaker.pre_dispatch()
    dispatched = False
    try:
        resp = await worker_client.post(
            "/dispatch",
            json=dispatch.model_dump(),
            headers=_trace_headers(),
        )
        dispatched = resp.is_success
        circuit_breaker.record_success()
        if dispatched:
            _mark_worker_connected(request)
    except httpx.HTTPError:
        circuit_breaker.record_failure()
        logger.warning(
            "Failed to dispatch resume dispatch_id=%s for thread %s",
            dispatch.dispatch_id,
            thread_id,
            extra={
                "thread_id": thread_id,
                "dispatch_id": dispatch.dispatch_id,
                "request_id": request_id,
                "action": dispatch.action,
                "option_id": body.option_id,
            },
            exc_info=True,
        )

    if dispatched:
        aggregator.resolve_permission(request_id)
        await update_thread_status(db, thread_id, ThreadStatus.RUNNING)
        await set_thread_repair_state(
            db,
            thread_id,
            repair_status=RepairStatus.HEALTHY,
            execution_readiness=RepairStatus.HEALTHY.value,
            last_requested_action=ControlActionType.PERMISSION_RESPONSE_SUBMITTED,
        )
        await db.commit()
        return PermissionResponseResult(
            request_id=request_id,
            accepted=True,
            applied=False,
            action_status=ControlActionResultStatus.ACCEPTED_NOT_APPLIED.value,
            thread_id=thread_id,
            action_id=action.id,
            idempotency_key=resolved_idempotency_key,
            approval_status=(
                ApprovalStatus.PENDING.value
                if permission.pause_reason_type in _PLAN_APPROVAL_PAUSE_CAUSES
                else thread_record.approval_status
            ),
        )

    action.result_status = ControlActionResultStatus.REJECTED_INVALID_STATE.value
    await db.commit()
    return PermissionResponseResult(
        request_id=request_id,
        accepted=False,
        applied=False,
        action_status=ControlActionResultStatus.REJECTED_INVALID_STATE.value,
        thread_id=thread_id,
        action_id=action.id,
        idempotency_key=resolved_idempotency_key,
        approval_status=thread_record.approval_status,
    )


# ---------------------------------------------------------------------------
# POST /threads/{thread_id}/cancel -- Cancel a running thread (MCP-R3)
# ---------------------------------------------------------------------------


@router.post(
    "/threads/{thread_id}/cancel",
    response_model=CancelThreadResponse,
)
async def cancel_thread_endpoint(
    thread_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    worker_client: httpx.AsyncClient = Depends(get_worker_client),
    circuit_breaker: Any = Depends(get_circuit_breaker),
    worker_spawner: Any = Depends(get_worker_spawner),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> CancelThreadResponse:
    """Cancel a running thread by dispatching a cancel action to the worker.

    Sends a cancel dispatch to the worker process. The thread is only
    transitioned to terminal ``cancelled`` when the worker later emits
    its terminal event.
    """
    thread = await get_thread(db, thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found")

    # Only cancel threads that are in a cancellable state.
    if thread.status in (
        ThreadStatus.COMPLETED,
        ThreadStatus.FAILED,
        ThreadStatus.CANCELLED,
        ThreadStatus.ARCHIVED,
    ):
        return CancelThreadResponse(
            thread_id=thread_id,
            status=thread.status,
            cancelled=False,
            accepted=False,
            applied=thread.status == ThreadStatus.CANCELLED.value,
            action_status=ControlActionResultStatus.REJECTED_INVALID_STATE.value,
        )

    resolved_idempotency_key = (
        idempotency_key or hashlib.sha256(f"{thread_id}:cancel".encode()).hexdigest()
    )
    existing_action = await get_control_action_by_idempotency_key(
        db, thread_id=thread_id, idempotency_key=resolved_idempotency_key
    )
    if existing_action is not None:
        return CancelThreadResponse(
            thread_id=thread_id,
            status=ThreadStatus.CANCELLING.value,
            cancelled=True,
            accepted=True,
            applied=existing_action.applied_at is not None,
            action_status=existing_action.result_status,
            action_id=existing_action.id,
            idempotency_key=resolved_idempotency_key,
        )

    dispatched = False
    action = await create_control_action(
        db,
        thread_id=thread_id,
        action_type=ControlActionType.CANCEL,
        idempotency_key=resolved_idempotency_key,
        payload={"thread_status": thread.status},
    )
    await set_thread_repair_state(
        db,
        thread_id,
        repair_status=RepairStatus.CANCEL_PENDING,
        execution_readiness=RepairStatus.CANCEL_PENDING.value,
        last_requested_action=ControlActionType.CANCEL,
    )
    dispatch = DispatchRequest(action="cancel", thread_id=thread_id)
    logger.info(
        "Dispatching cancel dispatch_id=%s for thread %s",
        dispatch.dispatch_id,
        thread_id,
        extra={
            "thread_id": thread_id,
            "dispatch_id": dispatch.dispatch_id,
            "action": dispatch.action,
        },
    )
    await worker_spawner.ensure_worker()
    # PROD-066: Cancel must bypass the circuit breaker — users must always
    # be able to stop a runaway agent, even when the breaker is OPEN.
    try:
        resp = await worker_client.post(
            "/dispatch",
            json=dispatch.model_dump(),
            headers=_trace_headers(),
        )
        dispatched = resp.is_success
        # 2xx → worker alive; record success so the CB can recover.
        if resp.is_success:
            circuit_breaker.record_success()
            _mark_worker_connected(request)
    except httpx.HTTPError:
        circuit_breaker.record_failure()
        logger.warning(
            "Failed to dispatch cancel dispatch_id=%s for thread %s",
            dispatch.dispatch_id,
            thread_id,
            extra={
                "thread_id": thread_id,
                "dispatch_id": dispatch.dispatch_id,
                "action": dispatch.action,
            },
            exc_info=True,
        )

    if not dispatched:
        logger.warning(
            "Cancel dispatch failed for thread %s — leaving DB status unchanged",
            thread_id,
            extra={
                "thread_id": thread_id,
                "dispatch_id": dispatch.dispatch_id,
                "action": dispatch.action,
            },
        )
        action.result_status = ControlActionResultStatus.REJECTED_INVALID_STATE.value
        await db.commit()
        return CancelThreadResponse(
            thread_id=thread_id,
            status=thread.status,
            cancelled=False,
            accepted=False,
            applied=False,
            action_status=ControlActionResultStatus.REJECTED_INVALID_STATE.value,
            action_id=action.id,
            idempotency_key=resolved_idempotency_key,
        )

    await update_thread_status(db, thread_id, ThreadStatus.CANCELLING)
    await db.commit()

    return CancelThreadResponse(
        thread_id=thread_id,
        status=ThreadStatus.CANCELLING.value,
        cancelled=True,
        accepted=True,
        applied=False,
        action_status=ControlActionResultStatus.ACCEPTED_NOT_APPLIED.value,
        action_id=action.id,
        idempotency_key=resolved_idempotency_key,
    )


# ---------------------------------------------------------------------------
# DELETE /threads/{thread_id} -- Hard-delete a thread (BE-D)
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
    # PROD-050: Refuse to hard-delete a live thread — callers must cancel first.
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
# POST /threads/{thread_id}/archive -- Archive a thread (BE-E)
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

    # Idempotent: already archived → return success without re-writing.
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


# ---------------------------------------------------------------------------
# POST /admin/shutdown -- Graceful shutdown (BE-G)
# ---------------------------------------------------------------------------


@router.post("/admin/shutdown", status_code=202)
async def shutdown_endpoint() -> dict[str, str]:
    """Initiate graceful server shutdown."""
    import os
    import signal

    os.kill(os.getpid(), signal.SIGINT)
    return {"status": "shutting_down"}

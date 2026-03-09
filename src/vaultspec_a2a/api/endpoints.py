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

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from fastapi import APIRouter, Depends, HTTPException, Header, Query, Request
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import StateSnapshot
from opentelemetry import propagate as _otel_propagate
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..core import (
    ConfigError,
    EventAggregator,
    NicknameConflictError,
    TeamConfigNotFoundError,
    ThreadMetadata,
    build_context_preamble,
    build_initial_vault_index,
    discover_context_refs,
    discover_team_preset_ids,
    generate_nickname,
    load_team_config,
)
from ..core.aggregator import _classify_tool_kind
from ..database.checkpoints import Checkpointer
from ..database.crud import (
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
    set_thread_repair_state,
    update_thread_status,
)
from ..database.session import get_db
from .projection import enrich_snapshot_from_durable_state
from .schemas.enums import AgentLifecycleState, PermissionType, ToolCallStatus
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
    TeamPresetSummary,
    TeamPresetsResponse,
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


def get_circuit_breaker(request: Request) -> Any:  # noqa: ANN401
    """FastAPI dependency for the WorkerCircuitBreaker (PROD-028)."""
    cb = getattr(request.app.state, "circuit_breaker", None)
    if cb is None:
        raise RuntimeError("WorkerCircuitBreaker not initialised in app state")
    return cb


def get_worker_spawner(request: Request) -> Any:  # noqa: ANN401
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
    circuit_breaker: Any = Depends(get_circuit_breaker),  # noqa: ANN401
    worker_spawner: Any = Depends(get_worker_spawner),  # noqa: ANN401
) -> dict:
    """Public health endpoint aggregating gateway, worker, and database status."""
    checks: dict[str, dict[str, str]] = {}

    # Gateway -- always ok if we're responding
    checks["gateway"] = {"status": "ok"}

    # Database -- execute a trivial query
    try:
        await db.execute(text("SELECT 1"))
        checks["database"] = {"status": "ok"}
    except Exception:
        logger.exception("Health check: database probe failed")
        checks["database"] = {"status": "error", "detail": "database probe failed"}

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

    overall = (
        "ok"
        if all(c["status"] in ("ok", "closed", "yes") for c in checks.values())
        else "degraded"
    )
    repair_summary = getattr(request.app.state, "repair_summary", {})
    return {
        "status": overall,
        "checks": checks,
        "repair_backlog": repair_summary.get("repair_backlog", 0),
        "paused_resumable": repair_summary.get("paused_resumable", 0),
        "checkpoint_unavailable": repair_summary.get("checkpoint_unavailable", 0),
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


# Guard against pipeline_loop topologies with large max_loops values
# hitting LangGraph's default recursion_limit of 25 (ADR-013 S5).
_GRAPH_RECURSION_LIMIT = 100


@router.post("/threads", response_model=CreateThreadResponse, status_code=201)
async def create_thread_endpoint(  # noqa: PLR0915
    body: CreateThreadRequest,
    services: tuple[
        AsyncSession,
        EventAggregator,
        Checkpointer,
        httpx.AsyncClient,
    ] = Depends(get_services),
    circuit_breaker: Any = Depends(get_circuit_breaker),  # noqa: ANN401
    worker_spawner: Any = Depends(get_worker_spawner),  # noqa: ANN401
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
                recursion_limit=_GRAPH_RECURSION_LIMIT,
                active_feature=feature_tag,
                pipeline_phase=None,
                vault_index=vault_index,
                validation_errors=[],
            )

            logger.info(
                "Dispatching ingest dispatch_id=%s for thread %s",
                dispatch.dispatch_id,
                thread.id,
            )
            await worker_spawner.ensure_worker()
            circuit_breaker.pre_dispatch()
            try:
                await worker_client.post(
                    "/dispatch",
                    json=dispatch.model_dump(),
                    headers=_trace_headers(),
                )
                circuit_breaker.record_success()
            except httpx.HTTPError:
                circuit_breaker.record_failure()
                logger.warning(
                    "Failed to dispatch ingest dispatch_id=%s for thread %s",
                    dispatch.dispatch_id,
                    thread.id,
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


def _enrich_snapshot_from_state(  # noqa: PLR0912, PLR0915
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
    for m in state.values.get("messages", []):
        if isinstance(m, AIMessage) and m.tool_calls:
            for tc in m.tool_calls:
                tc_id = tc.get("id", "")
                tc_name = tc.get("name", "unknown_tool")
                tool_call_snapshots.append(
                    ToolCallSnapshot(
                        tool_call_id=tc_id,
                        title=tc_name,
                        kind=_classify_tool_kind(tc_name),
                        status=(
                            ToolCallStatus.COMPLETED
                            if tc_id in answered_tool_ids
                            else ToolCallStatus.PENDING
                        ),
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


@router.get("/threads/{thread_id}/state", response_model=ThreadStateSnapshot)
async def get_thread_state_endpoint(  # noqa: PLR0915
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
    )
    snapshot = await enrich_snapshot_from_durable_state(
        db, thread=thread, snapshot=snapshot
    )
    checkpoint_loaded = False
    checkpoint_present = False

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
            checkpoint = checkpoint_tuple.checkpoint
            channel_values = checkpoint.get("channel_values", {})

            # Build a minimal StateSnapshot-like object for reuse of
            # _enrich_snapshot_from_state
            class _MinimalState:
                """Minimal adapter for _enrich_snapshot_from_state."""

                def __init__(self, values: dict, cfg: dict | None = None) -> None:
                    self.values = values
                    self.config = cfg

            config_dict = {"configurable": {"thread_id": thread_id}}
            if checkpoint_tuple.config:
                cp_id = checkpoint_tuple.config.get("configurable", {}).get(
                    "checkpoint_id"
                )
                if cp_id:
                    config_dict["configurable"]["checkpoint_id"] = cp_id

            minimal_state = _MinimalState(
                values=channel_values,
                cfg=config_dict,
            )
            snapshot = _enrich_snapshot_from_state(
                snapshot,
                minimal_state,  # type: ignore[arg-type]
                aggregator=aggregator,
            )
            checkpoint_loaded = True
    except TimeoutError:
        logger.warning(
            "Timed out loading checkpoint for thread %s after 10s; "
            "returning partial snapshot",
            thread_id,
        )
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
        snapshot.snapshot_complete = False
        snapshot.degraded_reasons.append("checkpoint_unavailable")
        snapshot.replay_status = "unknown"
        snapshot.repair_status = RepairStatus.CHECKPOINT_UNAVAILABLE.value

    if checkpoint_loaded:
        snapshot.snapshot_complete = True
        snapshot.replay_status = "durable"
    elif checkpoint_present:
        snapshot.snapshot_complete = False
        snapshot.replay_status = "best_effort"
    elif thread.status in (
        ThreadStatus.SUBMITTED.value,
        ThreadStatus.CREATED.value,
    ):
        snapshot.snapshot_complete = True
        snapshot.replay_status = "unknown"
    else:
        snapshot.snapshot_complete = False
        if "checkpoint_missing" not in snapshot.degraded_reasons:
            snapshot.degraded_reasons.append("checkpoint_missing")
        snapshot.replay_status = "gap_detected"

    return snapshot


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
    db: AsyncSession = Depends(get_db),
    aggregator: EventAggregator = Depends(get_aggregator),
    worker_client: httpx.AsyncClient = Depends(get_worker_client),
    circuit_breaker: Any = Depends(get_circuit_breaker),  # noqa: ANN401
    worker_spawner: Any = Depends(get_worker_spawner),  # noqa: ANN401
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
    )
    await worker_spawner.ensure_worker()
    circuit_breaker.pre_dispatch()
    try:
        await worker_client.post(
            "/dispatch",
            json=dispatch.model_dump(),
            headers=_trace_headers(),
        )
        circuit_breaker.record_success()
    except httpx.HTTPError:
        circuit_breaker.record_failure()
        logger.warning(
            "Failed to dispatch message dispatch_id=%s for thread %s",
            dispatch.dispatch_id,
            thread_id,
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
    aggregator: EventAggregator = Depends(get_aggregator),
    db: AsyncSession = Depends(get_db),
) -> TeamStatusResponse:
    """Return current team status: agents, active threads, pending permissions.

    ADR-019 NOTE: The gateway aggregator is lightweight.  Agent
    summaries come from node metadata registered via the worker relay.
    Pending permissions are tracked by the aggregator (MCP-R5).
    """
    active_threads = aggregator.get_active_thread_ids()
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
async def respond_to_permission_endpoint(  # noqa: PLR0912, PLR0915
    request_id: str,
    body: PermissionResponseRequest,
    db: AsyncSession = Depends(get_db),
    worker_client: httpx.AsyncClient = Depends(get_worker_client),
    aggregator: EventAggregator = Depends(get_aggregator),
    circuit_breaker: Any = Depends(get_circuit_breaker),  # noqa: ANN401
    worker_spawner: Any = Depends(get_worker_spawner),  # noqa: ANN401
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
    )

    # thread_id is embedded in request_id as "{thread_id}:{uuid}".
    # Split on the first colon; treat as opaque if no colon present.
    thread_id = ""
    if ":" in request_id:
        thread_id, _ = request_id.split(":", 1)

    if not thread_id:
        return PermissionResponseResult(
            request_id=request_id,
            accepted=False,
            applied=False,
            action_status=ControlActionResultStatus.REJECTED_INVALID_STATE.value,
            thread_id="",
        )

    permission = await get_permission_request(db, request_id)
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
    if permission.pause_reason_type == PermissionType.PLAN_APPROVAL.value:
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
    except httpx.HTTPError:
        circuit_breaker.record_failure()
        logger.warning(
            "Failed to dispatch resume dispatch_id=%s for thread %s",
            dispatch.dispatch_id,
            thread_id,
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
    db: AsyncSession = Depends(get_db),
    worker_client: httpx.AsyncClient = Depends(get_worker_client),
    circuit_breaker: Any = Depends(get_circuit_breaker),  # noqa: ANN401
    worker_spawner: Any = Depends(get_worker_spawner),  # noqa: ANN401
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
    )
    await worker_spawner.ensure_worker()
    circuit_breaker.pre_dispatch()
    try:
        resp = await worker_client.post(
            "/dispatch",
            json=dispatch.model_dump(),
            headers=_trace_headers(),
        )
        dispatched = resp.is_success
        circuit_breaker.record_success()
    except httpx.HTTPError:
        circuit_breaker.record_failure()
        logger.warning(
            "Failed to dispatch cancel dispatch_id=%s for thread %s",
            dispatch.dispatch_id,
            thread_id,
            exc_info=True,
        )

    if not dispatched:
        logger.warning(
            "Cancel dispatch failed for thread %s — leaving DB status unchanged",
            thread_id,
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
    import os  # noqa: PLC0415
    import signal  # noqa: PLC0415

    os.kill(os.getpid(), signal.SIGINT)
    return {"status": "shutting_down"}

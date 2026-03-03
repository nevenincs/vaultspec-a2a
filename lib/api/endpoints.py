"""REST API endpoints for the A2A Orchestrator (ADR-019 refactored).

Implements the 6 REST routes from ADR-011 section 2.2:
- POST /threads            -> CreateThreadResponse
- GET  /threads            -> ThreadListResponse (paginated)
- GET  /threads/{id}/state -> ThreadStateSnapshot (reconnection)
- POST /threads/{id}/messages -> 202 Accepted
- GET  /team/status        -> TeamStatusResponse
- POST /permissions/{id}/respond -> PermissionResponseResult

ADR-019: Graph compilation and ``aggregator.ingest()`` no longer run in
the control surface.  All work is dispatched to the worker process via
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
from uuid import uuid4

import httpx

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import StateSnapshot
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.aggregator import EventAggregator
from ..core.graph import _build_initial_vault_index
from ..core.exceptions import ConfigError, NicknameConflictError
from ..core.metadata import ThreadMetadata, discover_context_refs, generate_nickname
from ..core.preamble import build_context_preamble
from ..core.team_config import (
    TeamConfigNotFoundError,
    discover_team_preset_ids,
    load_team_config,
)
from ..database.crud import (
    ThreadStatus,
    create_thread,
    get_thread,
    get_thread_metadata,
    list_threads,
    update_thread_status,
)
from ..database.session import get_db
from .schemas.enums import AgentLifecycleState
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
from .schemas.snapshots import MessageSnapshot, ThreadStateSnapshot


__all__ = [
    "get_aggregator",
    "get_checkpointer",
    "get_worker_client",
    "router",
]


logger = logging.getLogger(__name__)

router = APIRouter()


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


def get_checkpointer(request: Request) -> AsyncSqliteSaver:
    """FastAPI dependency for the LangGraph checkpointer (read-only, ADR-019)."""
    checkpointer: AsyncSqliteSaver | None = getattr(
        request.app.state, "checkpointer", None
    )
    if checkpointer is None:
        raise RuntimeError("AsyncSqliteSaver checkpointer not initialised in app state")
    return checkpointer


def get_worker_client(request: Request) -> httpx.AsyncClient:
    """FastAPI dependency for the httpx client pointing at the worker."""
    client: httpx.AsyncClient | None = getattr(
        request.app.state, "worker_client", None
    )
    if client is None:
        raise RuntimeError("Worker httpx client not initialised in app state")
    return client


async def get_services(
    db: AsyncSession = Depends(get_db),
    aggregator: EventAggregator = Depends(get_aggregator),
    checkpointer: AsyncSqliteSaver = Depends(get_checkpointer),
    worker_client: httpx.AsyncClient = Depends(get_worker_client),
) -> tuple[AsyncSession, EventAggregator, AsyncSqliteSaver, httpx.AsyncClient]:
    """Dependency for bundling all required services into a single injection point.

    ADR-019: No longer includes GraphRegistry or TaskGroup -- the worker owns
    graph lifecycle, and the control surface does not run background agent tasks.
    """
    return db, aggregator, checkpointer, worker_client


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
async def create_thread_endpoint(
    body: CreateThreadRequest,
    services: tuple[
        AsyncSession,
        EventAggregator,
        AsyncSqliteSaver,
        httpx.AsyncClient,
    ] = Depends(get_services),
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
    db, aggregator, checkpointer, worker_client = services
    thread_id = uuid4().hex

    # --- ADR-014: Metadata processing ---
    ws_root, nickname, metadata_json = _process_metadata(body, thread_id)

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
            _build_initial_vault_index(ws_root, metadata.feature_tag)
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

        try:
            await worker_client.post(
                "/dispatch",
                json=dispatch.model_dump(),
            )
        except httpx.HTTPError:
            logger.warning(
                "Failed to dispatch ingest to worker for thread %s",
                thread.id,
                exc_info=True,
            )
            # Thread is still created in DB -- the worker can pick it up
            # when it comes online, or the user can retry via send_message.

    # Commit only after all synchronous setup succeeds -- prevents orphaned
    # thread rows when metadata processing fails (H9 fix).
    await db.commit()

    return CreateThreadResponse(
        thread_id=thread.id,
        status=thread.status,
        nickname=nickname,
    )


# ---------------------------------------------------------------------------
# GET /threads -- List threads (paginated)
# ---------------------------------------------------------------------------


@router.get("/threads", response_model=ThreadListResponse)
async def list_threads_endpoint(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> ThreadListResponse:
    """List orchestration threads with pagination.

    Enriches each thread summary with metadata fields (ADR-014) when
    available. Legacy threads without metadata gracefully omit these fields.
    """
    threads, total = await list_threads(db, offset=offset, limit=limit)
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
) -> ThreadStateSnapshot:
    """Populate snapshot fields from LangGraph checkpointer state.

    Maps LangChain ``BaseMessage`` objects to ``MessageSnapshot`` and
    extracts ``checkpoint_id`` from the state config.
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

    return snapshot.model_copy(
        update={
            "messages": msgs,
            "checkpoint_id": checkpoint_id,
        }
    )


@router.get("/threads/{thread_id}/state", response_model=ThreadStateSnapshot)
async def get_thread_state_endpoint(
    thread_id: str,
    db: AsyncSession = Depends(get_db),
    aggregator: EventAggregator = Depends(get_aggregator),
    checkpointer: AsyncSqliteSaver = Depends(get_checkpointer),
) -> ThreadStateSnapshot:
    """Return a complete thread state snapshot for client reconnection.

    The ``last_sequence`` field enables gap detection: the client discards
    any subsequent WebSocket events with ``sequence <= last_sequence``
    (ADR-011 section 2.3).

    ADR-019: The graph is no longer registered locally.  Snapshot enrichment
    reads directly from the shared SQLite checkpointer (read-only in the
    control surface, safe under WAL mode).  If checkpointer data is not
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
    )

    # ADR-019: Try to enrich from checkpointer directly.
    # The checkpointer.aget_tuple() returns raw checkpoint data.  We use
    # checkpointer.aget() which returns a Checkpoint dict with channel_values
    # containing the messages list.
    try:
        checkpoint = await asyncio.wait_for(
            checkpointer.aget({"configurable": {"thread_id": thread_id}}),
            timeout=10.0,
        )
        if checkpoint is not None:
            # Extract messages from checkpoint channel_values
            channel_values = checkpoint.get("channel_values", {})
            messages_raw = channel_values.get("messages", [])
            if messages_raw:
                # Build a minimal StateSnapshot-like object for reuse of
                # _enrich_snapshot_from_state
                class _MinimalState:
                    """Minimal adapter for _enrich_snapshot_from_state."""
                    def __init__(self, values: dict, config: dict | None = None) -> None:
                        self.values = values
                        self.config = config

                config_dict = {"configurable": {"thread_id": thread_id}}
                # checkpoint_id may be in the checkpoint metadata
                if "id" in checkpoint:
                    config_dict["configurable"]["checkpoint_id"] = checkpoint["id"]

                minimal_state = _MinimalState(
                    values=channel_values,
                    config=config_dict,
                )
                snapshot = _enrich_snapshot_from_state(
                    snapshot,
                    minimal_state,  # type: ignore[arg-type]
                )
    except TimeoutError:
        logger.warning(
            "Timed out loading checkpoint for thread %s after 10s; "
            "returning partial snapshot",
            thread_id,
        )
    except Exception:
        logger.warning(
            "Could not load checkpoint for thread %s; returning partial snapshot",
            thread_id,
            exc_info=True,
        )

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
) -> SendMessageResponse:
    """Send a user message into an existing thread.

    Returns 202 Accepted immediately; the message is dispatched to the
    worker process for graph execution (ADR-019).
    """
    thread = await get_thread(db, thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found")

    logger.info(
        "Message received for thread %s: %d chars",
        thread_id,
        len(body.content),
    )

    # Update thread status -- DB-C1: use ThreadStatus enum (DB-HIGH-02)
    await update_thread_status(db, thread_id, ThreadStatus.RUNNING)
    await db.commit()

    agent_id = body.agent_id or "vaultspec-supervisor"

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

    try:
        await worker_client.post(
            "/dispatch",
            json=dispatch.model_dump(),
        )
    except httpx.HTTPError:
        logger.warning(
            "Failed to dispatch message to worker for thread %s",
            thread_id,
            exc_info=True,
        )
        # Still return accepted -- the worker may pick it up when available,
        # or the message handler can retry.
        await aggregator.emit_agent_status(
            thread_id=thread_id,
            agent_id=agent_id,
            node_name="supervisor",
            state=AgentLifecycleState.SUBMITTED,
            detail="Message received, awaiting worker",
        )

    return SendMessageResponse(status="accepted", thread_id=thread_id)


# ---------------------------------------------------------------------------
# GET /team/status -- Team status snapshot
# ---------------------------------------------------------------------------


@router.get("/team/status", response_model=TeamStatusResponse)
async def get_team_status_endpoint(
    aggregator: EventAggregator = Depends(get_aggregator),
) -> TeamStatusResponse:
    """Return current team status: agents, active threads, pending permissions.

    ADR-019 NOTE: The control surface aggregator is lightweight.  Agent
    summaries come from node metadata registered via the worker relay.
    Pending permissions are tracked by the aggregator (MCP-R5).
    """
    active_threads = aggregator.get_active_thread_ids()
    node_summaries = aggregator.get_node_summaries()

    agents = [
        AgentStatusEntry(
            agent_id=s["agent_id"],
            node_name=s["node_name"],
            state=AgentLifecycleState.IDLE,
            role=s.get("role", ""),
            display_name=s.get("display_name", ""),
            description=s.get("description", ""),
        )
        for s in node_summaries
    ]

    pending = [
        PendingPermission(
            request_id=ev.request_id,
            thread_id=ev.thread_id,
            description=ev.description,
        )
        for ev in aggregator.get_pending_permissions()
    ]

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

    Dynamically discovers presets by globbing ``lib/core/presets/teams/*.toml``.
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
    db: AsyncSession = Depends(get_db),
    worker_client: httpx.AsyncClient = Depends(get_worker_client),
    aggregator: EventAggregator = Depends(get_aggregator),
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

    dispatched = False
    if thread_id:
        # Look up team_preset and workspace_root from DB for lazy recompile.
        team_preset: str | None = None
        workspace_root: str | None = None
        thread_record = await get_thread(db, thread_id)
        if thread_record is None:
            raise HTTPException(status_code=404, detail="Thread not found")
        team_preset = thread_record.team_preset
        if thread_record.thread_metadata:
            try:
                meta = json.loads(thread_record.thread_metadata)
                workspace_root = meta.get("workspace_root")
            except (json.JSONDecodeError, AttributeError):
                pass

        dispatch = DispatchRequest(
            action="resume",
            thread_id=thread_id,
            option_id=body.option_id,
            team_preset=team_preset,
            workspace_root=workspace_root,
        )

        try:
            resp = await worker_client.post(
                "/dispatch",
                json=dispatch.model_dump(),
            )
            dispatched = resp.is_success
        except httpx.HTTPError:
            logger.warning(
                "Failed to dispatch resume to worker for thread %s",
                thread_id,
                exc_info=True,
            )
    else:
        logger.warning(
            "No thread_id found in request_id=%s -- cannot dispatch resume",
            request_id,
        )

    # MCP-R5: clear from aggregator's pending set on successful dispatch.
    if dispatched:
        aggregator.resolve_permission(request_id)

    return PermissionResponseResult(
        request_id=request_id,
        accepted=dispatched,
        thread_id=thread_id,
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
) -> CancelThreadResponse:
    """Cancel a running thread by dispatching a cancel action to the worker.

    Sets the thread status to ``cancelled`` in the database and sends a
    cancel dispatch to the worker process (MCP-R3, ADR-019).
    """
    thread = await get_thread(db, thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found")

    # Only cancel threads that are in a cancellable state.
    if thread.status in (ThreadStatus.COMPLETED, ThreadStatus.FAILED, ThreadStatus.CANCELLED):
        return CancelThreadResponse(
            thread_id=thread_id,
            status=thread.status,
            cancelled=False,
        )

    dispatched = False
    dispatch = DispatchRequest(action="cancel", thread_id=thread_id)
    try:
        resp = await worker_client.post(
            "/dispatch",
            json=dispatch.model_dump(),
        )
        dispatched = resp.is_success
    except httpx.HTTPError:
        logger.warning(
            "Failed to dispatch cancel to worker for thread %s",
            thread_id,
            exc_info=True,
        )

    # Update DB status regardless of dispatch success — the thread is
    # considered cancelled from the control surface perspective.
    await update_thread_status(db, thread_id, ThreadStatus.CANCELLED)
    await db.commit()

    return CancelThreadResponse(
        thread_id=thread_id,
        status=ThreadStatus.CANCELLED,
        cancelled=True,
    )

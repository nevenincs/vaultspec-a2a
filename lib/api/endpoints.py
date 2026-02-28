"""REST API endpoints for the A2A Orchestrator.

Implements the 6 REST routes from ADR-011 section 2.2:
- POST /threads            -> CreateThreadResponse
- GET  /threads            -> ThreadListResponse (paginated)
- GET  /threads/{id}/state -> ThreadStateSnapshot (reconnection)
- POST /threads/{id}/messages -> 202 Accepted
- GET  /team/status        -> TeamStatusResponse
- POST /permissions/{id}/respond -> PermissionResponseResult

See: ADR-007 (FastAPI, SPA mount)
     ADR-011 (Frontend-Backend Wire Contract)
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

import anyio

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.aggregator import EventAggregator
from ..core.exceptions import NicknameConflictError
from ..core.graph import compile_team_graph
from ..core.metadata import ThreadMetadata, discover_context_refs, generate_nickname
from ..core.preamble import build_context_preamble
from ..core.team_config import (
    AgentConfig,
    AgentConfigNotFoundError,
    TeamConfigNotFoundError,
    load_agent_config,
    load_team_config,
)
from ..database.crud import (
    create_thread,
    get_thread,
    get_thread_metadata,
    list_threads,
    update_thread_status,
)
from ..database.session import get_db
from .schemas.enums import AgentLifecycleState
from .schemas.rest import (
    CreateThreadRequest,
    CreateThreadResponse,
    PermissionResponseRequest,
    PermissionResponseResult,
    SendMessageRequest,
    TeamPresetSummary,
    TeamPresetsResponse,
    TeamStatusResponse,
    ThreadListResponse,
    ThreadSummary,
    _AgentStatusEntry,
)
from .schemas.snapshots import MessageSnapshot, ThreadStateSnapshot


__all__ = [
    "GraphRegistry",
    "get_aggregator",
    "get_checkpointer",
    "get_graph_registry",
    "get_task_group",
    "router",
]


class GraphRegistry:
    """Thread-scoped registry of compiled LangGraph runnables.

    Maps ``thread_id`` to a compiled graph runnable so that the
    ``send_message`` endpoint and WebSocket handler can invoke ``ingest()``
    without re-compiling the graph on every message.

    Lifecycle: created in lifespan startup, stored in ``app.state.graph_registry``.
    """

    def __init__(self) -> None:
        """Initialise the registry with empty graph and resume tables."""
        self._graphs: dict[str, Any] = {}
        # pending LangGraph Command(resume=...) responses keyed by request_id
        self._pending_resumes: dict[str, tuple[str, str]] = {}
        # Tracks threads currently being ingested; prevents concurrent graph
        # execution on the same thread (which would race on checkpointer state).
        self._active_ingests: set[str] = set()

    def register(self, thread_id: str, graph: Any) -> None:  # noqa: ANN401
        """Register a compiled graph for *thread_id*."""
        self._graphs[thread_id] = graph

    def get(self, thread_id: str) -> Any | None:  # noqa: ANN401
        """Return the compiled graph for *thread_id*, or ``None``."""
        return self._graphs.get(thread_id)

    def register_pending_resume(
        self,
        request_id: str,
        thread_id: str,
        option_id: str,
    ) -> None:
        """Store a pending resume so the permission endpoint can retrieve it."""
        self._pending_resumes[request_id] = (thread_id, option_id)

    def pop_pending_resume(
        self,
        request_id: str,
    ) -> tuple[str, str] | None:
        """Remove and return ``(thread_id, option_id)`` for *request_id*."""
        return self._pending_resumes.pop(request_id, None)

    def mark_ingest_active(self, thread_id: str) -> bool:
        """Mark *thread_id* as having an active ingest.

        Returns ``True`` if the mark succeeded (caller may proceed).
        Returns ``False`` if an ingest is already running for this thread
        (caller should drop the duplicate request).
        """
        if thread_id in self._active_ingests:
            return False
        self._active_ingests.add(thread_id)
        return True

    def mark_ingest_done(self, thread_id: str) -> None:
        """Release the active-ingest mark for *thread_id*."""
        self._active_ingests.discard(thread_id)


logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Dependencies: EventAggregator, GraphRegistry
# ---------------------------------------------------------------------------
# Injected at lifespan startup via app.state; the dependencies just read it.


def get_aggregator(request: Request) -> EventAggregator:
    """FastAPI dependency for the EventAggregator singleton."""
    aggregator: EventAggregator | None = getattr(request.app.state, "aggregator", None)
    if aggregator is None:
        raise RuntimeError("EventAggregator not initialised in app state")
    return aggregator


def get_graph_registry(request: Request) -> GraphRegistry:
    """FastAPI dependency for the GraphRegistry singleton."""
    registry: GraphRegistry | None = getattr(request.app.state, "graph_registry", None)
    if registry is None:
        raise RuntimeError("GraphRegistry not initialised in app state")
    return registry


def get_checkpointer(request: Request) -> AsyncSqliteSaver:
    """FastAPI dependency for the LangGraph checkpointer."""
    checkpointer: AsyncSqliteSaver | None = getattr(
        request.app.state, "checkpointer", None
    )
    if checkpointer is None:
        raise RuntimeError("AsyncSqliteSaver checkpointer not initialised in app state")
    return checkpointer


def get_task_group(request: Request) -> anyio.abc.TaskGroup:
    """FastAPI dependency for the anyio task group (ADR-007 §5)."""
    tg: anyio.abc.TaskGroup | None = getattr(request.app.state, "task_group", None)
    if tg is None:
        raise RuntimeError("Task group not initialised in app state")
    return tg


async def get_services(
    db: AsyncSession = Depends(get_db),  # noqa: B008
    aggregator: EventAggregator = Depends(get_aggregator),  # noqa: B008
    registry: GraphRegistry = Depends(get_graph_registry),  # noqa: B008
    checkpointer: AsyncSqliteSaver = Depends(get_checkpointer),  # noqa: B008
    tg: anyio.abc.TaskGroup = Depends(get_task_group),  # noqa: B008
) -> tuple[
    AsyncSession, EventAggregator, GraphRegistry, AsyncSqliteSaver, anyio.abc.TaskGroup
]:
    """Dependency for bundling all required services into a single injection point."""
    return db, aggregator, registry, checkpointer, tg


async def get_message_services(
    db: AsyncSession = Depends(get_db),  # noqa: B008
    aggregator: EventAggregator = Depends(get_aggregator),  # noqa: B008
    registry: GraphRegistry = Depends(get_graph_registry),  # noqa: B008
    tg: anyio.abc.TaskGroup = Depends(get_task_group),  # noqa: B008
) -> tuple[AsyncSession, EventAggregator, GraphRegistry, anyio.abc.TaskGroup]:
    """Dependency for bundling services needed by message endpoints."""
    return db, aggregator, registry, tg


# ---------------------------------------------------------------------------
# POST /threads — Create a new orchestration thread
# ---------------------------------------------------------------------------


@router.post("/threads", response_model=CreateThreadResponse, status_code=201)
async def create_thread_endpoint(  # noqa: PLR0915
    body: CreateThreadRequest,
    services: tuple[
        AsyncSession,
        EventAggregator,
        GraphRegistry,
        AsyncSqliteSaver,
        anyio.abc.TaskGroup,
    ] = Depends(get_services),
) -> CreateThreadResponse:
    """Create a new orchestration thread and compile its LangGraph graph.

    If ``team_preset`` is set in the request, the matching ``TeamConfig`` is
    loaded, all worker ``AgentConfig`` objects are resolved, the graph is
    compiled via ``compile_team_graph()``, and the result is stored in the
    ``GraphRegistry`` so that subsequent ``send_message`` calls can call
    ``aggregator.ingest()`` without re-compiling.

    When ``metadata`` is provided (ADR-014), the endpoint:
    - Validates ``workspace_root`` as an existing directory (422 if not)
    - Auto-discovers ``.vault/`` documents when ``feature_tag`` is set
    - Generates a nickname if not explicitly provided
    - Injects a context preamble SystemMessage into the graph input
    - Threads ``workspace_root`` to config loaders and graph compilation
    """
    db, aggregator, registry, checkpointer, tg = services

    # --- ADR-014: Metadata processing ---
    metadata = body.metadata
    ws_root: Path | None = None
    nickname: str | None = None
    metadata_json: str | None = None

    # Pre-generate thread ID so we can use it for nickname generation
    thread_id = uuid4().hex

    if metadata is not None:
        # Validate workspace_root exists
        ws_root = Path(metadata.workspace_root)
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
            with contextlib.suppress(Exception):
                tc = load_team_config(body.team_preset, workspace_root=ws_root)
                topology = tc.topology.type
        nickname = metadata.nickname or generate_nickname(
            metadata.feature_tag, topology, thread_id
        )
        metadata.nickname = nickname

        metadata_json = metadata.model_dump_json()

    # Create thread in DB
    try:
        thread = await create_thread(
            db,
            title=body.title,
            status="submitted",
            metadata=metadata_json,
            nickname=nickname,
            thread_id=thread_id,
        )
    except NicknameConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail=f"Thread nickname already exists: {exc.nickname!r}",
        ) from exc
    await db.commit()

    logger.info(
        "Created thread %s (title=%s, preset=%s, nickname=%s)",
        thread.id,
        body.title,
        body.team_preset,
        nickname,
    )

    # Compile and register graph if a team preset was requested (ADR-013 §6)
    if body.team_preset:
        try:
            team_config = load_team_config(body.team_preset, workspace_root=ws_root)
        except TeamConfigNotFoundError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Team preset not found: {body.team_preset!r}",
            ) from exc

        # Resolve all worker AgentConfigs
        agent_configs: dict[str, AgentConfig] = {}
        for worker_ref in team_config.workers:
            try:
                agent_configs[worker_ref.agent_id] = load_agent_config(
                    worker_ref.agent_id, workspace_root=ws_root
                )
            except AgentConfigNotFoundError as exc:
                logger.warning(
                    "Agent config not found for %s: %s",
                    worker_ref.agent_id,
                    exc,
                )

        # Resolve optional supervisor config for star/pipeline_loop topologies
        supervisor_config: AgentConfig | None = None
        if team_config.topology.type in ("star", "pipeline_loop"):
            try:
                supervisor_config = load_agent_config(
                    "supervisor", workspace_root=ws_root
                )
            except AgentConfigNotFoundError:
                logger.debug("No supervisor agent config found; using default prompt")

        graph = compile_team_graph(
            team_config=team_config,
            agent_configs=agent_configs,
            checkpointer=checkpointer,
            supervisor_agent_config=supervisor_config,
            workspace_root=ws_root,
        )
        registry.register(thread.id, graph)
        aggregator.register_graph(graph)
        logger.info(
            "Compiled and registered graph for thread %s (preset=%s, topology=%s)",
            thread.id,
            body.team_preset,
            team_config.topology.type,
        )

        # Build graph_input with optional context preamble (ADR-014 §2.3)
        messages: list[SystemMessage | HumanMessage] = []
        if metadata is not None:
            messages.append(build_context_preamble(metadata))
        messages.append(HumanMessage(content=body.initial_message))

        graph_input = {"messages": messages}
        config = {
            "configurable": {"thread_id": thread.id},
            # Guard against pipeline_loop topologies with large max_loops values
            # hitting LangGraph's default recursion_limit of 25 (ADR-013 §5).
            "recursion_limit": 100,
        }
        registry.mark_ingest_active(thread.id)

        async def _ingest_and_release_create(
            _tid: str = thread.id,
        ) -> None:
            try:
                await aggregator.ingest(_tid, "supervisor", graph, graph_input, config)
            finally:
                registry.mark_ingest_done(_tid)

        tg.start_soon(_ingest_and_release_create)

    return CreateThreadResponse(
        thread_id=thread.id,
        status=thread.status,
        nickname=nickname,
    )


# ---------------------------------------------------------------------------
# GET /threads — List threads (paginated)
# ---------------------------------------------------------------------------


@router.get("/threads", response_model=ThreadListResponse)
async def list_threads_endpoint(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),  # noqa: B008
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
            with contextlib.suppress(Exception):
                meta_dict = json.loads(t.thread_metadata)
                feature_tag = meta_dict.get("feature_tag") or None
                source_branch = meta_dict.get("source_branch") or None
                callee = meta_dict.get("callee") or None

        summaries.append(
            ThreadSummary(
                thread_id=t.id,
                title=t.title,
                status=t.status,
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
# GET /threads/{thread_id}/metadata — Thread metadata (ADR-014)
# ---------------------------------------------------------------------------


@router.get("/threads/{thread_id}/metadata")
async def get_thread_metadata_endpoint(
    thread_id: str,
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> dict:
    """Return the full ThreadMetadata object for a thread.

    Used by the inspector panel for detailed provenance display.
    Returns 404 if the thread does not exist or has no metadata.
    """
    meta_json = await get_thread_metadata(db, thread_id)
    if meta_json is None:
        raise HTTPException(status_code=404, detail="Thread or metadata not found")
    return ThreadMetadata.model_validate_json(meta_json).model_dump()


# ---------------------------------------------------------------------------
# GET /threads/{thread_id}/state — Thread state snapshot (reconnection)
# ---------------------------------------------------------------------------


def _enrich_snapshot_from_state(
    snapshot: ThreadStateSnapshot,
    state: Any,  # noqa: ANN401
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
    db: AsyncSession = Depends(get_db),  # noqa: B008
    aggregator: EventAggregator = Depends(get_aggregator),  # noqa: B008
    registry: GraphRegistry = Depends(get_graph_registry),  # noqa: B008
) -> ThreadStateSnapshot:
    """Return a complete thread state snapshot for client reconnection.

    The ``last_sequence`` field enables gap detection: the client discards
    any subsequent WebSocket events with ``sequence <= last_sequence``
    (ADR-011 section 2.3).

    When a compiled graph is registered for the thread, the snapshot is
    enriched with messages and checkpoint_id from the LangGraph
    checkpointer state (ADR-011 §2.3 reconnection protocol).
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

    # Enrich from checkpointer state if a graph is registered
    graph = registry.get(thread_id)
    if graph is not None:
        try:
            state = await asyncio.wait_for(
                graph.aget_state({"configurable": {"thread_id": thread_id}}),
                timeout=10.0,
            )
            if state and state.values:
                snapshot = _enrich_snapshot_from_state(snapshot, state)
        except TimeoutError:
            logger.warning(
                "Timed out loading graph state for thread %s after 10s; "
                "returning partial snapshot",
                thread_id,
            )
        except Exception:
            logger.warning(
                "Could not load graph state for thread %s; returning partial snapshot",
                thread_id,
                exc_info=True,
            )

    return snapshot


# ---------------------------------------------------------------------------
# POST /threads/{thread_id}/messages — Send message into thread
# ---------------------------------------------------------------------------


@router.post("/threads/{thread_id}/messages", status_code=202)
async def send_message_endpoint(
    thread_id: str,
    body: SendMessageRequest,
    services: tuple[
        AsyncSession, EventAggregator, GraphRegistry, anyio.abc.TaskGroup
    ] = Depends(get_message_services),
) -> dict[str, str]:
    """Send a user message into an existing thread.

    Returns 202 Accepted immediately; graph processing runs asynchronously
    via ``aggregator.ingest()`` if a compiled graph is registered for this
    thread.  If no graph is registered the submitted status is still broadcast
    so the frontend receives feedback.
    """
    db, aggregator, registry, tg = services
    thread = await get_thread(db, thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found")

    logger.info(
        "Message received for thread %s: %d chars",
        thread_id,
        len(body.content),
    )

    # Update thread status
    await update_thread_status(db, thread_id, "active")
    await db.commit()

    graph = registry.get(thread_id)
    agent_id = body.agent_id or "supervisor"

    if graph is not None:
        if not registry.mark_ingest_active(thread_id):
            logger.warning(
                "Ingest already active for thread %s; dropping concurrent message",
                thread_id,
            )
            return {"status": "accepted", "thread_id": thread_id}
        graph_input = {"messages": [HumanMessage(content=body.content)]}
        config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 100}

        async def _ingest_and_release_send(
            _tid: str = thread_id,
            _aid: str = agent_id,
        ) -> None:
            try:
                await aggregator.ingest(_tid, _aid, graph, graph_input, config)
            finally:
                registry.mark_ingest_done(_tid)

        tg.start_soon(_ingest_and_release_send)
    else:
        # No graph registered: emit submitted status so the frontend knows
        # the message was received (graph may be wired via WebSocket later).
        await aggregator.emit_agent_status(
            thread_id=thread_id,
            agent_id=agent_id,
            node_name="supervisor",
            state=AgentLifecycleState.SUBMITTED,
            detail="Processing user message",
        )

    return {"status": "accepted", "thread_id": thread_id}


# ---------------------------------------------------------------------------
# GET /team/status — Team status snapshot
# ---------------------------------------------------------------------------


@router.get("/team/status", response_model=TeamStatusResponse)
async def get_team_status_endpoint(
    aggregator: EventAggregator = Depends(get_aggregator),  # noqa: B008
) -> TeamStatusResponse:
    """Return current team status: agents, active threads, pending permissions.

    Agent summaries are sourced from node metadata cached by
    ``aggregator.register_graph()`` at graph compilation time (ADR-012 §6).
    """
    active_threads = aggregator.get_active_thread_ids()
    node_summaries = aggregator.get_node_summaries()

    agents = [
        _AgentStatusEntry(
            agent_id=s["agent_id"],
            node_name=s["node_name"],
            state=AgentLifecycleState.IDLE,
            role=s.get("role", ""),
            display_name=s.get("display_name", ""),
            description=s.get("description", ""),
        )
        for s in node_summaries
    ]

    return TeamStatusResponse(
        agents=agents,
        active_threads=active_threads,
        pending_permissions=[],
    )


# ---------------------------------------------------------------------------
# GET /teams — List available team presets (ADR-013 §6)
# ---------------------------------------------------------------------------

# Built-in preset IDs shipped with the package (ADR-013 §2.9).
_BUNDLED_TEAM_PRESETS = (
    "coding-star",
    "coding-pipeline",
    "coding-loop",
    "solo-coder",
)


@router.get("/teams", response_model=TeamPresetsResponse)
async def list_team_presets_endpoint() -> TeamPresetsResponse:
    """Return all available team presets for the team picker UI.

    Scans the bundled preset list and loads each ``TeamConfig``.
    Workspace-local overrides are not included in this listing (they
    shadow individual presets but are not auto-discovered in v1).
    """
    summaries: list[TeamPresetSummary] = []
    for preset_id in _BUNDLED_TEAM_PRESETS:
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
# POST /permissions/{request_id}/respond — Permission response (REST)
# ---------------------------------------------------------------------------


@router.post(
    "/permissions/{request_id}/respond",
    response_model=PermissionResponseResult,
)
async def respond_to_permission_endpoint(
    request_id: str,
    body: PermissionResponseRequest,
    aggregator: EventAggregator = Depends(get_aggregator),  # noqa: B008
    registry: GraphRegistry = Depends(get_graph_registry),  # noqa: B008
    tg: anyio.abc.TaskGroup = Depends(get_task_group),  # noqa: B008
) -> PermissionResponseResult:
    """Submit a permission response via REST for guaranteed delivery.

    Permission responses are handled via REST rather than WebSocket
    to ensure guaranteed delivery (ADR-011 §3.1).

    Resumes the LangGraph graph interrupt via ``Command(resume=option_id)``.
    The graph is re-invoked with ``Command(resume=option_id)`` as input, which
    causes the ``interrupt()`` call in the worker node to return ``option_id``.
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

    graph = registry.get(thread_id) if thread_id else None

    if graph is not None:
        config = {"configurable": {"thread_id": thread_id}}
        tg.start_soon(
            aggregator.ingest,
            thread_id,
            "supervisor",
            graph,
            Command(resume=body.option_id),
            config,
        )
        logger.info(
            "Resuming graph for thread %s with option_id=%s",
            thread_id,
            body.option_id,
        )
    else:
        logger.warning(
            "No graph found for request_id=%s (thread_id=%r) — cannot resume",
            request_id,
            thread_id,
        )

    return PermissionResponseResult(
        request_id=request_id,
        accepted=graph is not None,
        thread_id=thread_id,
    )

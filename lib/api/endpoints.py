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

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.aggregator import EventAggregator
from ..core.team_config import TeamConfigNotFoundError, load_team_config
from ..database.crud import create_thread, get_thread, list_threads
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
)
from .schemas.snapshots import ThreadStateSnapshot


__all__ = ["get_aggregator", "router"]

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Dependency: EventAggregator
# ---------------------------------------------------------------------------
# Injected at lifespan startup via app.state; the dependency just reads it.


def get_aggregator(request: Request) -> EventAggregator:
    """FastAPI dependency for the EventAggregator singleton.

    Reads from ``app.state.aggregator`` which is set during lifespan startup.
    """
    aggregator: EventAggregator | None = getattr(request.app.state, "aggregator", None)
    if aggregator is None:
        raise RuntimeError("EventAggregator not initialised in app state")
    return aggregator


# ---------------------------------------------------------------------------
# POST /threads — Create a new orchestration thread
# ---------------------------------------------------------------------------


@router.post("/threads", response_model=CreateThreadResponse, status_code=201)
async def create_thread_endpoint(
    body: CreateThreadRequest,
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> CreateThreadResponse:
    """Create a new orchestration thread and optionally start graph execution."""
    thread = await create_thread(
        db,
        title=body.title,
        status="submitted",
    )
    await db.commit()

    logger.info("Created thread %s (title=%s)", thread.id, body.title)

    return CreateThreadResponse(
        thread_id=thread.id,
        status=thread.status,
    )


# ---------------------------------------------------------------------------
# GET /threads — List threads (paginated)
# ---------------------------------------------------------------------------


@router.get("/threads", response_model=ThreadListResponse)
async def list_threads_endpoint(
    offset: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> ThreadListResponse:
    """List orchestration threads with pagination."""
    threads, total = await list_threads(db, offset=offset, limit=limit)
    summaries = [
        ThreadSummary(
            thread_id=t.id,
            title=t.title,
            status=t.status,
            created_at=t.created_at,
            updated_at=t.updated_at,
        )
        for t in threads
    ]
    return ThreadListResponse(threads=summaries, total=total)


# ---------------------------------------------------------------------------
# GET /threads/{thread_id}/state — Thread state snapshot (reconnection)
# ---------------------------------------------------------------------------


@router.get("/threads/{thread_id}/state", response_model=ThreadStateSnapshot)
async def get_thread_state_endpoint(
    thread_id: str,
    db: AsyncSession = Depends(get_db),  # noqa: B008
    aggregator: EventAggregator = Depends(get_aggregator),  # noqa: B008
) -> ThreadStateSnapshot:
    """Return a complete thread state snapshot for client reconnection.

    The ``last_sequence`` field enables gap detection: the client discards
    any subsequent WebSocket events with ``sequence <= last_sequence``
    (ADR-011 section 2.3).
    """
    thread = await get_thread(db, thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found")

    last_seq = aggregator.get_sequence(thread_id)

    return ThreadStateSnapshot(
        thread_id=thread.id,
        status=thread.status,
        last_sequence=last_seq,
    )


# ---------------------------------------------------------------------------
# POST /threads/{thread_id}/messages — Send message into thread
# ---------------------------------------------------------------------------


@router.post("/threads/{thread_id}/messages", status_code=202)
async def send_message_endpoint(
    thread_id: str,
    body: SendMessageRequest,
    db: AsyncSession = Depends(get_db),  # noqa: B008
    aggregator: EventAggregator = Depends(get_aggregator),  # noqa: B008
) -> dict[str, str]:
    """Send a user message into an existing thread.

    Returns 202 Accepted immediately; the graph processes asynchronously.
    """
    thread = await get_thread(db, thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found")

    logger.info(
        "Message received for thread %s: %d chars",
        thread_id,
        len(body.content),
    )

    # Emit agent status -> working
    await aggregator.emit_agent_status(
        thread_id=thread_id,
        agent_id=body.agent_id or "supervisor",
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
    """Return current team status: agents, active threads, pending permissions."""
    active_threads = aggregator.get_active_thread_ids()

    return TeamStatusResponse(
        agents=[],
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
) -> PermissionResponseResult:
    """Submit a permission response via REST for guaranteed delivery.

    Permission responses are handled via REST rather than WebSocket
    to ensure guaranteed delivery (ADR-011 section 3.1).
    """
    logger.info(
        "Permission response: request_id=%s, option_id=%s",
        request_id,
        body.option_id,
    )

    # Pending (Task #5): wire to LangGraph Command(resume=option_id) once
    # graph execution integration is connected.
    return PermissionResponseResult(
        request_id=request_id,
        accepted=True,
        thread_id="",  # Will be resolved from permission state
    )

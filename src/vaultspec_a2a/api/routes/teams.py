"""Team-related routes: GET /teams, GET /team/status, GET /team/presets."""

import logging

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ...database.crud import get_pending_permission_requests
from ...database.session import get_db
from ...streaming.aggregator import EventAggregator
from ...team.team_config import discover_team_preset_ids, load_team_config
from ...thread.errors import TeamConfigNotFoundError
from ..dependencies import get_aggregator
from ..schemas.enums import AgentLifecycleState
from ..schemas.rest import (
    AgentStatusEntry,
    PendingPermission,
    TeamPresetsResponse,
    TeamPresetSummary,
    TeamStatusResponse,
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/team/status", response_model=TeamStatusResponse)
async def get_team_status_endpoint(
    request: Request,
    aggregator: EventAggregator = Depends(get_aggregator),
    db: AsyncSession = Depends(get_db),
) -> TeamStatusResponse:
    """Return current team status: agents, active threads, pending permissions."""
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


@router.get("/teams", response_model=TeamPresetsResponse)
async def list_team_presets_endpoint() -> TeamPresetsResponse:
    """Return all available team presets for the team picker UI."""
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

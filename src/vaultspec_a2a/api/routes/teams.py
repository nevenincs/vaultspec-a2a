"""Team-related routes: GET /teams, GET /team/status, GET /team/presets."""

import logging

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ...control.team_service import build_team_status
from ...database.session import get_db
from ...streaming.aggregator import EventAggregator
from ...team.team_config import discover_team_preset_ids, load_team_config
from ...thread.enums import PermissionRequestStatus
from ...thread.errors import TeamConfigNotFoundError
from ..dependencies import get_aggregator
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
    status = await build_team_status(
        db=db, aggregator=aggregator, heartbeat_threads=heartbeat_threads
    )
    # Field names are spelled out rather than splatted from ``asdict``: a splat
    # silently drops any descriptor field the wire model does not share, which
    # is how provider/model previously reached the client as unconditional null.
    return TeamStatusResponse(
        agents=[
            AgentStatusEntry(
                agent_id=a.agent_id,
                node_name=a.node_name,
                state=a.state,
                provider=a.provider,
                model=a.model,
                role=a.role,
                display_name=a.display_name,
                description=a.description,
            )
            for a in status.agents
        ],
        active_threads=status.active_threads,
        pending_permissions=[
            PendingPermission(
                request_id=p.request_id,
                thread_id=p.thread_id,
                description=p.description,
                request_status=p.request_status or PermissionRequestStatus.PENDING,
            )
            for p in status.pending_permissions
        ],
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

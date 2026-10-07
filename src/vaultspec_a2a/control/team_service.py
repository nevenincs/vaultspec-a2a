"""Team status assembly service.

Extracts the agent-list, active-thread, and pending-permission
aggregation from the ``/team/status`` route into a protocol-agnostic
function.  The route handler converts the result to a Pydantic wire model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..database import actionable_pending_permissions
from ..graph.enums import AgentLifecycleState
from ..thread.snapshots import AgentData, build_agent_descriptor
from .permission_options import pending_is_actionable

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from ..streaming import RelayHub, RunLiveStateMirror

__all__ = ["build_team_status"]


@dataclass(frozen=True, slots=True)
class PendingPermissionInfo:
    """Protocol-agnostic pending permission."""

    request_id: str
    thread_id: str
    description: str
    request_status: str | None = None


@dataclass(frozen=True, slots=True)
class TeamStatus:
    """Assembled team status returned by :func:`build_team_status`."""

    agents: list[AgentData] = field(default_factory=list)
    active_threads: list[str] = field(default_factory=list)
    pending_permissions: list[PendingPermissionInfo] = field(default_factory=list)


def _active_agent_descriptors(
    mirror: RunLiveStateMirror, active_threads: list[str]
) -> list[AgentData]:
    agents: list[AgentData] = []
    for thread_id in active_threads:
        agent_states = mirror.get_agent_states(thread_id)
        agents.extend(
            build_agent_descriptor(
                summary,
                agent_states.get(summary["agent_id"], AgentLifecycleState.IDLE),
                thread_id=thread_id,
            )
            for summary in mirror.get_node_summaries(thread_id)
        )
    return agents


async def build_team_status(
    *,
    db: AsyncSession,
    aggregator: RelayHub,
    heartbeat_threads: list[str],
) -> TeamStatus:
    """Assemble the full team status from DB and the relay hub's live state."""
    live_pending = await actionable_pending_permissions(db)
    # A run holding any unanswered request is active even when none of them is
    # actionable; only the actionable ones are advertised as waiting.
    public_pending: list[PendingPermissionInfo] = [
        PendingPermissionInfo(
            request_id=p.request.request_id,
            thread_id=p.request.thread_id,
            description=p.request.description,
            request_status=p.request.request_status,
        )
        for p in live_pending
        if pending_is_actionable(p)
    ]
    active_threads = sorted(
        set(heartbeat_threads)
        | set(aggregator.get_active_thread_ids())
        | {p.request.thread_id for p in live_pending}
    )

    # Public pending permissions must be durable-backed; the relay hub is
    # still read for agents and active-thread liveness, not permission truth.
    return TeamStatus(
        agents=_active_agent_descriptors(aggregator.mirror, active_threads),
        active_threads=active_threads,
        pending_permissions=public_pending,
    )

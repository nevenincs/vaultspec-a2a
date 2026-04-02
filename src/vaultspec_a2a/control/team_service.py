"""Team status assembly service.

Extracts the agent-list, active-thread, and pending-permission
aggregation from the ``/team/status`` route into a protocol-agnostic
function.  The route handler converts the result to a Pydantic wire model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..database import get_pending_permission_requests
from ..graph.enums import AgentLifecycleState

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from ..streaming.aggregator import EventAggregator

__all__ = ["TeamStatus", "build_team_status"]


@dataclass(frozen=True, slots=True)
class AgentInfo:
    """Protocol-agnostic agent summary."""

    agent_id: str
    node_name: str
    state: AgentLifecycleState
    role: str = ""
    display_name: str = ""
    description: str = ""


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

    agents: list[AgentInfo] = field(default_factory=list)
    active_threads: list[str] = field(default_factory=list)
    pending_permissions: list[PendingPermissionInfo] = field(default_factory=list)


async def build_team_status(
    *,
    db: AsyncSession,
    aggregator: EventAggregator,
    heartbeat_threads: list[str],
) -> TeamStatus:
    """Assemble the full team status from DB and in-memory aggregator state."""
    durable_pending = await get_pending_permission_requests(db)
    active_threads = sorted(
        set(heartbeat_threads)
        | set(aggregator.get_active_thread_ids())
        | {p.thread_id for p in durable_pending}
    )

    node_summaries = aggregator.get_node_summaries()
    agent_states = aggregator.get_agent_states()

    agents = [
        AgentInfo(
            agent_id=s["agent_id"],
            node_name=s["node_name"],
            state=agent_states.get(s["agent_id"], AgentLifecycleState.IDLE),
            role=s.get("role", ""),
            display_name=s.get("display_name", ""),
            description=s.get("description", ""),
        )
        for s in node_summaries
    ]

    # Durable permissions from DB, then deduplicate with in-memory aggregator.
    pending: list[PendingPermissionInfo] = [
        PendingPermissionInfo(
            request_id=p.request_id,
            thread_id=p.thread_id,
            description=p.description,
            request_status=p.request_status,
        )
        for p in durable_pending
    ]
    known_ids = {p.request_id for p in pending}
    pending.extend(
        PendingPermissionInfo(
            request_id=e.request_id,
            thread_id=e.thread_id,
            description=e.description,
        )
        for e in aggregator.get_pending_permissions()
        if e.request_id not in known_ids
    )

    return TeamStatus(
        agents=agents,
        active_threads=active_threads,
        pending_permissions=pending,
    )

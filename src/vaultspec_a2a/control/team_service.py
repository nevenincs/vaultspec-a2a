"""Team status assembly service.

Extracts the agent-list, active-thread, and pending-permission
aggregation from the ``/team/status`` route into a protocol-agnostic
function.  The route handler converts the result to a Pydantic wire model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from sqlalchemy import select

from ..database import get_pending_permission_requests
from ..database.models import ThreadModel
from ..graph.enums import AgentLifecycleState
from ..thread.enums import TERMINAL_STATUSES
from .permission_options import extract_allowed_option_ids

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from ..streaming.aggregator import EventAggregator

__all__ = ["TeamStatus", "build_team_status"]


def _has_valid_permission_options(raw_options_json: str | None) -> bool:
    """Return True only when a durable pending row exposes usable option ids."""
    return bool(extract_allowed_option_ids(raw_options_json))


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
    durable_pending = await get_pending_permission_requests(
        db,
        include_answered_pending_apply=False,
    )
    thread_ids = sorted({permission.thread_id for permission in durable_pending})
    terminal_thread_ids: set[str] = set()
    if thread_ids:
        terminal_statuses = [status.value for status in TERMINAL_STATUSES]
        rows = await db.execute(
            select(ThreadModel.id, ThreadModel.status).where(
                ThreadModel.id.in_(thread_ids)
            )
        )
        terminal_thread_ids = {
            thread_id for thread_id, status in rows.all() if status in terminal_statuses
        }

    nonterminal_durable_pending = [
        permission
        for permission in durable_pending
        if permission.thread_id not in terminal_thread_ids
    ]
    public_pending: list[PendingPermissionInfo] = [
        PendingPermissionInfo(
            request_id=p.request_id,
            thread_id=p.thread_id,
            description=p.description,
            request_status=p.request_status,
        )
        for p in nonterminal_durable_pending
        if _has_valid_permission_options(p.allowed_options_json)
    ]
    active_threads = sorted(
        set(heartbeat_threads)
        | set(aggregator.get_active_thread_ids())
        | {permission.thread_id for permission in nonterminal_durable_pending}
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

    # Public pending permissions must be durable-backed; aggregator state is
    # still used for agents and active-thread liveness, not permission truth.
    return TeamStatus(
        agents=agents,
        active_threads=active_threads,
        pending_permissions=public_pending,
    )

"""Team status assembly service.

Extracts the agent-list, active-thread, and pending-permission
aggregation from the ``/team/status`` route into a protocol-agnostic
function.  The route handler converts the result to a Pydantic wire model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from sqlalchemy import select

from ..database import (
    ThreadModel,
    get_pending_permission_requests,
    path_safe_run_id_clause,
)
from ..graph.enums import AgentLifecycleState
from ..thread.enums import TERMINAL_STATUS_VALUES, RepairStatus
from ..thread.snapshots import AgentData, build_agent_descriptor
from .permission_options import extract_allowed_option_ids

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from ..streaming.aggregator import EventAggregator

__all__ = ["build_team_status"]


def _has_valid_permission_options(raw_options_json: str | None) -> bool:
    """Return True only when a durable pending row exposes usable option ids."""
    return bool(extract_allowed_option_ids(raw_options_json))


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


async def _pending_thread_sets(
    db: AsyncSession, thread_ids: list[str]
) -> tuple[set[str], set[str], set[str]]:
    if not thread_ids:
        return set(), set(), set()
    # Path-unsafe or missing thread ids stay absent from known_thread_ids, so
    # their permissions are excluded below. The respond route cannot address
    # those ids; passing them to the status serializer would hide valid rows
    # behind a whole-response validation error.
    rows = await db.execute(
        select(
            ThreadModel.id,
            ThreadModel.status,
            ThreadModel.repair_status,
            ThreadModel.execution_readiness,
        ).where(ThreadModel.id.in_(thread_ids), path_safe_run_id_clause())
    )
    known_rows = rows.all()
    known_thread_ids = {thread_id for thread_id, *_rest in known_rows}
    terminal_thread_ids = {
        thread_id
        for thread_id, status, _repair_status, _execution_readiness in known_rows
        if status in TERMINAL_STATUS_VALUES
    }
    checkpoint_unavailable_thread_ids = {
        thread_id
        for thread_id, _status, repair_status, execution_readiness in known_rows
        if repair_status == RepairStatus.CHECKPOINT_UNAVAILABLE.value
        or execution_readiness == RepairStatus.CHECKPOINT_UNAVAILABLE.value
    }
    return known_thread_ids, terminal_thread_ids, checkpoint_unavailable_thread_ids


def _active_agent_descriptors(
    aggregator: EventAggregator, active_threads: list[str]
) -> list[AgentData]:
    agents: list[AgentData] = []
    for thread_id in active_threads:
        agent_states = aggregator.get_agent_states(thread_id)
        agents.extend(
            build_agent_descriptor(
                summary,
                agent_states.get(summary["agent_id"], AgentLifecycleState.IDLE),
                thread_id=thread_id,
            )
            for summary in aggregator.get_node_summaries(thread_id)
        )
    return agents


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
    (
        known_thread_ids,
        terminal_thread_ids,
        checkpoint_unavailable_thread_ids,
    ) = await _pending_thread_sets(db, thread_ids)

    nonterminal_durable_pending = [
        permission
        for permission in durable_pending
        if permission.thread_id in known_thread_ids
        and permission.thread_id not in terminal_thread_ids
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
        and p.thread_id not in checkpoint_unavailable_thread_ids
    ]
    active_threads = sorted(
        set(heartbeat_threads)
        | set(aggregator.get_active_thread_ids())
        | {permission.thread_id for permission in nonterminal_durable_pending}
    )

    # Public pending permissions must be durable-backed; aggregator state is
    # still used for agents and active-thread liveness, not permission truth.
    return TeamStatus(
        agents=_active_agent_descriptors(aggregator, active_threads),
        active_threads=active_threads,
        pending_permissions=public_pending,
    )

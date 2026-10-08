"""Run-status, the run listing and the team status read one run the same way.

Three surfaces answer "what is this run waiting on, and is its record sound":
``capture_thread_state`` for run-status and run-history, ``list_threads_service``
for the listing, and ``build_team_status`` for the team projection. They read the
same durable rows and the same checkpoint, so a question answered differently by
two of them is a defect in whichever one is wrong, not a feature of either.

Each case drives all three against ONE seeded run over a real SQLite store and a
real ``AsyncSqliteSaver``, with the pause parked by the graph's own interrupt so
the checkpoint half is genuine: the checkpoint is the pause authority, and a run
with no checkpoint is withheld for a different reason entirely, which would let
these cases pass without ever reaching the rule they are about.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import update

from ...database import PermissionRequestModel, record_permission_request
from ...streaming import RelayHub
from ...testing import (
    elect_status,
    park_journaled_permission,
    park_permission,
    park_plan_approval,
    seed_accepted_thread,
)
from ...thread.enums import DegradedReason, InterruptType, RepairStatus, ThreadStatus
from ..team_service import build_team_status
from ..thread_listing import list_threads_service
from ..thread_state_service import capture_thread_state

if TYPE_CHECKING:
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from ...thread.snapshots import ThreadStateSnapshot
    from ..thread_listing import ThreadSummaryData

#: An offer whose single entry carries no option id, so nothing a respond verb
#: could name is on it. The JSON is intact: the row reads perfectly, and what it
#: offers is what cannot be answered.
_UNNAMEABLE_OFFER: list[dict[str, object]] = [{"name": "Approve"}]

#: An offer a respond verb can act on.
_ALLOW_ONCE: list[dict[str, object]] = [
    {"optionId": "allow_once", "name": "Allow once", "kind": "allow_once"}
]

_WORKSPACE = Path(__file__).resolve().parent


async def _seed_run(
    session_factory: async_sessionmaker[AsyncSession], thread_id: str
) -> None:
    """Commit an accepted running run, as a real dispatch leaves one."""
    async with session_factory() as session:
        await seed_accepted_thread(session, thread_id=thread_id, workspace=_WORKSPACE)
        await session.commit()


async def _settle(
    session_factory: async_sessionmaker[AsyncSession],
    thread_id: str,
    status: ThreadStatus,
) -> None:
    """Move the run to *status* through the production election."""
    async with session_factory() as session:
        await elect_status(session, thread_id, status)
        await session.commit()


async def _journal_plan_approval(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    thread_id: str,
    request_id: str,
    offered: list[dict[str, object]],
) -> None:
    """Journal the plan approval a parked gate raised, as the relay journals it."""
    async with session_factory() as session:
        await record_permission_request(
            session,
            request_id=request_id,
            thread_id=thread_id,
            pause_reason_type=InterruptType.PLAN_APPROVAL_REQUEST.value,
            description="Approve the plan?",
            allowed_options=offered,
            tool_call=None,
        )
        await session.commit()


async def _corrupt_offer(
    session_factory: async_sessionmaker[AsyncSession], request_id: str
) -> None:
    """Leave the row's cached offer as something that is not a JSON list.

    The one shape the option decoder answers ``None`` for, so the row is
    genuinely unreadable rather than merely empty.
    """
    async with session_factory() as session:
        await session.execute(
            update(PermissionRequestModel)
            .where(PermissionRequestModel.request_id == request_id)
            .values(allowed_options_json='{"not": "a list"}')
        )
        await session.commit()


async def _capture(
    session_factory: async_sessionmaker[AsyncSession],
    checkpointer: AsyncSqliteSaver,
    thread_id: str,
) -> ThreadStateSnapshot:
    """The snapshot run-status and run-history both serve."""
    async with session_factory() as session:
        capture = await capture_thread_state(
            session,
            thread_id=thread_id,
            relay_hub=RelayHub(),
            checkpointer=checkpointer,
        )
    assert capture is not None
    return capture.snapshot


async def _summary(
    session_factory: async_sessionmaker[AsyncSession],
    checkpointer: AsyncSqliteSaver,
    thread_id: str,
) -> ThreadSummaryData:
    """The listing's summary of one run."""
    async with session_factory() as session:
        listing = await list_threads_service(session, checkpointer=checkpointer)
    return next(
        summary for summary in listing.threads if summary.thread_id == thread_id
    )


async def _team_pending(
    session_factory: async_sessionmaker[AsyncSession], thread_id: str
) -> list[str]:
    """The request ids the team status advertises as waiting on *thread_id*."""
    async with session_factory() as session:
        status = await build_team_status(
            db=session, relay_hub=RelayHub(), heartbeat_threads=[]
        )
    return [
        pending.request_id
        for pending in status.pending_permissions
        if pending.thread_id == thread_id
    ]


@pytest.mark.asyncio
async def test_a_row_offering_no_usable_option_is_hidden_by_every_surface(
    session_factory: async_sessionmaker[AsyncSession],
    checkpointer: AsyncSqliteSaver,
) -> None:
    """One visibility rule: an unanswerable offer is withheld and reported.

    The respond verb validates an answer against the offer, so a request
    offering nothing a response could name is a pause no caller can lift, and
    disclosing it as pending invites an answer that is refused. All three
    surfaces therefore withhold it, and run-status reports the row as degraded
    rather than dropping it silently: the tool-permission model refuses such a
    request at the worker, so a run parked on one is a fault in the record.
    """
    await _seed_run(session_factory, "no-usable-option")
    request_id = await park_journaled_permission(
        checkpointer,
        session_factory,
        thread_id="no-usable-option",
        options=_UNNAMEABLE_OFFER,
    )
    assert request_id

    snapshot = await _capture(session_factory, checkpointer, "no-usable-option")
    summary = await _summary(session_factory, checkpointer, "no-usable-option")
    team = await _team_pending(session_factory, "no-usable-option")

    assert snapshot.checkpoint_id is not None, "the run must have checkpoint truth"
    assert snapshot.pending_permissions == []
    assert (
        DegradedReason.PERMISSION_OFFERS_NO_USABLE_OPTION in snapshot.degraded_reasons
    )
    assert snapshot.repair_status == RepairStatus.OPERATOR_INTERVENTION_REQUIRED

    assert summary.repair_status == RepairStatus.OPERATOR_INTERVENTION_REQUIRED.value
    assert (
        summary.execution_readiness == RepairStatus.OPERATOR_INTERVENTION_REQUIRED.value
    )

    assert team == []


@pytest.mark.asyncio
async def test_an_answerable_plan_approval_is_disclosed_by_every_surface(
    session_factory: async_sessionmaker[AsyncSession],
    checkpointer: AsyncSqliteSaver,
) -> None:
    """The counterpart: a request that CAN be answered is served by all three.

    Without this the rule above would be satisfied by withholding everything.
    """
    await _seed_run(session_factory, "usable-option")
    request_id = await park_plan_approval(checkpointer, thread_id="usable-option")
    await _journal_plan_approval(
        session_factory,
        thread_id="usable-option",
        request_id=request_id,
        offered=_ALLOW_ONCE,
    )

    snapshot = await _capture(session_factory, checkpointer, "usable-option")
    summary = await _summary(session_factory, checkpointer, "usable-option")
    team = await _team_pending(session_factory, "usable-option")

    assert [p.request_id for p in snapshot.pending_permissions] == [request_id]
    assert snapshot.approval_request_id == request_id
    assert (
        DegradedReason.PERMISSION_PROJECTION_UNREADABLE not in snapshot.degraded_reasons
    )
    assert summary.approval_request_id == request_id
    assert team == [request_id]


@pytest.mark.asyncio
async def test_a_settled_run_holding_permission_residue_degrades_the_listing(
    session_factory: async_sessionmaker[AsyncSession],
    checkpointer: AsyncSqliteSaver,
) -> None:
    """The listing reports the residue run-status reports, not a healthy run.

    A run that settled while a request was still open left that request
    unanswerable forever. Run-status has always called that a run needing
    reconciliation; the listing called the same run healthy, so the reading an
    operator scans first was the one that hid it.
    """
    await _seed_run(session_factory, "terminal-residue")
    await park_journaled_permission(
        checkpointer,
        session_factory,
        thread_id="terminal-residue",
        options=_ALLOW_ONCE,
    )
    await _settle(session_factory, "terminal-residue", ThreadStatus.COMPLETED)

    snapshot = await _capture(session_factory, checkpointer, "terminal-residue")
    summary = await _summary(session_factory, checkpointer, "terminal-residue")

    assert (
        DegradedReason.TERMINAL_THREAD_PENDING_PERMISSION_RESIDUE
        in snapshot.degraded_reasons
    )
    assert snapshot.repair_status == RepairStatus.NEEDS_RECONCILIATION
    assert summary.repair_status == RepairStatus.NEEDS_RECONCILIATION.value
    assert summary.execution_readiness == RepairStatus.NEEDS_RECONCILIATION.value


@pytest.mark.asyncio
async def test_a_parked_permission_with_no_durable_row_degrades_the_listing(
    session_factory: async_sessionmaker[AsyncSession],
    checkpointer: AsyncSqliteSaver,
) -> None:
    """A pause the respond route cannot address degrades on both readings.

    The checkpoint is the pause authority, and the durable row is the only
    source of a pending request's content: parked with no row, the run is held
    by a question nothing can answer. Run-status reconciled that; the listing
    read the same checkpoint and called the run healthy.
    """
    await _seed_run(session_factory, "parked-no-row")
    assert await park_permission(checkpointer, thread_id="parked-no-row")

    snapshot = await _capture(session_factory, checkpointer, "parked-no-row")
    summary = await _summary(session_factory, checkpointer, "parked-no-row")

    assert (
        DegradedReason.CHECKPOINT_PERMISSION_WITHOUT_DURABLE_ROW
        in snapshot.degraded_reasons
    )
    assert snapshot.repair_status == RepairStatus.NEEDS_RECONCILIATION
    assert summary.repair_status == RepairStatus.NEEDS_RECONCILIATION.value
    assert summary.execution_readiness == RepairStatus.NEEDS_RECONCILIATION.value


@pytest.mark.asyncio
async def test_an_unreadable_pending_permission_escalates_on_both_readings(
    session_factory: async_sessionmaker[AsyncSession],
    checkpointer: AsyncSqliteSaver,
) -> None:
    """A row whose cached offer cannot be decoded needs a human on both readings."""
    await _seed_run(session_factory, "unreadable-offer")
    request_id = await park_journaled_permission(
        checkpointer,
        session_factory,
        thread_id="unreadable-offer",
        options=_ALLOW_ONCE,
    )
    await _corrupt_offer(session_factory, request_id)

    snapshot = await _capture(session_factory, checkpointer, "unreadable-offer")
    summary = await _summary(session_factory, checkpointer, "unreadable-offer")

    assert snapshot.pending_permissions == []
    assert DegradedReason.PERMISSION_PROJECTION_UNREADABLE in snapshot.degraded_reasons
    assert snapshot.repair_status == RepairStatus.OPERATOR_INTERVENTION_REQUIRED
    assert summary.repair_status == RepairStatus.OPERATOR_INTERVENTION_REQUIRED.value
    assert (
        summary.execution_readiness == RepairStatus.OPERATOR_INTERVENTION_REQUIRED.value
    )

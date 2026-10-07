"""A run's cursor is the highest frame number its stream issued.

The gateway numbers a run's frames through ``RunSequenceAllocator``, and
``ThreadModel.last_sequence`` is that same mark, recorded when the run settles
and served by ``capture_thread_state`` for a run that has not. These tests drive
the real production seam (``_handle_terminal_event`` against a real SQLite-backed
session, a real ``RelayHub`` numbering through a real ``RunEventStore``,
and ``capture_thread_state`` for the read side) and prove the cursor agrees with
the number the allocator handed out, not with any counter kept beside it.

A run no allocator numbers (replay disabled) records no cursor at all rather
than a number some other counter happened to hold.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from ...database import (
    RunEventRecord,
    RunEventStore,
    create_control_action,
    create_thread,
)
from ...database.models import ThreadModel
from ...graph.enums import AgentLifecycleState
from ...ipc.schemas import DispatchRequest
from ...streaming import RelayHub, RunSequenceAllocator
from ...team.team_config import load_team_config
from ...testing import DEFAULT_TEAM_PRESET
from ...tests._checkpoint_seeding import real_checkpoint
from ...tests._write_authority import make_test_write_authority
from ...thread.action_receipts import GraphActionReceipt, GraphCompletionReceipt
from ...thread.enums import ThreadStatus
from ...thread.executable_graph import freeze_graph_definition
from ...thread.idempotency import thread_create_action_key
from ..accepted_input import freeze_accepted_input
from ..dispatch_receipts import prepare_graph_action_receipt
from ..event_handlers import _handle_terminal_event
from ..thread_state_service import capture_thread_state

if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
    )


async def _seed_completed_authority(
    session: AsyncSession, checkpointer: AsyncSqliteSaver, *, title: str
) -> tuple[str, GraphActionReceipt]:
    authority = make_test_write_authority()
    workspace = Path.cwd()
    thread = await create_thread(
        session,
        write_authority=authority,
        status=ThreadStatus.RUNNING,
        title=title,
    )
    dispatch = DispatchRequest(
        dispatch_id=authority.action_receipt_id,
        action="ingest",
        thread_id=thread.id,
        content="sequence fixture",
        workspace_root=str(workspace),
        team_preset=DEFAULT_TEAM_PRESET,
        graph_definition=freeze_graph_definition(
            load_team_config(DEFAULT_TEAM_PRESET, workspace_root=workspace),
            workspace_root=workspace,
        ),
        recursion_limit=25,
    )
    await create_control_action(
        session,
        thread_id=thread.id,
        action_type=authority.action_type,
        idempotency_key=thread_create_action_key(thread.id),
        dispatch_id=authority.action_receipt_id,
        recovery_deadline_at=datetime.now(UTC) + timedelta(minutes=5),
        payload=freeze_accepted_input(dispatch, intent={"content": "sequence fixture"}),
    )
    receipt = await prepare_graph_action_receipt(
        session, thread_id=thread.id, dispatch_id=authority.action_receipt_id
    )
    assert receipt is not None
    await session.commit()
    config: RunnableConfig = {
        "configurable": {"thread_id": thread.id, "checkpoint_ns": ""}
    }
    checkpoint = await real_checkpoint()
    checkpoint["id"] = f"cp-{thread.id}"
    checkpoint["channel_values"] = {
        "active_graph_action_receipt": receipt.model_dump(mode="json"),
        "graph_action_receipts": {receipt.dispatch_id: receipt.model_dump(mode="json")},
        "graph_completion_receipts": {
            receipt.dispatch_id: GraphCompletionReceipt(
                schema_version="graph-completion-v1",
                action=receipt,
                outcome="completed",
            ).model_dump(mode="json")
        },
    }
    checkpoint["channel_versions"] = {
        "active_graph_action_receipt": checkpointer.get_next_version(None, None),
        "graph_action_receipts": checkpointer.get_next_version(None, None),
        "graph_completion_receipts": checkpointer.get_next_version(None, None),
    }
    await checkpointer.aput(
        config,
        checkpoint,
        {"source": "loop", "step": 1, "parents": {}},
        checkpoint["channel_versions"],
    )
    return thread.id, receipt


def _numbered_aggregator(
    session_factory: async_sessionmaker[AsyncSession],
) -> RelayHub:
    """A relay hub whose frames are numbered by the real allocator and store."""
    aggregator = RelayHub()
    aggregator.bind_sequence_allocator(
        RunSequenceAllocator(RunEventStore(session_factory))
    )
    return aggregator


async def _relay_frames(aggregator: RelayHub, thread_id: str, count: int) -> None:
    """Relay *count* worker frames, each carrying the worker's own ordering."""
    await aggregator.prepare_run(thread_id)
    for worker_sequence in range(1, count + 1):
        aggregator.relay_payload(
            thread_id,
            {
                "type": "agent_status",
                "event_type": "agent_status",
                "thread_id": thread_id,
                "agent_id": "coder",
                "state": AgentLifecycleState.WORKING.value,
                "sequence": worker_sequence,
            },
        )


async def _seed_running_thread(
    session_factory: async_sessionmaker[AsyncSession], *, title: str
) -> str:
    async with session_factory() as session:
        thread = await create_thread(
            session,
            write_authority=make_test_write_authority(),
            status=ThreadStatus.RUNNING,
            title=title,
        )
        await session.commit()
        return thread.id


@pytest.mark.asyncio
async def test_settle_records_the_number_the_allocator_issued(
    session_factory: async_sessionmaker[AsyncSession],
    checkpointer: AsyncSqliteSaver,
) -> None:
    """The durable column holds the allocator's mark, and the mark outlives the purge.

    The settle handler purges the aggregator's per-run state in its own final
    step. The allocator forgets the live counter on that purge but keeps the
    floor it reached, so the mark it issued stays readable afterwards and the
    column agrees with it.
    """
    async with session_factory() as session:
        thread_id, _receipt = await _seed_completed_authority(
            session, checkpointer, title="terminal sequence capture"
        )

    aggregator = _numbered_aggregator(session_factory)
    await _relay_frames(aggregator, thread_id, 7)
    assert aggregator.issued_sequence(thread_id) == 7

    await _handle_terminal_event(
        thread_id,
        {"event_type": "thread_terminal", "status": "completed"},
        aggregator=aggregator,
        session_factory=session_factory,
        checkpointer=checkpointer,
    )

    async with session_factory() as session:
        row = await session.get(ThreadModel, thread_id)
        assert row is not None
        assert row.last_sequence == 7
    assert aggregator.issued_sequence(thread_id) == 7


@pytest.mark.asyncio
async def test_a_reconnecting_client_reads_the_true_cursor_after_settle(
    session_factory: async_sessionmaker[AsyncSession], checkpointer: AsyncSqliteSaver
) -> None:
    """The read a reconnecting client actually makes: after the run has settled.

    A SECOND, LATER call, once the settle handler has purged the aggregator's
    state for the run: the cursor served is the durable column, not whatever the
    live allocator still holds.
    """
    async with session_factory() as session:
        thread_id, _receipt = await _seed_completed_authority(
            session, checkpointer, title="reconnect after settle"
        )

    aggregator = _numbered_aggregator(session_factory)
    await _relay_frames(aggregator, thread_id, 3)

    await _handle_terminal_event(
        thread_id,
        {"event_type": "thread_terminal", "status": "completed"},
        aggregator=aggregator,
        session_factory=session_factory,
        checkpointer=checkpointer,
    )

    async with session_factory() as db:
        capture = await capture_thread_state(
            db,
            thread_id=thread_id,
            aggregator=aggregator,
            checkpointer=checkpointer,
        )
    assert capture is not None
    assert capture.snapshot.last_sequence == 3


@pytest.mark.asyncio
async def test_a_live_run_reads_the_allocators_issued_mark(
    session_factory: async_sessionmaker[AsyncSession], checkpointer: AsyncSqliteSaver
) -> None:
    """A non-terminal thread has no durable cursor yet, so the allocator answers.

    `ThreadModel.last_sequence` stays NULL until a run settles, so
    `capture_thread_state` reads the allocator's mark for an active run -
    falling back to 0 instead would make an in-progress run look falsely reset.
    """
    thread_id = await _seed_running_thread(session_factory, title="still running")

    aggregator = _numbered_aggregator(session_factory)
    await _relay_frames(aggregator, thread_id, 4)

    async with session_factory() as db:
        capture = await capture_thread_state(
            db,
            thread_id=thread_id,
            aggregator=aggregator,
            checkpointer=checkpointer,
        )
    assert capture is not None
    assert capture.snapshot.last_sequence == 4


@pytest.mark.asyncio
async def test_a_live_run_after_a_gateway_restart_reads_the_retained_mark(
    session_factory: async_sessionmaker[AsyncSession], checkpointer: AsyncSqliteSaver
) -> None:
    """A fresh gateway has issued nothing yet, and must not report a rewound cursor.

    The allocator has not touched the run, so it has no mark of its own; the
    retained window's greatest sequence is what it would seed from, and what is
    served.
    """
    thread_id = await _seed_running_thread(session_factory, title="restarted gateway")
    await RunEventStore(session_factory).append(
        [
            RunEventRecord(
                thread_id=thread_id,
                sequence=sequence,
                event_type="agent_status",
                payload_json="{}",
                created_at=datetime.now(UTC),
            )
            for sequence in range(1, 10)
        ]
    )

    aggregator = _numbered_aggregator(session_factory)
    assert aggregator.issued_sequence(thread_id) is None

    async with session_factory() as db:
        capture = await capture_thread_state(
            db,
            thread_id=thread_id,
            aggregator=aggregator,
            checkpointer=checkpointer,
        )
    assert capture is not None
    assert capture.snapshot.last_sequence == 9


@pytest.mark.asyncio
async def test_a_run_no_allocator_numbers_settles_without_a_cursor(
    session_factory: async_sessionmaker[AsyncSession], checkpointer: AsyncSqliteSaver
) -> None:
    """Replay disabled: nothing is numbered, so settle records no cursor at all."""
    async with session_factory() as session:
        thread_id, _receipt = await _seed_completed_authority(
            session, checkpointer, title="no allocator"
        )

    aggregator = RelayHub()
    assert aggregator.issued_sequence(thread_id) is None

    await _handle_terminal_event(
        thread_id,
        {"event_type": "thread_terminal", "status": "completed"},
        aggregator=aggregator,
        session_factory=session_factory,
        checkpointer=checkpointer,
    )

    async with session_factory() as session:
        row = await session.get(ThreadModel, thread_id)
        assert row is not None
        assert row.last_sequence is None

    async with session_factory() as db:
        capture = await capture_thread_state(
            db,
            thread_id=thread_id,
            aggregator=aggregator,
            checkpointer=checkpointer,
        )
    assert capture is not None
    assert capture.snapshot.last_sequence == 0

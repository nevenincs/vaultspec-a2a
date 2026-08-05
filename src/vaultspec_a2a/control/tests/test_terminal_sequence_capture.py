"""F19: the reconnect cursor must survive the terminal-settle prune.

``EventAggregator``/``EventEmitters`` hold ``last_sequence`` only in memory,
keyed by thread id, and ``aggregator.clear_thread_state`` -- called from
``_handle_terminal_event``'s ``finally`` block on every terminal outcome --
prunes it the moment a run settles. A REST client's reconnect-cursor
comparison only matters *after* settle, so every read after that point was
answering the pruned default (0) regardless of how many events the run
actually emitted.

The fix captures the value before the prune and persists it durably
(``ThreadModel.last_sequence``) alongside ``failure_reason``/
``provider_condition``/``repair_status``, which already follow this exact
pattern for other terminal facts. These tests drive the real production
seam (``_handle_terminal_event`` against a real SQLite-backed session, a real
``EventAggregator``, and ``capture_thread_state`` for the read side) and
prove the *ordering*, not just the value: a durable capture that happened to
read a stale value because the prune ran first would report 0 here exactly
as the unfixed code did.

A separate local ``session_factory``/``checkpointer`` fixture pair rather than
importing the ones from ``test_event_handlers.py`` or ``api/tests/conftest.py``:
both those files are under concurrent edit by other sessions in this shared
tree, and this file must not depend on their in-flight state.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ...conftest import materialize_schema
from ...database import create_thread
from ...database.models import ThreadModel
from ...streaming.aggregator import EventAggregator
from ...thread.enums import ThreadStatus
from ..event_handlers import _handle_terminal_event
from ..thread_state_service import capture_thread_state


@pytest_asyncio.fixture
async def engine(tmp_path_factory: pytest.TempPathFactory):
    """Real SQLite-backed engine, isolated per test."""
    case_dir = tmp_path_factory.mktemp("terminal-sequence-capture-db")
    db_file = case_dir / "test.db"
    materialize_schema(Path(db_file))
    eng = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session_factory(engine):
    """Async session factory bound to the test engine."""
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def checkpointer(tmp_path_factory: pytest.TempPathFactory):
    """Real AsyncSqliteSaver, isolated per test (matches api/tests/conftest.py)."""
    case_dir = tmp_path_factory.mktemp("terminal-sequence-capture-checkpoints")
    db_file = case_dir / "test_checkpoints.db"
    async with AsyncSqliteSaver.from_conn_string(str(db_file)) as cp:
        yield cp


@pytest.mark.asyncio
async def test_the_sequence_is_captured_before_the_prune_discards_it(
    session_factory,
) -> None:
    """Fails on unfixed code: the durable column reads 0, not the real count.

    An aggregator whose sequence counter is genuinely non-zero for this
    thread proves the ordering, not just the value: `clear_thread_state`
    (called from the SAME handler's `finally` block, on every exit path)
    demonstrably ran -- the live counter reads 0 afterward -- yet the durable
    column holds the pre-prune value. That combination is only reachable if
    the capture happened before the prune; a capture reading the already-
    pruned default would durably persist 0 here too, indistinguishable from
    the defect.
    """
    async with session_factory() as session:
        thread = await create_thread(
            session, status=ThreadStatus.RUNNING, title="terminal sequence capture"
        )
        await session.commit()
        thread_id = thread.id

    aggregator = EventAggregator()
    for _ in range(7):
        aggregator.advance_sequence(thread_id)
    assert aggregator.get_sequence(thread_id) == 7

    await _handle_terminal_event(
        thread_id,
        {"event_type": "thread_terminal", "status": "completed"},
        aggregator=aggregator,
        session_factory=session_factory,
    )

    # The prune genuinely ran: the live counter is gone.
    assert aggregator.get_sequence(thread_id) == 0

    # And the durable column holds the value captured before it ran.
    async with session_factory() as session:
        row = await session.get(ThreadModel, thread_id)
        assert row is not None
        assert row.last_sequence == 7


@pytest.mark.asyncio
async def test_a_reconnecting_client_reads_the_true_cursor_after_settle(
    session_factory, checkpointer
) -> None:
    """The only read that matters -- after the run has already settled.

    A live-run assertion (reading `last_sequence` while the thread is still
    RUNNING) would pass on unfixed code too, since the in-memory value has
    not been pruned yet. This asserts the read that actually exercises the
    reconnect-cursor contract: a SECOND, LATER call, after the aggregator's
    copy is long gone.
    """
    async with session_factory() as session:
        thread = await create_thread(
            session, status=ThreadStatus.RUNNING, title="reconnect after settle"
        )
        await session.commit()
        thread_id = thread.id

    aggregator = EventAggregator()
    for _ in range(3):
        aggregator.advance_sequence(thread_id)

    await _handle_terminal_event(
        thread_id,
        {"event_type": "thread_terminal", "status": "completed"},
        aggregator=aggregator,
        session_factory=session_factory,
    )

    # The live copy is gone -- this is the state a client's REST reconnect
    # read actually lands in, well after the run's own settle.
    assert aggregator.get_sequence(thread_id) == 0

    async with session_factory() as db:
        capture = await capture_thread_state(
            db,
            thread_id=thread_id,
            aggregator=aggregator,
            checkpointer=checkpointer,
        )
    assert capture is not None
    assert capture.snapshot.last_sequence == 3
    assert capture.snapshot.last_sequence != 0


@pytest.mark.asyncio
async def test_a_live_run_still_reads_the_aggregators_own_counter(
    session_factory, checkpointer
) -> None:
    """Preservation: a non-terminal thread has no durable value to prefer yet.

    `ThreadModel.last_sequence` stays NULL until a run settles, so
    `capture_thread_state` must keep reading the live aggregator for an
    active run -- there is nothing durable yet, and falling back to 0 instead
    would make an in-progress run look falsely reset.
    """
    async with session_factory() as session:
        thread = await create_thread(
            session, status=ThreadStatus.RUNNING, title="still running"
        )
        await session.commit()
        thread_id = thread.id

    aggregator = EventAggregator()
    for _ in range(4):
        aggregator.advance_sequence(thread_id)

    async with session_factory() as db:
        capture = await capture_thread_state(
            db,
            thread_id=thread_id,
            aggregator=aggregator,
            checkpointer=checkpointer,
        )
    assert capture is not None
    assert capture.snapshot.last_sequence == 4

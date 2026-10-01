"""One run, one counter, and a number that survives the process that made it.

The gateway's chokepoint is the only place a run's frames are numbered, so
these proofs drive the real aggregator against a real migrated SQLite store
through the production repository - no stand-in implements the seed source,
because the behaviour under test is precisely what the real store answers.

The three seeding outcomes are each asserted separately, and the third is the
one that matters most: a store that cannot be read must leave the run
UNNUMBERED. Restarting its numbering instead would hand two different frames
the same number, which is the hazard that forced the SSE id to be withdrawn
the first time it shipped.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

import pytest
import pytest_asyncio
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ...database.migrate import run_migrations
from ...database.models import ThreadModel
from ...database.run_event_repository import RunEventRecord, RunEventStore
from ...database.session import configure_sqlite_engine
from ...database.thread_repository import create_thread
from ...graph.enums import AgentLifecycleState
from ...tests._write_authority import make_test_write_authority
from ...thread.enums import ThreadStatus
from ..aggregator import EventAggregator
from ..subscribers import RunSequenceAllocator
from ..types import SequencedEvent

if TYPE_CHECKING:
    import asyncio
    from collections.abc import AsyncIterator
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncEngine

_RUN = "sequence-authority-proof"


class _Backend:
    """A real migrated application store and the pieces built over it."""

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine
        self.session_factory = async_sessionmaker(engine, expire_on_commit=False)
        self.store = RunEventStore(self.session_factory)

    async def seed_thread(self, thread_id: str = _RUN) -> None:
        async with self.session_factory() as session:
            await create_thread(
                session,
                write_authority=make_test_write_authority(),
                thread_id=thread_id,
                status=ThreadStatus.RUNNING,
            )
            await session.commit()

    async def set_settled_cursor(self, value: int, thread_id: str = _RUN) -> None:
        async with self.session_factory() as session:
            await session.execute(
                update(ThreadModel)
                .where(ThreadModel.id == thread_id)
                .values(last_sequence=value)
            )
            await session.commit()

    async def retain(self, *sequences: int, thread_id: str = _RUN) -> None:
        await self.store.append(
            [
                RunEventRecord(
                    thread_id=thread_id,
                    sequence=sequence,
                    event_type="agent_status",
                    payload_json="{}",
                    created_at=datetime.now(UTC),
                )
                for sequence in sequences
            ]
        )

    async def break_the_replay_log(self) -> None:
        """Make the store genuinely unreadable, by removing what it reads."""
        async with self.engine.begin() as connection:
            await connection.execute(text("DROP TABLE run_events"))


@pytest_asyncio.fixture
async def backend(tmp_path: Path) -> AsyncIterator[_Backend]:
    """A real file-backed application database at the chain's head."""
    url = f"sqlite+aiosqlite:///{tmp_path / 'application.db'}"
    await run_migrations(url)
    engine = create_async_engine(url)
    configure_sqlite_engine(engine)
    try:
        yield _Backend(engine)
    finally:
        await engine.dispose()


def _worker_frame(sequence: int, *, thread_id: str = _RUN) -> dict[str, object]:
    """A relayed worker payload, carrying the worker's own ordering number."""
    return {
        "type": "agent_status",
        "event_type": "agent_status",
        "thread_id": thread_id,
        "agent_id": "coder",
        "state": AgentLifecycleState.WORKING.value,
        "sequence": sequence,
    }


def _attach(aggregator: EventAggregator, thread_id: str = _RUN) -> asyncio.Queue[Any]:
    """Register one viewer and return the queue it actually receives on.

    The queue is declared as holding sequenced domain events, and the relay
    path puts already-projected dictionaries on the same queue - which is why
    the stream's own reader decodes both shapes. This widens the annotation to
    what the queue genuinely carries rather than asserting on one half.
    """
    client_id = "allocation-proof-viewer"
    queue = aggregator.add_subscriber(client_id)
    aggregator.subscribe(client_id, [thread_id])
    return cast("asyncio.Queue[Any]", queue)


def _numbered_aggregator(backend: _Backend) -> EventAggregator:
    aggregator = EventAggregator()
    aggregator.bind_sequence_allocator(RunSequenceAllocator(backend.store))
    return aggregator


@pytest.mark.asyncio
async def test_two_producers_on_one_run_receive_consecutive_numbers(
    backend: _Backend,
) -> None:
    """A relayed worker frame and an in-process event share one counter.

    The relayed frames arrive carrying 100 and 7 - a second worker lifetime's
    ordering, which is exactly the shape that makes a worker number unusable
    as identity. What the subscriber receives is 1 and 2, because the gateway
    stamped its own, and the in-process event that follows takes 3 from the
    same counter rather than starting a second one.
    """
    await backend.seed_thread()
    aggregator = _numbered_aggregator(backend)
    queue = _attach(aggregator)

    await aggregator.prepare_run(_RUN)
    aggregator.relay_payload(_RUN, _worker_frame(100))
    aggregator.relay_payload(_RUN, _worker_frame(7))
    await aggregator.emit_agent_status(
        _RUN, "coder", "coder", AgentLifecycleState.COMPLETED
    )

    first = cast("dict[str, object]", queue.get_nowait())
    second = cast("dict[str, object]", queue.get_nowait())
    third = queue.get_nowait()

    assert first["sequence"] == 1
    assert second["sequence"] == 2
    assert isinstance(third, SequencedEvent)
    assert third.sequence == 3


@pytest.mark.asyncio
async def test_a_run_with_retained_rows_continues_from_the_stored_maximum(
    backend: _Backend,
) -> None:
    """A restarted gateway resumes the numbering rather than reusing it."""
    await backend.seed_thread()
    await backend.retain(1, 2, 3, 7)
    allocator = RunSequenceAllocator(backend.store)

    await allocator.seed(_RUN)

    assert allocator.allocate(_RUN) == 8
    assert allocator.allocate(_RUN) == 9


@pytest.mark.asyncio
async def test_a_run_with_no_retained_rows_continues_from_the_settled_cursor(
    backend: _Backend,
) -> None:
    """The cursor captured at settle is the second source, not a fresh start."""
    await backend.seed_thread()
    await backend.set_settled_cursor(42)
    allocator = RunSequenceAllocator(backend.store)

    await allocator.seed(_RUN)

    assert await backend.store.high_water_mark(_RUN) is None
    assert allocator.allocate(_RUN) == 43


@pytest.mark.asyncio
async def test_a_run_with_no_history_at_all_starts_at_one(
    backend: _Backend,
) -> None:
    """Zero is the honest floor when neither source has anything to say."""
    await backend.seed_thread()
    allocator = RunSequenceAllocator(backend.store)

    await allocator.seed(_RUN)

    assert allocator.allocate(_RUN) == 1


@pytest.mark.asyncio
async def test_an_unreadable_store_leaves_the_run_unnumbered(
    backend: _Backend,
) -> None:
    """Ids are withdrawn for the run; the numbering is never restarted."""
    await backend.seed_thread()
    await backend.retain(1, 2, 3)
    await backend.break_the_replay_log()
    allocator = RunSequenceAllocator(backend.store)

    await allocator.seed(_RUN)

    assert allocator.is_numbered(_RUN) is False
    assert allocator.allocate(_RUN) is None
    # A second attempt must not quietly start the run at one either.
    await allocator.seed(_RUN)
    assert allocator.allocate(_RUN) is None


@pytest.mark.asyncio
async def test_an_unnumbered_run_still_streams_the_worker_ordering_untouched(
    backend: _Backend,
) -> None:
    """Losing the number costs the run its id and never costs it a frame."""
    await backend.seed_thread()
    await backend.break_the_replay_log()
    aggregator = _numbered_aggregator(backend)
    queue = _attach(aggregator)

    await aggregator.prepare_run(_RUN)
    aggregator.relay_payload(_RUN, _worker_frame(17))

    delivered = cast("dict[str, object]", queue.get_nowait())
    assert delivered["sequence"] == 17


@pytest.mark.asyncio
async def test_a_forgotten_run_reseeds_from_the_durable_mark(
    backend: _Backend,
) -> None:
    """Purging a run's in-memory state costs a read, never a restart."""
    await backend.seed_thread()
    aggregator = _numbered_aggregator(backend)
    _attach(aggregator)
    await aggregator.prepare_run(_RUN)
    aggregator.relay_payload(_RUN, _worker_frame(1))
    aggregator.relay_payload(_RUN, _worker_frame(2))
    await backend.retain(1, 2)

    aggregator.clear_thread_state(_RUN)
    allocator = aggregator.sequence_allocator
    assert allocator is not None
    assert allocator.is_numbered(_RUN) is False

    await aggregator.prepare_run(_RUN)
    assert allocator.allocate(_RUN) == 3


@pytest.mark.asyncio
async def test_an_aggregator_with_no_allocator_numbers_nothing(
    backend: _Backend,
) -> None:
    """The worker's own aggregator binds none, and nothing about it changes."""
    await backend.seed_thread()
    aggregator = EventAggregator()
    queue = _attach(aggregator)

    assert aggregator.sequence_allocator is None
    await aggregator.prepare_run(_RUN)
    aggregator.relay_payload(_RUN, _worker_frame(5))

    delivered = cast("dict[str, object]", queue.get_nowait())
    assert delivered["sequence"] == 5

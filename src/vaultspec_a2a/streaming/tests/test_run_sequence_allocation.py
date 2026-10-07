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

import asyncio
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

import pytest
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from ...database.models import ThreadModel
from ...database.run_event_repository import RunEventRecord, RunEventStore
from ...database.thread_repository import create_thread
from ...graph.enums import AgentLifecycleState
from ...tests._write_authority import make_test_write_authority
from ...thread.enums import ThreadStatus
from ..aggregator import EventAggregator
from ..run_event_writer import RunEventWriter
from ..subscribers import RunSequenceAllocator
from ..types import SequencedEvent

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

_RUN = "sequence-authority-proof"

#: A flush cadence no test below reaches by waiting, so every write here is one
#: a test asked for and the unflushed window is under the test's control.
_IDLE_CADENCE = 30.0


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


@pytest.fixture
def backend(migrated_engine: AsyncEngine) -> _Backend:
    """The root migrated store, behind the operations these proofs drive."""
    return _Backend(migrated_engine)


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


def _terminal_frame(sequence: int, *, thread_id: str = _RUN) -> dict[str, object]:
    """The relayed frame that settles a run, as the worker posts it."""
    return {
        "type": "thread_terminal",
        "event_type": "thread_terminal",
        "thread_id": thread_id,
        "status": ThreadStatus.COMPLETED.value,
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


def _recording_aggregator(
    backend: _Backend,
) -> tuple[EventAggregator, RunEventWriter]:
    """A numbered aggregator with the real recorder seated behind it.

    The recorder is what makes the unflushed window real: a number is held in
    its ring from the moment it is allocated until a flush this test asks
    for, which is the state a terminal arriving mid-batch actually finds.
    """
    writer = RunEventWriter(
        backend.store, window=100, flush_interval_seconds=_IDLE_CADENCE
    )
    aggregator = EventAggregator()
    aggregator.bind_sequence_allocator(RunSequenceAllocator(backend.store), sink=writer)
    return aggregator, writer


async def _retained(backend: _Backend) -> list[tuple[int, int]]:
    """Each retained row as ``(row sequence, the sequence in its body)``."""
    rows = await backend.store.read_after(thread_id=_RUN, after_sequence=0, limit=1000)
    bodies = [cast("dict[str, Any]", json.loads(row.payload_json)) for row in rows]
    return [
        (row.sequence, int(body["sequence"]))
        for row, body in zip(rows, bodies, strict=True)
    ]


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
    # The counter itself is gone, so nothing may be numbered until the run is
    # seeded again. What the purge does NOT withdraw is the numbers already
    # stamped on the frames above, which is why the run still reads as a
    # numbered one.
    assert allocator.allocate(_RUN) is None
    assert allocator.is_numbered(_RUN) is True

    await aggregator.prepare_run(_RUN)
    assert allocator.allocate(_RUN) == 3


@pytest.mark.asyncio
async def test_a_run_forgotten_before_its_flush_never_reuses_a_sequence(
    backend: _Backend,
) -> None:
    """A terminal purges a run's state INSIDE the batch that carries it.

    Three frames, one ingested batch, one flush at the end of it - which is
    the production ordering: the terminal handler clears the aggregator's
    thread state before the relay route flushes, so the reseed in the middle
    sees a replay table that still holds nothing at all. Reseeding from that
    emptiness would hand the third frame the number the first already has,
    the second row would be swallowed by the idempotent insert, and a live
    viewer would de-duplicate the frame away. The decision's "monotonic per
    run, never reused" has to hold across the purge, not only within a
    counter's lifetime.
    """
    await backend.seed_thread()
    aggregator, writer = _recording_aggregator(backend)
    queue = _attach(aggregator)

    await aggregator.prepare_run(_RUN)
    aggregator.relay_payload(_RUN, _worker_frame(1))
    aggregator.relay_payload(_RUN, _terminal_frame(2))
    # Exactly what the terminal relay does, and it does it here: before the
    # batch is flushed, so the two frames above are still only in the ring.
    aggregator.clear_thread_state(_RUN)
    assert writer.pending(_RUN), "the proof needs the ring to still hold them"
    aggregator.subscribe("allocation-proof-viewer", [_RUN])

    # A trailing frame of the same run, in the same batch. A late relay or a
    # settlement racing the fan-out produces exactly this.
    await aggregator.prepare_run(_RUN)
    aggregator.relay_payload(_RUN, _worker_frame(1))
    written = await writer.flush()
    await writer.aclose()

    delivered = [
        cast("dict[str, object]", queue.get_nowait())["sequence"] for _ in range(3)
    ]
    assert delivered == [1, 2, 3], "a forgotten run restarted its numbering"
    assert written == 3
    assert await _retained(backend) == [(1, 1), (2, 2), (3, 3)], (
        "every allocated frame must keep its own row"
    )


@pytest.mark.asyncio
async def test_two_first_touches_of_one_run_cannot_rewind_the_counter(
    backend: _Backend,
) -> None:
    """Seeding awaits the store, and a second touch arrives inside that await.

    Reachable without contriving anything: the worker bridge re-posts a batch
    the gateway is still processing, or the WebSocket and HTTP ingest paths
    carry one run at once. Both callers find the run unseeded, both read the
    same mark, and the later assignment used to overwrite a counter the
    earlier one had already advanced - so six frames went out under three
    numbers and three of them were never stored.
    """
    await backend.seed_thread()
    aggregator = _numbered_aggregator(backend)
    queue = _attach(aggregator)

    async def touch_then_relay() -> None:
        await aggregator.prepare_run(_RUN)
        for index in range(3):
            aggregator.relay_payload(_RUN, _worker_frame(index + 1))

    await asyncio.gather(touch_then_relay(), touch_then_relay())

    delivered = [
        cast("dict[str, object]", queue.get_nowait())["sequence"] for _ in range(6)
    ]
    assert delivered == [1, 2, 3, 4, 5, 6], "a concurrent seed rewound the counter"


@pytest.mark.asyncio
async def test_a_frame_the_gateway_cannot_stamp_takes_no_number(
    backend: _Backend,
) -> None:
    """A number nothing retains is a hole, and a hole costs the older window.

    The replay reader serves the longest consecutive tail of what it finds,
    so one missing position discards every retained frame before it. A frame
    the chokepoint can neither stamp nor hand to the recorder therefore takes
    no number at all; it still reaches every subscriber.
    """
    await backend.seed_thread()
    aggregator, writer = _recording_aggregator(backend)
    queue = _attach(aggregator)

    await aggregator.prepare_run(_RUN)
    # A relayed payload that is not a frame body at all. The projector returns
    # it untouched, the chokepoint cannot stamp it, and the recorder declines
    # it - so nothing about it can ever be replayed.
    aggregator.relay_payload(_RUN, "not a frame body")
    aggregator.relay_payload(_RUN, _worker_frame(1))

    assert await writer.flush() == 1
    await writer.aclose()

    assert queue.get_nowait() == "not a frame body"
    stamped = cast("dict[str, object]", queue.get_nowait())
    assert stamped["sequence"] == 1, "a declined frame burned the run's first number"
    assert await _retained(backend) == [(1, 1)]


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

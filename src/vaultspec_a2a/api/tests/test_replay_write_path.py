"""The batch relay retains what it took, and a deleted run stops being held.

Resumption itself is covered where the stream is, so what is left unproven is
the relay's own flush. Nothing asserted that a batch arriving at the gateway
ever became a row - the recorder it is handed is read nowhere else, so an
unflushed ingest would have shown up only as a resume that was quietly short.

The delete is the opposite direction. A run whose thread is gone can never
take another row: the insert would reference a thread that no longer exists.
Frames still held for it are therefore not pending work, and leaving them held
made every later flush of every run fail against the same doomed rows.

Both are driven over a real socket against a real uvicorn server and a real
migrated SQLite database, because both are about what crosses a process
boundary and lands in a table.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx
import pytest

from ...database.run_event_repository import RunEventStore
from ...streaming.aggregator import EventAggregator
from ...streaming.run_event_writer import RunEventWriter
from ...streaming.subscribers import RunSequenceAllocator
from ...testing import seed_journaled_thread, serve_on_loopback
from ...thread.enums import ThreadStatus
from .._replay_writer_seat import replay_writer_seat
from .conftest import make_app, seed_run_with_status

if TYPE_CHECKING:
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    from .conftest import SessionFactory

_RETAINED_RUN = "retention-run"
_DELETED_RUN = "deleted-replay-run"


def _worker_frame(run_id: str, sequence: int) -> dict[str, Any]:
    """One progress frame, numbered as the WORKER numbers it."""
    return {
        "type": "agent_status",
        "event_type": "agent_status",
        "thread_id": run_id,
        "agent_id": "coder",
        "state": "working",
        "sequence": sequence,
    }


async def _seed_deletable_run(factory: SessionFactory, run_id: str) -> None:
    """Seed a settled run that the deletion election will actually accept.

    A deletion elects the thread into ``deleting`` against the write
    authority its creation recorded, so a thread row without the matching
    accepted action is refused before the saga begins - which would make this
    proof assert on a delete that never happened.
    """
    async with factory() as session:
        await seed_journaled_thread(
            session, thread_id=run_id, status=ThreadStatus.COMPLETED
        )
        await session.commit()


async def _retained(factory: SessionFactory, run_id: str) -> list[int]:
    return [
        record.sequence
        for record in await RunEventStore(factory).read_after(
            thread_id=run_id, after_sequence=0, limit=100
        )
    ]


#: A cadence no test here reaches by waiting. Seating it is what makes the
#: proof about the ingest's OWN flush rather than about the ticker that would
#: eventually have written the same row anyway.
_UNREACHABLE_CADENCE = 3600.0


def _seat_recorder_without_a_cadence(
    app: Any, aggregator: EventAggregator, factory: SessionFactory
) -> RunEventWriter:
    """Seat the real recorder and numbering authority, with its timer parked.

    The same two objects the gateway seats on its first relay, bound the same
    way; only the periodic flush is pushed out of reach, so the only thing
    that can make a frame durable within this test is an ingest path flushing
    the batch it just took.
    """
    store = RunEventStore(factory)
    writer = RunEventWriter(
        store, window=100, flush_interval_seconds=_UNREACHABLE_CADENCE
    )
    aggregator.bind_sequence_allocator(RunSequenceAllocator(store), sink=writer)
    app.state.run_event_writer = writer
    return writer


@pytest.mark.asyncio(loop_scope="function")
async def test_a_batch_relayed_over_http_is_retained_by_the_ingests_own_flush(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """The batch route writes the group it took before it answers.

    A real client on a real socket, speaking the envelope the worker speaks.
    The recorder's periodic flush is parked out of reach, so a row here can
    only come from the ingest path flushing behind its own fan-out; left to
    the timer, a resume taken in the interval reads a window that is short
    and a terminal can purge the run's numbering before its frames are
    durable.

    The numbers asserted are the gateway's own, stamped over the worker's,
    which is what makes the stored rows resumable positions rather than a
    second process's ordering.
    """
    aggregator = EventAggregator()
    app, _agg, _worker, _cp = make_app(session_factory, checkpointer, aggregator)
    await seed_run_with_status(session_factory, _RETAINED_RUN, ThreadStatus.RUNNING)
    writer = _seat_recorder_without_a_cadence(app, aggregator, session_factory)

    try:
        async with (
            serve_on_loopback(app) as base,
            httpx.AsyncClient(base_url=base, timeout=10.0) as client,
        ):
            relayed = await client.post(
                "/internal/events/batch",
                json={
                    "events": [
                        {
                            "thread_id": _RETAINED_RUN,
                            "ts": float(sequence),
                            "payload": _worker_frame(_RETAINED_RUN, sequence),
                        }
                        for sequence in (41, 42)
                    ]
                },
            )
            assert relayed.status_code == 200, relayed.text
        retained = await _retained(session_factory, _RETAINED_RUN)
    finally:
        await writer.aclose()

    assert retained == [1, 2], "the batch relay wrote nothing of its own"


@pytest.mark.asyncio(loop_scope="function")
async def test_deleting_a_run_releases_the_frames_its_recorder_still_holds(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """A deleted run's held frames are released, not carried forever.

    What the recorder holds is also what a resume reads before the table has
    caught up, so holding a deleted run's frames is wrong twice over: no
    flush can ever place them, and until they are evicted they are still
    offered as that run's replay window.
    """
    app, _agg, _worker, _cp = make_app(session_factory, checkpointer, EventAggregator())
    await checkpointer.setup()
    await _seed_deletable_run(session_factory, _DELETED_RUN)

    async with (
        serve_on_loopback(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
    ):
        relayed = await client.post(
            "/internal/events/batch",
            json={
                "events": [
                    {
                        "thread_id": _DELETED_RUN,
                        "ts": 1.0,
                        "payload": _worker_frame(_DELETED_RUN, 1),
                    }
                ]
            },
        )
        assert relayed.status_code == 200, relayed.text

        writer = replay_writer_seat(app)
        assert writer is not None
        assert writer.pending(_DELETED_RUN), "the proof needs the recorder to hold it"

        deleted = await client.delete(f"/v1/runs/{_DELETED_RUN}")
        assert deleted.status_code in (200, 204), deleted.text
        # The run really is gone, so nothing held for it can become a row.
        assert (await client.get(f"/v1/runs/{_DELETED_RUN}")).status_code == 404

        assert writer.pending(_DELETED_RUN) == []

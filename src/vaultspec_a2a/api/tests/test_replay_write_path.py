"""Both ingest transports retain, and a deleted run stops being held.

The HTTP relay routes are covered where resumption itself is, so what is left
unproven is the other half of the same seam. The worker's WebSocket channel
carries exactly the same frames through the same chokepoint, and nothing
asserted that a frame arriving that way ever became a row - the recorder it is
handed is read nowhere else, so an unflushed WebSocket ingest would have shown
up only as a resume that was quietly short.

The delete is the opposite direction. A run whose thread is gone can never
take another row: the insert would reference a thread that no longer exists.
Frames still held for it are therefore not pending work, and leaving them held
made every later flush of every run fail against the same doomed rows.

Both are driven over a real socket against a real uvicorn server and a real
migrated SQLite database, because both are about what crosses a process
boundary and lands in a table.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import httpx
import pytest
from websockets.asyncio.client import connect

from ...database.permission_repository import create_control_action
from ...database.run_event_repository import RunEventStore
from ...database.thread_repository import create_thread
from ...streaming.aggregator import EventAggregator
from ...streaming.run_event_writer import RunEventWriter
from ...streaming.subscribers import RunSequenceAllocator
from ...testing import serve_on_loopback
from ...tests._write_authority import make_test_write_authority
from ...thread.enums import ThreadStatus
from .._replay_writer_seat import replay_writer_seat
from .conftest import make_app, seed_run_with_status

if TYPE_CHECKING:
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    from .conftest import SessionFactory

_WS_RUN = "ws-retention-run"
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
        authority = make_test_write_authority()
        await create_thread(
            session,
            write_authority=authority,
            thread_id=run_id,
            status=ThreadStatus.COMPLETED,
        )
        await create_control_action(
            session,
            thread_id=run_id,
            action_type=authority.action_type,
            idempotency_key=f"thread-create:{run_id}",
            dispatch_id=authority.action_receipt_id,
            recovery_deadline_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        await session.commit()


async def _retained(factory: SessionFactory, run_id: str) -> list[int]:
    return [
        record.sequence
        for record in await RunEventStore(factory).read_after(
            thread_id=run_id, after_sequence=0, limit=100
        )
    ]


async def _retained_within(
    factory: SessionFactory, run_id: str, *, expected: int, timeout: float = 10.0
) -> list[int]:
    """Poll until the run holds *expected* rows, or the budget runs out.

    The WebSocket ingest answers nothing to its sender, so there is no reply
    to wait on; polling the table is what a real consumer of that channel can
    actually observe. The budget fails the test rather than relaxing the
    claim.
    """
    deadline = asyncio.get_running_loop().time() + timeout
    retained: list[int] = []
    while asyncio.get_running_loop().time() < deadline:
        retained = await _retained(factory, run_id)
        if len(retained) >= expected:
            return retained
        await asyncio.sleep(0.02)
    return retained


#: A cadence no test here reaches by waiting. Seating it is what makes the
#: WebSocket proof about the ingest's OWN flush rather than about the ticker
#: that would eventually have written the same row anyway.
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
async def test_a_frame_relayed_over_the_worker_websocket_is_retained(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """The WebSocket ingest writes the group it took, like the HTTP routes.

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
    await seed_run_with_status(session_factory, _WS_RUN, ThreadStatus.RUNNING)
    writer = _seat_recorder_without_a_cadence(app, aggregator, session_factory)

    try:
        async with (
            serve_on_loopback(app) as base,
            connect(base.replace("http://", "ws://") + "/internal/ws") as ws,
        ):
            for sequence in (41, 42):
                await ws.send(
                    json.dumps(
                        {
                            "type": "event",
                            "thread_id": _WS_RUN,
                            "payload": _worker_frame(_WS_RUN, sequence),
                        }
                    )
                )
            retained = await _retained_within(
                session_factory, _WS_RUN, expected=2, timeout=5.0
            )
    finally:
        await writer.aclose()

    assert retained == [1, 2], "the WebSocket relay wrote nothing of its own"


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

"""A reconnect is served the frames it missed, once each and in order.

Driven over a real socket against a real uvicorn server, the real internal
relay route and a real migrated SQLite database, because the property only
exists across a connection boundary: the first viewer has to genuinely go
away, frames have to be produced while nobody is attached, and the second
viewer has to be served out of what was retained rather than out of anything
the first connection left in memory.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import httpx
import pytest

from ...database.run_event_repository import RunEventRecord, RunEventStore
from ...streaming.aggregator import EventAggregator
from ...streaming.run_event_writer import RunEventWriter
from ...streaming.subscribers import SequenceAllocation
from ...thread.enums import ThreadStatus
from .._stream_replay import retained_after
from ._sse_reader import SseFrame, SseReader
from .conftest import _live_server, make_app, seed_run_with_status

if TYPE_CHECKING:
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    from .conftest import SessionFactory

_RUN = "replay-run"


def _progress_event(run_id: str, index: int) -> dict[str, Any]:
    return {
        "thread_id": run_id,
        "ts": float(index),
        "payload": {
            "type": "agent_status",
            "event_type": "agent_status",
            "thread_id": run_id,
            "agent_id": "coder",
            "state": "working",
            "detail": f"step {index}",
            "sequence": index,
        },
    }


def _terminal_event(run_id: str, index: int) -> dict[str, Any]:
    return {
        "thread_id": run_id,
        "ts": float(index),
        "payload": {
            "type": "thread_terminal",
            "event_type": "thread_terminal",
            "thread_id": run_id,
            "status": ThreadStatus.COMPLETED.value,
            "sequence": index,
        },
    }


async def _relay(client: httpx.AsyncClient, events: list[dict[str, Any]]) -> None:
    response = await client.post("/internal/events/batch", json={"events": events})
    assert response.status_code == 200, response.text


def _sequences(frames: list[SseFrame]) -> list[int]:
    """The delivered sequences, which are the ids the client could resume from."""
    return [frame.sequence for frame in frames if frame.sequence is not None]


@pytest.mark.asyncio(loop_scope="function")
async def test_a_reconnect_covers_every_sequence_to_the_terminal_exactly_once(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """The union of a killed connection and its resume has no gap and no duplicate.

    The second connection subscribes BEFORE it reads the retained window, so
    the frames relayed while it was replaying are in its queue as well as in
    the window. That overlap is the reason the stream tracks what it has
    emitted; without it the resume would deliver the same frames twice.
    """
    app, _agg, _worker, _cp = make_app(session_factory, checkpointer, EventAggregator())
    await seed_run_with_status(session_factory, _RUN, ThreadStatus.RUNNING)

    async with (
        _live_server(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
    ):
        async with client.stream("GET", f"/v1/runs/{_RUN}/stream") as first:
            assert first.status_code == 200
            reader = SseReader(first.aiter_bytes())
            assert (await reader.next_frame()).type == "stream_snapshot"
            await _relay(client, [_progress_event(_RUN, index) for index in (1, 2, 3)])
            seen_first = [await reader.next_frame() for _ in range(3)]
        # The viewer is gone. Everything below is produced with nobody
        # attached, which is exactly the history a resume has to recover.
        await _relay(
            client,
            [_progress_event(_RUN, index) for index in (4, 5, 6)]
            + [_terminal_event(_RUN, 7)],
        )

        cursor = seen_first[-1].event_id
        assert cursor == f"{_RUN}:3"
        async with client.stream(
            "GET", f"/v1/runs/{_RUN}/stream", headers={"Last-Event-ID": cursor}
        ) as second:
            assert second.status_code == 200
            resumed = SseReader(second.aiter_bytes())
            assert (await resumed.next_frame()).type == "stream_snapshot"
            seen_second = await resumed.until("thread_terminal")

    assert _sequences(seen_first) == [1, 2, 3]
    assert _sequences(seen_second) == [4, 5, 6, 7]
    assert seen_second[-1].type == "thread_terminal"
    # The replayed frames are the bodies that were delivered live, not a
    # reconstruction: the detail each one carried is still on it.
    assert [frame.data["detail"] for frame in seen_second[:3]] == [
        "step 4",
        "step 5",
        "step 6",
    ]

    union = _sequences(seen_first) + _sequences(seen_second)
    assert union == sorted(union)
    assert len(union) == len(set(union)), "a sequence was delivered twice"
    assert union == list(range(1, 8)), "the union of both connections has a gap"


@pytest.mark.asyncio(loop_scope="function")
async def test_the_window_sentinel_replays_everything_still_retained_once(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """A viewer with no position of its own is served the whole window, once.

    The fourth frame read is the proof of "once": those three frames are in
    the table AND still in the writer's ring, so a replay that served the two
    sources one after the other would answer with the window again instead of
    the live frame relayed below.
    """
    app, _agg, _worker, _cp = make_app(session_factory, checkpointer, EventAggregator())
    await seed_run_with_status(session_factory, _RUN, ThreadStatus.RUNNING)

    async with (
        _live_server(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
    ):
        await _relay(client, [_progress_event(_RUN, index) for index in (1, 2, 3)])
        async with client.stream(
            "GET", f"/v1/runs/{_RUN}/stream", headers={"Last-Event-ID": "-"}
        ) as response:
            assert response.status_code == 200
            reader = SseReader(response.aiter_bytes())
            assert (await reader.next_frame()).type == "stream_snapshot"
            replayed = [await reader.next_frame() for _ in range(3)]
            await _relay(client, [_progress_event(_RUN, 4)])
            after = await reader.next_frame()

    assert _sequences(replayed) == [1, 2, 3]
    assert after.sequence == 4


@pytest.mark.asyncio(loop_scope="function")
async def test_a_resume_at_the_head_of_the_window_replays_nothing(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """A caught-up client goes straight to live, with no frame repeated."""
    app, _agg, _worker, _cp = make_app(session_factory, checkpointer, EventAggregator())
    await seed_run_with_status(session_factory, _RUN, ThreadStatus.RUNNING)

    async with (
        _live_server(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
    ):
        await _relay(client, [_progress_event(_RUN, index) for index in (1, 2)])
        async with client.stream(
            "GET", f"/v1/runs/{_RUN}/stream", headers={"Last-Event-ID": f"{_RUN}:2"}
        ) as response:
            assert response.status_code == 200
            reader = SseReader(response.aiter_bytes())
            assert (await reader.next_frame()).type == "stream_snapshot"
            await _relay(client, [_progress_event(_RUN, 3)])
            live = await reader.next_frame()

    assert live.sequence == 3


def _ring_records(run_id: str, sequences: range) -> list[RunEventRecord]:
    """The records one allocation each would put in the writer's ring."""
    return [
        RunEventRecord(
            thread_id=run_id,
            sequence=sequence,
            event_type="agent_status",
            payload_json=json.dumps(
                {"type": "agent_status", "thread_id": run_id, "sequence": sequence}
            ),
            created_at=datetime.now(UTC),
        )
        for sequence in sequences
    ]


def _seat_ring(writer: RunEventWriter, run_id: str, sequences: range) -> None:
    """Record real allocations through the writer's own front door."""
    for record in _ring_records(run_id, sequences):
        writer.record(
            SequenceAllocation(
                thread_id=run_id,
                sequence=record.sequence,
                allocated_at=record.created_at,
            ),
            json.loads(record.payload_json),
        )


@pytest.mark.asyncio(loop_scope="function")
async def test_the_rows_and_the_ring_are_unioned_by_sequence_not_concatenated(
    session_factory: SessionFactory,
) -> None:
    """A flush does not empty the ring, so the two sources permanently overlap.

    This is the shape that makes concatenation wrong rather than merely
    wasteful: after the flush below, every sequence is in the table AND in the
    ring, so a reader that appended one source to the other would serve a
    resuming client the entire window twice.
    """
    store = RunEventStore(session_factory)
    writer = RunEventWriter(store, window=100)
    _seat_ring(writer, _RUN, range(1, 6))
    assert await writer.flush() == 5
    # Produced after the flush: in the ring, not yet in the table.
    _seat_ring(writer, _RUN, range(6, 8))

    served = await retained_after(
        session_factory=session_factory,
        writer=writer,
        thread_id=_RUN,
        after_sequence=0,
    )
    await writer.aclose()

    assert [frame.sequence for frame in served] == [1, 2, 3, 4, 5, 6, 7]


@pytest.mark.asyncio(loop_scope="function")
async def test_a_flush_landing_during_the_read_changes_nothing_it_serves(
    session_factory: SessionFactory,
) -> None:
    """The union is correct under either interleaving, so the read takes no lock.

    The flush is a real concurrent one, scheduled against the same event loop
    as the read: whichever of the two reaches the database first, the answer
    must be the same contiguous window with each sequence once.
    """
    store = RunEventStore(session_factory)
    writer = RunEventWriter(store, window=100)
    _seat_ring(writer, _RUN, range(1, 4))
    assert await writer.flush() == 3
    _seat_ring(writer, _RUN, range(4, 10))

    served, written = await asyncio.gather(
        retained_after(
            session_factory=session_factory,
            writer=writer,
            thread_id=_RUN,
            after_sequence=0,
        ),
        writer.flush(),
    )
    await writer.aclose()

    assert written == 6
    assert [frame.sequence for frame in served] == list(range(1, 10))
    assert await store.high_water_mark(_RUN) == 9

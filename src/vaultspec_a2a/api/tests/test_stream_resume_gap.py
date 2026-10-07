"""A resume that cannot be served completely says so, once, before it starts.

The gap cases are the ones a consumer cannot detect for itself: a replayed
stream that is simply short looks exactly like a complete one, which is the
whole reason the notice exists. Each case here is produced the way production
produces it - retention trimming a run below a cursor, a ring overflowing
before its flush, a store that cannot answer - rather than by asking the
stream to pretend.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import httpx
import pytest
from sqlalchemy import text

from ...database.run_event_repository import RunEventStore
from ...streaming.aggregator import EventAggregator
from ...streaming.run_event_writer import RunEventWriter
from ...streaming.subscribers import SequenceAllocation
from ...testing import SseReader, serve_on_loopback, settings_override
from ...thread.enums import ThreadStatus
from .._replay_writer_seat import replay_writer_seat
from .._stream_replay import ResumePosition, replay_window
from .conftest import make_app, seed_run_with_status
from .test_internal import _record_completed_checkpoint, _seed_accepted_thread
from .test_stream_resume_replay import _progress_event, _relay, _terminal_event

if TYPE_CHECKING:
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    from .conftest import SessionFactory

#: A flush cadence no test outlives. These tests ask the recorder for each
#: flush and assert what it wrote; a live cadence could flush first under load,
#: and the asked-for flush would then find nothing and report it.
_PARKED_CADENCE = 3600.0

_RUN = "gap-run"
_RETAINED = 2


@pytest.mark.asyncio(loop_scope="function")
async def test_a_cursor_behind_the_trimmed_window_is_told_where_the_replay_starts(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """One notice naming the first sequence served, then contiguous frames.

    Two gateways over one application database, because that is what makes
    the trim observable: the ring of the gateway that produced the frames
    still holds everything it wrote, and serving a resume from THAT gateway
    correctly reports no gap. The second gateway has only the table, which
    retention has cut to its newest rows - the state any later process, or
    any restart, actually finds.
    """
    producer, _agg, _worker, _cp = make_app(
        session_factory, checkpointer, EventAggregator()
    )
    viewer, _vagg, _vworker, _vcp = make_app(
        session_factory, checkpointer, EventAggregator()
    )
    await seed_run_with_status(session_factory, _RUN, ThreadStatus.RUNNING)

    with settings_override(stream_replay_window_events=_RETAINED):
        async with (
            serve_on_loopback(producer) as producer_base,
            httpx.AsyncClient(base_url=producer_base, timeout=10.0) as relay_client,
        ):
            await _relay(
                relay_client,
                [_progress_event(_RUN, index) for index in (1, 2, 3, 4, 5)],
            )
        assert replay_writer_seat(viewer) is None, (
            "the viewer gateway must serve the table, not another app's ring"
        )

        async with (
            serve_on_loopback(viewer) as viewer_base,
            httpx.AsyncClient(base_url=viewer_base, timeout=10.0) as client,
            client.stream(
                "GET", f"/v1/runs/{_RUN}/stream", headers={"Last-Event-ID": f"{_RUN}:1"}
            ) as response,
        ):
            assert response.status_code == 200
            reader = SseReader(response.aiter_lines())
            assert (await reader.next_frame()).type == "stream_snapshot"
            notice = await reader.next_frame()
            replayed = [await reader.next_frame() for _ in range(_RETAINED)]

    assert notice.type == "progress_dropped"
    assert notice.data["reason"] == "replay_window_exceeded"
    assert notice.data["first_sequence"] == 4
    # The notice names a position; it is not one, so it carries no id.
    assert notice.event_id is None
    sequences = [frame.sequence for frame in replayed]
    assert sequences == [4, 5], "the frames after the notice must be the window"
    assert sequences[0] == notice.data["first_sequence"]


@pytest.mark.asyncio(loop_scope="function")
async def test_a_resume_with_the_feature_off_is_told_the_replay_is_unavailable(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """Switched off, a cursor is accepted and answered - never silently ignored.

    Ignoring it would serve a live-only stream to a client that believes it
    resumed, which is the failure the notice exists to prevent; refusing the
    stream outright would deny a viewer the live frames it can still have.
    """
    app, _agg, _worker, _cp = make_app(session_factory, checkpointer, EventAggregator())
    await seed_run_with_status(session_factory, _RUN, ThreadStatus.RUNNING)

    with settings_override(stream_replay_enabled=False):
        async with (
            serve_on_loopback(app) as base,
            httpx.AsyncClient(base_url=base, timeout=10.0) as client,
            client.stream(
                "GET", f"/v1/runs/{_RUN}/stream", headers={"Last-Event-ID": "-"}
            ) as response,
        ):
            assert response.status_code == 200
            reader = SseReader(response.aiter_lines())
            assert (await reader.next_frame()).type == "stream_snapshot"
            notice = await reader.next_frame()

    assert notice.type == "progress_dropped"
    assert notice.data["reason"] == "replay_unavailable"
    assert "first_sequence" not in notice.data


@pytest.mark.asyncio(loop_scope="function")
async def test_a_store_that_cannot_answer_is_reported_rather_than_assumed_empty(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """A refusing store and an empty window must not read the same to a client.

    The refusal is a real one: the replay table is genuinely gone from the
    database the stream reads, which is what a store the gateway cannot serve
    from looks like from here.
    """
    app, _agg, _worker, _cp = make_app(session_factory, checkpointer, EventAggregator())
    await seed_run_with_status(session_factory, _RUN, ThreadStatus.RUNNING)
    async with session_factory() as session:
        await session.execute(text("DROP TABLE run_events"))
        await session.commit()

    async with (
        serve_on_loopback(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
        client.stream(
            "GET", f"/v1/runs/{_RUN}/stream", headers={"Last-Event-ID": f"{_RUN}:3"}
        ) as response,
    ):
        assert response.status_code == 200
        reader = SseReader(response.aiter_lines())
        assert (await reader.next_frame()).type == "stream_snapshot"
        notice = await reader.next_frame()

    assert notice.type == "progress_dropped"
    assert notice.data["reason"] == "replay_unavailable"


@pytest.mark.asyncio(loop_scope="function")
async def test_a_run_with_nothing_retained_cannot_serve_a_cursor(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """A position in a window that no longer exists is answered, not ignored."""
    app, _agg, _worker, _cp = make_app(session_factory, checkpointer, EventAggregator())
    await seed_run_with_status(session_factory, _RUN, ThreadStatus.RUNNING)

    async with (
        serve_on_loopback(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
        client.stream(
            "GET", f"/v1/runs/{_RUN}/stream", headers={"Last-Event-ID": f"{_RUN}:9"}
        ) as response,
    ):
        assert response.status_code == 200
        reader = SseReader(response.aiter_lines())
        assert (await reader.next_frame()).type == "stream_snapshot"
        notice = await reader.next_frame()

    assert notice.type == "progress_dropped"
    assert notice.data["reason"] == "replay_unavailable"


@pytest.mark.asyncio(loop_scope="function")
async def test_a_cursor_past_the_runs_mark_is_answered_and_still_goes_live(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """A position the run never reached is refused, not silently accepted.

    The cursor below names sequence 5000 on a run that has produced three
    frames. Nothing is retained after it and nothing ever will be, so the
    window is empty for a reason the other empty case does not share: this
    client is not at the head of the window, it is past the end of the run.
    Reported as complete, it reads to the consumer as a successful resume.

    Worse than the silence is what the claim used to buy. The stream seeded
    its de-duplication mark from the cursor, so every live frame at or below
    5000 - which is every frame this run will ever send, including its
    terminal - was dropped as a repeat, and the viewer heartbeated over a
    run it could see nothing of. The mark is now clamped to what the run has
    actually produced, so the stream goes live immediately after the notice
    and closes on the terminal like any other.
    """
    app, _agg, _worker, _cp = make_app(session_factory, checkpointer, EventAggregator())
    async with session_factory() as session:
        _, receipt = await _seed_accepted_thread(session, thread_id=_RUN)
        await session.commit()
    await _record_completed_checkpoint(checkpointer, receipt)

    async with (
        serve_on_loopback(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
    ):
        await _relay(client, [_progress_event(_RUN, index) for index in (1, 2, 3)])
        async with client.stream(
            "GET",
            f"/v1/runs/{_RUN}/stream",
            headers={"Last-Event-ID": f"{_RUN}:5000"},
        ) as response:
            assert response.status_code == 200
            reader = SseReader(response.aiter_lines())
            assert (await reader.next_frame()).type == "stream_snapshot"
            notice = await reader.next_frame()

            await _relay(client, [_progress_event(_RUN, 4)])
            live = await reader.next_frame()
            await _relay(client, [_terminal_event(_RUN, 5)])
            closing = await reader.next_frame()

    assert notice.type == "progress_dropped"
    assert notice.data["reason"] == "replay_unavailable"
    # Nothing was lost and no position can be named, so the notice names none.
    assert "first_sequence" not in notice.data
    assert live.type == "agent_status"
    assert live.sequence == 4, "a live frame was dropped against the client's cursor"
    assert closing.type == "thread_terminal"
    assert closing.sequence == 5


@pytest.mark.asyncio(loop_scope="function")
async def test_a_caught_up_resume_is_given_no_notice_at_all(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """An ordinary reconnect missed nothing and must not be told it did.

    The counterweight to every case above: a notice on each routine
    reconnection would train a consumer to ignore the one that matters.
    """
    app, _agg, _worker, _cp = make_app(session_factory, checkpointer, EventAggregator())
    await seed_run_with_status(session_factory, _RUN, ThreadStatus.RUNNING)

    async with (
        serve_on_loopback(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
    ):
        await _relay(client, [_progress_event(_RUN, index) for index in (1, 2)])
        async with client.stream(
            "GET", f"/v1/runs/{_RUN}/stream", headers={"Last-Event-ID": f"{_RUN}:2"}
        ) as response:
            assert response.status_code == 200
            reader = SseReader(response.aiter_lines())
            assert (await reader.next_frame()).type == "stream_snapshot"
            await _relay(client, [_progress_event(_RUN, 3)])
            following = await reader.next_frame()

    assert following.type == "agent_status"
    assert following.sequence == 3


def _record(writer: RunEventWriter, sequence: int) -> None:
    """Put one allocation through the writer's own front door."""
    writer.record(
        SequenceAllocation(
            thread_id=_RUN, sequence=sequence, allocated_at=datetime.now(UTC)
        ),
        {"type": "agent_status", "thread_id": _RUN, "sequence": sequence},
    )


@pytest.mark.asyncio(loop_scope="function")
async def test_a_ring_overflow_leaves_a_hole_the_window_reports(
    session_factory: SessionFactory,
) -> None:
    """A hole in the MIDDLE of a window is a gap, not a window that starts late.

    Produced by a real overflow rather than described: the ring below holds
    four frames, ten are recorded into it between flushes, and the six it had
    to drop were delivered live and never written. The table is then left
    holding two runs of sequences with a hole between them - the one shape
    retention alone can never produce, and the one a leading-edge check would
    miss, because the frames on the near side of the hole do continue from the
    cursor.
    """
    store = RunEventStore(session_factory)
    writer = RunEventWriter(
        store, window=100, ring_capacity=4, flush_interval_seconds=_PARKED_CADENCE
    )
    for sequence in (1, 2):
        _record(writer, sequence)
    assert await writer.flush() == 2
    for sequence in range(3, 13):
        _record(writer, sequence)
    assert await writer.flush() == 4

    retained = [
        record.sequence
        for record in await store.read_after(
            thread_id=_RUN, after_sequence=0, limit=100
        )
    ]
    assert retained == [1, 2, 9, 10, 11, 12], "the overflow did not leave a hole"

    window = await replay_window(
        session_factory=session_factory,
        writer=writer,
        thread_id=_RUN,
        resume=ResumePosition(after_sequence=1, from_window_start=False),
    )
    await writer.aclose()

    assert window.gap_reason == "replay_window_exceeded"
    assert window.first_sequence == 9
    assert [frame.sequence for frame in window.frames] == [9, 10, 11, 12]


@pytest.mark.asyncio(loop_scope="function")
async def test_the_window_sentinel_is_still_told_about_a_hole_inside_the_window(
    session_factory: SessionFactory,
) -> None:
    """The sentinel claims no position, so only a loss INSIDE the window is one.

    Asked for "whatever is retained", a window that starts late is exactly
    what was asked for; a window with a hole in it is not, and the difference
    is what keeps the notice meaningful for a client that never held a cursor.
    """
    store = RunEventStore(session_factory)
    writer = RunEventWriter(
        store, window=100, ring_capacity=4, flush_interval_seconds=_PARKED_CADENCE
    )
    for sequence in (1, 2):
        _record(writer, sequence)
    assert await writer.flush() == 2
    for sequence in range(3, 13):
        _record(writer, sequence)
    assert await writer.flush() == 4

    holed = await replay_window(
        session_factory=session_factory,
        writer=writer,
        thread_id=_RUN,
        resume=ResumePosition(after_sequence=0, from_window_start=True),
    )
    assert holed.gap_reason == "replay_window_exceeded"
    assert holed.first_sequence == 9

    whole = await replay_window(
        session_factory=session_factory,
        writer=writer,
        thread_id=_RUN,
        resume=ResumePosition(after_sequence=8, from_window_start=True),
    )
    await writer.aclose()

    assert whole.gap_reason is None
    assert [frame.sequence for frame in whole.frames] == [9, 10, 11, 12]


@pytest.mark.asyncio(loop_scope="function")
async def test_a_retained_row_that_cannot_be_decoded_counts_as_a_hole(
    session_factory: SessionFactory,
) -> None:
    """A damaged row costs its own frame and is reported, never skipped silently."""
    store = RunEventStore(session_factory)
    writer = RunEventWriter(store, window=100, flush_interval_seconds=_PARKED_CADENCE)
    for sequence in range(1, 5):
        _record(writer, sequence)
    assert await writer.flush() == 4
    await writer.aclose()
    async with session_factory() as session:
        await session.execute(
            text(
                "UPDATE run_events SET payload_json = :body "
                "WHERE thread_id = :run AND sequence = 2"
            ),
            {"body": json.dumps("not a frame body"), "run": _RUN},
        )
        await session.commit()

    window = await replay_window(
        session_factory=session_factory,
        writer=None,
        thread_id=_RUN,
        resume=ResumePosition(after_sequence=0, from_window_start=True),
    )

    assert window.gap_reason == "replay_window_exceeded"
    assert window.first_sequence == 3
    assert [frame.sequence for frame in window.frames] == [3, 4]

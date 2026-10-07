"""What a viewer is told, and in what order, from the moment it attaches.

Four properties of the attachment sequence, each of which a consumer must be able
to observe:

- the subscription exists before the run's authority is reported, so an outcome
  relayed from that point on cannot fall between the two;
- the stream leads with a snapshot of what was attached to;
- a run that settles without its terminal reaching this viewer still closes the
  stream, rather than heartbeating over a finished run;
- a viewer whose queue overflowed is told so, once, instead of silently losing
  history.

Driven against the real ``RelayHub``, the real subscriber registry and a
real file-backed SQLite run row. The generator is driven directly rather than
through a socket because these are properties of the body's own ordering, and a
socket would add a second source of interleaving without making any of them more
true.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from ...domain_config import domain_config
from ...streaming import RelayHub
from ...testing import (
    decode_frame,
    elect_status,
    seed_accepted_thread,
    settings_override,
)
from ...thread.enums import ThreadStatus
from ..thread_stream import ThreadStreamRequest, _stream_thread_events
from .conftest import seed_run_with_status

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from .conftest import SessionFactory

_RUN = "run-attachment-order"


def _progress(run_id: str, *, sequence: int, content: str) -> dict[str, object]:
    """A relayed worker progress payload, in the shape the relay seam produces."""
    return {
        "type": "message_chunk",
        "event_type": "message_chunk",
        "thread_id": run_id,
        "message_id": "m-1",
        "sequence": sequence,
        "content": content,
    }


def _terminal(run_id: str, status: ThreadStatus) -> dict[str, object]:
    return {
        "type": "thread_terminal",
        "event_type": "thread_terminal",
        "thread_id": run_id,
        "status": status.value,
    }


async def _close(stream: AsyncGenerator[bytes]) -> None:
    """Release the stream's registration the way a disconnect does."""
    await stream.aclose()


@pytest.mark.asyncio(loop_scope="function")
async def test_a_viewer_is_subscribed_before_it_is_told_the_run_state(
    session_factory: SessionFactory,
) -> None:
    """Authority is read inside the registered window, not before it.

    The old order read the run's durable state first and attached the
    subscription afterwards, so an outcome relayed between the two reached
    neither: too late for the read, too early for the queue, and the viewer
    heartbeated over a run that had ended. The snapshot frame is the observable
    boundary - it carries the state that was read - so a subscription that is
    already live when it arrives proves the read happened after attachment.
    """
    aggregator = RelayHub()
    await seed_run_with_status(session_factory, _RUN, ThreadStatus.RUNNING)

    stream = _stream_thread_events(
        ThreadStreamRequest(
            thread_id=_RUN,
            relay_hub=aggregator,
            session_factory=session_factory,
        )
    )
    try:
        snapshot = decode_frame(await anext(stream)).data

        assert snapshot["type"] == "stream_snapshot"
        assert snapshot["status"] == ThreadStatus.RUNNING.value
        assert snapshot["thread_id"] == _RUN
        assert aggregator.get_active_thread_ids() == [_RUN]

        # And the queue attached that early really is the delivery path: an
        # outcome relayed now arrives rather than being missed.
        aggregator.relay_payload(_RUN, _terminal(_RUN, ThreadStatus.COMPLETED))
        terminal = decode_frame(await anext(stream)).data
        assert terminal["type"] == "thread_terminal"
        assert terminal["status"] == ThreadStatus.COMPLETED.value

        with pytest.raises(StopAsyncIteration):
            await anext(stream)
    finally:
        await _close(stream)

    assert aggregator.subscriber_count() == 0


@pytest.mark.asyncio(loop_scope="function")
async def test_no_frame_claims_an_sse_id_the_stream_cannot_resume_from(
    session_factory: SessionFactory,
) -> None:
    """The run's sequence orders frames in the body and is never the SSE id.

    The sequence restarts with the worker and nothing buffers frames for a
    ``Last-Event-ID`` to resume from, so an id would promise a resumption this
    stream does not offer, and a consumer deduplicating by it would drop a
    restarted worker's events as ones it already held.
    """
    aggregator = RelayHub()
    await seed_run_with_status(session_factory, _RUN, ThreadStatus.RUNNING)

    stream = _stream_thread_events(
        ThreadStreamRequest(
            thread_id=_RUN,
            relay_hub=aggregator,
            session_factory=session_factory,
        )
    )
    try:
        snapshot_raw = await anext(stream)
        assert decode_frame(snapshot_raw).event_id is None

        aggregator.relay_payload(_RUN, _progress(_RUN, sequence=7, content="tick"))
        progress_raw = await anext(stream)

        assert decode_frame(progress_raw).event_id is None
        assert decode_frame(progress_raw).data["sequence"] == 7
    finally:
        await _close(stream)


@pytest.mark.asyncio(loop_scope="function")
async def test_a_run_that_settles_unheard_still_closes_the_stream(
    session_factory: SessionFactory,
) -> None:
    """A terminal this viewer never received must not leave it watching forever.

    The relay fans out before it persists, so a terminal delivered in that gap
    belongs to neither the queue nor the read that preceded it. Here the run
    settles durably and nothing at all is relayed - exactly what that gap leaves
    behind - and the stream still reports the outcome and ends, bounded by one
    idle beat rather than never.
    """
    aggregator = RelayHub()
    async with session_factory() as session:
        await seed_accepted_thread(session, thread_id=_RUN, status="running")
        await session.commit()

    with settings_override(stream_heartbeat_interval_seconds=0.05):
        stream = _stream_thread_events(
            ThreadStreamRequest(
                thread_id=_RUN,
                relay_hub=aggregator,
                session_factory=session_factory,
            )
        )
        try:
            assert decode_frame(await anext(stream)).data["type"] == "stream_snapshot"

            async with session_factory() as session:
                await elect_status(
                    session,
                    _RUN,
                    ThreadStatus.FAILED,
                    failure_reason="provider gave up",
                )
                await session.commit()

            frames: list[dict[str, object]] = []
            async with asyncio.timeout(10):
                async for raw in stream:
                    frames.append(decode_frame(raw).data)
                    if frames[-1]["type"] == "thread_terminal":
                        break
        finally:
            await _close(stream)

    kinds = [frame["type"] for frame in frames]
    assert kinds[-2:] == ["error", "thread_terminal"]
    assert frames[-1]["status"] == ThreadStatus.FAILED.value
    assert frames[-1]["replay"] is True
    assert frames[-2]["message"] == "provider gave up"


@pytest.mark.asyncio(loop_scope="function")
async def test_a_viewer_that_overflows_its_queue_is_told_to_resynchronize(
    session_factory: SessionFactory,
) -> None:
    """Overflow was reported to the operator's log and to nobody else.

    A viewer that fell behind lost the oldest events while its stream still read
    as a complete account of the run. It now receives one bounded notice naming
    backpressure and the number of events it cost, coalesced rather than one per
    lost event, and its remedy is the one every relay frame points at: re-read
    run status.

    The queue is genuinely overflowed through the production relay API while the
    generator is suspended at a yield, which is where a slow consumer actually
    sits.
    """
    aggregator = RelayHub()
    await seed_run_with_status(session_factory, _RUN, ThreadStatus.RUNNING)
    overflow = domain_config.event_queue_maxsize + 8

    stream = _stream_thread_events(
        ThreadStreamRequest(
            thread_id=_RUN,
            relay_hub=aggregator,
            session_factory=session_factory,
        )
    )
    try:
        assert decode_frame(await anext(stream)).data["type"] == "stream_snapshot"

        for sequence in range(overflow):
            aggregator.relay_payload(
                _RUN, _progress(_RUN, sequence=sequence, content=f"c{sequence}")
            )

        notices: list[dict[str, object]] = []
        first_progress: dict[str, object] | None = None
        for _ in range(4):
            frame = decode_frame(await anext(stream)).data
            if frame["type"] == "progress_dropped":
                notices.append(frame)
                continue
            first_progress = frame
            break
    finally:
        await _close(stream)

    assert len(notices) == 1, "the burst must coalesce into one resync notice"
    assert notices[0]["reason"] == "backpressure"
    dropped = notices[0]["dropped_count"]
    assert isinstance(dropped, int)
    assert dropped == overflow - domain_config.event_queue_maxsize
    # The notice precedes the surviving frames, and the survivors are the newest
    # ones: a viewer catching up is better served by recent state than by a
    # stale prefix.
    assert first_progress is not None
    assert first_progress["sequence"] == dropped

"""An SSE id is served exactly where the frame behind it can be replayed.

Driven over a real socket against a real uvicorn server, a real migrated
SQLite database and the real internal relay route the worker itself posts to,
because the property is about what a gateway WRITES while it streams: the id is
offered only once the run's number is the gateway's own and its frames are
being retained, and the two are seated together on the first relayed batch.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx
import pytest
from sqlalchemy import text

from ...control.config import settings
from ...streaming.aggregator import EventAggregator
from ...testing import serve_on_loopback, settings_override
from ...thread.enums import ThreadStatus
from ._sse_reader import SseReader
from .conftest import make_app, seed_run_with_status

if TYPE_CHECKING:
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    from .conftest import SessionFactory

_RUN = "resume-id-run"


def relay_batch(run_id: str, count: int, *, first: int = 1) -> dict[str, Any]:
    """One worker batch of progress frames, numbered as the WORKER numbers them.

    The worker's own counter is deliberately preserved in the bodies: the
    gateway must stamp its own number over it, so a batch that already agreed
    with the gateway would prove nothing.
    """
    return {
        "events": [
            {
                "thread_id": run_id,
                "ts": float(index),
                "payload": {
                    "type": "agent_status",
                    "event_type": "agent_status",
                    "thread_id": run_id,
                    "agent_id": "coder",
                    "state": "working",
                    "sequence": first + index,
                },
            }
            for index in range(count)
        ]
    }


async def post_relay_batch(
    client: httpx.AsyncClient, run_id: str, count: int, *, first: int = 1
) -> None:
    """Relay *count* frames through the route the worker posts to."""
    response = await client.post(
        "/internal/events/batch", json=relay_batch(run_id, count, first=first)
    )
    assert response.status_code == 200, response.text


@pytest.mark.asyncio(loop_scope="function")
async def test_a_served_frame_carries_its_run_and_sequence_as_the_sse_id(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """Every live frame names the position a reconnect can resume from."""
    aggregator = EventAggregator()
    app, _agg, _worker, _cp = make_app(session_factory, checkpointer, aggregator)
    await seed_run_with_status(session_factory, _RUN, ThreadStatus.RUNNING)

    async with (
        serve_on_loopback(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
        client.stream("GET", f"/v1/runs/{_RUN}/stream") as response,
    ):
        assert response.status_code == 200
        reader = SseReader(response.aiter_bytes())
        snapshot = await reader.next_frame()
        assert snapshot.type == "stream_snapshot"
        # The snapshot is produced by the stream itself and crosses no
        # chokepoint, so there is no retained row it could point at.
        assert snapshot.event_id is None

        await post_relay_batch(client, _RUN, 3)

        frames = [await reader.next_frame() for _ in range(3)]

    assert [frame.event_id for frame in frames] == [
        f"{_RUN}:1",
        f"{_RUN}:2",
        f"{_RUN}:3",
    ]
    assert [frame.data["sequence"] for frame in frames] == [1, 2, 3]


@pytest.mark.asyncio(loop_scope="function")
async def test_no_frame_carries_an_id_while_replay_is_switched_off(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """Off is the honest posture: no retention, no number, no cursor offered.

    The frames still carry the WORKER's sequence in their bodies, which is
    exactly why the id must be absent - that number restarts with its process,
    and a client handed it back would resume against a position no two runs of
    the worker agree on.
    """
    aggregator = EventAggregator()
    app, _agg, _worker, _cp = make_app(session_factory, checkpointer, aggregator)
    await seed_run_with_status(session_factory, _RUN, ThreadStatus.RUNNING)

    with settings_override(stream_replay_enabled=False):
        async with (
            serve_on_loopback(app) as base,
            httpx.AsyncClient(base_url=base, timeout=10.0) as client,
            client.stream("GET", f"/v1/runs/{_RUN}/stream") as response,
        ):
            assert response.status_code == 200
            reader = SseReader(response.aiter_bytes())
            assert (await reader.next_frame()).type == "stream_snapshot"

            await post_relay_batch(client, _RUN, 2)

            frames = [await reader.next_frame() for _ in range(2)]

    assert [frame.event_id for frame in frames] == [None, None]
    assert [frame.data["sequence"] for frame in frames] == [1, 2]


@pytest.mark.asyncio(loop_scope="function")
async def test_an_unnumbered_run_carries_no_id_although_replay_is_switched_on(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """The other half of the invariant: on, but this run has no number.

    The switch being on is not what entitles a frame to an id - the run
    having a durable number is. A run the gateway could not establish a
    number for is left unnumbered for the life of the process rather than
    restarted at one, and the id has to be withheld from it exactly as it is
    when the whole feature is off. The frames below carry the WORKER's
    sequence in their bodies, which is the number that must never be offered
    back as a cursor.

    The store is made genuinely unreadable rather than described as such:
    the replay table is gone from the database the gateway seeds from, which
    is what an unreadable mark looks like from the allocator's side.
    """
    aggregator = EventAggregator()
    app, _agg, _worker, _cp = make_app(session_factory, checkpointer, aggregator)
    await seed_run_with_status(session_factory, _RUN, ThreadStatus.RUNNING)
    async with session_factory() as session:
        await session.execute(text("DROP TABLE run_events"))
        await session.commit()

    assert settings.stream_replay_enabled, "this proof is about the switch being ON"
    async with (
        serve_on_loopback(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
        client.stream("GET", f"/v1/runs/{_RUN}/stream") as response,
    ):
        assert response.status_code == 200
        reader = SseReader(response.aiter_bytes())
        assert (await reader.next_frame()).type == "stream_snapshot"

        await post_relay_batch(client, _RUN, 2)

        frames = [await reader.next_frame() for _ in range(2)]

    assert [frame.event_id for frame in frames] == [None, None]
    assert [frame.data["sequence"] for frame in frames] == [1, 2]

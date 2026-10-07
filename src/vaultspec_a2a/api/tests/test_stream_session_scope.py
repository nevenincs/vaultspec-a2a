"""An attached viewer must not hold a database connection while it watches.

Driven over a real socket against a real uvicorn server and the file-backed
SQLite engine the other api tests use, because the defect is a property of the
dependency teardown boundary: it only appears once the response body is being
streamed to a client that has not disconnected, which an in-process transport
that buffers the whole response can never reproduce.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

import httpx
import pytest

from ...streaming import RelayHub
from ...testing import (
    ProgressDeadline,
    ProgressStalledError,
    seed_live_thread,
    serve_on_loopback,
    wait_for_async,
)
from ._relay_events import progress_event, relay_events
from .conftest import make_app

if TYPE_CHECKING:
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from sqlalchemy.ext.asyncio import AsyncEngine

    from .conftest import SessionFactory

_ATTACHED_VIEWERS = 3


@runtime_checkable
class _CheckedOutPool(Protocol):
    """The SQLAlchemy pool operation that counts connections in use."""

    def checkedout(self) -> int: ...


async def _wait_for_subscribers(aggregator: RelayHub, expected: int) -> None:
    async def _attached() -> bool | None:
        return True if aggregator.subscriber_count() >= expected else None

    try:
        await wait_for_async(
            _attached, deadline=ProgressDeadline(idle_window_s=5.0), interval_s=0.01
        )
    except ProgressStalledError as stalled:
        raise AssertionError(
            f"only {aggregator.subscriber_count()} of {expected} viewers attached"
        ) from stalled


async def _wait_for_idle_pool(pool: _CheckedOutPool) -> None:
    async def _idle() -> bool | None:
        return True if pool.checkedout() == 0 else None

    try:
        await wait_for_async(
            _idle, deadline=ProgressDeadline(idle_window_s=5.0), interval_s=0.01
        )
    except ProgressStalledError as stalled:
        raise AssertionError(
            f"{pool.checkedout()} pooled connections are still checked out"
        ) from stalled


@pytest.mark.asyncio(loop_scope="function")
async def test_attached_viewers_hold_no_pooled_connection(
    engine: AsyncEngine,
    session_factory: SessionFactory,
    checkpointer: AsyncSqliteSaver,
) -> None:
    """Every viewer's connection is back in the pool before its first frame.

    A viewer holds no connection for the duration of its stream: the pool has
    fifteen, so if each viewer kept one, about fifteen viewers would stall
    run-start, run-status, cancel and the event relay on the same engine. The
    count is read while the
    streams are demonstrably open, proven by the subscriber registrations rather
    than by a sleep.
    """
    aggregator = RelayHub()
    app, agg, _worker, _cp = make_app(session_factory, checkpointer, aggregator)
    run_id, _receipt = await seed_live_thread(session_factory, title="pool")

    pool = engine.sync_engine.pool
    assert isinstance(pool, _CheckedOutPool)

    async with (
        serve_on_loopback(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
    ):
        streams = [
            client.stream("GET", f"/v1/runs/{run_id}/stream")
            for _ in range(_ATTACHED_VIEWERS)
        ]
        responses = [await stream.__aenter__() for stream in streams]
        try:
            for response in responses:
                assert response.status_code == 200
            await _wait_for_subscribers(agg, _ATTACHED_VIEWERS)

            # Read each viewer's leading snapshot frame. That frame is emitted
            # after the body's own durable read, so receiving it is proof the
            # read happened AND finished - which is what makes the count below a
            # measurement of what a settled attached stream holds rather than a
            # race against a read still in flight. The iterators are held for the
            # rest of the test: abandoning one closes that response body, which
            # the server sees as the viewer disconnecting.
            bodies = [response.aiter_bytes() for response in responses]
            for body in bodies:
                assert b"stream_snapshot" in await anext(body)

            assert pool.checkedout() == 0, (
                "an attached viewer is still holding a pooled connection"
            )

            # The engine is genuinely usable while they watch: a read now would
            # have queued behind the streams under the old scoping. Its OWN
            # connection is request-scoped and returns once the server finishes
            # the response, which the client cannot observe synchronously, so the
            # settled count is waited for rather than sampled.
            status = await client.get(f"/v1/runs/{run_id}")
            assert status.status_code == 200
            assert agg.subscriber_count() == _ATTACHED_VIEWERS
            await _wait_for_idle_pool(pool)
        finally:
            for stream in streams:
                await stream.__aexit__(None, None, None)


@pytest.mark.asyncio(loop_scope="function")
async def test_a_resuming_viewer_hands_its_replay_connection_back(
    engine: AsyncEngine,
    session_factory: SessionFactory,
    checkpointer: AsyncSqliteSaver,
) -> None:
    """Replaying a window is a read that ends, not a read that watches.

    A resume adds a second database read to the attachment path, and it is the
    one most tempting to hold open: the obvious shape streams rows out of a
    cursor as the client consumes them, which would pin a pooled connection
    for the life of the stream and reintroduce the exhaustion the scoping
    above fixed. The count is read after the replayed frames have arrived, so
    the read is demonstrably finished rather than not yet started.
    """
    aggregator = RelayHub()
    app, agg, _worker, _cp = make_app(session_factory, checkpointer, aggregator)
    run_id, _receipt = await seed_live_thread(session_factory, title="resume-pool")

    pool = engine.sync_engine.pool
    assert isinstance(pool, _CheckedOutPool)

    async with (
        serve_on_loopback(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
    ):
        await relay_events(client, [progress_event(run_id, index) for index in (1, 2)])

        async with client.stream(
            "GET", f"/v1/runs/{run_id}/stream", headers={"Last-Event-ID": "-"}
        ) as response:
            assert response.status_code == 200
            body = response.aiter_bytes()
            received = b""
            # Read until the second replayed frame has arrived; the replay read
            # necessarily completed before the first of them was written.
            while received.count(b"agent_status") < 2:
                received += await anext(body)
            await _wait_for_subscribers(agg, 1)

            assert pool.checkedout() == 0, (
                "the replay read is still holding a pooled connection"
            )

"""An attached viewer must not hold a database connection while it watches.

Driven over a real socket against a real uvicorn server and the file-backed
SQLite engine the other api tests use, because the defect is a property of the
dependency teardown boundary: it only appears once the response body is being
streamed to a client that has not disconnected, which an in-process transport
that buffers the whole response can never reproduce.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Protocol, runtime_checkable

import httpx
import pytest

from ...streaming.aggregator import EventAggregator
from .conftest import make_app
from .test_gateway_live import _live_server, _seed_live_thread

if TYPE_CHECKING:
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from sqlalchemy.ext.asyncio import AsyncEngine

    from .conftest import SessionFactory

_ATTACHED_VIEWERS = 3


@runtime_checkable
class _CheckedOutPool(Protocol):
    """The SQLAlchemy pool operation that counts connections in use."""

    def checkedout(self) -> int: ...


async def _wait_for_subscribers(aggregator: EventAggregator, expected: int) -> None:
    for _ in range(500):
        if aggregator.subscriber_count() >= expected:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(
        f"only {aggregator.subscriber_count()} of {expected} viewers attached"
    )


async def _wait_for_idle_pool(pool: _CheckedOutPool) -> None:
    for _ in range(500):
        if pool.checkedout() == 0:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(
        f"{pool.checkedout()} pooled connections are still checked out"
    )


@pytest.mark.asyncio(loop_scope="function")
async def test_attached_viewers_hold_no_pooled_connection(
    engine: AsyncEngine,
    session_factory: SessionFactory,
    checkpointer: AsyncSqliteSaver,
) -> None:
    """Every viewer's connection is back in the pool before its first frame.

    Three viewers used to mean three connections checked out for the duration -
    the pool has fifteen, so about fifteen viewers stalled run-start, run-status,
    cancel and the event relay on the same engine. The count is read while the
    streams are demonstrably open, proven by the subscriber registrations rather
    than by a sleep.
    """
    aggregator = EventAggregator()
    app, agg, _worker, _cp = make_app(session_factory, checkpointer, aggregator)
    run_id, _receipt = await _seed_live_thread(session_factory, title="pool")

    pool = engine.sync_engine.pool
    assert isinstance(pool, _CheckedOutPool)

    async with (
        _live_server(app) as base,
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

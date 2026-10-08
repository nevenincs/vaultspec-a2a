"""Attached progress streams must not starve a concurrent run read.

The lead behind the 300s run-history stall: a reader that "never answered"
against an idle server is the signature of a wait for a CONNECTION rather than
for work, and a long-lived SSE stream is the only thing in this edge that holds
one open for minutes. There are two pools a stream could exhaust, and both are
driven here against a real gateway on a real loopback socket with real
``text/event-stream`` responses held open:

* the CLIENT's connection pool, when one ``httpx`` client both streams and
  reads. A held stream occupies one of the pool's connections for its whole
  life, and a read issued on the same client queues behind the pool when none
  is free.
* the GATEWAY's database pool. The stream handler takes its session at FUNCTION
  scope precisely so the connection goes back when the handler returns rather
  than when the stream ends; request scope held one per attached viewer, and the
  pool's ceiling (five connections plus ten overflow) then blocked every other
  database-using request - which is exactly what a never-answering history read
  on an idle server looks like.

Both are locked here rather than argued, because the same stall was first
attributed to the harness and the harness turned out not to be able to cause it.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from typing import TYPE_CHECKING

import httpx
import pytest

from ...streaming import RelayHub
from ...testing import (
    ProgressDeadline,
    seed_live_thread,
    serve_on_loopback,
    wait_until_async,
)
from .conftest import make_app

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

type SessionFactory = async_sessionmaker[AsyncSession]

#: More attached viewers than the gateway's database pool can hand out at once
#: (SQLAlchemy's queue pool defaults to five connections plus ten overflow), so
#: a handler that held its session for the life of its stream would leave the
#: read below with nothing to open.
_VIEWERS_PAST_THE_POOL = 16

#: A read that has to wait for a connection waits for the stream to end, which
#: is minutes. Anything inside this is "answered promptly" by any measure.
_PROMPT_SECONDS = 15.0

_WAIT_POLL_S = 0.005


@contextlib.asynccontextmanager
async def _attached_viewer(
    client: httpx.AsyncClient, run_id: str
) -> AsyncGenerator[httpx.Response]:
    """Hold one real progress stream open for the body of the block."""
    async with client.stream("GET", f"/v1/runs/{run_id}/stream") as response:
        assert response.status_code == 200, response.status_code
        assert response.headers["content-type"].startswith("text/event-stream")
        yield response


async def _timed_history(client: httpx.AsyncClient, run_id: str) -> float:
    """Read the run's history and return how long the answer took."""
    started = time.monotonic()
    answered = await client.get(f"/v1/runs/{run_id}/history")
    elapsed = time.monotonic() - started
    assert answered.status_code == 200, answered.text
    return elapsed


@pytest.mark.asyncio(loop_scope="function")
async def test_a_read_on_the_streaming_client_is_not_starved_by_its_own_stream(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """One client, one held stream, and the history read still answers."""
    hub = RelayHub()
    app, served_hub, _worker, _cp = make_app(session_factory, checkpointer, hub)
    run_id, _receipt = await seed_live_thread(session_factory, title="streamed")

    async with (
        serve_on_loopback(app) as base,
        httpx.AsyncClient(base_url=base, timeout=_PROMPT_SECONDS) as client,
        _attached_viewer(client, run_id),
    ):
        await wait_until_async(
            lambda: served_hub.subscriber_count() > 0,
            deadline=ProgressDeadline(idle_window_s=5.0),
            interval_s=_WAIT_POLL_S,
            stalled=lambda: "the progress stream never registered a subscriber",
        )
        elapsed = await _timed_history(client, run_id)

    assert elapsed < _PROMPT_SECONDS


@pytest.mark.asyncio(loop_scope="function")
async def test_a_read_answers_with_more_viewers_attached_than_the_pool_holds(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """The gateway's database pool survives more viewers than it has connections.

    The stream handler's session is function-scoped, so each of these viewers
    gave its connection back when its handler returned. Held for the life of the
    stream instead, the sixteenth viewer would own the pool's last connection
    and this read would wait for a stream that does not end.
    """
    hub = RelayHub()
    app, served_hub, _worker, _cp = make_app(session_factory, checkpointer, hub)
    run_id, _receipt = await seed_live_thread(session_factory, title="crowded")

    async with (
        serve_on_loopback(app) as base,
        # One client per viewer, so the client's own pool cannot be what is
        # under test here: every wait this measures is the gateway's.
        contextlib.AsyncExitStack() as viewers,
    ):
        for _ in range(_VIEWERS_PAST_THE_POOL):
            viewer = await viewers.enter_async_context(
                httpx.AsyncClient(base_url=base, timeout=_PROMPT_SECONDS)
            )
            await viewers.enter_async_context(_attached_viewer(viewer, run_id))
        await wait_until_async(
            lambda: served_hub.subscriber_count() >= _VIEWERS_PAST_THE_POOL,
            deadline=ProgressDeadline(idle_window_s=10.0),
            interval_s=_WAIT_POLL_S,
            stalled=lambda: (
                "only "
                f"{served_hub.subscriber_count()} of {_VIEWERS_PAST_THE_POOL} "
                "viewers attached"
            ),
        )
        async with httpx.AsyncClient(base_url=base, timeout=_PROMPT_SECONDS) as reader:
            elapsed = await asyncio.wait_for(
                _timed_history(reader, run_id), timeout=_PROMPT_SECONDS
            )

    assert elapsed < _PROMPT_SECONDS

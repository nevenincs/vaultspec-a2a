"""The run stream accepts a resumption cursor, and refuses one it cannot honour.

Driven over a real socket against a real uvicorn server, because the header
half of the contract only exists on the wire: an in-process call can be handed
a cursor directly, which proves nothing about what a reconnecting
``EventSource`` actually sends.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import pytest

from ...streaming.aggregator import EventAggregator
from ...testing import SseReader, serve_on_loopback
from ...thread.enums import ThreadStatus
from .conftest import make_app, seed_run_with_status

if TYPE_CHECKING:
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    from .conftest import SessionFactory

_RUN = "cursor-run"
_OTHER_RUN = "cursor-other-run"


async def _first_frame(
    client: httpx.AsyncClient,
    *,
    header: str | None = None,
    query: str | None = None,
):
    """Open the run stream with the given cursor and read its leading frame."""
    headers = {"Last-Event-ID": header} if header is not None else {}
    params = {"last_event_id": query} if query is not None else {}
    async with client.stream(
        "GET", f"/v1/runs/{_RUN}/stream", headers=headers, params=params
    ) as response:
        assert response.status_code == 200, response.text
        return await SseReader(response.aiter_lines()).next_frame()


@pytest.mark.asyncio(loop_scope="function")
@pytest.mark.parametrize(
    "cursor",
    [
        f"{_OTHER_RUN}:4",
        # Not a position at all. Serving these as though no cursor arrived
        # would hand the caller a live-only stream while it believed it had
        # resumed, which is the one outcome the refusal exists to prevent.
        "4",
        f"{_RUN}:not-a-number",
        f"{_RUN}:",
        "",
    ],
    ids=["another-run", "bare-number", "non-decimal", "empty-decimal", "empty"],
)
async def test_a_cursor_this_run_cannot_honour_closes_the_stream(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver, cursor: str
) -> None:
    """One typed refusal, before any snapshot and before any replay.

    The empty cursor is the exception that proves the shape: a client whose
    stored id is empty sends no position, so the stream opens normally instead
    of refusing something nobody asked for.
    """
    app, _agg, _worker, _cp = make_app(session_factory, checkpointer, EventAggregator())
    await seed_run_with_status(session_factory, _RUN, ThreadStatus.RUNNING)

    async with (
        serve_on_loopback(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
    ):
        frame = await _first_frame(client, header=cursor)

    if cursor == "":
        assert frame.type == "stream_snapshot"
        return
    assert frame.type == "stream_rejected"
    assert frame.data["reason"] == "resume_cursor_foreign_run"
    assert frame.event_id is None


@pytest.mark.asyncio(loop_scope="function")
async def test_the_query_fallback_is_honoured_for_a_client_that_cannot_set_headers(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """The browser EventSource constructor sets no header; the query is its way in."""
    app, _agg, _worker, _cp = make_app(session_factory, checkpointer, EventAggregator())
    await seed_run_with_status(session_factory, _RUN, ThreadStatus.RUNNING)

    async with (
        serve_on_loopback(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
    ):
        refused = await _first_frame(client, query=f"{_OTHER_RUN}:4")
        accepted = await _first_frame(client, query=f"{_RUN}:4")

    assert refused.type == "stream_rejected"
    assert refused.data["reason"] == "resume_cursor_foreign_run"
    assert accepted.type == "stream_snapshot"


@pytest.mark.asyncio(loop_scope="function")
async def test_the_header_wins_over_the_query_when_both_are_supplied(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """Precedence is asserted in both directions, so neither outcome is a coincidence.

    A conforming client re-sends the header by itself while the query is
    whatever the connecting URL happened to carry, so a stale URL must not
    override the position the client actually holds.
    """
    app, _agg, _worker, _cp = make_app(session_factory, checkpointer, EventAggregator())
    await seed_run_with_status(session_factory, _RUN, ThreadStatus.RUNNING)

    async with (
        serve_on_loopback(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
    ):
        header_refuses = await _first_frame(
            client, header=f"{_OTHER_RUN}:4", query=f"{_RUN}:4"
        )
        header_accepts = await _first_frame(
            client, header=f"{_RUN}:4", query=f"{_OTHER_RUN}:4"
        )

    assert header_refuses.type == "stream_rejected"
    assert header_refuses.data["reason"] == "resume_cursor_foreign_run"
    assert header_accepts.type == "stream_snapshot"


@pytest.mark.asyncio(loop_scope="function")
async def test_the_dash_sentinel_asks_for_the_retained_window(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """A viewer with no position of its own names the window, not a number."""
    app, _agg, _worker, _cp = make_app(session_factory, checkpointer, EventAggregator())
    await seed_run_with_status(session_factory, _RUN, ThreadStatus.RUNNING)

    async with (
        serve_on_loopback(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
    ):
        header = await _first_frame(client, header="-")
        query = await _first_frame(client, query="-")

    assert header.type == "stream_snapshot"
    assert query.type == "stream_snapshot"


@pytest.mark.asyncio(loop_scope="function")
async def test_a_cursor_longer_than_the_route_admits_is_refused_at_the_edge(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """The bound is the route's, so an unbounded cursor never reaches the body."""
    app, _agg, _worker, _cp = make_app(session_factory, checkpointer, EventAggregator())
    await seed_run_with_status(session_factory, _RUN, ThreadStatus.RUNNING)

    async with (
        serve_on_loopback(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
    ):
        response = await client.get(
            f"/v1/runs/{_RUN}/stream",
            params={"last_event_id": f"{_RUN}:" + "9" * 400},
        )

    assert response.status_code == 422

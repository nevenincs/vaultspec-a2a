"""run-status says whether a run's stream can be resumed, without probing.

A stream that serves no replay emits no id at all, so the two postures are
indistinguishable from the outside: a client would have to attach, wait for a
frame to arrive, and notice the absence of an id to learn what this field
states outright. Each case below is read from the same live gateway that
serves the stream, so the answer and the behaviour cannot drift apart.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import pytest

from ...streaming.aggregator import EventAggregator
from ...testing import settings_override
from ...thread.enums import ThreadStatus
from ._sse_reader import SseReader
from .conftest import _live_server, make_app, seed_run_with_status
from .test_stream_resume_replay import _progress_event, _relay

if TYPE_CHECKING:
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    from .conftest import SessionFactory

_RUN = "resumable-run"


@pytest.mark.asyncio(loop_scope="function")
async def test_a_run_with_retained_frames_reports_a_resumable_stream(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """The claim is checked against the stream, not only against the field.

    Reading the id off a real frame in the same test is what makes the
    boolean a promise rather than a configuration echo: it is true exactly
    when a client is being handed a cursor it can come back with.
    """
    app, _agg, _worker, _cp = make_app(session_factory, checkpointer, EventAggregator())
    await seed_run_with_status(session_factory, _RUN, ThreadStatus.RUNNING)

    async with (
        _live_server(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
    ):
        before = await client.get(f"/v1/runs/{_RUN}")
        await _relay(client, [_progress_event(_RUN, 1)])
        after = await client.get(f"/v1/runs/{_RUN}")
        async with client.stream(
            "GET", f"/v1/runs/{_RUN}/stream", headers={"Last-Event-ID": "-"}
        ) as response:
            reader = SseReader(response.aiter_bytes())
            assert (await reader.next_frame()).type == "stream_snapshot"
            replayed = await reader.next_frame()

    assert before.status_code == 200
    # Nothing retained yet, so there is nothing to resume from and the field
    # says so rather than promising the capability the service has in general.
    assert before.json()["stream_resumable"] is False
    assert after.status_code == 200
    assert after.json()["stream_resumable"] is True
    assert replayed.event_id == f"{_RUN}:1"


@pytest.mark.asyncio(loop_scope="function")
async def test_a_switched_off_service_reports_no_resumable_stream(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """Off, the field is false even for a run that produced frames."""
    app, _agg, _worker, _cp = make_app(session_factory, checkpointer, EventAggregator())
    await seed_run_with_status(session_factory, _RUN, ThreadStatus.RUNNING)

    with settings_override(stream_replay_enabled=False):
        async with (
            _live_server(app) as base,
            httpx.AsyncClient(base_url=base, timeout=10.0) as client,
        ):
            await _relay(client, [_progress_event(_RUN, 1)])
            status = await client.get(f"/v1/runs/{_RUN}")

    assert status.status_code == 200
    assert status.json()["stream_resumable"] is False

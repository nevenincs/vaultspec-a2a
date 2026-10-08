"""run-status says whether a run's stream can be resumed, without probing.

A stream that serves no replay emits no id at all, so the two postures are
indistinguishable from the outside: a client would have to attach, wait for a
frame to arrive, and notice the absence of an id to learn what this field
states outright. Each case below is read from the same live gateway that
serves the stream, so the answer and the behaviour cannot drift apart.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ...database import Base, RunEventRecord, RunEventStore
from ...streaming import RelayHub
from ...testing import SseReader, serve_on_loopback, settings_override
from ...thread.enums import ThreadStatus
from .._replay_writer_seat import replay_writer_seat
from ._relay_events import progress_event, relay_events
from .conftest import make_app, seed_run_with_status

if TYPE_CHECKING:
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from sqlalchemy.ext.asyncio import AsyncEngine

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
    app, _agg, _worker, _cp = make_app(session_factory, checkpointer, RelayHub())
    await seed_run_with_status(session_factory, _RUN, ThreadStatus.RUNNING)

    async with (
        serve_on_loopback(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
    ):
        before = await client.get(f"/v1/runs/{_RUN}")
        await relay_events(client, [progress_event(_RUN, 1)])
        after = await client.get(f"/v1/runs/{_RUN}")
        async with client.stream(
            "GET", f"/v1/runs/{_RUN}/stream", headers={"Last-Event-ID": "-"}
        ) as response:
            reader = SseReader(response.aiter_lines())
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
    app, _agg, _worker, _cp = make_app(session_factory, checkpointer, RelayHub())
    await seed_run_with_status(session_factory, _RUN, ThreadStatus.RUNNING)

    with settings_override(stream_replay_enabled=False):
        async with (
            serve_on_loopback(app) as base,
            httpx.AsyncClient(base_url=base, timeout=10.0) as client,
        ):
            await relay_events(client, [progress_event(_RUN, 1)])
            status = await client.get(f"/v1/runs/{_RUN}")

    assert status.status_code == 200
    assert status.json()["stream_resumable"] is False


@pytest.mark.asyncio(loop_scope="function")
async def test_a_run_whose_numbering_could_not_be_established_is_not_resumable(
    engine: AsyncEngine,
    session_factory: SessionFactory,
    checkpointer: AsyncSqliteSaver,
) -> None:
    """A run this gateway could not number serves no id, and the field says so.

    The honest half of the posture that the retained window alone cannot see.
    Seeding a run's counter needs two durable reads, and a run whose reads
    failed is left UNNUMBERED for the whole life of this process - restarting
    its numbering instead would hand two frames one number, which is the
    hazard that forced the id to be withdrawn once already. Its frames
    therefore carry no id at all.

    Reading the retained window would still answer true here, because the
    window is a property of the run and the failure is a property of this
    process: a store that recovers after the failed seed leaves rows a resume
    could in principle be served from, while this gateway hands the client no
    cursor to ask with. That is a capability reported to a client that cannot
    reach it.

    The failure is real rather than arranged: the replay table is dropped, so
    the two seed reads fail against a live store the way they would under any
    other storage fault, and it is restored afterwards with the rows an
    earlier gateway lifetime left behind.
    """
    app, _agg, _worker, _cp = make_app(session_factory, checkpointer, RelayHub())
    await seed_run_with_status(session_factory, _RUN, ThreadStatus.RUNNING)

    async with (
        serve_on_loopback(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
    ):
        async with engine.begin() as connection:
            await connection.execute(text("DROP TABLE run_events"))
        # The relay seeds the run's numbering on this batch and cannot, so the
        # run is unnumbered from here on.
        await relay_events(client, [progress_event(_RUN, 1)])
        async with engine.begin() as connection:
            await connection.run_sync(
                Base.metadata.tables["run_events"].create, checkfirst=True
            )
        await RunEventStore(session_factory).append(
            [
                RunEventRecord(
                    thread_id=_RUN,
                    sequence=sequence,
                    event_type="agent_status",
                    payload_json="{}",
                    created_at=datetime.now(UTC),
                )
                for sequence in (1, 2, 3)
            ]
        )

        status = await client.get(f"/v1/runs/{_RUN}")
        await relay_events(client, [progress_event(_RUN, 2)])
        async with client.stream("GET", f"/v1/runs/{_RUN}/stream") as response:
            reader = SseReader(response.aiter_lines())
            assert (await reader.next_frame()).type == "stream_snapshot"
            await relay_events(client, [progress_event(_RUN, 3)])
            live = await reader.next_frame()

    # The store answers, so the window exists; the stream still carries no
    # cursor, and the two must not disagree.
    assert await RunEventStore(session_factory).high_water_mark(_RUN) == 3
    assert live.event_id is None, "an unnumbered run must serve no resumable id"
    assert status.status_code == 200, status.text
    assert status.json()["stream_resumable"] is False


@pytest.mark.asyncio(loop_scope="function")
async def test_run_status_answers_the_field_on_one_pooled_connection(
    engine: AsyncEngine, session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """The additive boolean must not cost the request a second connection.

    run-status is the hottest read on this gateway, and its handler already
    holds a request-scoped session for the life of the request. Probing the
    replay log through a factory of its own opened a second pooled
    connection beside that one, halving how many of these calls an engine
    could serve at once - which is not an abstraction to be argued about but
    a bound to be measured, so this engine has exactly one connection and a
    one-second patience.

    Two gateways over one database, because the probe only reaches the store
    when the recorder holds nothing: the producing gateway's unflushed ring
    answers from memory, and the gateway that has only the table is the
    state any second process, or any restart, actually finds.
    """
    producer, _agg, _worker, _cp = make_app(session_factory, checkpointer, RelayHub())
    single = create_async_engine(
        engine.url, pool_size=1, max_overflow=0, pool_timeout=1.0
    )
    viewer, _vagg, _vworker, _vcp = make_app(
        async_sessionmaker(single, expire_on_commit=False),
        checkpointer,
        RelayHub(),
    )
    await seed_run_with_status(session_factory, _RUN, ThreadStatus.RUNNING)

    try:
        async with (
            serve_on_loopback(producer) as producer_base,
            httpx.AsyncClient(base_url=producer_base, timeout=10.0) as relay_client,
        ):
            await relay_events(relay_client, [progress_event(_RUN, 1)])
        assert replay_writer_seat(viewer) is None, (
            "the viewer gateway must reach the store, not another app's ring"
        )

        async with (
            serve_on_loopback(viewer) as viewer_base,
            httpx.AsyncClient(base_url=viewer_base, timeout=10.0) as client,
        ):
            status = await client.get(f"/v1/runs/{_RUN}")
    finally:
        await single.dispose()

    assert status.status_code == 200
    assert status.json()["stream_resumable"] is True

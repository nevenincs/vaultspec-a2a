"""The wide read never passes an unread checkpoint off as a silent run.

A run's conversation lives only in its checkpoint. When the checkpoint is gone,
the snapshot's message list is empty for a reason that has nothing to do with
what the run said - and an empty list is indistinguishable from a run that
genuinely said nothing. That is the failure mode these tests exist to forbid:
loss of the record answered as a successful read.

Driven through the REAL seam end to end - a real gateway on a real socket, a
real SQLite thread store, a real ``AsyncSqliteSaver`` checkpointer, and runs
whose checkpoints are genuinely absent because nothing ever wrote one. Asserting
against a hand-built snapshot would prove only that a dataclass holds the value
assigned to it, and would stay green if the endpoint never consulted it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import pytest
from langgraph.checkpoint.base import empty_checkpoint

from ...database import update_thread_status
from ...thread.enums import ThreadStatus, TranscriptAvailability
from .conftest import async_catalog_run_fields, make_app
from .test_gateway_drain import _relay_terminal
from .test_gateway_live import _live_server

if TYPE_CHECKING:
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    type SessionFactory = async_sessionmaker[AsyncSession]

_PRESET = "mock-success-single"


async def _start_run(client: httpx.AsyncClient, run_id: str) -> str:
    """Start one real run through the real run-start verb."""
    started = await client.post(
        "/v1/runs",
        json={
            "team_preset": _PRESET,
            "message": "remember this",
            "autonomous": True,
            "run_id": run_id,
            **await async_catalog_run_fields(client),
        },
    )
    assert started.status_code == 201, started.text
    run_id_out = started.json()["run_id"]
    assert isinstance(run_id_out, str)
    return run_id_out


@pytest.mark.asyncio(loop_scope="function")
async def test_a_completed_run_without_a_checkpoint_reports_the_transcript_lost(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """A settled run owing a transcript it cannot produce is reported, not hidden.

    The run really reaches COMPLETED - the terminal event travels the production
    worker relay - and no checkpoint was ever written for it, so the wide read
    faces exactly the state a genuine checkpoint loss produces. Before this
    contract the endpoint answered 200 with ``messages: []`` and nothing else,
    which reads as a run that never spoke.
    """
    app, _agg, _worker, _cp = make_app(session_factory, checkpointer)
    async with (
        _live_server(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
    ):
        run_id = await _start_run(client, "hist-lost-01")
        await _relay_terminal(client, run_id)

        history = await client.get(f"/v1/runs/{run_id}/history")
        assert history.status_code == 200, history.text
        body = history.json()

        # The run really is settled, so the absent transcript is a fault and not
        # a run that simply has not started yet.
        assert body["state"]["status"] == ThreadStatus.COMPLETED.value

        # The whole point: the empty list is qualified rather than left to speak
        # for itself.
        assert body["state"]["messages"] == []
        assert body["transcript_available"] is False
        assert body["transcript_status"] == TranscriptAvailability.MISSING.value

        # The durable half of the record survives and is still served - refusing
        # the whole read over an absent transcript would cost the caller the
        # half that is intact.
        assert body["run_id"] == run_id
        assert body["metadata"] is not None
        assert body["metadata"]["workspace_root"]


@pytest.mark.asyncio(loop_scope="function")
async def test_an_archived_run_without_a_checkpoint_still_answers_the_durable_record(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """Archiving does not turn a missing transcript into an empty conversation.

    Archived is the state under which a transcript could one day be absent by
    policy rather than by fault, which makes it the state most at risk of having
    the absence waved through. It is driven here through the real archive verb,
    and the read must still say the transcript is not part of what it returned.
    """
    app, _agg, _worker, _cp = make_app(session_factory, checkpointer)
    async with (
        _live_server(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
    ):
        run_id = await _start_run(client, "hist-archived-01")
        await _relay_terminal(client, run_id)
        archived = await client.post(f"/v1/runs/{run_id}/archive")
        assert archived.status_code == 200, archived.text

        history = await client.get(f"/v1/runs/{run_id}/history")
        assert history.status_code == 200, history.text
        body = history.json()

        assert body["state"]["status"] == ThreadStatus.ARCHIVED.value
        assert body["state"]["messages"] == []
        assert body["transcript_available"] is False
        # No production seam prunes a checkpoint today, so an archived run's
        # absent transcript is still a genuine loss and must be named one. When
        # a retention policy can release a transcript on purpose, THIS is the
        # assertion that must be revisited rather than quietly satisfied.
        assert body["transcript_status"] == TranscriptAvailability.MISSING.value


@pytest.mark.asyncio(loop_scope="function")
async def test_a_live_run_before_its_first_checkpoint_is_not_reported_as_a_loss(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """An empty transcript during startup is honest, and must not read as a fault.

    The counterweight to the tests above, and not a hypothetical one: a run is
    marked RUNNING the moment it dispatches, which is before any worker has
    written a checkpoint, so EVERY healthy run passes through this window. If
    the window were called a loss the signal would fire constantly on ordinary
    traffic and be trained away, leaving the real losses just as invisible as
    the empty list did.

    The run is deliberately left live here - no terminal event is relayed - so
    the state under test is the genuine startup window rather than a settled
    run.
    """
    app, _agg, _worker, _cp = make_app(session_factory, checkpointer)
    async with (
        _live_server(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
    ):
        run_id = await _start_run(client, "hist-fresh-01")

        history = await client.get(f"/v1/runs/{run_id}/history")
        assert history.status_code == 200, history.text
        body = history.json()

        assert body["state"]["status"] in {
            ThreadStatus.SUBMITTED.value,
            ThreadStatus.RUNNING.value,
        }
        assert body["state"]["messages"] == []
        assert body["transcript_available"] is False
        assert (
            body["transcript_status"] == TranscriptAvailability.NOT_YET_RECORDED.value
        )


@pytest.mark.asyncio(loop_scope="function")
async def test_a_parked_run_without_a_checkpoint_is_a_loss_not_a_pending_transcript(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """Being still "active" does not excuse an absent transcript by itself.

    A run parked awaiting input was checkpointed in order to park, so its
    checkpoint cannot be merely unwritten. Excusing every active status would
    soft-pedal precisely the states most likely to BE the loss - a run in a
    recovery state is there because something already went wrong. Only the
    dispatch-to-first-write window earns the benefit of the doubt.

    The status is moved through the real durable transition guard, so this is
    the lifecycle the production store actually permits.
    """
    app, _agg, _worker, _cp = make_app(session_factory, checkpointer)
    async with (
        _live_server(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
    ):
        run_id = await _start_run(client, "hist-parked-01")
        async with session_factory() as db:
            await update_thread_status(db, run_id, ThreadStatus.INPUT_REQUIRED)
            await db.commit()

        history = await client.get(f"/v1/runs/{run_id}/history")
        assert history.status_code == 200, history.text
        body = history.json()

        assert body["state"]["status"] == ThreadStatus.INPUT_REQUIRED.value
        assert body["transcript_available"] is False
        assert body["transcript_status"] == TranscriptAvailability.MISSING.value


@pytest.mark.asyncio(loop_scope="function")
async def test_a_run_with_a_real_checkpoint_reports_its_transcript_available(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """The positive case, so the fault fields are not trivially always false.

    Without this, every assertion above would still pass if the endpoint hard-
    coded ``transcript_available=False``. A real checkpoint is written through
    the real checkpointer for the same run the gateway serves, and the verdict
    must flip.
    """
    app, _agg, _worker, _cp = make_app(session_factory, checkpointer)
    async with (
        _live_server(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
    ):
        run_id = await _start_run(client, "hist-present-01")

        # A real checkpoint for this run, written through the same checkpointer
        # instance the app reads - the production read path, not a stand-in.
        await checkpointer.setup()
        checkpoint = empty_checkpoint()
        checkpoint["id"] = "cp-hist-present-01"
        await checkpointer.aput(
            {"configurable": {"thread_id": run_id, "checkpoint_ns": ""}},
            checkpoint,
            {"source": "loop", "step": 1, "parents": {}},
            {},
        )

        history = await client.get(f"/v1/runs/{run_id}/history")
        assert history.status_code == 200, history.text
        body = history.json()

        assert body["state"]["checkpoint_id"] == "cp-hist-present-01"
        assert body["transcript_available"] is True
        assert body["transcript_status"] == TranscriptAvailability.AVAILABLE.value

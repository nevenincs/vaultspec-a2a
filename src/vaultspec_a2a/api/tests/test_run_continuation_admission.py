"""A busy run takes one follow-up turn and holds it, reserving nothing else.

The published 202 becomes reachable here. A run still executing its first
turn admits a continuation, and admitting is deliberately almost nothing: a
journal row with a place in the queue and a lease, no graph receipt, no
writer, no dispatch. Installing any of those now would hand the run's write
authority to a turn that has not started, after which the turn that IS
running has its own terminal refused as superseded and the run quarantines.

Every claim below is read off the real gateway over real HTTP and then off
the durable journal, because the response alone cannot distinguish a turn
that was queued from one that was queued AND dispatched.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import pytest
from httpx import ASGITransport

from ...database import get_thread
from ...database.models import ControlActionModel
from ...thread.dispatch_policy import FailureType
from ...thread.enums import ControlActionResultStatus, ControlActionType
from .conftest import async_catalog_run_fields, make_app

if TYPE_CHECKING:
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

type SessionFactory = async_sessionmaker[AsyncSession]

_PRESET = "mock-success-single"


async def _start_run(client: httpx.AsyncClient, run_id: str) -> str:
    response = await client.post(
        "/v1/runs",
        json={
            "run_id": run_id,
            "team_preset": _PRESET,
            "message": "start the turn",
            **await async_catalog_run_fields(client),
        },
    )
    assert response.status_code == 201, response.text
    return str(response.json()["run_id"])


async def _followup(
    client: httpx.AsyncClient, run_id: str, *, key: str, content: str
) -> httpx.Response:
    return await client.post(
        f"/v1/runs/{run_id}/messages",
        json={"content": content},
        headers={"Idempotency-Key": key},
    )


async def _waiting_rows(
    sessions: SessionFactory, run_id: str
) -> list[ControlActionModel]:
    """Every continuation this run is holding, in the order it would promote."""
    from sqlalchemy import select

    async with sessions() as db:
        return list(
            (
                await db.scalars(
                    select(ControlActionModel)
                    .where(
                        ControlActionModel.thread_id == run_id,
                        ControlActionModel.action_type
                        == ControlActionType.MESSAGE_FOLLOWUP_REQUESTED.value,
                    )
                    .order_by(ControlActionModel.queue_position)
                )
            ).all()
        )


@pytest.mark.asyncio
async def test_a_busy_run_queues_one_turn_and_dispatches_nothing(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """202 queued at position one, and the journal row owns nothing."""
    app, _agg, worker, _cp = make_app(session_factory, checkpointer)
    run_id = "admit-queued-01"
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://gateway", timeout=30.0
    ) as client:
        await _start_run(client, run_id)
        async with session_factory() as db:
            before = await get_thread(db, run_id)
            assert before is not None
            writer_before = before.writer_action_receipt_id
            revision_before = before.run_revision
        worker.clear()

        queued = await _followup(client, run_id, key="admit-01", content="second turn")

    assert queued.status_code == 202, queued.text
    body = queued.json()
    assert body["action_status"] == "queued"
    assert body["queue_position"] == 1
    assert body["accepted"] is True
    assert body["applied"] is False
    assert body["idempotency_key"] == "admit-01"
    assert body["action_id"]

    assert worker.dispatches == [], "a queued turn must reach no worker"

    rows = await _waiting_rows(session_factory, run_id)
    assert len(rows) == 1
    waiting = rows[0]
    assert waiting.result_status == ControlActionResultStatus.QUEUED.value
    assert waiting.queue_position == 1
    # The three things a reservation deliberately stops short of.
    assert waiting.graph_receipt_json is None
    assert waiting.applied_at is None
    # The lease is what makes two identical admissions one.
    assert waiting.claim_token is not None

    async with session_factory() as db:
        after = await get_thread(db, run_id)
    assert after is not None
    assert after.writer_action_receipt_id == writer_before
    assert after.run_revision == revision_before


@pytest.mark.asyncio
async def test_a_second_continuation_refuses_queue_full_while_one_waits(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """The per-run depth is a typed refusal, never a silent drop or a queue."""
    app, _agg, worker, _cp = make_app(session_factory, checkpointer)
    run_id = "admit-queued-02"
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://gateway", timeout=30.0
    ) as client:
        await _start_run(client, run_id)
        worker.clear()

        first = await _followup(client, run_id, key="admit-02a", content="second turn")
        second = await _followup(client, run_id, key="admit-02b", content="third turn")

    assert first.status_code == 202, first.text
    assert second.status_code == 409, second.text
    assert second.json()["detail"]["code"] == FailureType.QUEUE_FULL.value
    assert second.json()["detail"]["message"]

    # The refusal reserved nothing: the first turn still holds the only place.
    rows = await _waiting_rows(session_factory, run_id)
    assert [row.queue_position for row in rows] == [1]
    assert worker.dispatches == []


@pytest.mark.asyncio
async def test_a_cancelling_run_still_refuses_as_busy(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """A run that is leaving can never promote a turn queued behind it."""
    app, _agg, worker, _cp = make_app(session_factory, checkpointer)
    run_id = "admit-cancelling-03"
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://gateway", timeout=30.0
    ) as client:
        await _start_run(client, run_id)
        worker.clear()
        cancelled = await client.post(f"/v1/runs/{run_id}/cancel")
        assert cancelled.status_code in {200, 202}, cancelled.text
        async with session_factory() as db:
            cancelling = await get_thread(db, run_id)
        assert cancelling is not None and cancelling.status == "cancelling"

        refused = await _followup(client, run_id, key="admit-03", content="second turn")

    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"]["code"] == FailureType.RUN_BUSY.value
    assert await _waiting_rows(session_factory, run_id) == []

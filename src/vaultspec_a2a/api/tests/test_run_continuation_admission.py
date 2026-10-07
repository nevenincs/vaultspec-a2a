"""A busy run takes one follow-up turn and holds it, reserving nothing else.

The published 202 becomes reachable here. A run still executing its first
turn admits a continuation, and admitting is deliberately almost nothing: a
journal row with a place in the queue and a lease, no graph receipt, no
writer, no dispatch. Installing any of those now would hand the run's write
authority to a turn that has not started, after which the turn that IS
running has its own terminal refused as superseded and the run quarantines.

A parked run still refuses, and the refusal is read off the durable journal
rather than guessed: INPUT_REQUIRED is one status over two unrelated pauses
with two unrelated respond verbs, and the wrong guess is this route, which
would start a turn and orphan the pause.

Every claim below is read off the real gateway over real HTTP and then off
the durable journal, because the response alone cannot distinguish a turn
that was queued from one that was queued AND dispatched.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import pytest
from httpx import ASGITransport

from ...database import create_thread, get_thread, record_permission_request
from ...database.models import ControlActionModel
from ...testing import async_catalog_run_fields
from ...tests._write_authority import make_test_write_authority
from ...thread.dispatch_policy import FailureType
from ...thread.enums import ControlActionResultStatus, ControlActionType, ThreadStatus
from .conftest import make_app

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


async def _park_run(
    sessions: SessionFactory, run_id: str, *, request_id: str | None
) -> None:
    """Seed a run parked for input, with or without a permission request.

    The two shapes of one status: a run waiting on a permission request the
    journal holds, and a run waiting at a clarification interrupt it does not.
    """
    async with sessions() as db:
        await create_thread(
            db,
            write_authority=make_test_write_authority(),
            thread_id=run_id,
            status=ThreadStatus.INPUT_REQUIRED,
            team_preset=_PRESET,
        )
        if request_id is not None:
            await record_permission_request(
                db,
                request_id=request_id,
                thread_id=run_id,
                pause_reason_type="tool_permission",
                description="May I write the file?",
                allowed_options=[
                    {"option_id": "allow", "name": "Allow", "kind": "allow_once"}
                ],
                tool_call="write_file",
            )
        await db.commit()


@pytest.mark.asyncio
async def test_a_permission_pause_refuses_by_naming_its_own_respond_verb(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """The served refusal carries the exact address of the waiting request."""
    app, _agg, worker, _cp = make_app(session_factory, checkpointer)
    run_id = "parked-permission-04"
    await _park_run(session_factory, run_id, request_id="perm-req-1")

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://gateway", timeout=30.0
    ) as client:
        refused = await _followup(client, run_id, key="parked-04", content="go on")

    assert refused.status_code == 409, refused.text
    detail = refused.json()["detail"]
    assert detail["code"] == FailureType.INPUT_REQUIRED.value
    assert f"POST /v1/runs/{run_id}/permissions/perm-req-1/respond" in detail["message"]
    assert worker.dispatches == []
    assert await _waiting_rows(session_factory, run_id) == []


@pytest.mark.asyncio
async def test_a_clarification_pause_refuses_by_naming_the_other_verb(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """No permission row in the journal is itself the answer about the pause."""
    app, _agg, worker, _cp = make_app(session_factory, checkpointer)
    run_id = "parked-clarification-05"
    await _park_run(session_factory, run_id, request_id=None)

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://gateway", timeout=30.0
    ) as client:
        refused = await _followup(client, run_id, key="parked-05", content="go on")

    assert refused.status_code == 409, refused.text
    detail = refused.json()["detail"]
    assert detail["code"] == FailureType.INPUT_REQUIRED.value
    assert f"/v1/runs/{run_id}/clarifications/" in detail["message"]
    assert "run-status" in detail["message"]
    assert "permissions" not in detail["message"]
    assert worker.dispatches == []


@pytest.mark.asyncio
async def test_run_status_discloses_the_queue_depth_a_client_cannot_see(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """A reloading client reads the waiting turn from authoritative state.

    Nothing else tells it: a queued turn has not started, so the progress
    stream carries no frame for it, and a run whose turn ended with one
    waiting is RUNNING with a quiet stream - indistinguishable from idle.
    Read before and after so the number is this run's queue and not a
    constant that happens to match.
    """
    app, _agg, worker, _cp = make_app(session_factory, checkpointer)
    run_id = "queue-depth-06"
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://gateway", timeout=30.0
    ) as client:
        await _start_run(client, run_id)
        worker.clear()

        before = await client.get(f"/v1/runs/{run_id}")
        assert before.status_code == 200, before.text
        assert before.json()["queued_messages"] == 0

        queued = await _followup(client, run_id, key="depth-06", content="second turn")
        assert queued.status_code == 202, queued.text

        after = await client.get(f"/v1/runs/{run_id}")

    assert after.status_code == 200, after.text
    body = after.json()
    assert body["queued_messages"] == 1
    # The run has not changed state, which is exactly why the count is needed.
    assert body["status"] == before.json()["status"]

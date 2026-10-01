"""The follow-up verb takes the caller's key and derives none of its own.

A key derived from the request can only be derived from what the request
already says: the run, the agent, and the text. That is right for an action
that addresses something already durable - one permission request has one
answer - and wrong for a turn, because two deliberate identical continuations
are two turns and a content digest folds the second into the first and answers
it as a replay of the first that never ran.

So the key is required here, and a request that names none is refused before
the run is read: the refusals below are observed against runs whose own
answers would be different statuses, which is what shows the check runs first.
"""

from __future__ import annotations

import itertools
from typing import TYPE_CHECKING

import httpx
import pytest
from httpx import ASGITransport

from ...thread.idempotency import IDEMPOTENCY_KEY_MAX_LENGTH
from .conftest import async_catalog_run_fields, make_app

if TYPE_CHECKING:
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

type SessionFactory = async_sessionmaker[AsyncSession]

_PRESET = "mock-success-single"
_RUN_SEQ = itertools.count(1)


async def _start_run(client: httpx.AsyncClient) -> str:
    response = await client.post(
        "/v1/runs",
        json={
            "run_id": f"followup-key-{next(_RUN_SEQ):02d}",
            "team_preset": _PRESET,
            "message": "start the turn",
            **await async_catalog_run_fields(client),
        },
    )
    assert response.status_code == 201, response.text
    return str(response.json()["run_id"])


def _names_the_header(body: object) -> bool:
    """Say whether a validation body blames the idempotency header."""
    assert isinstance(body, dict)
    errors = body["detail"]
    assert isinstance(errors, list)
    return any(
        "idempotency-key" in "/".join(str(part) for part in error["loc"]).lower()
        for error in errors
    )


@pytest.mark.asyncio
async def test_a_follow_up_naming_no_key_is_refused_before_the_run_is_read(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """No key is a malformed request, whatever the run would have answered.

    Both runs below have an answer of their own for a well-formed follow-up -
    one is executing its first turn, the other does not exist - and neither
    answer is served, because the key is missing and the request never reaches
    the state machine that would give one.
    """
    app, _agg, worker, _cp = make_app(session_factory, checkpointer)
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://gateway", timeout=30.0
    ) as client:
        run_id = await _start_run(client)
        worker.clear()

        on_a_busy_run = await client.post(
            f"/v1/runs/{run_id}/messages", json={"content": "second turn"}
        )
        on_no_run = await client.post(
            "/v1/runs/no-such-run/messages", json={"content": "second turn"}
        )

    assert on_a_busy_run.status_code == 422, on_a_busy_run.text
    assert _names_the_header(on_a_busy_run.json())
    assert on_no_run.status_code == 422, on_no_run.text
    assert _names_the_header(on_no_run.json())
    assert worker.dispatches == [], "a refused follow-up must not dispatch"


@pytest.mark.asyncio
async def test_a_supplied_key_is_bounded_and_otherwise_taken_as_given(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """The key is opaque, so the only thing the gateway says about one is its size.

    A key at the published bound is carried into the verb, which then answers
    with the run's own answer; one byte longer is a malformed request. The
    bound is at the edge because the value reaches a durable uniqueness
    constraint, and an unbounded header has no business there.
    """
    app, _agg, worker, _cp = make_app(session_factory, checkpointer)
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://gateway", timeout=30.0
    ) as client:
        run_id = await _start_run(client)
        worker.clear()

        at_bound = await client.post(
            f"/v1/runs/{run_id}/messages",
            json={"content": "second turn"},
            headers={"Idempotency-Key": "k" * IDEMPOTENCY_KEY_MAX_LENGTH},
        )
        over_bound = await client.post(
            f"/v1/runs/{run_id}/messages",
            json={"content": "second turn"},
            headers={"Idempotency-Key": "k" * (IDEMPOTENCY_KEY_MAX_LENGTH + 1)},
        )
        empty = await client.post(
            f"/v1/runs/{run_id}/messages",
            json={"content": "second turn"},
            headers={"Idempotency-Key": ""},
        )

    # The run answers its own way, which is the proof the key was accepted and
    # the request went on to the verb rather than being rejected at the edge.
    assert at_bound.status_code == 202, at_bound.text
    assert at_bound.json()["action_status"] == "queued"

    assert over_bound.status_code == 422, over_bound.text
    assert _names_the_header(over_bound.json())
    assert empty.status_code == 422, empty.text
    assert _names_the_header(empty.json())
    assert worker.dispatches == [], "a queued follow-up must not dispatch"

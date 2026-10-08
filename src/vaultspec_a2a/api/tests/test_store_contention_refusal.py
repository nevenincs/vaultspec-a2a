"""A contended application store refuses a run verb; it never faults it.

Two writers on one SQLite file is an ordinary condition, not damage: the write
that lost the race changed nothing, and the one that won is the run's current
state. Every attempt being refused is therefore something the caller retries,
and the gateway says so with the retryable refusal every verb shares. Reported
as a 500 instead, the same condition told a client the gateway had broken and
that the run's state was unknown.

The competing writer here is a real second connection to the same file holding a
real ``BEGIN IMMEDIATE``; the refusal is read off the real gateway over real
HTTP, and the run's own durable state is read afterwards to prove nothing was
applied.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import TYPE_CHECKING

import httpx
import pytest
from httpx import ASGITransport
from sqlalchemy import select

from ...conftest import SqlitePosture
from ...database import ControlActionModel, get_thread
from ...testing import DEFAULT_TEAM_PRESET, async_catalog_run_fields, settings_override
from ...thread.enums import ControlActionType
from .conftest import make_app

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

type SessionFactory = async_sessionmaker[AsyncSession]

#: Short enough that four refused attempts and their backoff finish inside the
#: test, long enough that an uncontended write never sees it.
_BUSY_TIMEOUT_MS = 60

pytestmark = pytest.mark.sqlite_engine(SqlitePosture.APPLICATION)


@contextmanager
def _competing_writer(database_file: Path, run_id: str) -> Generator[None]:
    """Hold the store's write lock from another connection for the block.

    A real second SQLite connection in its own ``BEGIN IMMEDIATE``, with a write
    behind it, so the lock is genuinely taken and genuinely held until this
    context exits.
    """
    holder = sqlite3.connect(database_file, isolation_level=None, timeout=10.0)
    try:
        holder.execute("PRAGMA busy_timeout=10000")
        holder.execute("BEGIN IMMEDIATE")
        holder.execute("UPDATE threads SET title = ? WHERE id = ?", ("held", run_id))
        yield
    finally:
        holder.rollback()
        holder.close()


async def _start_run(client: httpx.AsyncClient, run_id: str) -> None:
    response = await client.post(
        "/v1/runs",
        json={
            "run_id": run_id,
            "team_preset": DEFAULT_TEAM_PRESET,
            "message": "start the turn",
            **await async_catalog_run_fields(client),
        },
    )
    assert response.status_code == 201, response.text


async def _cancel_actions(
    sessions: SessionFactory, run_id: str
) -> list[ControlActionModel]:
    async with sessions() as db:
        return list(
            (
                await db.scalars(
                    select(ControlActionModel).where(
                        ControlActionModel.thread_id == run_id,
                        ControlActionModel.action_type
                        == ControlActionType.CANCEL.value,
                    )
                )
            ).all()
        )


@pytest.mark.asyncio
async def test_a_contended_store_refuses_run_start_as_retryable(
    database_file: Path,
    session_factory: SessionFactory,
    checkpointer: AsyncSqliteSaver,
) -> None:
    """The creating write meets the same refusal, and creates no run."""
    held_run_id = "contended-start-holder"
    refused_run_id = "contended-start-02"
    with settings_override(sqlite_busy_timeout_ms=_BUSY_TIMEOUT_MS):
        app, _hub, worker, _cp = make_app(session_factory, checkpointer)
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://gateway", timeout=30.0
        ) as client:
            await _start_run(client, held_run_id)
            worker.clear()
            body = {
                "run_id": refused_run_id,
                "team_preset": DEFAULT_TEAM_PRESET,
                "message": "start the turn",
                **await async_catalog_run_fields(client),
            }
            with _competing_writer(database_file, held_run_id):
                refused = await client.post("/v1/runs", json=body)

    assert refused.status_code == 503, refused.text
    assert "nothing was applied" in refused.json()["detail"]
    async with session_factory() as db:
        absent = await get_thread(db, refused_run_id)
    assert absent is None
    assert worker.dispatches == []


@pytest.mark.asyncio
async def test_a_contended_store_refuses_cancel_as_retryable(
    database_file: Path,
    session_factory: SessionFactory,
    checkpointer: AsyncSqliteSaver,
) -> None:
    """503 with the shared retryable account, and no cancellation reserved."""
    run_id = "contended-cancel-01"
    with settings_override(sqlite_busy_timeout_ms=_BUSY_TIMEOUT_MS):
        app, _hub, worker, _cp = make_app(session_factory, checkpointer)
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://gateway", timeout=30.0
        ) as client:
            await _start_run(client, run_id)
            async with session_factory() as db:
                before = await get_thread(db, run_id)
            assert before is not None
            worker.clear()

            with _competing_writer(database_file, run_id):
                refused = await client.post(f"/v1/runs/{run_id}/cancel")

    assert refused.status_code == 503, refused.text
    assert "nothing was applied" in refused.json()["detail"]
    # Nothing was reserved and nothing was delivered: the run is as it was.
    assert await _cancel_actions(session_factory, run_id) == []
    assert worker.dispatches == []
    async with session_factory() as db:
        after = await get_thread(db, run_id)
    assert after is not None
    assert after.status == before.status
    assert after.repair_status == before.repair_status

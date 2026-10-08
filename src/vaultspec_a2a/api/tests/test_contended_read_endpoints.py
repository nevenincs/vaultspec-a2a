"""A contended application store never faults a run read.

Both `/v1` run reads run the recovery coordinator before they project, so a run
whose checkpoint proves its turn completed is settled by the read that asks
about it. That settlement is a durable write, and a competing writer holding
`BEGIN IMMEDIATE` made the driver error the response: run-status and run-history
each answered 500 - "the gateway has broken and this run's state is unknown" -
over a store condition that resolves by itself.

A read's product is the truth about the run, and the durable row is that truth
whether or not the owed settlement lands. So these answer 200 with the record
they can read and name the owed settlement in `degraded_reasons`, which is what
the state-truthfulness contract asks of a read that cannot complete its pass.

The competing writer is a real second connection to the same file holding a real
`BEGIN IMMEDIATE`; the responses are read off the real gateway over real HTTP.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import TYPE_CHECKING

import httpx
import pytest
from httpx import ASGITransport

from ...conftest import SqlitePosture
from ...database import get_thread
from ...testing import seed_completed_authority, settings_override
from ...thread.enums import DegradedReason, ThreadStatus
from .conftest import make_app

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

type SessionFactory = async_sessionmaker[AsyncSession]

#: Short enough that four refused attempts and their backoff finish inside the
#: test, long enough that an uncontended write never meets it.
_BUSY_TIMEOUT_MS = 200

pytestmark = pytest.mark.sqlite_engine(SqlitePosture.APPLICATION)


@pytest.fixture(autouse=True)
def _short_lock_wait() -> Generator[None]:
    """Narrow the store's lock wait for the whole test, seeding included.

    The engine applies the configured wait per CONNECTION, and the pool keeps
    the one the seeding opened, so an override entered after the seed leaves the
    contended attempts waiting out the full production budget instead.
    """
    with settings_override(sqlite_busy_timeout_ms=_BUSY_TIMEOUT_MS):
        yield


@contextmanager
def _competing_writer(database_file: Path, run_id: str) -> Generator[None]:
    """Hold the store's write lock from another real connection for the block."""
    holder = sqlite3.connect(database_file, isolation_level=None, timeout=10.0)
    try:
        holder.execute("PRAGMA busy_timeout=10000")
        holder.execute("BEGIN IMMEDIATE")
        holder.execute("UPDATE threads SET title = ? WHERE id = ?", ("held", run_id))
        yield
    finally:
        holder.rollback()
        holder.close()


async def _seed_proven_terminal(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver, title: str
) -> str:
    async with session_factory() as session:
        run_id, _receipt = await seed_completed_authority(
            session, checkpointer, title=title
        )
    return run_id


def _client(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> httpx.AsyncClient:
    """A real HTTP client over the real gateway app these reads are served by."""
    app = make_app(session_factory, checkpointer)[0]
    return httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://gateway", timeout=30.0
    )


@pytest.mark.asyncio
async def test_run_status_answers_the_durable_record_under_a_held_lock(
    database_file: Path,
    session_factory: SessionFactory,
    checkpointer: AsyncSqliteSaver,
) -> None:
    """200 with the pre-settlement status and the owed settlement named."""
    run_id = await _seed_proven_terminal(
        session_factory, checkpointer, "contended run-status"
    )
    async with _client(session_factory, checkpointer) as client:
        with _competing_writer(database_file, run_id):
            answered = await client.get(f"/v1/runs/{run_id}")

    assert answered.status_code == 200, answered.text
    body = answered.json()
    assert body["status"] == ThreadStatus.RUNNING.value
    assert DegradedReason.SETTLEMENT_STORE_CONTENDED.value in body["degraded_reasons"]
    # Nothing was applied: the run is exactly as the read found it.
    async with session_factory() as db:
        held = await get_thread(db, run_id)
    assert held is not None
    assert held.status == ThreadStatus.RUNNING.value


@pytest.mark.asyncio
async def test_run_history_answers_the_durable_record_under_a_held_lock(
    database_file: Path,
    session_factory: SessionFactory,
    checkpointer: AsyncSqliteSaver,
) -> None:
    """The wide read keeps the half it can read, and settles once free."""
    run_id = await _seed_proven_terminal(
        session_factory, checkpointer, "contended run-history"
    )
    async with _client(session_factory, checkpointer) as client:
        with _competing_writer(database_file, run_id):
            answered = await client.get(f"/v1/runs/{run_id}/history")
        freed = await client.get(f"/v1/runs/{run_id}/history")

    assert answered.status_code == 200, answered.text
    state = answered.json()["state"]
    assert state["status"] == ThreadStatus.RUNNING.value
    assert DegradedReason.SETTLEMENT_STORE_CONTENDED.value in state["degraded_reasons"]

    # The settlement was owed, not lost: the next read makes it.
    assert freed.status_code == 200, freed.text
    assert freed.json()["state"]["status"] == ThreadStatus.COMPLETED.value

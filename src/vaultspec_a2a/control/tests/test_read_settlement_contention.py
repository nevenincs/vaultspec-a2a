"""A read that discovers a settlement answers even while the store is locked.

``capture_thread_state`` runs the recovery coordinator before it projects, so a
run whose checkpoint proves its turn completed is settled by the very read that
asks about it. That settlement is a durable write, and it was made outside the
store's write-contention policy: a competing writer holding ``BEGIN IMMEDIATE``
turned both read verbs - run-status and run-history - into a driver error, which
the gateway served as a 500.

The settlement is not the read's product. The read's product is the truth about
the run, and the durable row is that truth whether or not the owed settlement
lands. So contention that outlasts the retry budget leaves the read answering
from durable state with a typed degraded reason, and the settlement is still
owed - the next pass makes it, once the lock is free.

Driven against a real on-disk application store with a real second SQLite
connection holding a real ``BEGIN IMMEDIATE``, a real ``AsyncSqliteSaver``, and
the production coordinator.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

import pytest

from ...conftest import SqlitePosture
from ...database import get_thread
from ...streaming import RelayHub
from ...testing import held_write_lock, seed_completed_authority, settings_override
from ...thread.enums import DegradedReason, ThreadStatus
from ..thread_state_service import capture_thread_state

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

type SessionFactory = async_sessionmaker[AsyncSession]

#: Short enough that four refused attempts and their backoff finish inside the
#: test, long enough that an uncontended write never meets it.
_BUSY_TIMEOUT_MS = 500

#: Held for longer than one attempt's lock wait and well inside the whole retry
#: budget (four lock waits plus their growing pauses, about 2.3s), so the
#: settlement can only land by being retried after the lock comes free - with
#: enough headroom that a loaded machine does not move the release outside the
#: budget.
_TRANSIENT_HOLD_SECONDS = 0.4

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


async def _capture_status(
    session_factory: SessionFactory,
    checkpointer: AsyncSqliteSaver,
    run_id: str,
) -> tuple[str, list[DegradedReason]]:
    """Read the run through the production capture, as both read verbs do."""
    async with session_factory() as db:
        capture = await capture_thread_state(
            db,
            thread_id=run_id,
            relay_hub=RelayHub(),
            checkpointer=checkpointer,
        )
    assert capture is not None
    return capture.snapshot.status, capture.snapshot.degraded_reasons


@pytest.mark.asyncio
async def test_a_read_answers_durable_truth_while_the_store_is_locked(
    database_file: Path,
    session_factory: SessionFactory,
    checkpointer: AsyncSqliteSaver,
) -> None:
    """The read answers, says why it is incomplete, and settles once free."""
    async with session_factory() as session:
        run_id, _receipt = await seed_completed_authority(
            session, checkpointer, title="contended read settlement"
        )

    with held_write_lock(
        database_file,
        statement="UPDATE threads SET title = ? WHERE id = ?",
        parameters=("held", run_id),
    ):
        status, degraded = await _capture_status(session_factory, checkpointer, run_id)

    # The durable row is what it was: the settlement was refused, not
    # half-applied, and the read says so instead of claiming completion.
    assert status == ThreadStatus.RUNNING.value
    assert DegradedReason.SETTLEMENT_STORE_CONTENDED in degraded

    async with session_factory() as db:
        held = await get_thread(db, run_id)
    assert held is not None
    assert held.status == ThreadStatus.RUNNING.value

    # The lock is gone, so the still-owed settlement lands on the next read
    # and that read reports the terminal it proved.
    settled, settled_degraded = await _capture_status(
        session_factory, checkpointer, run_id
    )

    assert settled == ThreadStatus.COMPLETED.value
    assert DegradedReason.SETTLEMENT_STORE_CONTENDED not in settled_degraded
    async with session_factory() as db:
        after = await get_thread(db, run_id)
    assert after is not None
    assert after.status == ThreadStatus.COMPLETED.value


@pytest.mark.asyncio
async def test_a_transient_writer_costs_the_settlement_latency_not_the_read(
    database_file: Path,
    session_factory: SessionFactory,
    checkpointer: AsyncSqliteSaver,
) -> None:
    """A lock released inside the retry budget still lets the settlement land.

    The companion half of the policy: the retry exists so ordinary momentary
    contention is waited out rather than degraded over, and the run reaches its
    proven terminal on the read that discovered it. The lock is let go while the
    read is already attempting the settlement, so only a retry can explain the
    terminal.
    """
    async with session_factory() as session:
        run_id, _receipt = await seed_completed_authority(
            session, checkpointer, title="transient read settlement"
        )

    with held_write_lock(
        database_file,
        statement="UPDATE threads SET title = ? WHERE id = ?",
        parameters=("held", run_id),
    ) as holder:

        async def release_after_one_attempt() -> None:
            await asyncio.sleep(_TRANSIENT_HOLD_SECONDS)
            holder.rollback()

        releasing = asyncio.create_task(release_after_one_attempt())
        started = time.monotonic()
        status, degraded = await _capture_status(session_factory, checkpointer, run_id)
        waited = time.monotonic() - started
        await releasing

    # The read answered only after the lock came free: an answer inside the
    # first attempt's own lock wait would mean nothing was ever held.
    assert waited >= _TRANSIENT_HOLD_SECONDS
    assert status == ThreadStatus.COMPLETED.value
    assert DegradedReason.SETTLEMENT_STORE_CONTENDED not in degraded

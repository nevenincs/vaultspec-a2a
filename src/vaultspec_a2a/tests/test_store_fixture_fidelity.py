"""The store fixtures stand in for the stores the service actually serves.

Production serves the run's durable rows and its checkpoints from ONE SQLite
file: ``settings.checkpoint_connection_string`` falls back to ``database_url``,
so the two stores share a single write lock, and the saver's connection carries
the configured posture through ``checkpoint_pragmas``.

The fixtures used to differ on both counts - a separate file, no pragmas at all
- which made a whole class of defect unreachable from any tier: a read failing
over the settlement it discovered, a graph event stream failing a run, each
reported only from a live service and never from a suite. These are the proofs
that the fixtures no longer differ, driven against the real fixtures through
real connections.
"""

from __future__ import annotations

import asyncio
import sqlite3
import time
from typing import TYPE_CHECKING

import pytest
from langgraph.checkpoint.base import empty_checkpoint
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from ..conftest import SqlitePosture
from ..control.config import settings
from ..database import WriteContentionError, checkpoint_pragmas, open_checkpointer
from ..testing import held_write_lock, settings_override

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from langchain_core.runnables import RunnableConfig

#: Deliberately not the configured default, so a posture that silently keeps
#: the driver's own lock wait cannot pass this; small enough that the whole
#: retry budget (four lock waits plus their growing pauses) finishes inside a
#: test.
_BUSY_TIMEOUT_MS = 321

#: Held for longer than one attempt's lock wait and well inside the retry
#: budget, so the checkpoint can only land by being retried once the lock comes
#: free.
_TRANSIENT_HOLD_SECONDS = 0.4


def _run_config(run_id: str) -> RunnableConfig:
    return {"configurable": {"thread_id": run_id, "checkpoint_ns": ""}}


@pytest.fixture(autouse=True)
def _declared_lock_wait() -> Generator[None]:
    """Put a non-default lock wait in force before the fixtures open anything."""
    with settings_override(sqlite_busy_timeout_ms=_BUSY_TIMEOUT_MS):
        yield


@pytest.mark.asyncio
async def test_the_checkpointer_shares_the_application_store_file(
    database_file: Path,
    checkpoint_file: Path,
    checkpointer: AsyncSqliteSaver,
) -> None:
    """One file, and the saver's tables really are in it."""
    assert checkpoint_file == database_file

    await checkpointer.aput(_run_config("shared-store"), empty_checkpoint(), {}, {})

    connection = sqlite3.connect(str(database_file))
    try:
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        stored = connection.execute("SELECT count(*) FROM checkpoints").fetchone()[0]
    finally:
        connection.close()

    # The application schema and the saver's own tables, in the same file.
    assert {"threads", "control_actions", "checkpoints", "writes"} <= tables
    assert stored == 1


@pytest.mark.asyncio
async def test_the_checkpointer_carries_the_served_pragma_posture(
    checkpointer: AsyncSqliteSaver,
) -> None:
    """WAL, the configured lock wait, and foreign keys - read back from SQLite."""
    assert settings.sqlite_busy_timeout_ms == _BUSY_TIMEOUT_MS
    observed: dict[str, object] = {}
    for name in ("journal_mode", "busy_timeout", "foreign_keys"):
        row = await (await checkpointer.conn.execute(f"PRAGMA {name}")).fetchone()
        assert row is not None, name
        observed[name] = row[0]

    assert observed == {
        "journal_mode": "wal",
        "busy_timeout": _BUSY_TIMEOUT_MS,
        "foreign_keys": 1,
    }
    # The posture comes from the one source production reads, not from a
    # restatement that could drift from it.
    assert checkpoint_pragmas(_BUSY_TIMEOUT_MS) == (
        f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}",
        "PRAGMA journal_mode=WAL",
        "PRAGMA foreign_keys=ON",
    )


@pytest.mark.asyncio
async def test_the_fixture_yields_the_saver_the_service_serves(
    checkpointer: AsyncSqliteSaver, tmp_path: Path
) -> None:
    """The fixture's saver is the one ``open_checkpointer`` builds, not the base.

    Production never serves a bare ``AsyncSqliteSaver``: the factory wraps it in
    the store's write-contention policy and seats the strict deserializer on it.
    A fixture that handed suites the library saver let every claim about a
    contended or a maliciously shaped checkpoint be made against a saver with
    neither, so the posture is compared against a saver the production factory
    opens right here rather than described.

    The factory is pointed at a store of its own for the comparison, so this
    never opens the developer's configured checkpoint store.
    """
    with settings_override(
        checkpoint_database_url=f"sqlite+aiosqlite:///{tmp_path / 'served.sqlite'}"
    ):
        async with open_checkpointer() as served:
            assert type(checkpointer) is type(served)
            assert type(served) is not AsyncSqliteSaver


@pytest.mark.sqlite_engine(SqlitePosture.APPLICATION)
@pytest.mark.asyncio
async def test_a_transient_application_writer_delays_a_fixture_checkpoint(
    database_file: Path,
    checkpointer: AsyncSqliteSaver,
) -> None:
    """The shared write lock is real, and the fixture's saver survives meeting it.

    The fact the separate-file fixture could not express at all: a real second
    connection takes the application store's write lock with a real row write
    behind it, and a checkpoint write runs straight into it.

    The library saver FAILED here. Its connection already carries an implicit
    read transaction, and a write that upgrades one is refused outright without
    the lock wait being consulted, so a moment of ordinary contention raised
    ``database is locked`` out of the fixture. The served saver answers exactly
    that condition with a rollback and the store's retry policy
    (``database.checkpoints``), so the write costs latency and lands - which is
    the behaviour every suite reaching a checkpoint through this fixture is
    entitled to assume.
    """
    with held_write_lock(
        database_file,
        statement="UPDATE threads SET title = ? WHERE id = ?",
        parameters=("held", "absent"),
    ) as holder:

        async def release_after_one_attempt() -> None:
            await asyncio.sleep(_TRANSIENT_HOLD_SECONDS)
            holder.rollback()

        releasing = asyncio.create_task(release_after_one_attempt())
        started = time.monotonic()
        await checkpointer.aput(_run_config("shared-lock"), empty_checkpoint(), {}, {})
        waited = time.monotonic() - started
        await releasing

    # It really met the lock: a write that answered before the holder let go
    # would mean the shared lock was never taken.
    assert waited >= _TRANSIENT_HOLD_SECONDS

    read = await checkpointer.aget_tuple(_run_config("shared-lock"))
    assert read is not None


@pytest.mark.sqlite_engine(SqlitePosture.APPLICATION)
@pytest.mark.asyncio
async def test_exhausted_contention_refuses_a_fixture_checkpoint_as_retryable(
    database_file: Path,
    checkpointer: AsyncSqliteSaver,
) -> None:
    """Contention that outlasts the budget is the store's typed refusal.

    The discriminating half: the library saver let the driver's own
    ``database is locked`` out of the fixture, which is the same error a corrupt
    store raises and carries no statement about retryability. The served saver
    exhausts its budget and refuses with ``WriteContentionError``, which is what
    the ``/v1`` verbs turn into a retryable refusal. A suite asserting on how the
    service answers a busy store has to be given the saver that produces that
    answer.
    """
    with (
        held_write_lock(
            database_file,
            statement="UPDATE threads SET title = ? WHERE id = ?",
            parameters=("held", "absent"),
        ),
        pytest.raises(WriteContentionError) as refused,
    ):
        await checkpointer.aput(
            _run_config("exhausted-lock"), empty_checkpoint(), {}, {}
        )

    assert "nothing was applied" in str(refused.value)

    # The store is writable again, so the refusal was contention rather than a
    # connection the refused write left poisoned.
    await checkpointer.aput(_run_config("exhausted-lock"), empty_checkpoint(), {}, {})


@pytest.mark.separate_checkpoint_store
@pytest.mark.asyncio
async def test_the_opt_out_mark_gives_the_checkpointer_its_own_file(
    database_file: Path,
    checkpoint_file: Path,
    checkpointer: AsyncSqliteSaver,
) -> None:
    """A test that needs two stores still gets two, and the posture holds."""
    assert checkpoint_file != database_file
    row = await (await checkpointer.conn.execute("PRAGMA busy_timeout")).fetchone()
    assert row is not None
    assert row[0] == _BUSY_TIMEOUT_MS

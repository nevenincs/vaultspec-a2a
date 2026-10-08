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

import sqlite3
from typing import TYPE_CHECKING

import pytest
from langgraph.checkpoint.base import empty_checkpoint

from ..conftest import SqlitePosture
from ..control.config import settings
from ..database import checkpoint_pragmas
from ..testing import settings_override

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from langchain_core.runnables import RunnableConfig
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

#: Deliberately not the configured default, so a posture that silently keeps
#: the driver's own lock wait cannot pass this.
_BUSY_TIMEOUT_MS = 7321


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


@pytest.mark.sqlite_engine(SqlitePosture.APPLICATION)
@pytest.mark.asyncio
async def test_a_checkpoint_write_contends_with_an_application_writer(
    database_file: Path,
    checkpointer: AsyncSqliteSaver,
) -> None:
    """The shared write lock is real, and the fixture's saver now meets it.

    The fact the separate-file fixture could not express at all: a real second
    connection takes the application store's write lock with a real row write
    behind it, and the saver's checkpoint is refused for it.

    Refused rather than waited out because the saver this fixture opens is the
    LIBRARY'S, and the saver's connection already carries an implicit read
    transaction - a write that upgrades one is refused outright without the lock
    wait being consulted. The served saver answers exactly this condition with
    the store's retry policy and a rollback between attempts
    (``database.checkpoints``), which the fixture does not reproduce. That is
    why a test holding an uncommitted application transaction ACROSS a
    checkpoint write declares ``separate_checkpoint_store`` instead.
    """
    holder = sqlite3.connect(str(database_file), isolation_level=None, timeout=10.0)
    try:
        holder.execute("PRAGMA busy_timeout=10000")
        holder.execute("BEGIN IMMEDIATE")
        holder.execute("UPDATE threads SET title = 'held' WHERE id = 'absent'")
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            await checkpointer.aput(
                _run_config("shared-lock"), empty_checkpoint(), {}, {}
            )
        holder.rollback()
    finally:
        holder.close()

    # The lock is free again, so the same write lands: the refusal above was
    # contention, not a store the fixture left broken.
    await checkpointer.aput(_run_config("shared-lock"), empty_checkpoint(), {}, {})


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

"""Real-connection proofs that every checkpoint writer shares one PRAGMA posture.

The checkpoint store has more than one connection authority: the LangGraph saver
opened by ``open_checkpointer``, and the stdlib ``sqlite3`` connection the schema
identity installer opens against the same file. Both are writers, and by default
they address the same database file as the application store. Every assertion
here opens a real connection and reads the PRAGMA back out of SQLite; none of
them inspects source text.
"""

from __future__ import annotations

import asyncio
import sqlite3
import time
from typing import TYPE_CHECKING

import pytest
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from ...testing import settings_override as _settings_override
from ..checkpoint_schema import (
    checkpoint_pragmas,
    install_checkpoint_schema_identity,
    open_checkpoint_read_only,
)
from ..checkpoints import open_checkpointer

if TYPE_CHECKING:
    from pathlib import Path


async def _create_langgraph_store(path: Path) -> None:
    async with AsyncSqliteSaver.from_conn_string(str(path)) as checkpointer:
        await checkpointer.setup()


def _read_pragmas(path: Path) -> dict[str, object]:
    connection = sqlite3.connect(str(path))
    try:
        return {
            name: connection.execute(f"PRAGMA {name}").fetchone()[0]
            for name in ("journal_mode", "foreign_keys", "busy_timeout")
        }
    finally:
        connection.close()


@pytest.mark.asyncio
async def test_saver_connection_carries_the_configured_posture(
    runtime_dir: Path,
) -> None:
    """The saver applies WAL, the configured busy timeout, and FK enforcement.

    The busy timeout was hardcoded to 5000 here, silently discarding
    ``VAULTSPEC_SQLITE_BUSY_TIMEOUT_MS``; the override below is deliberately not
    the default so a regression to a literal cannot pass.
    """
    db_file = runtime_dir / "posture.sqlite"
    with _settings_override(
        checkpoint_backend="sqlite",
        checkpoint_database_url=f"sqlite+aiosqlite:///{db_file}",
        sqlite_busy_timeout_ms=7321,
    ):
        async with open_checkpointer() as checkpointer:
            assert isinstance(checkpointer, AsyncSqliteSaver)
            observed: dict[str, object] = {}
            for name in ("journal_mode", "busy_timeout", "foreign_keys"):
                cursor = await checkpointer.conn.execute(f"PRAGMA {name}")
                row = await cursor.fetchone()
                assert row is not None, name
                observed[name] = row[0]

    assert observed == {
        "journal_mode": "wal",
        "busy_timeout": 7321,
        "foreign_keys": 1,
    }


@pytest.mark.asyncio
async def test_identity_installer_connection_carries_the_same_posture(
    runtime_dir: Path,
) -> None:
    """The installer's writable connection is no longer PRAGMA-less.

    ``journal_mode`` is the one member of the set persisted in the database
    header, so it is the one an out-of-process reader can still observe after the
    installer has closed its connection. The per-connection members are proven by
    behaviour in the contention test below.
    """
    checkpoint = runtime_dir / "installer-posture.db"
    await _create_langgraph_store(checkpoint)

    connection = sqlite3.connect(str(checkpoint))
    try:
        connection.execute("PRAGMA journal_mode=DELETE")
    finally:
        connection.close()
    assert _read_pragmas(checkpoint)["journal_mode"] == "delete"

    await asyncio.to_thread(install_checkpoint_schema_identity, checkpoint)

    assert _read_pragmas(checkpoint)["journal_mode"] == "wal"


@pytest.mark.asyncio
async def test_installer_waits_for_the_configured_busy_timeout(
    runtime_dir: Path,
) -> None:
    """A configured busy timeout really reaches the installer's connection.

    Python's ``sqlite3.connect`` already defaults to a 5s busy timeout, which
    happens to equal this project's default, so a passive assertion could not
    tell the configured value from the accident. Holding a real EXCLUSIVE lock
    and timing the failure does: with a 400ms budget the installer must give up
    an order of magnitude sooner than the stdlib default it would otherwise
    inherit.
    """
    checkpoint = runtime_dir / "installer-contention.db"
    await _create_langgraph_store(checkpoint)

    blocker = sqlite3.connect(str(checkpoint), isolation_level=None)
    try:
        blocker.execute("BEGIN EXCLUSIVE")
        started = time.monotonic()
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            await asyncio.to_thread(
                install_checkpoint_schema_identity, checkpoint, busy_timeout_ms=400
            )
        elapsed = time.monotonic() - started
    finally:
        blocker.rollback()
        blocker.close()

    # Lower bound: it waited rather than failing instantly, so a timeout was set.
    # Upper bound: it was the configured 400ms, not the 5s stdlib default.
    assert 0.3 <= elapsed < 3.0, elapsed


@pytest.mark.asyncio
async def test_read_only_connection_carries_the_configured_busy_timeout(
    runtime_dir: Path,
) -> None:
    """A reader can be blocked behind a writer's lock, so it is bounded too."""
    checkpoint = runtime_dir / "reader-posture.db"
    await _create_langgraph_store(checkpoint)

    connection = open_checkpoint_read_only(checkpoint, busy_timeout_ms=1234)
    try:
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 1234
    finally:
        connection.close()


@pytest.mark.asyncio
async def test_checkpoint_tables_declare_no_foreign_keys(runtime_dir: Path) -> None:
    """Pin why ``foreign_keys=ON`` is a consistency fix and not a correctness one.

    ``foreign_keys`` is per-connection and off by default, so the checkpoint
    writers ran with enforcement disabled against a file that, by default, also
    holds the application schema. That is a posture inconsistency rather than a
    live data-integrity hole only because neither LangGraph table declares a
    foreign key: a connection touching only these tables has nothing to enforce.
    If LangGraph ever adds one, this test fails and the claim must be revisited.
    """
    checkpoint = runtime_dir / "fk-closure.db"
    await _create_langgraph_store(checkpoint)
    await asyncio.to_thread(install_checkpoint_schema_identity, checkpoint)

    connection = sqlite3.connect(str(checkpoint))
    try:
        tables = [
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        ]
        foreign_keys = {
            table: connection.execute(f"PRAGMA foreign_key_list({table})").fetchall()
            for table in tables
        }
    finally:
        connection.close()

    assert set(tables) >= {"checkpoints", "writes"}
    assert all(not entries for entries in foreign_keys.values()), foreign_keys


def test_pragma_set_is_shared_and_carries_the_supplied_timeout() -> None:
    """The single statement source both writable paths consume."""
    assert checkpoint_pragmas(9999) == (
        "PRAGMA journal_mode=WAL",
        "PRAGMA busy_timeout=9999",
        "PRAGMA foreign_keys=ON",
    )

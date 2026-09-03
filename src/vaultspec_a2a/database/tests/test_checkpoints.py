"""SQLite checkpoint backend enables WAL + busy_timeout (task #15 fix B).

Real on-disk SQLite file, no mocks: open_checkpointer must leave the checkpoint
connection in WAL journal mode (so the gateway's status reads run concurrently with
the worker's checkpoint writes instead of blocking on a writer lock) with a bounded
busy_timeout.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from ...testing import settings_override as _settings_override
from ..checkpoints import open_checkpointer

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.asyncio
async def test_sqlite_checkpointer_enables_wal_and_busy_timeout(tmp_path: Path) -> None:
    db_file = tmp_path / "checkpoints.sqlite"
    with _settings_override(
        checkpoint_backend="sqlite",
        checkpoint_database_url=f"sqlite+aiosqlite:///{db_file}",
    ):
        async with open_checkpointer() as checkpointer:
            # Narrows the broad Checkpointer alias to the concrete saver AND asserts
            # the sqlite branch actually yielded it, so .conn is well-typed and real.
            assert isinstance(checkpointer, AsyncSqliteSaver)
            journal_row = await (
                await checkpointer.conn.execute("PRAGMA journal_mode")
            ).fetchone()
            busy_row = await (
                await checkpointer.conn.execute("PRAGMA busy_timeout")
            ).fetchone()

    assert journal_row is not None
    assert busy_row is not None
    assert journal_row[0] == "wal"
    assert busy_row[0] == 5000

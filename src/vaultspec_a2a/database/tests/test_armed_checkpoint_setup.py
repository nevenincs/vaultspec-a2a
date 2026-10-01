"""An armed desktop boot must not create the checkpoint schema, ever.

The desktop profile separates migration from boot: the staged-generation
entrypoint owns every schema mutation under a one-time transaction descriptor,
and ordinary boot validates what it finds and refuses to change it. The
checkpoint store was the hole in that rule. Skipping ``setup()`` at boot did
not skip the DDL - the SQLite saver runs setup itself before its first read or
write - so an armed gateway pointed at an unmigrated store quietly created the
tables instead of failing the way the primary database does.

Against a real SQLite file, and judged by what is in that file afterwards
rather than by what the saver says about itself.
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, Any, cast
from uuid import uuid4

import pytest
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from ...testing import armed_desktop_app_home, settings_override
from ...tests._checkpoint_seeding import real_checkpoint
from ..checkpoints import Checkpointer, open_checkpointer

if TYPE_CHECKING:
    from pathlib import Path


def _table_names(db_file: Path) -> set[str]:
    connection = sqlite3.connect(str(db_file))
    try:
        return {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    finally:
        connection.close()


async def _write_one_checkpoint(saver: Checkpointer, thread_id: str) -> None:
    checkpoint = await real_checkpoint()
    checkpoint["id"] = f"cp-{uuid4().hex}"
    await saver.aput(
        cast("Any", {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}),
        checkpoint,
        cast("Any", {"source": "loop", "step": 1, "parents": {}}),
        checkpoint["channel_versions"],
    )


@pytest.mark.asyncio
async def test_an_armed_boot_never_creates_the_checkpoint_tables(
    tmp_path: Path,
) -> None:
    """An unmigrated store must stay unmigrated, and the write must fail loud.

    This is the whole point of the armed profile: a store the migration
    entrypoint has not brought forward is refused, not repaired in passing by
    whichever process happened to open it.
    """
    db_file = tmp_path / "checkpoints.sqlite"
    db_file.touch()

    with (
        armed_desktop_app_home(tmp_path / "app-home"),
        settings_override(
            checkpoint_backend="sqlite",
            checkpoint_database_url=f"sqlite+aiosqlite:///{db_file}",
        ),
    ):
        async with open_checkpointer() as checkpointer:
            assert isinstance(checkpointer, AsyncSqliteSaver)

            with pytest.raises(sqlite3.OperationalError, match="no such table"):
                await _write_one_checkpoint(checkpointer, f"armed-{uuid4().hex}")

    assert "checkpoints" not in _table_names(db_file)
    assert "writes" not in _table_names(db_file)


@pytest.mark.asyncio
async def test_an_unarmed_boot_still_creates_the_checkpoint_tables(
    tmp_path: Path,
) -> None:
    """The ordinary profile owns its own schema and must keep creating it.

    The guard above must be the armed profile's, not a new refusal for every
    deployment: development and server boots have no separate migration step
    for the checkpoint store.
    """
    db_file = tmp_path / "checkpoints.sqlite"

    with settings_override(
        checkpoint_backend="sqlite",
        checkpoint_database_url=f"sqlite+aiosqlite:///{db_file}",
    ):
        async with open_checkpointer() as checkpointer:
            thread_id = f"unarmed-{uuid4().hex}"
            await _write_one_checkpoint(checkpointer, thread_id)
            stored = await checkpointer.aget_tuple(
                cast("Any", {"configurable": {"thread_id": thread_id}})
            )

    assert stored is not None
    assert {"checkpoints", "writes"} <= _table_names(db_file)

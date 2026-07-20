"""Real LangGraph checkpoint tests for the SDD state migration."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest
from langgraph.checkpoint.base import empty_checkpoint
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from ..checkpoint_schema import (
    install_checkpoint_schema_identity,
    validate_checkpoint_schema_identity,
)
from ..migrations import (
    CheckpointStateMigrationError,
    backfill_teamstate_sdd_fields,
    count_pending_sdd_backfill,
)

if TYPE_CHECKING:
    from pathlib import Path

    from langchain_core.runnables import RunnableConfig


async def _write_legacy_checkpoint(path: Path) -> RunnableConfig:
    checkpoint = empty_checkpoint()
    checkpoint["channel_values"] = {"messages": []}
    config: RunnableConfig = {
        "configurable": {
            "thread_id": "legacy-thread",
            "checkpoint_ns": "",
        }
    }
    async with AsyncSqliteSaver.from_conn_string(str(path)) as checkpointer:
        return await checkpointer.aput(config, checkpoint, {}, {})


async def _write_start_staging_checkpoint(path: Path) -> RunnableConfig:
    checkpoint = empty_checkpoint()
    checkpoint["channel_values"] = {"__start__": {"messages": []}}
    config: RunnableConfig = {
        "configurable": {
            "thread_id": "start-staging-thread",
            "checkpoint_ns": "",
        }
    }
    async with AsyncSqliteSaver.from_conn_string(str(path)) as checkpointer:
        return await checkpointer.aput(config, checkpoint, {}, {})


@pytest.mark.asyncio
async def test_real_serialized_checkpoint_is_backfilled_before_stamp(
    tmp_path: Path,
) -> None:
    checkpoint_path = tmp_path / "checkpoints.db"
    config = await _write_legacy_checkpoint(checkpoint_path)

    assert count_pending_sdd_backfill(checkpoint_path) == 1
    assert backfill_teamstate_sdd_fields(checkpoint_path) == 1
    assert count_pending_sdd_backfill(checkpoint_path) == 0

    install_checkpoint_schema_identity(checkpoint_path)
    validate_checkpoint_schema_identity(checkpoint_path)

    async with AsyncSqliteSaver.from_conn_string(str(checkpoint_path)) as checkpointer:
        stored = await checkpointer.aget_tuple(config)
    assert stored is not None
    channel_values = stored.checkpoint["channel_values"]
    assert channel_values["messages"] == []
    assert channel_values["active_feature"] is None
    assert channel_values["pipeline_phase"] is None
    assert channel_values["vault_index"] == {}
    assert channel_values["validation_errors"] == []


@pytest.mark.asyncio
async def test_langgraph_start_staging_checkpoint_is_not_teamstate_drift(
    tmp_path: Path,
) -> None:
    checkpoint_path = tmp_path / "checkpoints.db"
    await _write_start_staging_checkpoint(checkpoint_path)

    assert count_pending_sdd_backfill(checkpoint_path) == 0
    assert backfill_teamstate_sdd_fields(checkpoint_path) == 0


@pytest.mark.asyncio
async def test_unreadable_serialized_checkpoint_fails_loud(tmp_path: Path) -> None:
    checkpoint_path = tmp_path / "checkpoints.db"
    await _write_legacy_checkpoint(checkpoint_path)

    connection = sqlite3.connect(str(checkpoint_path))
    try:
        connection.execute(
            "UPDATE checkpoints SET type = 'foreign', checkpoint = X'00'"
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(CheckpointStateMigrationError, match="unreadable"):
        count_pending_sdd_backfill(checkpoint_path)
    with pytest.raises(CheckpointStateMigrationError, match="unreadable"):
        backfill_teamstate_sdd_fields(checkpoint_path)

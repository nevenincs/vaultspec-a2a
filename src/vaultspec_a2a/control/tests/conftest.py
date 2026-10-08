"""Test configuration for control-plane tests."""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

import pytest_asyncio

if TYPE_CHECKING:
    from pathlib import Path

    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from ._continuation import BusyRun

# Warm the graph package before any control test module imports
# ``control.thread_service``. That module imports ``context.metadata`` first,
# which triggers a latent ``context -> thread -> graph -> nodes -> supervisor ->
# context`` import cycle when it is the first vaultspec import in a fresh
# interpreter; importing ``graph`` up front resolves ``context.token_budget``
# fully so the later import finds it cached. (Source-level fix for the cycle is
# graph-domain work tracked outside this test package.)
importlib.import_module("vaultspec_a2a.graph")


@pytest_asyncio.fixture
async def busy_run(
    tmp_path: Path,
    migrated_session_factory: async_sessionmaker[AsyncSession],
    checkpointer: AsyncSqliteSaver,
) -> BusyRun:
    """One real run mid-first-turn, in the root migrated store and checkpointer."""
    from ._continuation import start_busy_run

    return await start_busy_run(migrated_session_factory, checkpointer, tmp_path)

"""Thread-state assembly regressions for checkpoint failure handling."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from vaultspec_a2a.control.thread_state_service import build_thread_state
from vaultspec_a2a.database import create_thread
from vaultspec_a2a.database.models import Base
from vaultspec_a2a.streaming.aggregator import EventAggregator


@pytest.mark.asyncio
async def test_checkpoint_failure_updates_execution_readiness_with_repair_status() -> (
    None
):
    """Checkpoint read failures must not leave stale readiness on the snapshot."""
    case_dir = (
        Path.home()
        / ".codex"
        / "memories"
        / "tmp"
        / "thread-state-service-db"
        / uuid4().hex
    )
    case_dir.mkdir(parents=True, exist_ok=True)
    db_file = case_dir / "test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    checkpoints_file = case_dir / "checkpoints.db"
    async with AsyncSqliteSaver.from_conn_string(str(checkpoints_file)) as checkpointer:
        pass

    async with session_factory() as session:
        await create_thread(
            session,
            thread_id="thread-closed-checkpointer",
            repair_status="healthy",
            execution_readiness="healthy",
        )
        await session.commit()

    async with session_factory() as session:
        snapshot = await build_thread_state(
            session,
            thread_id="thread-closed-checkpointer",
            aggregator=EventAggregator(),
            checkpointer=checkpointer,
        )

    assert snapshot is not None
    assert snapshot.snapshot_complete is False
    assert snapshot.repair_status == "checkpoint_unavailable"
    assert snapshot.execution_readiness == "checkpoint_unavailable"
    assert snapshot.replay_status == "unknown"
    assert "checkpoint_unavailable" in snapshot.degraded_reasons

    await engine.dispose()

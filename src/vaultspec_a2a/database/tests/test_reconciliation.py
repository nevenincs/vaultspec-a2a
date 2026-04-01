"""Database-backed startup reconciliation tests with a real checkpointer."""

from __future__ import annotations

import pytest
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from vaultspec_a2a.database import (
    create_thread,
    get_thread,
    record_permission_request,
)
from vaultspec_a2a.database.models import Base
from vaultspec_a2a.database.reconciliation import reconcile_threads_on_startup


@pytest.mark.asyncio
async def test_pending_permission_without_checkpoint_is_not_marked_resumable(
    runtime_dir,
) -> None:
    """Missing checkpoint truth must win over a surviving permission row."""
    db_file = runtime_dir / "reconciliation.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    checkpoints_file = runtime_dir / "checkpoints.db"

    async with AsyncSqliteSaver.from_conn_string(str(checkpoints_file)) as checkpointer:
        async with session_factory() as session:
            thread = await create_thread(session, thread_id="thread-missing-checkpoint")
            await record_permission_request(
                session,
                request_id=f"{thread.id}:perm-1",
                thread_id=thread.id,
                pause_reason_type="bash",
                description="Allow action?",
                allowed_options=[
                    {
                        "option_id": "allow_once",
                        "name": "Allow once",
                        "kind": "allow_once",
                    }
                ],
                tool_call="bash",
            )
            await session.commit()

        async with session_factory() as session:
            summary = await reconcile_threads_on_startup(session, checkpointer)
            await session.commit()
            repaired = await get_thread(session, "thread-missing-checkpoint")

    assert summary["paused_resumable"] == 0
    assert summary["checkpoint_unavailable"] == 1
    assert repaired is not None
    assert repaired.status == "repair_needed"
    assert repaired.repair_status == "checkpoint_unavailable"
    assert repaired.execution_readiness == "checkpoint_unavailable"
    assert repaired.recovery_epoch == 1
    assert repaired.repair_generation == 1

    await engine.dispose()

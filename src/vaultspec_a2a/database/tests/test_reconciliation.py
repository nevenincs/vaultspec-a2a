"""Database-backed startup reconciliation tests with a real checkpointer."""

from __future__ import annotations

from pathlib import Path

import pytest
from langgraph.checkpoint.base import empty_checkpoint
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ...conftest import materialize_schema
from ...database import (
    create_thread,
    get_thread,
    record_permission_request,
    record_permission_response_submission,
)
from ...database.reconciliation import reconcile_threads_on_startup


@pytest.mark.asyncio
async def test_pending_permission_without_checkpoint_is_not_marked_resumable(
    runtime_dir,
) -> None:
    """Missing checkpoint truth must win over a surviving permission row."""
    db_file = runtime_dir / "reconciliation.db"
    materialize_schema(Path(db_file))
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
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


@pytest.mark.asyncio
async def test_cancelling_without_checkpoint_is_not_marked_cancel_pending(
    runtime_dir,
) -> None:
    """Missing checkpoint truth must beat a surviving cancelling status."""
    db_file = runtime_dir / "reconciliation-cancelling.db"
    materialize_schema(Path(db_file))
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    checkpoints_file = runtime_dir / "checkpoints-cancelling.db"

    async with AsyncSqliteSaver.from_conn_string(str(checkpoints_file)) as checkpointer:
        async with session_factory() as session:
            await create_thread(
                session,
                thread_id="thread-cancelling-missing-checkpoint",
                status="cancelling",
            )
            await session.commit()

        async with session_factory() as session:
            summary = await reconcile_threads_on_startup(session, checkpointer)
            await session.commit()
            repaired = await get_thread(
                session,
                "thread-cancelling-missing-checkpoint",
            )

    assert summary["paused_resumable"] == 0
    assert summary["checkpoint_unavailable"] == 1
    assert repaired is not None
    assert repaired.status == "repair_needed"
    assert repaired.repair_status == "checkpoint_unavailable"
    assert repaired.execution_readiness == "checkpoint_unavailable"
    assert repaired.recovery_epoch == 1
    assert repaired.repair_generation == 1

    await engine.dispose()


@pytest.mark.asyncio
async def test_deleting_thread_with_pending_permission_is_never_swept(
    runtime_dir,
) -> None:
    """A thread mid-teardown must stay invisible to startup reconciliation.

    ``DELETING`` is a lifecycle sink with no valid outbound transition
    (``thread.transitions``), set out of band by the deletion saga alone. Before
    ``list_non_terminal_threads`` excluded it explicitly, this exact shape - a
    pending permission survives restart AND its checkpoint is available, the
    one branch that assigns a new thread status - would have driven
    ``update_thread_status`` to request ``DELETING -> input_required`` and raise
    ``InvalidTransitionError`` out of startup reconciliation.
    """
    db_file = runtime_dir / "reconciliation-deleting.db"
    materialize_schema(Path(db_file))
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    checkpoints_file = runtime_dir / "checkpoints-deleting.db"
    thread_id = "thread-deleting-pending-permission"

    async with AsyncSqliteSaver.from_conn_string(str(checkpoints_file)) as checkpointer:
        await checkpointer.setup()
        checkpoint = empty_checkpoint()
        checkpoint["id"] = "cp-deleting-pending-permission"
        await checkpointer.aput(
            {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}},
            checkpoint,
            {"source": "loop", "step": 1, "parents": {}},
            {},
        )

        async with session_factory() as session:
            await create_thread(session, thread_id=thread_id, status="deleting")
            await record_permission_request(
                session,
                request_id=f"{thread_id}:perm-1",
                thread_id=thread_id,
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
            unswept = await get_thread(session, thread_id)

    assert summary["repair_backlog"] == 0
    assert summary["paused_resumable"] == 0
    assert unswept is not None
    assert unswept.status == "deleting"
    assert unswept.repair_status == "healthy"
    assert unswept.execution_readiness == "healthy"
    assert unswept.recovery_epoch == 0

    await engine.dispose()


@pytest.mark.asyncio
async def test_answered_pending_apply_with_checkpoint_is_not_marked_resumable(
    runtime_dir,
) -> None:
    """Answered-not-applied rows must not be treated as user-paused on restart."""
    db_file = runtime_dir / "reconciliation-answered-pending-apply.db"
    materialize_schema(Path(db_file))
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    checkpoints_file = runtime_dir / "checkpoints-answered-pending-apply.db"

    async with AsyncSqliteSaver.from_conn_string(str(checkpoints_file)) as checkpointer:
        await checkpointer.setup()
        checkpoint = empty_checkpoint()
        checkpoint["id"] = "cp-answered-pending-apply"
        await checkpointer.aput(
            {
                "configurable": {
                    "thread_id": "thread-answered-pending-apply-reconcile",
                    "checkpoint_ns": "",
                }
            },
            checkpoint,
            {"source": "loop", "step": 1, "parents": {}},
            {},
        )

        async with session_factory() as session:
            thread = await create_thread(
                session,
                thread_id="thread-answered-pending-apply-reconcile",
                status="running",
            )
            await record_permission_request(
                session,
                request_id=f"{thread.id}:perm-1",
                thread_id=thread.id,
                pause_reason_type="plan_approval_request",
                description="Approve plan?",
                allowed_options=[{"option_id": "approve", "name": "Approve"}],
                tool_call=None,
            )
            await record_permission_response_submission(
                session,
                request_id=f"{thread.id}:perm-1",
                option_id="approve",
                idempotency_key="idem-reconcile-answered-pending-apply",
            )
            await session.commit()

        async with session_factory() as session:
            summary = await reconcile_threads_on_startup(session, checkpointer)
            await session.commit()
            repaired = await get_thread(
                session,
                "thread-answered-pending-apply-reconcile",
            )

    assert summary["paused_resumable"] == 0
    assert repaired is not None
    assert repaired.status == "reconciling"
    assert repaired.repair_status == "needs_reconciliation"
    assert repaired.execution_readiness == "needs_reconciliation"
    assert repaired.recovery_epoch == 1
    assert repaired.repair_generation == 1

    await engine.dispose()

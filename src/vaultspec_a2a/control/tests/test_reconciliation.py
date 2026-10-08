"""Database-backed startup reconciliation tests with a real checkpointer."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ...database import (
    create_thread,
    get_thread,
    record_permission_request,
    record_permission_response_submission,
)
from ...testing import (
    current_execution_metadata,
    park_clarification,
    seed_accepted_thread,
    seed_create_action,
)
from ...tests._checkpoint_seeding import real_checkpoint
from ...tests._write_authority import make_test_write_authority
from ..reconciliation import reconcile_threads_on_startup

if TYPE_CHECKING:
    from pathlib import Path

    from langchain_core.runnables import RunnableConfig
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.mark.asyncio
async def test_a_park_whose_nudge_died_with_its_process_is_re_projected(
    tmp_path: Path,
    session_factory: async_sessionmaker[AsyncSession],
    checkpointer: AsyncSqliteSaver,
) -> None:
    """Startup reads the pause off the checkpoint before reconciling against it.

    The relayed nudge that records a pause is in-process state: a gateway that
    dies between the park and the nudge leaves a parked run reading ``running``.
    Checkpoint reconciliation reads that as a writer that died and elects
    ``reconciling``, after which the re-dispatch sweep sends the run's accepted
    work to a worker again - while a human is still answering its question. The
    pause is therefore re-projected first, and a run that reads
    ``input_required`` is left alone.
    """
    async with session_factory() as session:
        thread_id, _receipt = await seed_accepted_thread(
            session, status="running", workspace=tmp_path
        )
        await session.commit()
    # A real interrupt from the real clarification nodes, over the real store.
    await park_clarification(checkpointer, thread_id=thread_id)

    async with session_factory() as session:
        summary = await reconcile_threads_on_startup(session, checkpointer)
        await session.commit()
        reprojected = await get_thread(session, thread_id)

    assert reprojected is not None
    assert reprojected.status == "input_required", reprojected.status
    assert summary["paused_resumable"] == 1, summary
    # Not held for repair either: there is nothing wrong with a run whose
    # checkpoint says it is waiting for an answer.
    assert reprojected.repair_status == "healthy", reprojected.repair_status
    assert reprojected.execution_readiness == "healthy"
    # And not boot damage: a run waiting on a human is nobody's repair backlog,
    # so a boot that found one found nothing to look at.
    assert summary["repair_backlog"] == 0, summary


@pytest.mark.asyncio
async def test_pending_permission_without_checkpoint_is_not_marked_resumable(
    tmp_path: Path,
    session_factory: async_sessionmaker[AsyncSession],
    checkpointer: AsyncSqliteSaver,
) -> None:
    """Missing checkpoint truth must win over a surviving permission row."""
    async with session_factory() as session:
        thread = await create_thread(
            session,
            write_authority=make_test_write_authority(),
            thread_id="thread-missing-checkpoint",
            metadata=current_execution_metadata(tmp_path),
        )
        await seed_create_action(session, thread.id, workspace=tmp_path)
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
    assert summary["checkpoint_unavailable"] == 0
    assert repaired is not None
    assert repaired.status == "reconciling"
    assert repaired.repair_status == "needs_reconciliation"
    assert repaired.execution_readiness == "needs_reconciliation"
    assert repaired.repair_reason == "checkpoint_absent"


@pytest.mark.asyncio
async def test_cancelling_without_checkpoint_is_not_marked_cancel_pending(
    tmp_path: Path,
    session_factory: async_sessionmaker[AsyncSession],
    checkpointer: AsyncSqliteSaver,
) -> None:
    """Missing checkpoint truth must beat a surviving cancelling status."""
    async with session_factory() as session:
        thread = await create_thread(
            session,
            write_authority=make_test_write_authority(),
            thread_id="thread-cancelling-missing-checkpoint",
            status="cancelling",
            metadata=current_execution_metadata(tmp_path),
        )
        await seed_create_action(session, thread.id, workspace=tmp_path)
        await session.commit()

    async with session_factory() as session:
        summary = await reconcile_threads_on_startup(session, checkpointer)
        await session.commit()
        repaired = await get_thread(
            session,
            "thread-cancelling-missing-checkpoint",
        )

    assert summary["paused_resumable"] == 0
    assert summary["checkpoint_unavailable"] == 0
    assert repaired is not None
    assert repaired.status == "reconciling"
    assert repaired.repair_status == "needs_reconciliation"
    assert repaired.execution_readiness == "needs_reconciliation"
    assert repaired.repair_reason == "checkpoint_absent"


@pytest.mark.asyncio
async def test_deleting_thread_with_pending_permission_is_never_swept(
    session_factory: async_sessionmaker[AsyncSession],
    checkpointer: AsyncSqliteSaver,
) -> None:
    """A thread mid-teardown must stay invisible to startup reconciliation.

    ``DELETING`` is a lifecycle sink with no valid outbound transition
    (``thread.transitions``), set out of band by the deletion saga alone. Before
    ``list_non_terminal_threads`` excluded it explicitly, this exact shape - a
    pending permission survives restart AND its checkpoint is available, the
    one branch that assigns a new thread status - would have driven a status
    election to request ``DELETING -> input_required`` and raise
    ``InvalidTransitionError`` out of startup reconciliation.
    """
    thread_id = "thread-deleting-pending-permission"

    config: RunnableConfig = {
        "configurable": {"thread_id": thread_id, "checkpoint_ns": ""}
    }
    checkpoint = await real_checkpoint()
    checkpoint["id"] = "cp-deleting-pending-permission"
    await checkpointer.aput(
        config,
        checkpoint,
        {"source": "loop", "step": 1, "parents": {}},
        {},
    )

    async with session_factory() as session:
        await create_thread(
            session,
            write_authority=make_test_write_authority(),
            thread_id=thread_id,
            status="deleting",
        )
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


@pytest.mark.asyncio
async def test_answered_pending_apply_with_checkpoint_is_not_marked_resumable(
    tmp_path: Path,
    session_factory: async_sessionmaker[AsyncSession],
    checkpointer: AsyncSqliteSaver,
) -> None:
    """Answered-not-applied rows must not be treated as user-paused on restart."""

    config: RunnableConfig = {
        "configurable": {
            "thread_id": "thread-answered-pending-apply-reconcile",
            "checkpoint_ns": "",
        }
    }
    checkpoint = await real_checkpoint()
    checkpoint["id"] = "cp-answered-pending-apply"
    await checkpointer.aput(
        config,
        checkpoint,
        {"source": "loop", "step": 1, "parents": {}},
        {},
    )

    async with session_factory() as session:
        thread = await create_thread(
            session,
            write_authority=make_test_write_authority(),
            thread_id="thread-answered-pending-apply-reconcile",
            status="running",
            metadata=current_execution_metadata(tmp_path),
        )
        await seed_create_action(session, thread.id, workspace=tmp_path)
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
            session, request_id=f"{thread.id}:perm-1"
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

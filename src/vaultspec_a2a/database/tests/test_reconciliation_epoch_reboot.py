"""Repeated startup reconciliation preserves exact graph authority.

Current recovery uses the accepted graph action and checkpoint evidence. An
unfinished checkpoint leaves the run reconciling without appending a repair
journal row, so a second boot and historical repair key stay harmless.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from ...control.reconciliation import reconcile_threads_on_startup
from ...database import (
    create_thread,
    get_thread,
    record_permission_request,
)
from ...testing import current_execution_metadata, seed_create_action
from ...tests._checkpoint_seeding import real_checkpoint
from ...tests._write_authority import make_test_write_authority
from ...thread.enums import ControlActionType
from ..control_action_repository import (
    create_control_action,
    get_control_action_by_idempotency_key,
    get_or_create_control_action,
)

if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def _seed_paused_thread(session: AsyncSession, tid: str) -> None:
    thread = await create_thread(
        session,
        write_authority=make_test_write_authority(),
        thread_id=tid,
        status="running",
        metadata=current_execution_metadata(Path.cwd()),
    )
    await seed_create_action(session, tid, workspace=Path.cwd())
    await record_permission_request(
        session,
        request_id=f"{thread.id}:perm-1",
        thread_id=thread.id,
        pause_reason_type="bash",
        description="Allow action?",
        allowed_options=[
            {"option_id": "allow_once", "name": "Allow once", "kind": "allow_once"}
        ],
        tool_call="bash",
    )


async def _put_checkpoint(checkpointer: AsyncSqliteSaver, tid: str) -> None:
    await checkpointer.setup()
    config: RunnableConfig = {"configurable": {"thread_id": tid, "checkpoint_ns": ""}}
    checkpoint = await real_checkpoint()
    checkpoint["id"] = f"cp-{tid}"
    await checkpointer.aput(
        config,
        checkpoint,
        {"source": "loop", "step": 1, "parents": {}},
        {},
    )


@pytest.mark.asyncio
async def test_unfinished_graph_survives_reboot_without_repair_journal_growth(
    session_factory: async_sessionmaker[AsyncSession],
    checkpointer: AsyncSqliteSaver,
) -> None:
    """Repeated recovery leaves the accepted graph action unchanged."""
    tid = "thread-paused-reboot"

    await _put_checkpoint(checkpointer, tid)
    async with session_factory() as session:
        await _seed_paused_thread(session, tid)
        await session.commit()

    # Boot 1: first reconciliation.
    async with session_factory() as session:
        summary1 = await reconcile_threads_on_startup(session, checkpointer)
        await session.commit()
        after1 = await get_thread(session, tid)
        started1 = await get_control_action_by_idempotency_key(
            session, thread_id=tid, idempotency_key=f"startup-repair:{tid}:1"
        )
    assert summary1["paused_resumable"] == 0
    assert after1 is not None
    assert after1.status == "reconciling"
    assert after1.repair_status == "needs_reconciliation"
    assert after1.recovery_epoch == 0
    assert started1 is None

    # Boot 2: a reboot must not crash with an IntegrityError.
    async with session_factory() as session:
        summary2 = await reconcile_threads_on_startup(session, checkpointer)
        await session.commit()
        after2 = await get_thread(session, tid)
        started2 = await get_control_action_by_idempotency_key(
            session, thread_id=tid, idempotency_key=f"startup-repair:{tid}:2"
        )

    assert summary2["paused_resumable"] == 0
    assert after2 is not None
    assert after2.repair_status == "needs_reconciliation"
    assert after2.recovery_epoch == 0
    assert started2 is None


@pytest.mark.asyncio
async def test_historical_repair_row_does_not_crash_graph_recovery(
    session_factory: async_sessionmaker[AsyncSession],
    checkpointer: AsyncSqliteSaver,
) -> None:
    """A historical repair row does not collide with current recovery."""
    tid = "thread-historical-stuck"

    await _put_checkpoint(checkpointer, tid)
    async with session_factory() as session:
        await _seed_paused_thread(session, tid)
        # Simulate the pre-fix crash state: the repair action was journaled at
        # epoch key :1 but the epoch never advanced (still 0 on the thread row).
        await create_control_action(
            session,
            thread_id=tid,
            action_type=ControlActionType.REPAIR_STARTED,
            idempotency_key=f"startup-repair:{tid}:1",
            payload={"status": "input_required"},
        )
        await session.commit()

    # Boot: must not raise IntegrityError; the duplicate key replays as a no-op.
    async with session_factory() as session:
        summary = await reconcile_threads_on_startup(session, checkpointer)
        await session.commit()
        healed = await get_thread(session, tid)

    assert summary["paused_resumable"] == 0
    assert healed is not None
    assert healed.status == "reconciling"
    assert healed.recovery_epoch == 0


@pytest.mark.asyncio
async def test_get_or_create_control_action_is_idempotent_across_sessions(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Two separate sessions requesting the same key yield one row, no duplicate.

    The atomic get-or-create must return the already-committed row on the second
    call (``created=False``) rather than inserting a duplicate that would violate the
    UNIQUE constraint - the guarantee its name makes under concurrent boots.
    """
    tid = "thread-idempotent-key"
    key = f"startup-repair:{tid}:1"

    async with session_factory() as session:
        await create_thread(
            session,
            write_authority=make_test_write_authority(),
            thread_id=tid,
            status="running",
        )
        await session.commit()

    async with session_factory() as session_a:
        row_a, created_a = await get_or_create_control_action(
            session_a,
            thread_id=tid,
            action_type=ControlActionType.REPAIR_STARTED,
            idempotency_key=key,
        )
        await session_a.commit()

    async with session_factory() as session_b:
        row_b, created_b = await get_or_create_control_action(
            session_b,
            thread_id=tid,
            action_type=ControlActionType.REPAIR_STARTED,
            idempotency_key=key,
        )
        await session_b.commit()

    assert created_a is True
    assert created_b is False
    assert row_a.id == row_b.id

    # Exactly one journal row exists for the key.
    async with session_factory() as session:
        found = await get_control_action_by_idempotency_key(
            session, thread_id=tid, idempotency_key=key
        )
    assert found is not None
    assert found.id == row_a.id

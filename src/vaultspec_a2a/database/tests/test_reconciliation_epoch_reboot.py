"""Repeated startup reconciliation preserves exact graph authority.

Current recovery uses the accepted graph action and checkpoint evidence. An
unfinished checkpoint leaves the run reconciling without appending a repair
journal row, so a second boot and historical repair key stay harmless.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from langgraph.checkpoint.base import empty_checkpoint
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ...conftest import materialize_schema
from ...control.tests._catalog_authority import current_execution_metadata
from ...control.tests.test_dispatch_failure_transitions import (
    _seed_accepted_initial_action,
)
from ...database import (
    create_thread,
    get_thread,
    record_permission_request,
)
from ...database.permission_repository import (
    create_control_action,
    get_control_action_by_idempotency_key,
    get_or_create_control_action,
)
from ...database.reconciliation import reconcile_threads_on_startup
from ...tests._write_authority import make_test_write_authority
from ...thread.enums import ControlActionType


async def _seed_paused_thread(session: AsyncSession, tid: str) -> None:
    thread = await create_thread(
        session,
        write_authority=make_test_write_authority(),
        thread_id=tid,
        status="running",
        metadata=current_execution_metadata(Path.cwd()),
    )
    await _seed_accepted_initial_action(session, tid, workspace=Path.cwd())
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
    checkpoint = empty_checkpoint()
    checkpoint["id"] = f"cp-{tid}"
    await checkpointer.aput(
        {"configurable": {"thread_id": tid, "checkpoint_ns": ""}},
        checkpoint,
        {"source": "loop", "step": 1, "parents": {}},
        {},
    )


@pytest.mark.asyncio
async def test_unfinished_graph_survives_reboot_without_repair_journal_growth(
    runtime_dir: Path,
) -> None:
    """Repeated recovery leaves the accepted graph action unchanged."""
    tid = "thread-paused-reboot"
    db_file = runtime_dir / "reconciliation-reboot.db"
    materialize_schema(Path(db_file))
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    checkpoints_file = runtime_dir / "checkpoints-reboot.db"

    async with AsyncSqliteSaver.from_conn_string(str(checkpoints_file)) as checkpointer:
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

        # Boot 2: the reboot that used to crash with an IntegrityError.
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

    await engine.dispose()


@pytest.mark.asyncio
async def test_historical_repair_row_does_not_crash_graph_recovery(
    runtime_dir: Path,
) -> None:
    """A historical repair row does not collide with current recovery."""
    tid = "thread-historical-stuck"
    db_file = runtime_dir / "reconciliation-historical.db"
    materialize_schema(Path(db_file))
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    checkpoints_file = runtime_dir / "checkpoints-historical.db"

    async with AsyncSqliteSaver.from_conn_string(str(checkpoints_file)) as checkpointer:
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

    await engine.dispose()


@pytest.mark.asyncio
async def test_get_or_create_control_action_is_idempotent_across_sessions(
    runtime_dir: Path,
) -> None:
    """Two separate sessions requesting the same key yield one row, no duplicate.

    The atomic get-or-create must return the already-committed row on the second
    call (``created=False``) rather than inserting a duplicate that would violate the
    UNIQUE constraint - the guarantee its name makes under concurrent boots.
    """
    tid = "thread-idempotent-key"
    key = f"startup-repair:{tid}:1"
    db_file = runtime_dir / "reconciliation-idempotent.db"
    materialize_schema(Path(db_file))
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

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

    await engine.dispose()

"""Boot-reboot reconciliation over a paused_resumable thread — the epoch bug.

Real SQLite database and a real langgraph checkpointer, no mocks. Pins the fix
for the crash where a paused_resumable repair never advanced ``recovery_epoch``:
the second boot re-derived the same ``startup-repair:{tid}:{epoch}`` idempotency
key and the control_actions INSERT died on the UNIQUE constraint, taking the whole
app down. The epoch must now advance every applied outcome, and a duplicate
idempotency key must replay as a no-op rather than crash - so both freshly-written
and pre-fix historical rows survive a reboot.
"""

from __future__ import annotations

import pytest
from langgraph.checkpoint.base import empty_checkpoint
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from vaultspec_a2a.database import (
    create_thread,
    get_thread,
    record_permission_request,
)
from vaultspec_a2a.database.models import Base
from vaultspec_a2a.database.permission_repository import (
    create_control_action,
    get_control_action_by_idempotency_key,
    get_or_create_control_action,
)
from vaultspec_a2a.database.reconciliation import reconcile_threads_on_startup
from vaultspec_a2a.thread.enums import ControlActionType


async def _seed_paused_thread(session: AsyncSession, tid: str) -> None:
    thread = await create_thread(session, thread_id=tid, status="running")
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
async def test_paused_resumable_survives_reboot_and_advances_epoch(runtime_dir) -> None:
    """A paused_resumable thread reconciled twice must not crash on the 2nd boot."""
    tid = "thread-paused-reboot"
    db_file = runtime_dir / "reconciliation-reboot.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
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
        assert summary1["paused_resumable"] == 1
        assert after1 is not None
        assert after1.repair_status == "paused_resumable"
        assert after1.recovery_epoch == 1
        assert started1 is not None

        # Boot 2: the reboot that used to crash with an IntegrityError.
        async with session_factory() as session:
            summary2 = await reconcile_threads_on_startup(session, checkpointer)
            await session.commit()
            after2 = await get_thread(session, tid)
            started2 = await get_control_action_by_idempotency_key(
                session, thread_id=tid, idempotency_key=f"startup-repair:{tid}:2"
            )

    assert summary2["paused_resumable"] == 1
    assert after2 is not None
    assert after2.repair_status == "paused_resumable"
    # Epoch advanced again — the second boot derived a fresh idempotency key.
    assert after2.recovery_epoch == 2
    assert started2 is not None

    await engine.dispose()


@pytest.mark.asyncio
async def test_historical_stuck_row_self_heals_without_crashing(runtime_dir) -> None:
    """A pre-fix row (epoch 0 with startup-repair:{tid}:1 already journaled) must
    replay as a no-op and advance, not crash the boot."""
    tid = "thread-historical-stuck"
    db_file = runtime_dir / "reconciliation-historical.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
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

    assert summary["paused_resumable"] == 1
    assert healed is not None
    # The stuck epoch advanced, so the NEXT boot will derive a fresh, uncollided key.
    assert healed.recovery_epoch == 1

    await engine.dispose()


@pytest.mark.asyncio
async def test_get_or_create_control_action_is_idempotent_across_sessions(
    runtime_dir,
) -> None:
    """Two separate sessions requesting the same key yield one row, no duplicate.

    The atomic get-or-create must return the already-committed row on the second
    call (``created=False``) rather than inserting a duplicate that would violate the
    UNIQUE constraint - the guarantee its name makes under concurrent boots.
    """
    tid = "thread-idempotent-key"
    key = f"startup-repair:{tid}:1"
    db_file = runtime_dir / "reconciliation-idempotent.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with session_factory() as session:
        await create_thread(session, thread_id=tid, status="running")
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

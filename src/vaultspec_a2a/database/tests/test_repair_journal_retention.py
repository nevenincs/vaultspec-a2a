"""Repair-journal pruning preserves every recoverable action.

Current graph recovery does not append repair pairs on each boot. Historical
pairs can still be pruned; the repository primitive must retain a whole pair
and leave every non-repair action intact.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from langgraph.checkpoint.base import empty_checkpoint
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ...conftest import materialize_schema
from ...database import create_thread
from ...database.models import ControlActionModel
from ...database.permission_repository import (
    create_control_action,
    get_control_action_by_dispatch_id,
    get_control_action_by_idempotency_key,
    get_latest_control_action,
    prune_repair_journal,
)
from ...database.reconciliation import reconcile_threads_on_startup
from ...tests._write_authority import make_test_write_authority
from ...thread.enums import ControlActionResultStatus, ControlActionType

_REPAIR_TYPES = (
    ControlActionType.REPAIR_STARTED.value,
    ControlActionType.REPAIR_FINISHED.value,
)

# One unapplied row per class a recovery path scans for, plus the settled row an
# idempotent replay reads back. Every one of these must outlive any number of
# capped boots.
_CLARIFICATION_KEY = "clarification-response:req-clarify-1"
_PERMISSION_KEY = "permission-response:req-perm-1"


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


async def _seed_recoverable_actions(session: AsyncSession, tid: str) -> None:
    """Journal the rows a crash would need to redrive, all still unapplied."""
    await create_control_action(
        session,
        thread_id=tid,
        action_type=ControlActionType.CANCEL,
        idempotency_key=f"cancel:{tid}",
        payload={"reason": "operator"},
        dispatch_id="dispatch-cancel-1",
        recovery_deadline_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    await create_control_action(
        session,
        thread_id=tid,
        action_type=ControlActionType.MESSAGE_FOLLOWUP_REQUESTED,
        idempotency_key=f"followup:{tid}",
        payload={"message": "carry on"},
        dispatch_id="dispatch-followup-1",
        recovery_deadline_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    await create_control_action(
        session,
        thread_id=tid,
        action_type=ControlActionType.PERMISSION_RESPONSE_SUBMITTED,
        request_id="req-perm-1",
        idempotency_key=_PERMISSION_KEY,
        payload={"option_id": "allow_once"},
        dispatch_id="dispatch-permission-1",
        recovery_deadline_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    await create_control_action(
        session,
        thread_id=tid,
        action_type=ControlActionType.RESUME,
        request_id="req-clarify-1",
        idempotency_key=_CLARIFICATION_KEY,
        payload={"answers": [{"question_id": "q1", "option_id": "a"}]},
        dispatch_id="dispatch-clarification-1",
        recovery_deadline_at=datetime.now(UTC) + timedelta(minutes=5),
    )


async def _journal_inventory(
    session: AsyncSession, tid: str
) -> dict[str, tuple[str, str, str | None, str | None, bool]]:
    """Every non-repair row, keyed by id, in the fields recovery reads."""
    rows = (
        (
            await session.execute(
                select(ControlActionModel).where(
                    ControlActionModel.thread_id == tid,
                    ControlActionModel.action_type.notin_(_REPAIR_TYPES),
                )
            )
        )
        .scalars()
        .all()
    )
    return {
        row.id: (
            row.action_type,
            row.idempotency_key,
            row.dispatch_id,
            row.payload_json,
            row.applied_at is None,
        )
        for row in rows
    }


async def _repair_row_count(session: AsyncSession, tid: str) -> int:
    return (
        await session.execute(
            select(func.count())
            .select_from(ControlActionModel)
            .where(
                ControlActionModel.thread_id == tid,
                ControlActionModel.action_type.in_(_REPAIR_TYPES),
            )
        )
    ).scalar_one()


def _database(
    runtime_dir: Path, name: str
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    db_file = runtime_dir / f"{name}.db"
    materialize_schema(Path(db_file))
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    return engine, async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )


@pytest.mark.asyncio
async def test_capped_boots_do_not_create_repair_history(runtime_dir: Path) -> None:
    """Repeated graph recovery does not append obsolete repair pairs."""
    tid = "thread-repair-capped"
    engine, session_factory = _database(runtime_dir, "repair-retention-capped")

    async with AsyncSqliteSaver.from_conn_string(
        str(runtime_dir / "checkpoints-capped.db")
    ) as checkpointer:
        await _put_checkpoint(checkpointer, tid)
        async with session_factory() as session:
            await create_thread(
                session,
                write_authority=make_test_write_authority(),
                thread_id=tid,
                status="running",
            )
            await session.commit()

        for _ in range(12):
            async with session_factory() as session:
                await reconcile_threads_on_startup(
                    session, checkpointer, retain_repair_boots=2
                )
                await session.commit()

        async with session_factory() as session:
            capped = await _repair_row_count(session, tid)

    assert capped == 0

    await engine.dispose()


@pytest.mark.asyncio
async def test_uncapped_boots_do_not_create_repair_history(runtime_dir: Path) -> None:
    """Disabling pruning does not restore obsolete repair writes."""
    tid = "thread-repair-uncapped"
    engine, session_factory = _database(runtime_dir, "repair-retention-uncapped")

    async with AsyncSqliteSaver.from_conn_string(
        str(runtime_dir / "checkpoints-uncapped.db")
    ) as checkpointer:
        await _put_checkpoint(checkpointer, tid)
        async with session_factory() as session:
            await create_thread(
                session,
                write_authority=make_test_write_authority(),
                thread_id=tid,
                status="running",
            )
            await session.commit()

        for _ in range(12):
            async with session_factory() as session:
                await reconcile_threads_on_startup(
                    session, checkpointer, retain_repair_boots=0
                )
                await session.commit()

        async with session_factory() as session:
            uncapped = await _repair_row_count(session, tid)

    assert uncapped == 0

    await engine.dispose()


@pytest.mark.asyncio
async def test_capped_boots_leave_every_recoverable_row_intact(
    runtime_dir: Path,
) -> None:
    """The surviving set must still be sufficient to redrive after the prune.

    The assertion is deliberately an inventory identity rather than a re-check of
    two predicates: if not one non-repair row changed across twelve aggressively
    capped boots, then every scan-based recovery reader sees exactly the corpus it
    saw before, whatever its predicate. The named production readers are then
    driven on top of that to show the individual lookups still resolve.
    """
    tid = "thread-repair-recovery"
    engine, session_factory = _database(runtime_dir, "repair-retention-recovery")

    async with AsyncSqliteSaver.from_conn_string(
        str(runtime_dir / "checkpoints-recovery.db")
    ) as checkpointer:
        await _put_checkpoint(checkpointer, tid)
        async with session_factory() as session:
            await create_thread(
                session,
                write_authority=make_test_write_authority(),
                thread_id=tid,
                status="running",
            )
            await _seed_recoverable_actions(session, tid)
            await session.commit()

        async with session_factory() as session:
            before = await _journal_inventory(session, tid)

        for _ in range(12):
            async with session_factory() as session:
                await reconcile_threads_on_startup(
                    session, checkpointer, retain_repair_boots=1
                )
                await session.commit()

        async with session_factory() as session:
            after = await _journal_inventory(session, tid)
            repair_rows = await _repair_row_count(session, tid)

            # Direct-control recovery redrives by action type over unapplied rows.
            cancel = await get_latest_control_action(
                session, thread_id=tid, action_type=ControlActionType.CANCEL
            )
            # A worker receipt settles the exact row its dispatch id names.
            by_dispatch = await get_control_action_by_dispatch_id(
                session, thread_id=tid, dispatch_id="dispatch-permission-1"
            )
            # An idempotent retry replays the durable outcome by key.
            permission_replay = await get_control_action_by_idempotency_key(
                session, thread_id=tid, idempotency_key=_PERMISSION_KEY
            )
            clarification_replay = await get_control_action_by_idempotency_key(
                session, thread_id=tid, idempotency_key=_CLARIFICATION_KEY
            )

    # Four seeded actions remain intact through repeated startup passes.
    assert len(before) == 4
    assert after == before
    assert repair_rows == 0

    assert cancel is not None
    assert cancel.applied_at is None
    assert by_dispatch is not None
    assert by_dispatch.request_id == "req-perm-1"
    assert permission_replay is not None
    assert clarification_replay is not None
    assert clarification_replay.applied_at is None

    await engine.dispose()


@pytest.mark.asyncio
async def test_current_pass_pair_survives_a_cap_below_the_pair(
    runtime_dir: Path,
) -> None:
    """A cap of one must not reclaim a row the running pass is still holding.

    ``execute_reconciliation`` mutates the started row after writing it and writes
    the finished row after that, so a prune that ranked either as history would
    delete a live object mid-transaction. The boot-counted setting cannot express
    a sub-pair cap at all, so this drives the repository primitive directly - the
    seam where the clamp actually lives and the only way in that can still ask
    for half a pair.
    """
    tid = "thread-repair-tight-cap"
    engine, session_factory = _database(runtime_dir, "repair-retention-tight")

    async with AsyncSqliteSaver.from_conn_string(
        str(runtime_dir / "checkpoints-tight.db")
    ) as checkpointer:
        await _put_checkpoint(checkpointer, tid)
        async with session_factory() as session:
            await create_thread(
                session,
                write_authority=make_test_write_authority(),
                thread_id=tid,
                status="running",
            )
            await session.commit()

        async with session_factory() as session:
            for epoch in range(1, 4):
                await create_control_action(
                    session,
                    thread_id=tid,
                    action_type=ControlActionType.REPAIR_STARTED,
                    idempotency_key=f"startup-repair:{tid}:{epoch}",
                    result_status=ControlActionResultStatus.APPLIED,
                )
                await create_control_action(
                    session,
                    thread_id=tid,
                    action_type=ControlActionType.REPAIR_FINISHED,
                    idempotency_key=f"startup-repair-finished:{tid}:{epoch - 1}",
                    result_status=ControlActionResultStatus.APPLIED,
                )
            await session.commit()

        async with session_factory() as session:
            hoarded = await _repair_row_count(session, tid)
            deleted = await prune_repair_journal(session, thread_ids=[tid], keep_rows=1)
            await session.commit()

        async with session_factory() as session:
            surviving = await _repair_row_count(session, tid)
            started = await get_control_action_by_idempotency_key(
                session, thread_id=tid, idempotency_key=f"startup-repair:{tid}:3"
            )
            finished = await get_control_action_by_idempotency_key(
                session,
                thread_id=tid,
                idempotency_key=f"startup-repair-finished:{tid}:2",
            )

    # Three historical pairs, then a cap of one row raised to a whole pair.
    assert hoarded == 6
    assert deleted == 4
    assert surviving == 2
    # The newest pair is the one kept, and it is a PAIR - not a half of one.
    assert started is not None
    assert finished is not None

    await engine.dispose()

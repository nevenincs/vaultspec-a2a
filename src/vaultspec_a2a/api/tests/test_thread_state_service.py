"""Thread-state assembly regressions for checkpoint failure handling."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from langgraph.checkpoint.base import empty_checkpoint
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from vaultspec_a2a.control.thread_state_service import build_thread_state
from vaultspec_a2a.database import create_thread, record_permission_request
from vaultspec_a2a.database.models import (
    Base,
    PermissionRequestModel,
    ThreadExecutionStateModel,
)
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


@pytest.mark.asyncio
async def test_missing_checkpoint_degrades_snapshot_readiness() -> None:
    """A missing checkpoint must not leave the snapshot looking healthy."""
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
        async with session_factory() as session:
            await create_thread(
                session,
                thread_id="thread-missing-checkpoint",
                status="running",
                repair_status="healthy",
                execution_readiness="healthy",
            )
            await session.commit()

        async with session_factory() as session:
            snapshot = await build_thread_state(
                session,
                thread_id="thread-missing-checkpoint",
                aggregator=EventAggregator(),
                checkpointer=checkpointer,
            )

    assert snapshot is not None
    assert snapshot.snapshot_complete is False
    assert snapshot.replay_status == "gap_detected"
    assert snapshot.repair_status == "checkpoint_unavailable"
    assert snapshot.execution_readiness == "checkpoint_unavailable"
    assert "checkpoint_missing" in snapshot.degraded_reasons

    await engine.dispose()


@pytest.mark.asyncio
async def test_unreadable_execution_state_degrades_readiness_even_with_checkpoint() -> (
    None
):
    """Checkpoint-backed snapshots must still surface durable state corruption."""
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
        await checkpointer.setup()
        checkpoint = empty_checkpoint()
        checkpoint["id"] = "cp-corrupt-state"
        await checkpointer.aput(
            {
                "configurable": {
                    "thread_id": "thread-corrupt-state",
                    "checkpoint_ns": "",
                }
            },
            checkpoint,
            {"source": "loop", "step": 1, "parents": {}},
            {},
        )

        async with session_factory() as session:
            await create_thread(
                session,
                thread_id="thread-corrupt-state",
                status="running",
                repair_status="healthy",
                execution_readiness="healthy",
            )
            session.add(
                ThreadExecutionStateModel(
                    thread_id="thread-corrupt-state",
                    checkpoint_id="cp-corrupt-state",
                    parent_checkpoint_id=None,
                    recovery_epoch=0,
                    task_count=0,
                    interrupt_count=0,
                    next_nodes_json="{",
                    interrupt_types_json="[]",
                    tasks_json="[]",
                    degraded_reasons_json="[]",
                )
            )
            await session.commit()

        async with session_factory() as session:
            snapshot = await build_thread_state(
                session,
                thread_id="thread-corrupt-state",
                aggregator=EventAggregator(),
                checkpointer=checkpointer,
            )

    assert snapshot is not None
    assert snapshot.snapshot_complete is False
    assert snapshot.replay_status == "durable"
    assert "execution_state_projection_unreadable" in snapshot.degraded_reasons
    assert snapshot.repair_status == "operator_intervention_required"
    assert snapshot.execution_readiness == "operator_intervention_required"

    await engine.dispose()


@pytest.mark.asyncio
async def test_unreadable_durable_permission_degrades_snapshot_without_crashing() -> (
    None
):
    """Corrupted durable permission rows must degrade the snapshot, not break it."""
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
        await checkpointer.setup()
        checkpoint = empty_checkpoint()
        checkpoint["id"] = "cp-corrupt-permission"
        await checkpointer.aput(
            {
                "configurable": {
                    "thread_id": "thread-corrupt-permission",
                    "checkpoint_ns": "",
                }
            },
            checkpoint,
            {"source": "loop", "step": 1, "parents": {}},
            {},
        )
        async with session_factory() as session:
            await create_thread(
                session,
                thread_id="thread-corrupt-permission",
                status="input_required",
                repair_status="healthy",
                execution_readiness="healthy",
            )
            await record_permission_request(
                session,
                request_id="perm-corrupt",
                thread_id="thread-corrupt-permission",
                pause_reason_type="permission_request",
                description="Allow file write?",
                allowed_options=[{"option_id": "allow_once", "name": "Allow Once"}],
                tool_call="bash",
            )
            permission = await session.get(PermissionRequestModel, "perm-corrupt")
            assert permission is not None
            permission.allowed_options_json = '{"broken":'
            await session.commit()

        async with session_factory() as session:
            snapshot = await build_thread_state(
                session,
                thread_id="thread-corrupt-permission",
                aggregator=EventAggregator(),
                checkpointer=checkpointer,
            )

    assert snapshot is not None
    assert snapshot.snapshot_complete is False
    assert snapshot.pending_permissions == []
    assert snapshot.replay_status == "durable"
    assert "permission_projection_unreadable" in snapshot.degraded_reasons
    assert snapshot.repair_status == "operator_intervention_required"
    assert snapshot.execution_readiness == "operator_intervention_required"

    await engine.dispose()


@pytest.mark.asyncio
async def test_unreadable_plan_approval_row_does_not_seed_pending_approval() -> None:
    """Unreadable plan-approval rows must not leak mirrored approval metadata."""
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
        await checkpointer.setup()
        checkpoint = empty_checkpoint()
        checkpoint["id"] = "cp-corrupt-plan-approval"
        await checkpointer.aput(
            {
                "configurable": {
                    "thread_id": "thread-corrupt-plan-approval",
                    "checkpoint_ns": "",
                }
            },
            checkpoint,
            {"source": "loop", "step": 1, "parents": {}},
            {},
        )
        async with session_factory() as session:
            await create_thread(
                session,
                thread_id="thread-corrupt-plan-approval",
                status="input_required",
                repair_status="healthy",
                execution_readiness="healthy",
            )
            await record_permission_request(
                session,
                request_id="perm-corrupt-plan",
                thread_id="thread-corrupt-plan-approval",
                pause_reason_type="plan_approval_request",
                description="Approve plan?",
                allowed_options=[{"option_id": "approve", "name": "Approve"}],
                tool_call="plan_approval",
            )
            permission = await session.get(PermissionRequestModel, "perm-corrupt-plan")
            assert permission is not None
            permission.allowed_options_json = '{"broken":'
            await session.commit()

        async with session_factory() as session:
            snapshot = await build_thread_state(
                session,
                thread_id="thread-corrupt-plan-approval",
                aggregator=EventAggregator(),
                checkpointer=checkpointer,
            )

    assert snapshot is not None
    assert snapshot.snapshot_complete is False
    assert snapshot.pending_permissions == []
    assert snapshot.approval_status is None
    assert snapshot.approval_request_id is None
    assert "permission_projection_unreadable" in snapshot.degraded_reasons

    await engine.dispose()

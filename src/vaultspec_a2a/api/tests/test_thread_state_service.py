"""Thread-state assembly regressions for checkpoint failure handling."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from langgraph.checkpoint.base import empty_checkpoint
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Interrupt
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from vaultspec_a2a.control.thread_state_service import build_thread_state
from vaultspec_a2a.database import create_thread, record_permission_request
from vaultspec_a2a.database.models import (
    Base,
    PermissionRequestModel,
    ThreadExecutionStateModel,
    ThreadModel,
)
from vaultspec_a2a.graph.events import PermissionRequest
from vaultspec_a2a.streaming.aggregator import EventAggregator

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.asyncio
async def test_checkpoint_failure_updates_execution_readiness_with_repair_status(
    tmp_path: Path,
) -> None:
    """Checkpoint read failures must not leave stale readiness on the snapshot."""
    case_dir = tmp_path / "thread-state-service-db-closed"
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
async def test_missing_checkpoint_degrades_snapshot_readiness(tmp_path: Path) -> None:
    """A missing checkpoint must not leave the snapshot looking healthy."""
    case_dir = tmp_path / "thread-state-service-db-missing"
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
async def test_unreadable_execution_state_degrades_readiness_even_with_checkpoint(
    tmp_path: Path,
) -> None:
    """Checkpoint-backed snapshots must still surface durable state corruption."""
    case_dir = tmp_path / "thread-state-service-db-corrupt-state"
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
async def test_stale_execution_state_degrades_snapshot_readiness(
    tmp_path: Path,
) -> None:
    """Stale durable execution-state lineage must not leave reconnect healthy."""
    case_dir = tmp_path / "thread-state-service-db-stale-state"
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
        checkpoint["id"] = "cp-fresh-state"
        await checkpointer.aput(
            {
                "configurable": {
                    "thread_id": "thread-stale-state",
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
                thread_id="thread-stale-state",
                status="running",
                repair_status="healthy",
                execution_readiness="healthy",
            )
            thread = await session.get(ThreadModel, "thread-stale-state")
            assert thread is not None
            thread.recovery_epoch = 3
            session.add(
                ThreadExecutionStateModel(
                    thread_id="thread-stale-state",
                    checkpoint_id="cp-fresh-state",
                    parent_checkpoint_id=None,
                    recovery_epoch=1,
                    task_count=1,
                    interrupt_count=0,
                    next_nodes_json='["worker"]',
                    interrupt_types_json="[]",
                    tasks_json="[]",
                    degraded_reasons_json="[]",
                )
            )
            await session.commit()

        async with session_factory() as session:
            snapshot = await build_thread_state(
                session,
                thread_id="thread-stale-state",
                aggregator=EventAggregator(),
                checkpointer=checkpointer,
            )

    assert snapshot is not None
    assert snapshot.snapshot_complete is False
    assert snapshot.replay_status == "durable"
    assert "execution_state_projection_stale" in snapshot.degraded_reasons
    assert snapshot.repair_status == "needs_reconciliation"
    assert snapshot.execution_readiness == "needs_reconciliation"
    assert snapshot.next_nodes == []
    assert snapshot.task_count == 0
    assert snapshot.pending_interrupt_count == 0
    assert snapshot.execution_tasks == []

    await engine.dispose()


@pytest.mark.asyncio
async def test_unreadable_durable_permission_degrades_snapshot_without_crashing(
    tmp_path: Path,
) -> None:
    """Corrupted durable permission rows must degrade the snapshot, not break it."""
    case_dir = tmp_path / "thread-state-service-db-corrupt-permission"
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
async def test_unreadable_plan_approval_row_does_not_seed_pending_approval(
    tmp_path: Path,
) -> None:
    """Unreadable plan-approval rows must not leak mirrored approval metadata."""
    case_dir = tmp_path / "thread-state-service-db-corrupt-plan"
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


@pytest.mark.asyncio
async def test_unreadable_plan_approval_row_clears_stale_thread_approval_state(
    tmp_path: Path,
) -> None:
    """Corrupt plan-approval rows must override stale thread-row approval state."""
    case_dir = tmp_path / "thread-state-service-db-stale-plan"
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
        checkpoint["id"] = "cp-stale-plan-approval"
        await checkpointer.aput(
            {
                "configurable": {
                    "thread_id": "thread-stale-plan-approval",
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
                thread_id="thread-stale-plan-approval",
                status="input_required",
                repair_status="healthy",
                execution_readiness="healthy",
            )
            thread.approval_status = "pending"
            thread.approval_request_id = "perm-stale-plan"
            await record_permission_request(
                session,
                request_id="perm-stale-plan",
                thread_id="thread-stale-plan-approval",
                pause_reason_type="plan_approval_request",
                description="Approve plan?",
                allowed_options=[{"option_id": "approve", "name": "Approve"}],
                tool_call="plan_approval",
            )
            permission = await session.get(PermissionRequestModel, "perm-stale-plan")
            assert permission is not None
            permission.allowed_options_json = '{"broken":'
            await session.commit()

        async with session_factory() as session:
            snapshot = await build_thread_state(
                session,
                thread_id="thread-stale-plan-approval",
                aggregator=EventAggregator(),
                checkpointer=checkpointer,
            )

    assert snapshot is not None
    assert snapshot.snapshot_complete is False
    assert snapshot.approval_status is None
    assert snapshot.approval_request_id is None
    assert "permission_projection_unreadable" in snapshot.degraded_reasons

    await engine.dispose()


@pytest.mark.asyncio
async def test_missing_plan_approval_request_clears_stale_thread_pending_approval(
    tmp_path: Path,
) -> None:
    """Stale thread-row pending approval must not survive without backing state."""
    case_dir = tmp_path / "thread-state-service-db-missing-plan"
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
        checkpoint["id"] = "cp-no-plan-approval"
        await checkpointer.aput(
            {
                "configurable": {
                    "thread_id": "thread-stale-pending-approval",
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
                thread_id="thread-stale-pending-approval",
                status="input_required",
                repair_status="healthy",
                execution_readiness="healthy",
            )
            thread.approval_status = "pending"
            thread.approval_request_id = "perm-missing-plan"
            await session.commit()

        async with session_factory() as session:
            snapshot = await build_thread_state(
                session,
                thread_id="thread-stale-pending-approval",
                aggregator=EventAggregator(),
                checkpointer=checkpointer,
            )

    assert snapshot is not None
    assert snapshot.approval_status is None
    assert snapshot.approval_request_id is None
    assert snapshot.replay_status == "durable"

    await engine.dispose()


@pytest.mark.asyncio
async def test_plan_approval_without_tool_call_preserves_pending_approval(
    tmp_path: Path,
) -> None:
    """Plan approval rows created without tool_call must stay actionable."""
    case_dir = tmp_path / "thread-state-service-db-plan-no-tool-call"
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
        checkpoint["id"] = "cp-plan-no-tool-call"
        await checkpointer.aput(
            {
                "configurable": {
                    "thread_id": "thread-plan-no-tool-call",
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
                thread_id="thread-plan-no-tool-call",
                status="input_required",
                repair_status="healthy",
                execution_readiness="healthy",
            )
            thread.approval_status = "pending"
            thread.approval_request_id = "perm-plan-no-tool-call"
            await record_permission_request(
                session,
                request_id="perm-plan-no-tool-call",
                thread_id="thread-plan-no-tool-call",
                pause_reason_type="plan_approval_request",
                description="Approve plan without tool call?",
                allowed_options=[{"option_id": "approve", "name": "Approve"}],
                tool_call=None,
            )
            await session.commit()

        async with session_factory() as session:
            snapshot = await build_thread_state(
                session,
                thread_id="thread-plan-no-tool-call",
                aggregator=EventAggregator(),
                checkpointer=checkpointer,
            )

    assert snapshot is not None
    assert snapshot.approval_status == "pending"
    assert snapshot.approval_request_id == "perm-plan-no-tool-call"
    assert len(snapshot.pending_permissions) == 1
    assert snapshot.pending_permissions[0].tool_call == "plan_approval"

    await engine.dispose()


@pytest.mark.asyncio
async def test_aggregator_only_pending_permission_does_not_surface_in_thread_state(
    tmp_path: Path,
) -> None:
    """Reconnect snapshots must not expose permissions without durable rows."""
    import time

    case_dir = tmp_path / "thread-state-service-db-aggregator-only-permission"
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
        checkpoint["id"] = "cp-aggregator-only-permission"
        await checkpointer.aput(
            {
                "configurable": {
                    "thread_id": "thread-aggregator-only-permission",
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
                thread_id="thread-aggregator-only-permission",
                status="input_required",
                repair_status="healthy",
                execution_readiness="healthy",
            )
            await session.commit()

        aggregator = EventAggregator()
        aggregator._emitters._pending_permissions[
            "thread-aggregator-only-permission:perm-1"
        ] = (
            PermissionRequest(
                thread_id="thread-aggregator-only-permission",
                agent_id="vaultspec-coder",
                timestamp=time.time(),
                request_id="thread-aggregator-only-permission:perm-1",
                description="Allow file write?",
                options=[],
            ),
            0.0,
        )

        async with session_factory() as session:
            snapshot = await build_thread_state(
                session,
                thread_id="thread-aggregator-only-permission",
                aggregator=aggregator,
                checkpointer=checkpointer,
            )

    assert snapshot is not None
    assert snapshot.pending_permissions == []
    assert snapshot.approval_status is None
    assert snapshot.approval_request_id is None

    await engine.dispose()


@pytest.mark.asyncio
async def test_checkpoint_only_pending_permission_does_not_surface_in_thread_state(
    tmp_path: Path,
) -> None:
    """Checkpoint interrupts alone must not advertise actionable permissions."""
    case_dir = tmp_path / "thread-state-service-db-checkpoint-only-permission"
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
        checkpoint["id"] = "cp-checkpoint-only-permission"
        config = await checkpointer.aput(
            {
                "configurable": {
                    "thread_id": "thread-checkpoint-only-permission",
                    "checkpoint_ns": "",
                }
            },
            checkpoint,
            {"source": "loop", "step": 1, "parents": {}},
            {},
        )
        await checkpointer.aput_writes(
            config,
            [
                (
                    "__interrupt__",
                    [
                        Interrupt(
                            value={
                                "type": "permission_request",
                                "tool_name": "bash",
                                "options": [
                                    {
                                        "optionId": "allow_once",
                                        "name": "Allow Once",
                                    }
                                ],
                            },
                            id="perm-checkpoint-only",
                        )
                    ],
                )
            ],
            task_id="task-checkpoint-only-permission",
        )

        async with session_factory() as session:
            await create_thread(
                session,
                thread_id="thread-checkpoint-only-permission",
                status="input_required",
                repair_status="healthy",
                execution_readiness="healthy",
            )
            await session.commit()

        async with session_factory() as session:
            snapshot = await build_thread_state(
                session,
                thread_id="thread-checkpoint-only-permission",
                aggregator=EventAggregator(),
                checkpointer=checkpointer,
            )

    assert snapshot is not None
    assert snapshot.pending_permissions == []
    assert snapshot.snapshot_complete is False
    assert "checkpoint_permission_without_durable_row" in snapshot.degraded_reasons
    assert snapshot.repair_status == "needs_reconciliation"
    assert snapshot.execution_readiness == "needs_reconciliation"

    await engine.dispose()

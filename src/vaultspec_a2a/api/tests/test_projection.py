"""Tests for repair-aware checkpoint projection helpers."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from langgraph.checkpoint.base import CheckpointTuple
from langgraph.types import Interrupt
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ...control.projection import (
    apply_checkpoint_projection,
    apply_execution_state_projection,
    enrich_snapshot_from_execution_state,
    project_execution_state_model,
)
from ...database import (
    create_thread,
    record_thread_execution_state,
    set_thread_repair_state,
)
from ...database.models import Base, ThreadExecutionStateModel
from ...thread.snapshots import (
    CheckpointProjection,
    ExecutionStateProjection,
    ExecutionTaskData,
    ProjectedInterrupt,
    ThreadStateData,
    project_checkpoint_tuple,
)


def test_project_checkpoint_tuple_extracts_plan_approval_interrupt() -> None:
    """Real LangGraph checkpoint tuples expose interrupt data via pending_writes."""
    checkpoint_tuple = CheckpointTuple(
        config={"configurable": {"thread_id": "thread-1", "checkpoint_id": "cp-1"}},
        checkpoint={
            "v": 1,
            "id": "cp-1",
            "ts": "2026-03-09T10:20:49.387246+00:00",
            "channel_values": {"plan": [{"content": "Draft plan"}]},
            "channel_versions": {},
            "versions_seen": {},
            "updated_channels": [],
        },
        metadata={"source": "loop", "step": 0, "parents": {}},
        pending_writes=[
            (
                "task-1",
                "__interrupt__",
                [
                    Interrupt(
                        value={
                            "type": "plan_approval_request",
                            "feature": "auth",
                            "plan_paths": ["plan.md"],
                            "exec_worker": "vaultspec-coder",
                        },
                        id="interrupt-plan-1",
                    )
                ],
            )
        ],
    )

    projection = project_checkpoint_tuple(
        checkpoint_tuple,
        thread_id="thread-1",
        history_depth=2,
    )

    assert projection.checkpoint_id == "cp-1"
    assert projection.checkpoint_parent_id is None
    assert projection.checkpoint_source == "loop"
    assert projection.checkpoint_step == 0
    assert projection.history_depth == 2
    assert projection.pause_cause == "plan_approval_request"
    assert projection.checkpoint_created_at == datetime(
        2026,
        3,
        9,
        10,
        20,
        49,
        387246,
        tzinfo=UTC,
    )
    assert len(projection.pending_interrupts) == 1
    assert projection.pending_interrupts[0].interrupt_id == "interrupt-plan-1"
    assert projection.pending_write_channels == ["__interrupt__"]
    assert projection.pending_write_count == 1


def test_project_checkpoint_tuple_surfaces_metadata_parent_and_pending_writes() -> None:
    """Projection exposes durable tuple metadata without inventing task state."""
    checkpoint_tuple = CheckpointTuple(
        config={"configurable": {"thread_id": "thread-1", "checkpoint_id": "cp-2"}},
        checkpoint={
            "v": 1,
            "id": "cp-2",
            "ts": "2026-03-09T10:21:49.387246+00:00",
            "channel_values": {"messages": []},
            "channel_versions": {},
            "versions_seen": {},
            "updated_channels": ["messages", "plan"],
        },
        metadata={"source": "input", "step": 3, "parents": {}},
        parent_config={
            "configurable": {
                "thread_id": "thread-1",
                "checkpoint_id": "cp-1",
            }
        },
        pending_writes=[
            ("task-1", "messages", {"role": "user", "content": "hi"}),
            ("task-2", "branch:to:worker", None),
        ],
    )

    projection = project_checkpoint_tuple(checkpoint_tuple, thread_id="thread-1")

    assert projection.checkpoint_parent_id == "cp-1"
    assert projection.checkpoint_source == "input"
    assert projection.checkpoint_step == 3
    assert projection.checkpoint_updated_channels == ["messages", "plan"]
    assert projection.pending_write_channels == ["messages", "branch:to:worker"]
    assert projection.pending_write_count == 2
    assert projection.history_depth is None
    assert "checkpoint_history_unknown" in projection.degraded_reasons


def test_apply_checkpoint_projection_merges_interrupt_permissions() -> None:
    """Projected interrupts should surface as pending permissions in snapshots."""
    snapshot = ThreadStateData(
        thread_id="thread-1",
        status="input_required",
        last_sequence=0,
    )
    projection = CheckpointProjection(
        channel_values={},
        config={"configurable": {"thread_id": "thread-1", "checkpoint_id": "cp-1"}},
        checkpoint_id="cp-1",
        checkpoint_created_at=datetime(2026, 3, 9, 10, 20, tzinfo=UTC),
        checkpoint_parent_id="cp-0",
        checkpoint_source="loop",
        checkpoint_step=4,
        checkpoint_updated_channels=["messages"],
        pending_write_channels=["__interrupt__"],
        pending_write_count=1,
        history_depth=2,
        pause_cause="permission_request",
        pending_interrupts=[
            ProjectedInterrupt(
                interrupt_id="interrupt-tool-1",
                interrupt_type="permission_request",
                payload={
                    "type": "permission_request",
                    "tool_name": "bash",
                    "options": [
                        {"optionId": "allow_once", "name": "Allow Once"},
                        {"optionId": "reject_once", "name": "Reject Once"},
                    ],
                },
            )
        ],
    )

    projected = apply_checkpoint_projection(snapshot, projection)

    assert projected.checkpoint_id == "cp-1"
    assert projected.checkpoint_created_at == datetime(2026, 3, 9, 10, 20, tzinfo=UTC)
    assert projected.checkpoint_parent_id == "cp-0"
    assert projected.checkpoint_source == "loop"
    assert projected.checkpoint_step == 4
    assert projected.checkpoint_updated_channels == ["messages"]
    assert projected.pending_write_channels == ["__interrupt__"]
    assert projected.pending_write_count == 1
    assert projected.history_depth == 2
    assert projected.pause_cause == "permission_request"
    assert len(projected.pending_permissions) == 1
    permission = projected.pending_permissions[0]
    assert permission.request_id == "interrupt-tool-1"
    assert permission.tool_call == "bash"
    assert [option.option_id for option in permission.options] == [
        "allow_once",
        "reject_once",
    ]


def test_project_execution_state_model_normalizes_latest_row() -> None:
    """Execution-state rows should deserialize into frontend-safe snapshots."""
    model = ThreadExecutionStateModel(
        thread_id="thread-1",
        checkpoint_id="cp-1",
        parent_checkpoint_id="cp-0",
        recovery_epoch=2,
        task_count=1,
        interrupt_count=1,
        next_nodes_json='["supervisor"]',
        interrupt_types_json='["permission_request"]',
        tasks_json=(
            '[{"task_id":"task-1","name":"supervisor","path":["supervisor"],'
            '"has_error":false,"error_type":null,"interrupt_ids":["interrupt-1"],'
            '"interrupt_types":["permission_request"],"has_nested_state":false,'
            '"has_result":false}]'
        ),
        degraded_reasons_json='["execution_state_projection_partial"]',
    )

    projection = project_execution_state_model(model)

    assert projection.checkpoint_id == "cp-1"
    assert projection.parent_checkpoint_id == "cp-0"
    assert projection.recovery_epoch == 2
    assert projection.next_nodes == ["supervisor"]
    assert projection.interrupt_types == ["permission_request"]
    assert projection.task_count == 1
    assert projection.interrupt_count == 1
    assert projection.degraded_reasons == ["execution_state_projection_partial"]
    assert projection.execution_tasks == [
        ExecutionTaskData(
            task_id="task-1",
            name="supervisor",
            path=["supervisor"],
            has_error=False,
            error_type=None,
            interrupt_ids=["interrupt-1"],
            interrupt_types=["permission_request"],
            has_nested_state=False,
            has_result=False,
        )
    ]


def test_apply_execution_state_projection_merges_normalized_fields() -> None:
    """Durable execution-state projection should enrich reconnect snapshots."""
    snapshot = ThreadStateData(
        thread_id="thread-1",
        status="running",
        last_sequence=0,
    )
    projection = ExecutionStateProjection(
        checkpoint_id="cp-1",
        parent_checkpoint_id="cp-0",
        recovery_epoch=1,
        task_count=1,
        interrupt_count=1,
        next_nodes=["supervisor"],
        interrupt_types=["permission_request"],
        execution_tasks=[
            ExecutionTaskData(
                task_id="task-1",
                name="supervisor",
                path=["supervisor"],
                has_error=False,
                error_type=None,
                interrupt_ids=["interrupt-1"],
                interrupt_types=["permission_request"],
                has_nested_state=False,
                has_result=False,
            )
        ],
        degraded_reasons=["execution_state_projection_partial"],
    )

    projected = apply_execution_state_projection(snapshot, projection)

    assert projected.next_nodes == ["supervisor"]
    assert projected.task_count == 1
    assert projected.pending_interrupt_count == 1
    assert len(projected.execution_tasks) == 1
    assert "execution_state_projection_partial" in projected.degraded_reasons


@pytest.mark.asyncio
async def test_enrich_snapshot_from_execution_state_detects_stale_checkpoint(
    tmp_path: Path,
) -> None:
    """Checkpoint mismatch should explicitly mark execution-state projection stale."""
    case_dir = tmp_path / "api-test-projection-db-stale"
    case_dir.mkdir(parents=True, exist_ok=True)
    db_file = case_dir / "test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        thread = await create_thread(session, thread_id="thread-1")
        await record_thread_execution_state(
            session,
            thread_id="thread-1",
            checkpoint_id="cp-old",
            parent_checkpoint_id=None,
            snapshot_created_at=None,
            task_count=0,
            interrupt_count=0,
            next_nodes=["supervisor"],
            interrupt_types=[],
            tasks=[],
            degraded_reasons=[],
        )
        await session.commit()

        snapshot = ThreadStateData(
            thread_id="thread-1",
            status=thread.status,
            last_sequence=0,
            checkpoint_id="cp-new",
        )
        snapshot = await enrich_snapshot_from_execution_state(
            session,
            thread=thread,
            snapshot=snapshot,
            checkpoint_present=True,
            checkpoint_id="cp-new",
        )

        assert snapshot.snapshot_complete is False
        assert "execution_state_projection_stale" in snapshot.degraded_reasons

    await engine.dispose()


@pytest.mark.asyncio
async def test_degraded_projection_does_not_mask_recovery_epoch_staleness(
    tmp_path: Path,
) -> None:
    """A degraded-only projection must not refresh recovery_epoch on old state."""
    case_dir = tmp_path / "api-test-projection-db-epoch"
    case_dir.mkdir(parents=True, exist_ok=True)
    db_file = case_dir / "test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        thread = await create_thread(session, thread_id="thread-epoch")
        await record_thread_execution_state(
            session,
            thread_id="thread-epoch",
            checkpoint_id="cp-good",
            parent_checkpoint_id=None,
            snapshot_created_at=None,
            task_count=0,
            interrupt_count=0,
            next_nodes=["worker"],
            interrupt_types=[],
            tasks=[],
            degraded_reasons=[],
        )
        await set_thread_repair_state(
            session,
            "thread-epoch",
            repair_status="needs_reconciliation",
            execution_readiness="needs_reconciliation",
            increment_recovery_epoch=True,
        )
        await record_thread_execution_state(
            session,
            thread_id="thread-epoch",
            checkpoint_id=None,
            parent_checkpoint_id=None,
            snapshot_created_at=None,
            task_count=0,
            interrupt_count=0,
            next_nodes=[],
            interrupt_types=[],
            tasks=[],
            degraded_reasons=["execution_state_projection_unavailable"],
        )
        await session.commit()
        await session.refresh(thread)

        snapshot = ThreadStateData(
            thread_id="thread-epoch",
            status=thread.status,
            last_sequence=0,
        )
        snapshot = await enrich_snapshot_from_execution_state(
            session,
            thread=thread,
            snapshot=snapshot,
            checkpoint_present=False,
            checkpoint_id=None,
        )

        projection = await session.get(ThreadExecutionStateModel, "thread-epoch")

    assert projection is not None
    assert projection.checkpoint_id == "cp-good"
    assert projection.recovery_epoch == 0
    assert snapshot.snapshot_complete is False
    assert "execution_state_projection_stale" in snapshot.degraded_reasons

    await engine.dispose()


@pytest.mark.asyncio
async def test_unreadable_execution_state_requires_operator_intervention(
    tmp_path: Path,
) -> None:
    """Corrupted durable execution-state rows must fail closed on readiness."""
    case_dir = tmp_path / "api-test-projection-db-corrupt"
    case_dir.mkdir(parents=True, exist_ok=True)
    db_file = case_dir / "test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        thread = await create_thread(
            session,
            thread_id="thread-corrupt-execution-state",
            repair_status="healthy",
            execution_readiness="healthy",
        )
        session.add(
            ThreadExecutionStateModel(
                thread_id="thread-corrupt-execution-state",
                checkpoint_id="cp-1",
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

        snapshot = ThreadStateData(
            thread_id=thread.id,
            status=thread.status,
            last_sequence=0,
        )
        snapshot = await enrich_snapshot_from_execution_state(
            session,
            thread=thread,
            snapshot=snapshot,
            checkpoint_present=True,
            checkpoint_id="cp-1",
        )

    assert snapshot.snapshot_complete is False
    assert "execution_state_projection_unreadable" in snapshot.degraded_reasons
    assert snapshot.repair_status == "operator_intervention_required"
    assert snapshot.execution_readiness == "operator_intervention_required"

    await engine.dispose()

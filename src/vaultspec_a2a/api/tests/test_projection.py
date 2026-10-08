"""Tests for repair-aware checkpoint projection helpers."""

from datetime import UTC, datetime, timedelta

import pytest
from langgraph.checkpoint.base import CheckpointTuple
from langgraph.types import Interrupt
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ...control.projection import (
    apply_checkpoint_projection,
    apply_execution_state_projection,
    enrich_snapshot_from_durable_state,
    enrich_snapshot_from_execution_state,
    project_execution_state_model,
    reconcile_checkpoint_permissions_with_durable_state,
)
from ...database import (
    ThreadExecutionStateModel,
    create_control_action,
    create_thread,
    record_permission_request,
    record_thread_execution_state,
)
from ...tests._write_authority import make_test_write_authority
from ...thread.enums import (
    ControlActionResultStatus,
    ControlActionType,
    DegradedReason,
    RepairStatus,
    ThreadStatus,
)
from ...thread.snapshots import (
    CheckpointProjection,
    ExecutionStateProjection,
    ExecutionTaskSnapshot,
    ProjectedInterrupt,
    ThreadStateSnapshot,
    project_checkpoint_tuple,
)


def _projected_interrupt_with_runtime_payload(
    interrupt_id: str,
    interrupt_type: str,
    payload: object,
) -> ProjectedInterrupt:
    """Build a valid interrupt, then model the untrusted runtime payload boundary."""
    interrupt = ProjectedInterrupt(
        interrupt_id=interrupt_id,
        interrupt_type=interrupt_type,
        payload={},
    )
    object.__setattr__(interrupt, "payload", payload)
    return interrupt


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
                            "request_id": "plan-approval-1",
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
    # The id the producer named the request by, not LangGraph's interrupt id.
    assert projection.pending_interrupts[0].interrupt_id == "plan-approval-1"
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


def test_a_checkpoint_only_permission_is_flagged_rather_than_merged() -> None:
    """A parked permission is never built from the checkpoint alone.

    The durable row is the only source of a pending permission's content, so a
    permission the checkpoint is parked on with no row behind it contributes
    nothing to the snapshot's pending permissions: it is flagged as an orphan
    the respond route cannot act on, and the run is held for reconciliation.
    """
    snapshot = ThreadStateSnapshot(
        thread_id="thread-1",
        status=ThreadStatus.INPUT_REQUIRED,
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
                    "request_id": "interrupt-tool-1",
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
    assert projected.pending_permissions == []

    reconciled = reconcile_checkpoint_permissions_with_durable_state(
        projected, projection
    )

    assert reconciled.pending_permissions == []
    assert (
        DegradedReason.CHECKPOINT_PERMISSION_WITHOUT_DURABLE_ROW
        in reconciled.degraded_reasons
    )
    assert reconciled.snapshot_complete is False
    assert reconciled.repair_status == RepairStatus.NEEDS_RECONCILIATION
    assert reconciled.execution_readiness == RepairStatus.NEEDS_RECONCILIATION
    # No actionable permission remains, so the pause it named is withdrawn.
    assert reconciled.pause_cause is None


@pytest.mark.parametrize(
    "interrupt_type",
    [
        "permission_request",
        "plan_approval_request",
        "document_approval_request",
        "clarification_request",
        "unknown_interrupt",
    ],
)
def test_apply_checkpoint_projection_discards_runtime_corrupt_interrupt_payload(
    interrupt_type: str,
) -> None:
    """A corrupt checkpoint payload cannot surface an actionable interrupt."""
    snapshot = ThreadStateSnapshot(
        thread_id="thread-corrupt-interrupt",
        status=ThreadStatus.INPUT_REQUIRED,
        last_sequence=0,
    )
    projection = CheckpointProjection(
        channel_values={},
        config={"configurable": {"thread_id": "thread-corrupt-interrupt"}},
        checkpoint_id="cp-corrupt-interrupt",
        checkpoint_created_at=datetime(2026, 3, 9, 10, 20, tzinfo=UTC),
        pending_interrupts=[
            _projected_interrupt_with_runtime_payload(
                interrupt_id="interrupt-corrupt",
                interrupt_type=interrupt_type,
                payload="runtime-corrupt-payload",
            )
        ],
    )

    projected = apply_checkpoint_projection(snapshot, projection)

    assert projected.pending_permissions == []
    assert projected.pending_clarification is None
    assert projected.degraded_reasons == []


def test_apply_checkpoint_projection_merges_clarification_request() -> None:
    """A clarification_request interrupt surfaces as pending_clarification.

    Mirrors the permission-merge test above but for the clarification
    interrupt kind, disclosed on a separate field (not pending_permissions —
    its bounded questions do not fit the single-decision PermissionSnapshot
    shape).
    """
    snapshot = ThreadStateSnapshot(
        thread_id="thread-1",
        status=ThreadStatus.INPUT_REQUIRED,
        last_sequence=0,
    )
    projection = CheckpointProjection(
        channel_values={},
        config={"configurable": {"thread_id": "thread-1", "checkpoint_id": "cp-1"}},
        checkpoint_id="cp-1",
        checkpoint_created_at=datetime(2026, 3, 9, 10, 20, tzinfo=UTC),
        pause_cause="clarification_request",
        pending_interrupts=[
            ProjectedInterrupt(
                interrupt_id="interrupt-clarify-1",
                interrupt_type="clarification_request",
                payload={
                    "type": "clarification_request",
                    "request_id": "interrupt-clarify-1",
                    "questions": [
                        {
                            "id": "provider",
                            "prompt": "Which provider?",
                            "kind": "choice",
                            "required": True,
                            "options": ["codex", "zai"],
                        }
                    ],
                },
            )
        ],
    )

    projected = apply_checkpoint_projection(snapshot, projection)

    assert projected.pending_clarification is not None
    assert projected.pending_clarification.request_id == "interrupt-clarify-1"
    assert len(projected.pending_clarification.questions) == 1
    question = projected.pending_clarification.questions[0]
    assert question.id == "provider"
    assert question.required is True
    assert question.options == ["codex", "zai"]
    # A clarification interrupt must never populate pending_permissions — the
    # two disclosure surfaces are distinct.
    assert projected.pending_permissions == []


def test_apply_checkpoint_projection_uses_later_valid_clarification_sibling() -> None:
    """A corrupt clarification interrupt must not hide a later valid sibling."""
    snapshot = ThreadStateSnapshot(
        thread_id="thread-corrupt-clarification-sibling",
        status=ThreadStatus.INPUT_REQUIRED,
        last_sequence=0,
    )
    projection = CheckpointProjection(
        channel_values={},
        config={"configurable": {"thread_id": "thread-corrupt-clarification-sibling"}},
        checkpoint_id="cp-corrupt-clarification-sibling",
        checkpoint_created_at=datetime(2026, 3, 9, 10, 20, tzinfo=UTC),
        pending_interrupts=[
            _projected_interrupt_with_runtime_payload(
                interrupt_id="interrupt-corrupt-clarification",
                interrupt_type="clarification_request",
                payload="runtime-corrupt-payload",
            ),
            ProjectedInterrupt(
                interrupt_id="interrupt-valid-clarification",
                interrupt_type="clarification_request",
                payload={
                    "type": "clarification_request",
                    "request_id": "interrupt-valid-clarification",
                    "questions": [
                        {
                            "id": "provider",
                            "prompt": "Which provider?",
                            "kind": "choice",
                            "options": ["codex", "zai"],
                        }
                    ],
                },
            ),
        ],
    )

    projected = apply_checkpoint_projection(snapshot, projection)

    assert projected.pending_permissions == []
    assert projected.pending_clarification is not None
    assert projected.pending_clarification.request_id == "interrupt-valid-clarification"
    assert projected.degraded_reasons == []


def test_project_execution_state_model_normalizes_latest_row() -> None:
    """Execution-state rows should deserialize into frontend-safe snapshots."""
    model = ThreadExecutionStateModel(
        thread_id="thread-1",
        checkpoint_id="cp-1",
        parent_checkpoint_id="cp-0",
        task_count=1,
        interrupt_count=1,
        next_nodes_json='["supervisor"]',
        tasks_json=(
            '[{"task_id":"task-1","name":"supervisor","path":["supervisor"],'
            '"has_error":false,"error_type":null,"interrupt_ids":["interrupt-1"],'
            '"interrupt_types":["permission_request"],"has_nested_state":false,'
            '"has_result":false}]'
        ),
        degraded_reasons_json='["execution_state_projection_timeout"]',
    )

    projection = project_execution_state_model(model)

    assert projection.next_nodes == ["supervisor"]
    assert projection.task_count == 1
    assert projection.interrupt_count == 1
    assert projection.degraded_reasons == [
        DegradedReason.EXECUTION_STATE_PROJECTION_TIMEOUT
    ]
    assert projection.execution_tasks == [
        ExecutionTaskSnapshot(
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


def test_project_execution_state_model_recovers_valid_task_siblings() -> None:
    """Durable task-list corruption drops only unreadable task siblings."""
    model = ThreadExecutionStateModel(
        thread_id="thread-task-siblings",
        checkpoint_id="cp-task-siblings",
        parent_checkpoint_id=None,
        task_count=2,
        interrupt_count=0,
        next_nodes_json="[]",
        tasks_json=(
            '[{"task_id":"task-first","name":"first"},'
            '"not-a-task",'
            '{"task_id":"task-invalid","name":"invalid","path":42},'
            '{"task_id":"task-second","name":"second"}]'
        ),
        degraded_reasons_json="[]",
    )

    projection = project_execution_state_model(model)

    assert [task.task_id for task in projection.execution_tasks] == [
        "task-first",
        "task-second",
    ]


@pytest.mark.asyncio
async def test_enrich_snapshot_from_durable_state_recovers_valid_permission_siblings(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Durable permission-list corruption drops only unreadable option siblings."""
    async with session_factory() as session:
        thread = await create_thread(
            session,
            write_authority=make_test_write_authority(),
            thread_id="thread-permission-siblings",
        )
        permission = await record_permission_request(
            session,
            request_id="permission-siblings",
            thread_id=thread.id,
            pause_reason_type="permission_request",
            description="Choose an option",
            allowed_options=[],
            tool_call="bash",
        )
        permission.allowed_options_json = (
            '[{"option_id":"allow_once","name":"Allow Once"},'
            '"not-an-option",'
            '{"option_id":"reject_once","name":"Reject Once","kind":"reject_once"}]'
        )
        await session.commit()

        snapshot = ThreadStateSnapshot(
            thread_id=thread.id,
            status=ThreadStatus(thread.status),
            last_sequence=0,
        )
        projected = await enrich_snapshot_from_durable_state(
            session,
            thread=thread,
            snapshot=snapshot,
        )

    assert len(projected.pending_permissions) == 1
    assert [
        option.option_id for option in projected.pending_permissions[0].options
    ] == ["allow_once", "reject_once"]


@pytest.mark.asyncio
async def test_enrich_snapshot_from_durable_state_degrades_a_corrupt_repair_status(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A corrupt repair_status column degrades the row instead of raising.

    Nothing in the schema stops a legacy write or an out-of-band UPDATE from
    leaving an unrecognised string in ``threads.repair_status``. One row like
    that must not take the whole listing or run-status down with it.
    """
    async with session_factory() as session:
        thread = await create_thread(
            session,
            write_authority=make_test_write_authority(),
            thread_id="thread-corrupt-repair-status",
        )
        thread.repair_status = "not-a-real-status"
        await session.commit()
        await session.refresh(thread)

        snapshot = ThreadStateSnapshot(
            thread_id=thread.id,
            status=ThreadStatus(thread.status),
            last_sequence=0,
        )
        projected = await enrich_snapshot_from_durable_state(
            session,
            thread=thread,
            snapshot=snapshot,
        )

    assert projected.repair_status == RepairStatus.OPERATOR_INTERVENTION_REQUIRED
    assert projected.execution_readiness == RepairStatus.OPERATOR_INTERVENTION_REQUIRED
    assert DegradedReason.REPAIR_STATUS_UNREADABLE in projected.degraded_reasons


@pytest.mark.asyncio
async def test_enrich_snapshot_from_durable_state_ignores_a_corrupt_approval_column(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The durable approval answer comes from pending requests, never the column.

    ``threads.approval_status`` is read as a plain string only, in the
    terminal-residue check; a legacy or corrupt value in it must not reach an
    enum coercion that could raise and take the read down with it.
    """
    async with session_factory() as session:
        thread = await create_thread(
            session,
            write_authority=make_test_write_authority(),
            thread_id="thread-corrupt-approval-status",
        )
        thread.approval_status = "not-a-real-status"
        await session.commit()
        await session.refresh(thread)

        snapshot = ThreadStateSnapshot(
            thread_id=thread.id,
            status=ThreadStatus(thread.status),
            last_sequence=0,
        )
        projected = await enrich_snapshot_from_durable_state(
            session,
            thread=thread,
            snapshot=snapshot,
        )

    assert projected.approval_status is None


@pytest.mark.asyncio
async def test_a_withheld_permission_row_is_not_also_reported_as_absent(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A durable row that offers nothing answerable is not ALSO orphaned.

    The checkpoint parks on the same request id a durable row already
    answers for; that row's content is withheld (it offers no usable
    option), but it is not ABSENT, and CHECKPOINT_PERMISSION_WITHOUT_DURABLE_ROW
    must not claim the row never existed when the withholding reason already
    reported the real fault.
    """
    async with session_factory() as session:
        thread = await create_thread(
            session,
            write_authority=make_test_write_authority(),
            thread_id="thread-withheld-row",
        )
        await record_permission_request(
            session,
            request_id="withheld-1",
            thread_id=thread.id,
            pause_reason_type="permission_request",
            description="Approve?",
            allowed_options=[{"name": "Approve"}],
            tool_call="bash",
        )
        await session.commit()

        snapshot = ThreadStateSnapshot(
            thread_id=thread.id,
            status=ThreadStatus(thread.status),
            last_sequence=0,
        )
        durable_permission_ids: set[str] = set()
        snapshot = await enrich_snapshot_from_durable_state(
            session,
            thread=thread,
            snapshot=snapshot,
            durable_permission_ids=durable_permission_ids,
        )

    assert snapshot.pending_permissions == []
    assert (
        DegradedReason.PERMISSION_OFFERS_NO_USABLE_OPTION in snapshot.degraded_reasons
    )
    assert durable_permission_ids == {"withheld-1"}

    projection = CheckpointProjection(
        channel_values={},
        config={"configurable": {"thread_id": thread.id, "checkpoint_id": "cp-1"}},
        checkpoint_id="cp-1",
        checkpoint_created_at=datetime(2026, 3, 9, 10, 20, tzinfo=UTC),
        pending_interrupts=[
            ProjectedInterrupt(
                interrupt_id="withheld-1",
                interrupt_type="permission_request",
                payload={"type": "permission_request", "request_id": "withheld-1"},
            )
        ],
    )

    reconciled = reconcile_checkpoint_permissions_with_durable_state(
        snapshot, projection, durable_permission_ids=durable_permission_ids
    )

    assert (
        DegradedReason.CHECKPOINT_PERMISSION_WITHOUT_DURABLE_ROW
        not in reconciled.degraded_reasons
    )


@pytest.mark.asyncio
async def test_report_queued_messages_false_skips_the_queue_depth_read(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A caller whose served shape has no field for it skips the read.

    The listing summary never had a ``queued_messages`` field to put this
    in, so the per-row read ran for a number nothing downstream served. With
    the flag off, the field stays at its unread default even though a real
    continuation is waiting; with it on (the default), the real count comes
    through.
    """
    async with session_factory() as session:
        thread = await create_thread(
            session,
            write_authority=make_test_write_authority(),
            thread_id="thread-queued-continuation",
        )
        action = await create_control_action(
            session,
            thread_id=thread.id,
            action_type=ControlActionType.MESSAGE_FOLLOWUP_REQUESTED,
            idempotency_key="queued-continuation-1",
            dispatch_id="dispatch-queued-continuation-1",
            recovery_deadline_at=datetime.now(UTC) + timedelta(hours=1),
        )
        # Mutated in place after the accepted-row insert above validated the
        # recovery deadline it shares with every dispatchable outcome - the
        # same route the continuation-queue schema tests seed a queued row
        # through, since create_control_action has no queue_position
        # parameter of its own.
        action.result_status = ControlActionResultStatus.QUEUED.value
        action.queue_position = 1
        await session.commit()

        skipped = await enrich_snapshot_from_durable_state(
            session,
            thread=thread,
            snapshot=ThreadStateSnapshot(
                thread_id=thread.id,
                status=ThreadStatus(thread.status),
                last_sequence=0,
            ),
            report_queued_messages=False,
        )
        read = await enrich_snapshot_from_durable_state(
            session,
            thread=thread,
            snapshot=ThreadStateSnapshot(
                thread_id=thread.id,
                status=ThreadStatus(thread.status),
                last_sequence=0,
            ),
        )

    assert skipped.queued_messages == 0
    assert read.queued_messages == 1


def test_apply_execution_state_projection_merges_normalized_fields() -> None:
    """Durable execution-state projection should enrich reconnect snapshots."""
    snapshot = ThreadStateSnapshot(
        thread_id="thread-1",
        status=ThreadStatus.RUNNING,
        last_sequence=0,
    )
    projection = ExecutionStateProjection(
        task_count=1,
        interrupt_count=1,
        next_nodes=["supervisor"],
        execution_tasks=[
            ExecutionTaskSnapshot(
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
        degraded_reasons=[DegradedReason.EXECUTION_STATE_PROJECTION_TIMEOUT],
    )

    projected = apply_execution_state_projection(snapshot, projection)

    assert projected.next_nodes == ["supervisor"]
    assert projected.task_count == 1
    assert projected.pending_interrupt_count == 1
    assert len(projected.execution_tasks) == 1
    assert (
        DegradedReason.EXECUTION_STATE_PROJECTION_TIMEOUT in projected.degraded_reasons
    )


@pytest.mark.asyncio
async def test_enrich_snapshot_from_execution_state_detects_stale_checkpoint(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Checkpoint mismatch should explicitly mark execution-state projection stale."""
    async with session_factory() as session:
        thread = await create_thread(
            session, write_authority=make_test_write_authority(), thread_id="thread-1"
        )
        await record_thread_execution_state(
            session,
            thread_id="thread-1",
            checkpoint_id="cp-old",
            parent_checkpoint_id=None,
            task_count=0,
            interrupt_count=0,
            next_nodes=["supervisor"],
            tasks=[],
            degraded_reasons=[],
        )
        await session.commit()

        snapshot = ThreadStateSnapshot(
            thread_id="thread-1",
            status=ThreadStatus(thread.status),
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


@pytest.mark.asyncio
async def test_degraded_only_projection_keeps_the_prior_lineage(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A degraded-only write must not overwrite the row's last real lineage."""
    async with session_factory() as session:
        thread = await create_thread(
            session,
            write_authority=make_test_write_authority(),
            thread_id="thread-degraded-only",
        )
        await record_thread_execution_state(
            session,
            thread_id="thread-degraded-only",
            checkpoint_id="cp-good",
            parent_checkpoint_id=None,
            task_count=0,
            interrupt_count=0,
            next_nodes=["worker"],
            tasks=[],
            degraded_reasons=[],
        )
        await record_thread_execution_state(
            session,
            thread_id="thread-degraded-only",
            checkpoint_id=None,
            parent_checkpoint_id=None,
            task_count=0,
            interrupt_count=0,
            next_nodes=[],
            tasks=[],
            degraded_reasons=[DegradedReason.EXECUTION_STATE_PROJECTION_UNAVAILABLE],
        )
        await session.commit()

        snapshot = ThreadStateSnapshot(
            thread_id="thread-degraded-only",
            status=ThreadStatus(thread.status),
            last_sequence=0,
        )
        snapshot = await enrich_snapshot_from_execution_state(
            session,
            thread=thread,
            snapshot=snapshot,
            checkpoint_present=False,
            checkpoint_id=None,
        )

        projection = await session.get(
            ThreadExecutionStateModel, "thread-degraded-only"
        )

    assert projection is not None
    assert projection.checkpoint_id == "cp-good"
    assert snapshot.snapshot_complete is False
    assert "execution_state_projection_stale" in snapshot.degraded_reasons


@pytest.mark.asyncio
async def test_unreadable_execution_state_requires_operator_intervention(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Corrupted durable execution-state rows must fail closed on readiness."""
    async with session_factory() as session:
        thread = await create_thread(
            session,
            write_authority=make_test_write_authority(),
            thread_id="thread-corrupt-execution-state",
            repair_status="healthy",
        )
        session.add(
            ThreadExecutionStateModel(
                thread_id="thread-corrupt-execution-state",
                checkpoint_id="cp-1",
                parent_checkpoint_id=None,
                task_count=0,
                interrupt_count=0,
                next_nodes_json="{",
                tasks_json="[]",
                degraded_reasons_json="[]",
            )
        )
        await session.commit()

        snapshot = ThreadStateSnapshot(
            thread_id=thread.id,
            status=ThreadStatus(thread.status),
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

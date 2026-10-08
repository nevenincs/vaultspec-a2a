"""Contract tests for the run snapshot as the gateway serves it.

``ThreadStateSnapshot`` is both the domain read model and the wire declaration, so
these tests drive the real pydantic machinery over it: the validation the
history route applies, the JSON it emits, the bounds it carries, and the shared
execution-task shape the worker sends across the gateway-worker wire.
"""

import dataclasses
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from ....graph.enums import PermissionOptionKind, ToolCallStatus, ToolKind
from ....ipc.schemas import ExecutionStateProjectionPayload
from ....thread.enums import (
    ApprovalStatus,
    RepairStatus,
    ThreadStatus,
    TranscriptAvailability,
)
from ....thread.snapshots import (
    MAX_REPAIR_REASON_CHARS,
    MODEL_ASSIGNMENT_DIGEST_CHARS,
    ArtifactSnapshot,
    ExecutionTaskSnapshot,
    MessageSnapshot,
    PermissionSnapshot,
    ThreadStateSnapshot,
    ToolCallContentDiff,
    ToolCallContentTerminal,
    ToolCallContentText,
    ToolCallLocation,
    ToolCallSnapshot,
)
from ..gateway import RunHistoryResponse

NOW = datetime.now(tz=UTC)

_THREAD_STATE = TypeAdapter(ThreadStateSnapshot)

# The order the snapshot's fields are served in, which clients may rely on.
_SERVED_FIELD_ORDER = [
    "thread_id",
    "status",
    "messages",
    "tool_calls",
    "pending_permissions",
    "pending_clarification",
    "artifacts",
    "plan",
    "agents",
    "model_assignment_digest",
    "last_sequence",
    "checkpoint_id",
    "checkpoint_created_at",
    "checkpoint_parent_id",
    "checkpoint_source",
    "checkpoint_step",
    "checkpoint_updated_channels",
    "pending_write_channels",
    "pending_write_count",
    "history_depth",
    "next_nodes",
    "task_count",
    "pending_interrupt_count",
    "execution_tasks",
    "snapshot_complete",
    "degraded_reasons",
    "replay_status",
    "repair_status",
    "execution_readiness",
    "pause_cause",
    "approval_status",
    "approval_request_id",
    "failure_reason",
    "provider_condition",
    "repair_reason",
    "queued_messages",
]


def _populated_snapshot() -> ThreadStateSnapshot:
    return ThreadStateSnapshot(
        thread_id="t-1",
        status=ThreadStatus.RUNNING,
        messages=[
            MessageSnapshot(
                message_id="m-1",
                role="user",
                content="Hello",
                timestamp=NOW,
            ),
        ],
        tool_calls=[
            ToolCallSnapshot(
                tool_call_id="tc-1",
                title="Read file",
                kind=ToolKind.READ,
                status=ToolCallStatus.COMPLETED,
            ),
        ],
        artifacts=[
            ArtifactSnapshot(
                artifact_id="art-1",
                filename="out.txt",
                content="data",
                complete=True,
            ),
        ],
        last_sequence=42,
        checkpoint_id="cp-1",
        checkpoint_created_at=NOW,
        checkpoint_parent_id="cp-0",
        checkpoint_source="loop",
        checkpoint_step=4,
        checkpoint_updated_channels=["messages"],
        pending_write_channels=["messages"],
        pending_write_count=1,
        history_depth=2,
        next_nodes=["supervisor"],
        task_count=1,
        pending_interrupt_count=1,
        execution_tasks=[
            ExecutionTaskSnapshot(
                task_id="task-1",
                name="supervisor",
                path=["supervisor"],
                has_error=False,
                interrupt_ids=["interrupt-1"],
                interrupt_types=["permission_request"],
                has_nested_state=False,
                has_result=False,
            )
        ],
        pause_cause="permission_request",
        approval_status=ApprovalStatus.PENDING,
        approval_request_id="approval-1",
    )


class TestToolCallContentUnion:
    """The tool-call content blocks are told apart by their ``content_type``."""

    def test_text_content(self) -> None:
        """ToolCallContentText carries its own discriminator."""
        tc = ToolCallContentText(text="hello")
        assert tc.content_type == "text"

    def test_diff_content(self) -> None:
        """ToolCallContentDiff carries its discriminator and an optional old_text."""
        tc = ToolCallContentDiff(path="a.py", new_text="new")
        assert tc.content_type == "diff"
        assert tc.old_text is None

    def test_terminal_content(self) -> None:
        """ToolCallContentTerminal carries its own discriminator."""
        tc = ToolCallContentTerminal(terminal_id="term-1")
        assert tc.content_type == "terminal"

    def test_validation_dispatches_each_block_to_its_own_type(self) -> None:
        """Raw blocks resolve to the block their ``content_type`` names."""
        restored = TypeAdapter(ToolCallSnapshot).validate_python(
            {
                "tool_call_id": "tc-1",
                "title": "Edit file",
                "kind": "edit",
                "status": "completed",
                "locations": [{"path": "a.py", "line": 3}, {"path": "b.py"}],
                "content": [
                    {"content_type": "text", "text": "hello"},
                    {
                        "content_type": "diff",
                        "path": "a.py",
                        "old_text": None,
                        "new_text": "new",
                    },
                    {"content_type": "terminal", "terminal_id": "term-1"},
                ],
            }
        )
        assert restored.locations == [
            ToolCallLocation(path="a.py", line=3),
            ToolCallLocation(path="b.py"),
        ]
        assert restored.content == [
            ToolCallContentText(text="hello"),
            ToolCallContentDiff(path="a.py", new_text="new"),
            ToolCallContentTerminal(terminal_id="term-1"),
        ]

    def test_an_unknown_content_type_is_refused(self) -> None:
        """A block outside the three declared kinds is not served."""
        with pytest.raises(ValidationError):
            TypeAdapter(ToolCallSnapshot).validate_python(
                {
                    "tool_call_id": "tc-1",
                    "title": "Edit file",
                    "kind": "edit",
                    "status": "completed",
                    "content": [{"content_type": "image", "url": "x"}],
                }
            )


class TestServedSnapshot:
    """The snapshot validates, serializes and bounds as the history route serves it."""

    def test_snapshot_survives_a_json_round_trip(self) -> None:
        """Every populated field comes back from the JSON the route would emit."""
        snapshot = _populated_snapshot()
        restored = _THREAD_STATE.validate_json(_THREAD_STATE.dump_json(snapshot))
        assert restored == snapshot
        assert restored.last_sequence == 42
        assert restored.checkpoint_created_at == NOW
        assert restored.approval_status is ApprovalStatus.PENDING
        assert restored.messages[0].timestamp == NOW

    def test_snapshot_default_empty_lists(self) -> None:
        """A snapshot defaults all collections to empty lists."""
        snapshot = ThreadStateSnapshot(
            thread_id="t-2",
            status=ThreadStatus.SUBMITTED,
            last_sequence=0,
        )
        assert snapshot.messages == []
        assert snapshot.tool_calls == []
        assert snapshot.artifacts == []
        assert snapshot.plan == []
        assert snapshot.agents == []
        assert snapshot.pending_permissions == []
        assert snapshot.checkpoint_created_at is None
        assert snapshot.checkpoint_parent_id is None
        assert snapshot.checkpoint_source is None
        assert snapshot.checkpoint_step is None
        assert snapshot.checkpoint_updated_channels == []
        assert snapshot.pending_write_channels == []
        assert snapshot.pending_write_count == 0
        assert snapshot.history_depth is None
        assert snapshot.next_nodes == []
        assert snapshot.task_count == 0
        assert snapshot.pending_interrupt_count == 0
        assert snapshot.execution_tasks == []
        assert snapshot.pause_cause is None
        assert snapshot.approval_status is None
        assert snapshot.approval_request_id is None

    def test_fields_are_served_in_their_declared_order(self) -> None:
        """The JSON object lists the snapshot's fields in the order clients read."""
        served = _THREAD_STATE.dump_python(_populated_snapshot(), mode="json")
        assert list(served) == _SERVED_FIELD_ORDER

    def test_nested_blocks_are_served_in_their_declared_order(self) -> None:
        """Message, tool-call and content objects keep their field order."""
        snapshot = _populated_snapshot()
        snapshot.tool_calls[0].locations.append(ToolCallLocation(path="a.py"))
        snapshot.tool_calls[0].content.extend(
            [
                ToolCallContentText(text="hello"),
                ToolCallContentDiff(path="a.py", new_text="new"),
                ToolCallContentTerminal(terminal_id="term-1"),
            ]
        )
        served = _THREAD_STATE.dump_python(snapshot, mode="json")
        assert list(served["messages"][0]) == [
            "message_id",
            "role",
            "content",
            "agent_id",
            "timestamp",
        ]
        tool_call = served["tool_calls"][0]
        assert list(tool_call) == [
            "tool_call_id",
            "title",
            "kind",
            "status",
            "locations",
            "content",
        ]
        assert list(tool_call["locations"][0]) == ["path", "line"]
        assert [list(block) for block in tool_call["content"]] == [
            ["content_type", "text"],
            ["content_type", "path", "old_text", "new_text"],
            ["content_type", "terminal_id"],
        ]

    def test_strings_assigned_by_the_projection_steps_resolve_to_enums(self) -> None:
        """Durable strings and raw blocks leave the seam as their declared types."""
        raw: dict[str, Any] = {
            "thread_id": "t-4",
            "status": "input_required",
            "last_sequence": 3,
            "repair_status": "needs_reconciliation",
            "execution_readiness": "needs_reconciliation",
            "approval_status": "pending",
            "tool_calls": [
                {
                    "tool_call_id": "tc-1",
                    "title": "run",
                    "kind": "execute",
                    "status": "pending",
                }
            ],
            "pending_permissions": [
                {
                    "request_id": "req-1",
                    "description": "run a command",
                    "options": [
                        {
                            "option_id": "allow_once",
                            "name": "Allow once",
                            "kind": "allow_once",
                        }
                    ],
                    "tool_kind": "execute",
                }
            ],
        }
        restored = _THREAD_STATE.validate_python(raw)
        assert restored.status is ThreadStatus.INPUT_REQUIRED
        assert restored.repair_status is RepairStatus.NEEDS_RECONCILIATION
        assert restored.execution_readiness is RepairStatus.NEEDS_RECONCILIATION
        assert restored.approval_status is ApprovalStatus.PENDING
        assert restored.tool_calls[0].kind is ToolKind.EXECUTE
        assert restored.tool_calls[0].status is ToolCallStatus.PENDING
        permission = restored.pending_permissions[0]
        assert isinstance(permission, PermissionSnapshot)
        assert permission.options[0].kind is PermissionOptionKind.ALLOW_ONCE
        assert permission.tool_kind is ToolKind.EXECUTE

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("status", "not-a-status"),
            ("repair_status", "not-a-posture"),
            ("approval_status", "not-an-approval"),
            ("queued_messages", -1),
            ("repair_reason", "x" * (MAX_REPAIR_REASON_CHARS + 1)),
            ("model_assignment_digest", "a" * (MODEL_ASSIGNMENT_DIGEST_CHARS - 1)),
            ("model_assignment_digest", "a" * (MODEL_ASSIGNMENT_DIGEST_CHARS + 1)),
            ("model_assignment_digest", "Z" * MODEL_ASSIGNMENT_DIGEST_CHARS),
        ],
    )
    def test_a_value_outside_its_declared_bound_is_refused(
        self, field: str, value: object
    ) -> None:
        """The vocabulary and the caps are enforced where the snapshot is served."""
        raw: dict[str, Any] = {
            "thread_id": "t-5",
            "status": "running",
            "last_sequence": 0,
            field: value,
        }
        with pytest.raises(ValidationError):
            _THREAD_STATE.validate_python(raw)

    def test_values_at_their_declared_bound_are_served(self) -> None:
        """The caps are inclusive."""
        restored = _THREAD_STATE.validate_python(
            {
                "thread_id": "t-6",
                "status": "running",
                "last_sequence": 0,
                "queued_messages": 0,
                "repair_reason": "x" * MAX_REPAIR_REASON_CHARS,
                "model_assignment_digest": "a" * MODEL_ASSIGNMENT_DIGEST_CHARS,
            }
        )
        assert restored.queued_messages == 0
        assert restored.repair_reason == "x" * MAX_REPAIR_REASON_CHARS

    def test_documented_fields_carry_their_description_into_the_schema(self) -> None:
        """The published schema keeps the guidance on the two fields that need it."""
        schema = _THREAD_STATE.json_schema(mode="serialization")
        declared = (
            schema if "properties" in schema else schema["$defs"]["ThreadStateSnapshot"]
        )
        properties = declared["properties"]
        assert "no longer exists" in properties["checkpoint_parent_id"]["description"]
        assert "ancestry" in properties["history_depth"]["description"]

    def test_history_response_embeds_the_snapshot(self) -> None:
        """Run-history serves the snapshot itself, enums spelled as their values."""
        response = RunHistoryResponse(
            run_id="t-1",
            state=_populated_snapshot(),
            transcript_available=True,
            transcript_status=TranscriptAvailability.AVAILABLE,
        )
        served = response.model_dump(mode="json")["state"]
        assert list(served) == _SERVED_FIELD_ORDER
        assert served["status"] == "running"
        assert served["approval_status"] == "pending"
        assert served["tool_calls"][0]["kind"] == "read"
        assert served["tool_calls"][0]["status"] == "completed"
        assert served["last_sequence"] == 42


class TestExecutionTaskAcrossTheWorkerWire:
    """The execution task is one type from the worker's payload to the snapshot."""

    def test_task_crosses_the_worker_wire_intact(self) -> None:
        """A task the worker emits is rebuilt unchanged by the gateway."""
        payload = ExecutionStateProjectionPayload(
            task_count=1,
            tasks=[
                ExecutionTaskSnapshot(
                    task_id="task-9",
                    name="supervisor",
                    path=["__pregel_pull", "supervisor"],
                    has_error=True,
                    error_type="ValueError",
                    interrupt_ids=["int-1"],
                    interrupt_types=["permission_request"],
                    has_nested_state=True,
                    has_result=True,
                )
            ],
        )
        emitted = payload.model_dump(mode="json")
        assert emitted["tasks"][0] == dataclasses.asdict(payload.tasks[0])
        rebuilt = ExecutionStateProjectionPayload.model_validate(emitted)
        assert rebuilt.tasks == payload.tasks
        assert all(isinstance(task, ExecutionTaskSnapshot) for task in rebuilt.tasks)

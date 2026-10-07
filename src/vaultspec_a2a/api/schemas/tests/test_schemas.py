"""Contract schema tests for the wire-only models.

Instantiates the tool-call content blocks and the snapshot models, serializes to
JSON, and deserializes back to verify Pydantic validation and discriminated
union dispatch.
"""

from datetime import UTC, datetime

from ....graph.enums import ToolCallStatus, ToolKind
from ....thread.enums import ThreadStatus
from .. import (
    ArtifactSnapshot,
    ExecutionTaskSnapshot,
    MessageSnapshot,
    ThreadStateSnapshot,
    ToolCallContentDiff,
    ToolCallContentTerminal,
    ToolCallContentText,
    ToolCallSnapshot,
)

NOW = datetime.now(tz=UTC)


class TestToolCallContentDiscriminator:
    """ToolCallContent discriminated union dispatches correctly."""

    def test_text_content(self) -> None:
        """ToolCallContentText has correct discriminator."""
        tc = ToolCallContentText(text="hello")
        assert tc.content_type == "text"

    def test_diff_content(self) -> None:
        """ToolCallContentDiff has correct discriminator and optional old_text."""
        tc = ToolCallContentDiff(path="a.py", new_text="new")
        assert tc.content_type == "diff"
        assert tc.old_text is None

    def test_terminal_content(self) -> None:
        """ToolCallContentTerminal has correct discriminator."""
        tc = ToolCallContentTerminal(terminal_id="term-1")
        assert tc.content_type == "terminal"


class TestSnapshotModels:
    """Snapshot models for reconnection state replay."""

    def test_thread_state_snapshot(self) -> None:
        """ThreadStateSnapshot includes messages, tool calls, artifacts, sequence."""
        expected_seq = 42
        snapshot = ThreadStateSnapshot(
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
            last_sequence=expected_seq,
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
            approval_status="pending",
            approval_request_id="approval-1",
        )
        json_bytes = snapshot.model_dump_json()
        restored = ThreadStateSnapshot.model_validate_json(json_bytes)
        assert restored.last_sequence == expected_seq
        assert len(restored.messages) == 1
        assert len(restored.tool_calls) == 1
        assert len(restored.artifacts) == 1
        assert restored.checkpoint_id == "cp-1"
        assert restored.checkpoint_created_at == NOW
        assert restored.checkpoint_parent_id == "cp-0"
        assert restored.checkpoint_source == "loop"
        assert restored.checkpoint_step == 4
        assert restored.checkpoint_updated_channels == ["messages"]
        assert restored.pending_write_channels == ["messages"]
        assert restored.pending_write_count == 1
        assert restored.history_depth == 2
        assert restored.next_nodes == ["supervisor"]
        assert restored.task_count == 1
        assert restored.pending_interrupt_count == 1
        assert len(restored.execution_tasks) == 1
        assert restored.pause_cause == "permission_request"
        assert restored.approval_status == "pending"
        assert restored.approval_request_id == "approval-1"

    def test_snapshot_default_empty_lists(self) -> None:
        """ThreadStateSnapshot defaults all collections to empty lists."""
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

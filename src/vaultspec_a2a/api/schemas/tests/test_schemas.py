"""Contract schema round-trip tests.

Instantiates every model in the ServerEvent union and the snapshot models,
serializes to JSON, and deserializes back to verify Pydantic validation and
discriminated union dispatch.
"""

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, TypedDict

import pytest
from pydantic import TypeAdapter

from ....graph.enums import (
    AgentLifecycleState,
    Model,
    PermissionOptionKind,
    Provider,
    ToolCallStatus,
    ToolKind,
)
from ....thread.enums import ThreadStatus
from ....thread.models import PlanEntry
from .. import (
    AgentStatusEvent,
    AgentSummary,
    ArtifactSnapshot,
    ArtifactUpdateEvent,
    ErrorEvent,
    ExecutionTaskSnapshot,
    HeartbeatEvent,
    MessageChunkEvent,
    MessageSnapshot,
    PermissionOption,
    PermissionRequestEvent,
    PlanEntryPriority,
    PlanEntryStatus,
    PlanUpdateEvent,
    ServerEvent,
    TeamStatusEvent,
    ThoughtChunkEvent,
    ThreadStateSnapshot,
    ToolCallContentDiff,
    ToolCallContentTerminal,
    ToolCallContentText,
    ToolCallLocation,
    ToolCallSnapshot,
    ToolCallStartEvent,
    ToolCallUpdateEvent,
)

NOW = datetime.now(tz=UTC)


class Envelope(TypedDict):
    """Envelope dictionary for thread-scoped events."""

    thread_id: str
    agent_id: str
    timestamp: datetime
    sequence: int


ENVELOPE: Envelope = {
    "thread_id": "thread-1",
    "agent_id": "agent-1",
    "timestamp": NOW,
    "sequence": 1,
}

server_event_adapter = TypeAdapter(ServerEvent)


# ---------------------------------------------------------------------------
# Server event fixtures
# ---------------------------------------------------------------------------


def _agent_status() -> AgentStatusEvent:
    return AgentStatusEvent(
        **ENVELOPE,
        state=AgentLifecycleState.WORKING,
        node_name="coder",
        detail="Processing request",
    )


def _message_chunk() -> MessageChunkEvent:
    return MessageChunkEvent(
        **ENVELOPE,
        content="Hello",
        message_id="msg-1",
        finish_reason=None,
    )


def _thought_chunk() -> ThoughtChunkEvent:
    return ThoughtChunkEvent(
        **ENVELOPE,
        content="Let me think...",
        message_id="msg-2",
    )


def _tool_call_start() -> ToolCallStartEvent:
    return ToolCallStartEvent(
        **ENVELOPE,
        tool_call_id="tc-1",
        title="Read file",
        kind=ToolKind.READ,
        status=ToolCallStatus.PENDING,
        locations=[ToolCallLocation(path="src/main.py", line=42)],
        content=[ToolCallContentText(text="Reading src/main.py")],
    )


def _tool_call_update() -> ToolCallUpdateEvent:
    return ToolCallUpdateEvent(
        **ENVELOPE,
        tool_call_id="tc-1",
        status=ToolCallStatus.COMPLETED,
        content=[
            ToolCallContentDiff(
                path="src/main.py",
                old_text="print('hello')",
                new_text="print('world')",
            ),
        ],
    )


def _permission_request() -> PermissionRequestEvent:
    return PermissionRequestEvent(
        **ENVELOPE,
        request_id="perm-1",
        description="Execute shell command",
        options=[
            PermissionOption(
                option_id="opt-1",
                name="Allow once",
                kind=PermissionOptionKind.ALLOW_ONCE,
            ),
            PermissionOption(
                option_id="opt-2",
                name="Reject",
                kind=PermissionOptionKind.REJECT_ONCE,
            ),
        ],
        tool_call="tc-1",
    )


def _artifact_update() -> ArtifactUpdateEvent:
    return ArtifactUpdateEvent(
        **ENVELOPE,
        artifact_id="art-1",
        filename="output.txt",
        content="chunk data",
        append=True,
        last_chunk=False,
    )


def _plan_update() -> PlanUpdateEvent:
    return PlanUpdateEvent(
        **ENVELOPE,
        entries=[
            PlanEntry(
                content="Implement feature",
                status=PlanEntryStatus.IN_PROGRESS,
                priority=PlanEntryPriority.HIGH,
            ),
            PlanEntry(content="Write tests"),
        ],
    )


def _team_status() -> TeamStatusEvent:
    return TeamStatusEvent(
        **ENVELOPE,
        agents=[
            AgentSummary(
                agent_id="agent-1",
                node_name="coder",
                state=AgentLifecycleState.WORKING,
                provider=Provider.CLAUDE,
                model=Model.MID,
            ),
        ],
        active_thread_ids=["thread-1"],
    )


def _error_event() -> ErrorEvent:
    return ErrorEvent(
        **ENVELOPE,
        code="RATE_LIMIT",
        message="Too many requests",
        recoverable=True,
    )


def _heartbeat() -> HeartbeatEvent:
    return HeartbeatEvent(
        timestamp=NOW,
        server_uptime_seconds=3600.5,
    )


ALL_SERVER_EVENTS = [
    _agent_status,
    _message_chunk,
    _thought_chunk,
    _tool_call_start,
    _tool_call_update,
    _permission_request,
    _artifact_update,
    _plan_update,
    _team_status,
    _error_event,
    _heartbeat,
]


# ---------------------------------------------------------------------------
# Round-trip tests
# ---------------------------------------------------------------------------


class TestServerEventRoundTrip:
    """Every ServerEvent model survives JSON serialization and deserialization."""

    @pytest.mark.parametrize(
        "factory",
        ALL_SERVER_EVENTS,
        ids=[f.__name__.lstrip("_") for f in ALL_SERVER_EVENTS],
    )
    def test_round_trip(self, factory: Callable[[], Any]) -> None:
        """Every field survives the JSON wire form, not just the discriminator.

        Comparing only the resolved type and its discriminator would pass while
        the payload was dropped entirely: the union dispatches on ``type``, so a
        field excluded from serialization still round-trips to a same-typed
        object carrying defaults. Full equality is what makes this a
        content-preservation check rather than a dispatch check.
        """
        event = factory()
        json_bytes = event.model_dump_json()
        restored = server_event_adapter.validate_json(json_bytes)
        assert type(restored) is type(event)
        assert restored == event

    @pytest.mark.parametrize(
        "factory",
        ALL_SERVER_EVENTS,
        ids=[f.__name__.lstrip("_") for f in ALL_SERVER_EVENTS],
    )
    def test_model_dump_dict(self, factory: Callable[[], Any]) -> None:
        """The Python dump preserves every field, as the JSON form does."""
        event = factory()
        data = event.model_dump()
        restored = server_event_adapter.validate_python(data)
        assert type(restored) is type(event)
        assert restored == event

    def test_the_wire_form_is_the_shape_a_consumer_parses(self) -> None:
        """Pin one event's serialized keys and values against a written literal.

        Symmetric round-tripping cannot see a change that renames or re-types a
        field on BOTH sides at once - encode and decode stay agreed while every
        consumer of the published contract breaks. The expectation below is
        written out in full, against a fixed timestamp rather than the module's
        ``NOW``, so nothing in the model or the test module can move it.

        The timestamp is asserted in RFC 3339 UTC form with the ``Z``
        designator, which is what the stream actually emits. Python's
        ``datetime.isoformat`` writes ``+00:00`` for the same instant, so a
        consumer parsing strictly gets one of the two - and the difference is
        invisible to any check that compares a serialized value against
        ``isoformat``.
        """
        event = MessageChunkEvent(
            thread_id="thread-1",
            agent_id="agent-1",
            timestamp=datetime(2026, 8, 1, 12, 30, 45, 123456, tzinfo=UTC),
            sequence=1,
            content="Hello",
            message_id="msg-1",
            finish_reason=None,
        )

        assert json.loads(event.model_dump_json()) == {
            "type": "message_chunk",
            "thread_id": "thread-1",
            "agent_id": "agent-1",
            "timestamp": "2026-08-01T12:30:45.123456Z",
            "sequence": 1,
            "metadata": None,
            "content": "Hello",
            "message_id": "msg-1",
            "finish_reason": None,
        }


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

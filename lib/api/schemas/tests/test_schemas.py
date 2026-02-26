"""Contract schema round-trip tests.

Instantiates every model in the ServerEvent and ClientMessage unions,
serializes to JSON, and deserializes back to verify Pydantic validation
and discriminated union dispatch.
"""

from datetime import UTC, datetime

import pytest

from pydantic import TypeAdapter

from .. import (
    AgentControlAction,
    AgentControlCommand,
    AgentLifecycleState,
    AgentStatusEvent,
    AgentSummary,
    ArtifactSnapshot,
    ArtifactUpdateEvent,
    ClientMessage,
    ConnectedEvent,
    CreateThreadRequest,
    CreateThreadResponse,
    ErrorEvent,
    HeartbeatEvent,
    MessageChunkEvent,
    MessageSnapshot,
    PermissionOption,
    PermissionOptionKind,
    PermissionRequestEvent,
    PermissionResponseCommand,
    PermissionResponseRequest,
    PermissionResponseResult,
    PingCommand,
    PlanEntry,
    PlanEntryPriority,
    PlanEntryStatus,
    PlanUpdateEvent,
    SendMessageCommand,
    SendMessageRequest,
    ServerEvent,
    SubscribeCommand,
    TeamStatusEvent,
    TeamStatusResponse,
    ThoughtChunkEvent,
    ThreadListResponse,
    ThreadStateSnapshot,
    ThreadSummary,
    ToolCallContentDiff,
    ToolCallContentTerminal,
    ToolCallContentText,
    ToolCallLocation,
    ToolCallSnapshot,
    ToolCallStartEvent,
    ToolCallStatus,
    ToolCallUpdateEvent,
    ToolKind,
    UnsubscribeCommand,
)
from ....utils.enums import Model, Provider


NOW = datetime.now(tz=UTC)

# Shared envelope kwargs for thread-scoped events
ENVELOPE = {
    "thread_id": "thread-1",
    "agent_id": "agent-1",
    "timestamp": NOW,
    "sequence": 1,
}

server_event_adapter = TypeAdapter(ServerEvent)
client_message_adapter = TypeAdapter(ClientMessage)


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
                model=Model.CLAUDE_4_6_SONNET,
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


def _connected() -> ConnectedEvent:
    return ConnectedEvent(
        client_id="client-abc",
        server_version="0.1.0",
        active_threads=["thread-1"],
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
    _connected,
    _heartbeat,
]


# ---------------------------------------------------------------------------
# Client command fixtures
# ---------------------------------------------------------------------------


def _subscribe() -> SubscribeCommand:
    return SubscribeCommand(thread_ids=["thread-1", "thread-2"])


def _unsubscribe() -> UnsubscribeCommand:
    return UnsubscribeCommand(thread_ids=["thread-1"])


def _send_message() -> SendMessageCommand:
    return SendMessageCommand(
        thread_id="thread-1",
        content="Hello agent",
        agent_id="agent-1",
    )


def _agent_control() -> AgentControlCommand:
    return AgentControlCommand(
        thread_id="thread-1",
        agent_id="agent-1",
        action=AgentControlAction.PAUSE,
    )


def _permission_response() -> PermissionResponseCommand:
    return PermissionResponseCommand(
        request_id="perm-1",
        option_id="opt-1",
    )


def _ping() -> PingCommand:
    return PingCommand()


ALL_CLIENT_COMMANDS = [
    _subscribe,
    _unsubscribe,
    _send_message,
    _agent_control,
    _permission_response,
    _ping,
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
    def test_round_trip(self, factory: object) -> None:
        """Serialize ServerEvent to JSON and deserialize back."""
        event = factory()
        json_bytes = event.model_dump_json()
        restored = server_event_adapter.validate_json(json_bytes)
        assert type(restored) is type(event)
        assert restored.type == event.type

    @pytest.mark.parametrize(
        "factory",
        ALL_SERVER_EVENTS,
        ids=[f.__name__.lstrip("_") for f in ALL_SERVER_EVENTS],
    )
    def test_model_dump_dict(self, factory: object) -> None:
        """Serialize ServerEvent to dict and deserialize back."""
        event = factory()
        data = event.model_dump()
        restored = server_event_adapter.validate_python(data)
        assert type(restored) is type(event)


class TestClientMessageRoundTrip:
    """Every ClientMessage model survives JSON serialization and deserialization."""

    @pytest.mark.parametrize(
        "factory",
        ALL_CLIENT_COMMANDS,
        ids=[f.__name__.lstrip("_") for f in ALL_CLIENT_COMMANDS],
    )
    def test_round_trip(self, factory: object) -> None:
        """Serialize ClientMessage to JSON and deserialize back."""
        cmd = factory()
        json_bytes = cmd.model_dump_json()
        restored = client_message_adapter.validate_json(json_bytes)
        assert type(restored) is type(cmd)
        assert restored.type == cmd.type


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


class TestRESTModels:
    """REST models serialize and validate correctly."""

    def test_create_thread_request(self) -> None:
        """CreateThreadRequest serializes with provider and model."""
        req = CreateThreadRequest(
            initial_message="Hello",
            provider=Provider.CLAUDE,
            model=Model.CLAUDE_4_6_SONNET,
        )
        data = req.model_dump()
        restored = CreateThreadRequest.model_validate(data)
        assert restored.initial_message == "Hello"
        assert restored.provider == Provider.CLAUDE

    def test_create_thread_response(self) -> None:
        """CreateThreadResponse validates thread_id and status."""
        resp = CreateThreadResponse(thread_id="t-1", status="created")
        assert resp.thread_id == "t-1"

    def test_thread_list_response(self) -> None:
        """ThreadListResponse round-trip with nested ThreadSummary."""
        resp = ThreadListResponse(
            threads=[
                ThreadSummary(
                    thread_id="t-1",
                    status="active",
                    created_at=NOW,
                    updated_at=NOW,
                ),
            ],
            total=1,
        )
        json_bytes = resp.model_dump_json()
        restored = ThreadListResponse.model_validate_json(json_bytes)
        assert restored.total == 1
        assert len(restored.threads) == 1

    def test_send_message_request(self) -> None:
        """SendMessageRequest allows optional agent_id."""
        req = SendMessageRequest(content="test")
        assert req.agent_id is None

    def test_team_status_response(self) -> None:
        """TeamStatusResponse with empty lists validates."""
        resp = TeamStatusResponse(agents=[], active_threads=[], pending_permissions=[])
        data = resp.model_dump()
        restored = TeamStatusResponse.model_validate(data)
        assert restored.agents == []

    def test_permission_response_request(self) -> None:
        """PermissionResponseRequest allows optional kind."""
        req = PermissionResponseRequest(option_id="opt-1")
        assert req.kind is None

    def test_permission_response_result(self) -> None:
        """PermissionResponseResult round-trip preserves accepted flag."""
        result = PermissionResponseResult(
            request_id="perm-1", accepted=True, thread_id="t-1"
        )
        json_bytes = result.model_dump_json()
        restored = PermissionResponseResult.model_validate_json(json_bytes)
        assert restored.accepted is True


class TestSnapshotModels:
    """Snapshot models for reconnection state replay."""

    def test_thread_state_snapshot(self) -> None:
        """ThreadStateSnapshot includes messages, tool calls, artifacts, sequence."""
        expected_seq = 42
        snapshot = ThreadStateSnapshot(
            thread_id="t-1",
            status="active",
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
        )
        json_bytes = snapshot.model_dump_json()
        restored = ThreadStateSnapshot.model_validate_json(json_bytes)
        assert restored.last_sequence == expected_seq
        assert len(restored.messages) == 1
        assert len(restored.tool_calls) == 1
        assert len(restored.artifacts) == 1
        assert restored.checkpoint_id == "cp-1"

    def test_snapshot_default_empty_lists(self) -> None:
        """ThreadStateSnapshot defaults all collections to empty lists."""
        snapshot = ThreadStateSnapshot(
            thread_id="t-2",
            status="idle",
            last_sequence=0,
        )
        assert snapshot.messages == []
        assert snapshot.tool_calls == []
        assert snapshot.artifacts == []
        assert snapshot.plan == []
        assert snapshot.agents == []
        assert snapshot.pending_permissions == []

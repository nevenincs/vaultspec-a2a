"""Tests for the EventAggregator central event bus."""

import asyncio

import pytest

from ...api.schemas.enums import (
    AgentLifecycleState,
    PermissionOptionKind,
    ServerEventType,
    ToolCallStatus,
    ToolKind,
)
from ...api.schemas.events import (
    AgentStatusEvent,
    ErrorEvent,
    MessageChunkEvent,
    PermissionRequestEvent,
    TeamStatusEvent,
    ThoughtChunkEvent,
    ToolCallStartEvent,
    ToolCallUpdateEvent,
)
from .. import EventAggregator as CoreAggregator
from .. import aggregator as agg_module
from ..aggregator import (
    _CHUNK_BUFFER_MAX_BYTES,
    _CHUNK_FLUSH_INTERVAL,
    _QUEUE_MAXSIZE,
    EventAggregator,
)
from ..exceptions import EventAggregatorError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def aggregator() -> EventAggregator:
    """Return a fresh EventAggregator for each test."""
    return EventAggregator()


# ---------------------------------------------------------------------------
# Sequence management
# ---------------------------------------------------------------------------


class TestSequenceManagement:
    """Tests for per-thread monotonic sequence counters."""

    def test_initial_sequence_is_zero(self, aggregator: EventAggregator) -> None:
        """Fresh aggregator reports sequence 0 for any unseen thread."""
        assert aggregator.get_sequence("thread-1") == 0

    def test_sequence_increments(self, aggregator: EventAggregator) -> None:
        """advance_sequence returns 1 then 2 on successive calls."""
        seq1 = aggregator.advance_sequence("thread-1")
        seq2 = aggregator.advance_sequence("thread-1")
        expected_first = 1
        expected_second = 2
        assert seq1 == expected_first
        assert seq2 == expected_second

    def test_sequences_are_per_thread(self, aggregator: EventAggregator) -> None:
        """Sequence counters are independent across threads."""
        aggregator.advance_sequence("thread-a")
        aggregator.advance_sequence("thread-a")
        aggregator.advance_sequence("thread-b")
        expected_a = 2
        expected_b = 1
        assert aggregator.get_sequence("thread-a") == expected_a
        assert aggregator.get_sequence("thread-b") == expected_b


# ---------------------------------------------------------------------------
# Subscriber management
# ---------------------------------------------------------------------------


class TestSubscriberManagement:
    """Tests for subscriber registration and thread subscription management."""

    def test_add_subscriber_returns_bounded_queue(
        self, aggregator: EventAggregator
    ) -> None:
        """add_subscriber returns an asyncio.Queue with maxsize=_QUEUE_MAXSIZE."""
        queue = aggregator.add_subscriber("client-1")
        assert isinstance(queue, asyncio.Queue)
        assert queue.maxsize == _QUEUE_MAXSIZE

    def test_remove_subscriber(self, aggregator: EventAggregator) -> None:
        """remove_subscriber is idempotent — double-remove does not raise."""
        aggregator.add_subscriber("client-1")
        aggregator.remove_subscriber("client-1")
        aggregator.remove_subscriber("client-1")

    def test_subscribe_unregistered_client_raises(
        self, aggregator: EventAggregator
    ) -> None:
        """Subscribe raises EventAggregatorError for unknown client_id."""
        with pytest.raises(EventAggregatorError, match="not registered"):
            aggregator.subscribe("unknown", ["thread-1"])

    def test_subscribe_to_threads(self, aggregator: EventAggregator) -> None:
        """Subscribe records thread_ids for the given client."""
        aggregator.add_subscriber("client-1")
        aggregator.subscribe("client-1", ["thread-a", "thread-b"])
        assert aggregator.get_subscriptions("client-1") == {"thread-a", "thread-b"}

    def test_unsubscribe_from_threads(self, aggregator: EventAggregator) -> None:
        """Unsubscribe removes the specified thread_id from the subscription set."""
        aggregator.add_subscriber("client-1")
        aggregator.subscribe("client-1", ["thread-a", "thread-b"])
        aggregator.unsubscribe("client-1", ["thread-a"])
        assert aggregator.get_subscriptions("client-1") == {"thread-b"}

    def test_get_active_thread_ids(self, aggregator: EventAggregator) -> None:
        """get_active_thread_ids returns a sorted union of all subscribed threads."""
        aggregator.add_subscriber("c1")
        aggregator.add_subscriber("c2")
        aggregator.subscribe("c1", ["t1", "t2"])
        aggregator.subscribe("c2", ["t2", "t3"])
        active = aggregator.get_active_thread_ids()
        assert active == ["t1", "t2", "t3"]  # sorted


# ---------------------------------------------------------------------------
# Event emission and broadcasting
# ---------------------------------------------------------------------------


class TestEventEmission:
    """Tests for the high-level emit_* helpers."""

    @pytest.mark.asyncio
    async def test_emit_agent_status(self, aggregator: EventAggregator) -> None:
        """emit_agent_status delivers an AgentStatusEvent with correct fields."""
        queue = aggregator.add_subscriber("client-1")
        aggregator.subscribe("client-1", ["thread-1"])

        await aggregator.emit_agent_status(
            thread_id="thread-1",
            agent_id="agent-1",
            node_name="worker",
            state=AgentLifecycleState.WORKING,
            detail="processing task",
        )

        event = queue.get_nowait()
        assert isinstance(event, AgentStatusEvent)
        assert event.type == ServerEventType.AGENT_STATUS
        assert event.thread_id == "thread-1"
        assert event.agent_id == "agent-1"
        assert event.node_name == "worker"
        assert event.state == AgentLifecycleState.WORKING
        assert event.detail == "processing task"
        expected_seq = 1
        assert event.sequence == expected_seq

    @pytest.mark.asyncio
    async def test_emit_message_chunk(self, aggregator: EventAggregator) -> None:
        """emit_message_chunk delivers a MessageChunkEvent with correct content."""
        queue = aggregator.add_subscriber("client-1")
        aggregator.subscribe("client-1", ["thread-1"])

        await aggregator.emit_message_chunk(
            thread_id="thread-1",
            agent_id="agent-1",
            content="Hello",
            message_id="msg-1",
        )

        event = queue.get_nowait()
        assert isinstance(event, MessageChunkEvent)
        assert event.content == "Hello"
        assert event.message_id == "msg-1"

    @pytest.mark.asyncio
    async def test_emit_thought_chunk(self, aggregator: EventAggregator) -> None:
        """emit_thought_chunk delivers a ThoughtChunkEvent."""
        queue = aggregator.add_subscriber("client-1")
        aggregator.subscribe("client-1", ["thread-1"])

        await aggregator.emit_thought_chunk(
            thread_id="thread-1",
            agent_id="agent-1",
            content="thinking...",
            message_id="msg-1",
        )

        event = queue.get_nowait()
        assert isinstance(event, ThoughtChunkEvent)
        assert event.content == "thinking..."

    @pytest.mark.asyncio
    async def test_emit_tool_call_start(self, aggregator: EventAggregator) -> None:
        """emit_tool_call_start delivers a ToolCallStartEvent with PENDING status."""
        queue = aggregator.add_subscriber("client-1")
        aggregator.subscribe("client-1", ["thread-1"])

        await aggregator.emit_tool_call_start(
            thread_id="thread-1",
            agent_id="agent-1",
            tool_call_id="tc-1",
            title="read_file",
            kind=ToolKind.READ,
        )

        event = queue.get_nowait()
        assert isinstance(event, ToolCallStartEvent)
        assert event.tool_call_id == "tc-1"
        assert event.title == "read_file"
        assert event.kind == ToolKind.READ
        assert event.status == ToolCallStatus.PENDING

    @pytest.mark.asyncio
    async def test_emit_permission_request(self, aggregator: EventAggregator) -> None:
        """emit_permission_request delivers a PermissionRequestEvent."""
        queue = aggregator.add_subscriber("client-1")
        aggregator.subscribe("client-1", ["thread-1"])

        await aggregator.emit_permission_request(
            thread_id="thread-1",
            agent_id="agent-1",
            request_id="perm-1",
            description="Allow file write?",
            options=[
                {
                    "option_id": "allow",
                    "name": "Allow",
                    "kind": "allow_once",
                },
                {
                    "option_id": "deny",
                    "name": "Deny",
                    "kind": "reject_once",
                },
            ],
        )

        event = queue.get_nowait()
        assert isinstance(event, PermissionRequestEvent)
        assert event.request_id == "perm-1"
        expected_option_count = 2
        assert len(event.options) == expected_option_count
        assert event.options[0].option_id == "allow"
        assert event.options[0].kind == PermissionOptionKind.ALLOW_ONCE

    @pytest.mark.asyncio
    async def test_emit_error(self, aggregator: EventAggregator) -> None:
        """emit_error delivers an ErrorEvent with the supplied code."""
        queue = aggregator.add_subscriber("client-1")
        aggregator.subscribe("client-1", ["thread-1"])

        await aggregator.emit_error(
            thread_id="thread-1",
            code="PROVIDER_TIMEOUT",
            message="Claude API timed out",
            recoverable=True,
        )

        event = queue.get_nowait()
        assert isinstance(event, ErrorEvent)
        assert event.code == "PROVIDER_TIMEOUT"
        assert event.recoverable is True

    @pytest.mark.asyncio
    async def test_emit_team_status(self, aggregator: EventAggregator) -> None:
        """emit_team_status delivers a TeamStatusEvent with agent summaries."""
        queue = aggregator.add_subscriber("client-1")
        aggregator.subscribe("client-1", ["thread-1"])

        await aggregator.emit_team_status(
            thread_id="thread-1",
            agents=[
                {
                    "agent_id": "a1",
                    "node_name": "worker",
                    "state": AgentLifecycleState.WORKING,
                    "provider": "claude",
                    "model": "mid",
                },
            ],
            active_thread_ids=["thread-1"],
        )

        event = queue.get_nowait()
        assert isinstance(event, TeamStatusEvent)
        expected_agent_count = 1
        assert len(event.agents) == expected_agent_count
        assert event.agents[0].agent_id == "a1"


# ---------------------------------------------------------------------------
# Thread-scoped event isolation
# ---------------------------------------------------------------------------


class TestThreadIsolation:
    """Tests that events are only delivered to clients subscribed to the thread."""

    @pytest.mark.asyncio
    async def test_events_only_go_to_subscribed_clients(
        self, aggregator: EventAggregator
    ) -> None:
        """An event on thread-a must not reach a client subscribed only to thread-b."""
        q1 = aggregator.add_subscriber("client-1")
        q2 = aggregator.add_subscriber("client-2")
        aggregator.subscribe("client-1", ["thread-a"])
        aggregator.subscribe("client-2", ["thread-b"])

        await aggregator.emit_message_chunk(
            thread_id="thread-a",
            agent_id="agent-1",
            content="for client-1 only",
            message_id="msg-1",
        )

        assert q2.qsize() == 0
        assert q1.qsize() == 1

    @pytest.mark.asyncio
    async def test_multiple_subscribers_same_thread(
        self, aggregator: EventAggregator
    ) -> None:
        """All clients subscribed to the same thread receive each event."""
        q1 = aggregator.add_subscriber("client-1")
        q2 = aggregator.add_subscriber("client-2")
        aggregator.subscribe("client-1", ["thread-1"])
        aggregator.subscribe("client-2", ["thread-1"])

        await aggregator.emit_message_chunk(
            thread_id="thread-1",
            agent_id="agent-1",
            content="shared event",
            message_id="msg-1",
        )

        assert q1.qsize() == 1
        assert q2.qsize() == 1


# ---------------------------------------------------------------------------
# Sequence numbering on emitted events
# ---------------------------------------------------------------------------


class TestSequenceOnEvents:
    """Tests that emitted events carry correct monotonic sequence numbers."""

    @pytest.mark.asyncio
    async def test_sequence_increments_across_events(
        self, aggregator: EventAggregator
    ) -> None:
        """Consecutive events on the same thread get sequences 1, 2."""
        queue = aggregator.add_subscriber("client-1")
        aggregator.subscribe("client-1", ["thread-1"])

        await aggregator.emit_message_chunk(
            thread_id="thread-1",
            agent_id="agent-1",
            content="first",
            message_id="msg-1",
        )
        await aggregator.emit_message_chunk(
            thread_id="thread-1",
            agent_id="agent-1",
            content="second",
            message_id="msg-2",
        )

        e1 = queue.get_nowait()
        e2 = queue.get_nowait()
        first_seq = 1
        second_seq = 2
        assert e1.sequence == first_seq
        assert e2.sequence == second_seq

    @pytest.mark.asyncio
    async def test_sequences_independent_per_thread(
        self, aggregator: EventAggregator
    ) -> None:
        """Sequence counters restart from 1 for each distinct thread."""
        queue = aggregator.add_subscriber("client-1")
        aggregator.subscribe("client-1", ["thread-a", "thread-b"])

        await aggregator.emit_message_chunk(
            thread_id="thread-a",
            agent_id="agent-1",
            content="a-1",
            message_id="msg-1",
        )
        await aggregator.emit_message_chunk(
            thread_id="thread-b",
            agent_id="agent-1",
            content="b-1",
            message_id="msg-2",
        )
        await aggregator.emit_message_chunk(
            thread_id="thread-a",
            agent_id="agent-1",
            content="a-2",
            message_id="msg-3",
        )

        events = [queue.get_nowait() for _ in range(3)]
        a_events = [e for e in events if e.thread_id == "thread-a"]
        b_events = [e for e in events if e.thread_id == "thread-b"]

        first_seq = 1
        second_seq = 2
        assert a_events[0].sequence == first_seq
        assert a_events[1].sequence == second_seq
        assert b_events[0].sequence == first_seq


# ---------------------------------------------------------------------------
# LangGraph event processing with langgraph_node filtering
# ---------------------------------------------------------------------------


class TestLangGraphEventProcessing:
    """Tests for the LangGraph astream_events adapter."""

    @pytest.mark.asyncio
    async def test_on_chat_model_stream_batched(
        self, aggregator: EventAggregator
    ) -> None:
        """on_chat_model_stream events are batched and flushed after 50ms."""
        queue = aggregator.add_subscriber("client-1")
        aggregator.subscribe("client-1", ["thread-1"])

        class FakeChunk:
            content = "Hello world"

        await aggregator.process_langgraph_event(
            event_data={
                "event": "on_chat_model_stream",
                "run_id": "run-123",
                "metadata": {},
                "data": {"chunk": FakeChunk()},
            },
            thread_id="thread-1",
            agent_id="agent-1",
        )

        # Event is buffered, not yet emitted
        assert queue.empty()

        # Wait for the 50ms flush timer
        await asyncio.sleep(_CHUNK_FLUSH_INTERVAL + 0.02)

        event = queue.get_nowait()
        assert isinstance(event, MessageChunkEvent)
        assert event.content == "Hello world"
        assert event.message_id == "run-123"

    @pytest.mark.asyncio
    async def test_on_chat_model_stream_4kb_threshold(
        self, aggregator: EventAggregator
    ) -> None:
        """Token chunks flush immediately when buffer exceeds 4KB."""
        queue = aggregator.add_subscriber("client-1")
        aggregator.subscribe("client-1", ["thread-1"])

        # Build a chunk larger than 4KB
        large_content = "x" * (_CHUNK_BUFFER_MAX_BYTES + 100)

        class BigChunk:
            content = large_content

        await aggregator.process_langgraph_event(
            event_data={
                "event": "on_chat_model_stream",
                "run_id": "run-big",
                "metadata": {},
                "data": {"chunk": BigChunk()},
            },
            thread_id="thread-1",
            agent_id="agent-1",
        )

        # Should flush immediately (4KB threshold exceeded)
        event = queue.get_nowait()
        assert isinstance(event, MessageChunkEvent)
        assert len(event.content) > _CHUNK_BUFFER_MAX_BYTES

    @pytest.mark.asyncio
    async def test_on_tool_start_with_node_metadata(
        self, aggregator: EventAggregator
    ) -> None:
        """on_tool_start only emits when langgraph_node is set."""
        queue = aggregator.add_subscriber("client-1")
        aggregator.subscribe("client-1", ["thread-1"])

        await aggregator.process_langgraph_event(
            event_data={
                "event": "on_tool_start",
                "run_id": "run-456",
                "name": "search_code",
                "metadata": {"langgraph_node": "coder"},
            },
            thread_id="thread-1",
            agent_id="agent-1",
        )

        event = queue.get_nowait()
        assert isinstance(event, ToolCallStartEvent)
        assert event.tool_call_id == "run-456"
        assert event.title == "search_code"

    @pytest.mark.asyncio
    async def test_on_tool_start_without_node_filtered(
        self, aggregator: EventAggregator
    ) -> None:
        """on_tool_start without langgraph_node is filtered out."""
        queue = aggregator.add_subscriber("client-1")
        aggregator.subscribe("client-1", ["thread-1"])

        await aggregator.process_langgraph_event(
            event_data={
                "event": "on_tool_start",
                "run_id": "run-456",
                "name": "internal_tool",
                "metadata": {},  # No langgraph_node
            },
            thread_id="thread-1",
            agent_id="agent-1",
        )

        assert queue.empty()

    @pytest.mark.asyncio
    async def test_on_tool_end_with_node_metadata(
        self, aggregator: EventAggregator
    ) -> None:
        """on_tool_end with langgraph_node emits a ToolCallUpdateEvent."""
        queue = aggregator.add_subscriber("client-1")
        aggregator.subscribe("client-1", ["thread-1"])

        await aggregator.process_langgraph_event(
            event_data={
                "event": "on_tool_end",
                "run_id": "run-456",
                "metadata": {"langgraph_node": "coder"},
            },
            thread_id="thread-1",
            agent_id="agent-1",
        )

        event = queue.get_nowait()
        assert isinstance(event, ToolCallUpdateEvent)
        assert event.tool_call_id == "run-456"
        assert event.status == ToolCallStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_on_tool_end_without_node_filtered(
        self, aggregator: EventAggregator
    ) -> None:
        """on_tool_end without langgraph_node is filtered out."""
        queue = aggregator.add_subscriber("client-1")
        aggregator.subscribe("client-1", ["thread-1"])

        await aggregator.process_langgraph_event(
            event_data={
                "event": "on_tool_end",
                "run_id": "run-456",
                "metadata": {},
            },
            thread_id="thread-1",
            agent_id="agent-1",
        )

        assert queue.empty()

    @pytest.mark.asyncio
    async def test_on_chain_start_emits_working(
        self, aggregator: EventAggregator
    ) -> None:
        """on_chain_start with langgraph_node -> agent_status(working)."""
        queue = aggregator.add_subscriber("client-1")
        aggregator.subscribe("client-1", ["thread-1"])

        await aggregator.process_langgraph_event(
            event_data={
                "event": "on_chain_start",
                "run_id": "run-chain-1",
                "name": "coder",
                "metadata": {"langgraph_node": "coder"},
            },
            thread_id="thread-1",
            agent_id="agent-1",
        )

        event = queue.get_nowait()
        assert isinstance(event, AgentStatusEvent)
        assert event.state == AgentLifecycleState.WORKING
        assert event.node_name == "coder"

    @pytest.mark.asyncio
    async def test_on_chain_end_emits_idle(self, aggregator: EventAggregator) -> None:
        """on_chain_end with langgraph_node -> agent_status(idle)."""
        queue = aggregator.add_subscriber("client-1")
        aggregator.subscribe("client-1", ["thread-1"])

        await aggregator.process_langgraph_event(
            event_data={
                "event": "on_chain_end",
                "run_id": "run-chain-1",
                "name": "coder",
                "metadata": {"langgraph_node": "coder"},
            },
            thread_id="thread-1",
            agent_id="agent-1",
        )

        event = queue.get_nowait()
        assert isinstance(event, AgentStatusEvent)
        assert event.state == AgentLifecycleState.IDLE
        assert event.node_name == "coder"

    @pytest.mark.asyncio
    async def test_on_chain_start_without_node_filtered(
        self, aggregator: EventAggregator
    ) -> None:
        """on_chain_start without langgraph_node is filtered (sub-runnable)."""
        queue = aggregator.add_subscriber("client-1")
        aggregator.subscribe("client-1", ["thread-1"])

        await aggregator.process_langgraph_event(
            event_data={
                "event": "on_chain_start",
                "run_id": "run-sub",
                "name": "RunnableSequence",
                "metadata": {},  # No langgraph_node = sub-runnable
            },
            thread_id="thread-1",
            agent_id="agent-1",
        )

        assert queue.empty()

    @pytest.mark.asyncio
    async def test_on_custom_event_emits_thought_chunk(
        self, aggregator: EventAggregator
    ) -> None:
        """on_custom_event maps to ThoughtChunkEvent."""
        queue = aggregator.add_subscriber("client-1")
        aggregator.subscribe("client-1", ["thread-1"])

        await aggregator.process_langgraph_event(
            event_data={
                "event": "on_custom_event",
                "run_id": "run-thought-1",
                "metadata": {"langgraph_node": "coder"},
                "data": {"content": "Let me think about this..."},
            },
            thread_id="thread-1",
            agent_id="agent-1",
        )

        event = queue.get_nowait()
        assert isinstance(event, ThoughtChunkEvent)
        assert event.content == "Let me think about this..."

    @pytest.mark.asyncio
    async def test_unknown_event_does_not_emit(
        self, aggregator: EventAggregator
    ) -> None:
        """Events outside the known set are silently filtered."""
        queue = aggregator.add_subscriber("client-1")
        aggregator.subscribe("client-1", ["thread-1"])

        await aggregator.process_langgraph_event(
            event_data={
                "event": "on_retriever_start",
                "run_id": "run-789",
                "metadata": {},
            },
            thread_id="thread-1",
            agent_id="agent-1",
        )

        assert queue.empty()

    @pytest.mark.asyncio
    async def test_empty_content_chunk_not_buffered(
        self, aggregator: EventAggregator
    ) -> None:
        """Empty-string content chunks are not buffered or emitted."""
        queue = aggregator.add_subscriber("client-1")
        aggregator.subscribe("client-1", ["thread-1"])

        class EmptyChunk:
            content = ""

        await aggregator.process_langgraph_event(
            event_data={
                "event": "on_chat_model_stream",
                "run_id": "run-000",
                "metadata": {},
                "data": {"chunk": EmptyChunk()},
            },
            thread_id="thread-1",
            agent_id="agent-1",
        )

        # Wait for potential flush
        await asyncio.sleep(_CHUNK_FLUSH_INTERVAL + 0.02)
        assert queue.empty()


# ---------------------------------------------------------------------------
# Token chunk batching
# ---------------------------------------------------------------------------


class TestTokenChunkBatching:
    """Tests for the 50ms / 4KB token chunk batching mechanism."""

    @pytest.mark.asyncio
    async def test_multiple_chunks_batched_into_one(
        self, aggregator: EventAggregator
    ) -> None:
        """Multiple small token chunks are combined into one event."""
        queue = aggregator.add_subscriber("client-1")
        aggregator.subscribe("client-1", ["thread-1"])

        for token in ["Hello", " ", "world"]:

            class Chunk:
                content = token

            await aggregator.process_langgraph_event(
                event_data={
                    "event": "on_chat_model_stream",
                    "run_id": "run-batch",
                    "metadata": {},
                    "data": {"chunk": Chunk()},
                },
                thread_id="thread-1",
                agent_id="agent-1",
            )

        # All buffered, nothing emitted yet
        assert queue.empty()

        # Wait for flush
        await asyncio.sleep(_CHUNK_FLUSH_INTERVAL + 0.02)

        event = queue.get_nowait()
        assert isinstance(event, MessageChunkEvent)
        assert event.content == "Hello world"

    @pytest.mark.asyncio
    async def test_flush_on_shutdown(self, aggregator: EventAggregator) -> None:
        """Remaining chunk buffer is flushed via flush_chunk_buffer."""
        queue = aggregator.add_subscriber("client-1")
        aggregator.subscribe("client-1", ["thread-1"])

        # Buffer a chunk via the public API
        await aggregator.buffer_message_chunk(
            thread_id="thread-1",
            agent_id="agent-1",
            content="pending data",
            message_id="msg-flush",
        )

        assert queue.empty()

        # Explicit flush via public API
        await aggregator.flush_chunk_buffer("thread-1")

        event = queue.get_nowait()
        assert isinstance(event, MessageChunkEvent)
        assert event.content == "pending data"


# ---------------------------------------------------------------------------
# Tool call update debouncing
# ---------------------------------------------------------------------------


class TestToolCallUpdateDebouncing:
    """Tests for the 100ms per-tool-call debounce on update events."""

    @pytest.mark.asyncio
    async def test_first_update_emits_immediately(
        self, aggregator: EventAggregator
    ) -> None:
        """The first tool call update for a given key is emitted without delay."""
        queue = aggregator.add_subscriber("client-1")
        aggregator.subscribe("client-1", ["thread-1"])

        await aggregator.emit_tool_call_update(
            thread_id="thread-1",
            agent_id="agent-1",
            tool_call_id="tc-1",
            status=ToolCallStatus.IN_PROGRESS,
        )

        assert queue.qsize() == 1
        event = queue.get_nowait()
        assert isinstance(event, ToolCallUpdateEvent)
        assert event.status == ToolCallStatus.IN_PROGRESS


# ---------------------------------------------------------------------------
# Shutdown
# ---------------------------------------------------------------------------


class TestShutdown:
    """Tests for the aggregator shutdown / state-clear path."""

    @pytest.mark.asyncio
    async def test_shutdown_clears_state(self, aggregator: EventAggregator) -> None:
        """shutdown() drains all internal state tables to zero length."""
        aggregator.add_subscriber("client-1")
        aggregator.subscribe("client-1", ["thread-1"])
        aggregator.advance_sequence("thread-1")

        await aggregator.shutdown()

        assert aggregator.subscriber_count() == 0
        assert aggregator.subscription_count() == 0
        assert aggregator.sequence_count() == 0


# ---------------------------------------------------------------------------
# __all__ exports
# ---------------------------------------------------------------------------


class TestExports:
    """Tests that the aggregator module and core facade export expected names."""

    def test_all_defined(self) -> None:
        """Aggregator module declares __all__ containing EventAggregator."""
        assert hasattr(agg_module, "__all__")
        assert "EventAggregator" in agg_module.__all__

    def test_facade_reexports(self) -> None:
        """lib.core re-exports EventAggregator and it is the same class."""
        assert CoreAggregator is EventAggregator

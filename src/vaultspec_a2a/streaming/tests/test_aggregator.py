"""Tests for the EventAggregator central event bus."""

import asyncio
from datetime import UTC, datetime
from typing import ClassVar, cast

import pytest
from langchain_core.messages import AIMessageChunk
from langgraph.errors import GraphInterrupt

from vaultspec_a2a.thread.errors import EventAggregatorError

from ...domain_config import domain_config
from ...graph.enums import (
    AgentLifecycleState,
    PermissionOptionKind,
    ToolCallStatus,
    ToolKind,
)
from ...graph.events import (
    AgentStatus,
    ErrorOccurred,
    MessageChunk,
    PermissionRequest,
    TeamStatus,
    ThoughtChunk,
    ToolCallStart,
    ToolCallUpdate,
)
from .. import EventAggregator as CoreAggregator
from .. import aggregator as agg_module
from ..aggregator import EventAggregator, SequencedEvent

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
        """add_subscriber returns a bounded Queue."""
        queue = aggregator.add_subscriber("client-1")
        assert isinstance(queue, asyncio.Queue)
        assert queue.maxsize == domain_config.event_queue_maxsize

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

        sequenced = queue.get_nowait()
        assert isinstance(sequenced, SequencedEvent)
        event = sequenced.event
        assert isinstance(event, AgentStatus)
        assert event.thread_id == "thread-1"
        assert event.agent_id == "agent-1"
        assert event.node_name == "worker"
        assert event.state == AgentLifecycleState.WORKING
        assert event.detail == "processing task"
        expected_seq = 1
        assert sequenced.sequence == expected_seq

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

        sequenced = queue.get_nowait()
        event = sequenced.event
        assert isinstance(event, MessageChunk)
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

        sequenced = queue.get_nowait()
        event = sequenced.event
        assert isinstance(event, ThoughtChunk)
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

        sequenced = queue.get_nowait()
        event = sequenced.event
        assert isinstance(event, ToolCallStart)
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

        sequenced = queue.get_nowait()
        event = sequenced.event
        assert isinstance(event, PermissionRequest)
        assert event.request_id == "perm-1"
        expected_option_count = 2
        assert len(event.options) == expected_option_count
        assert event.options[0]["option_id"] == "allow"
        assert event.options[0]["kind"] == str(PermissionOptionKind.ALLOW_ONCE)

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

        sequenced = queue.get_nowait()
        event = sequenced.event
        assert isinstance(event, ErrorOccurred)
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

        sequenced = queue.get_nowait()
        event = sequenced.event
        assert isinstance(event, TeamStatus)
        expected_agent_count = 1
        assert len(event.agents) == expected_agent_count
        assert event.agents[0]["agent_id"] == "a1"

    @pytest.mark.asyncio
    async def test_emit_team_status_node_metadata(
        self,
        aggregator: EventAggregator,
    ) -> None:
        """register_graph populates metadata; emit_team_status reads it."""
        queue = aggregator.add_subscriber("client-1")
        aggregator.subscribe("client-1", ["thread-1"])

        # Policy exception: register_graph() uses duck typing via getattr(graph,
        # "nodes") and getattr(node, "metadata"). Constructing a real compiled
        # LangGraph graph requires a full StateGraph definition, checkpointer, and
        # channel setup — none of which are relevant to testing metadata caching.
        # These minimal structural stubs satisfy the protocol without LLM/IO deps.
        class _MinimalNode:
            metadata: ClassVar[dict[str, str]] = {
                "role": "reviewer",
                "display_name": "Code Reviewer",
                "description": "Reviews code for correctness",
            }

        class _MinimalGraph:
            nodes: ClassVar[dict[str, _MinimalNode]] = {"worker": _MinimalNode()}

        aggregator.register_graph(_MinimalGraph())  # type: ignore[arg-type]

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

        sequenced = queue.get_nowait()
        event = sequenced.event
        assert isinstance(event, TeamStatus)
        assert event.agents[0]["role"] == "reviewer"
        assert event.agents[0]["display_name"] == "Code Reviewer"
        assert event.agents[0]["description"] == "Reviews code for correctness"


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

        s1 = cast("SequencedEvent", queue.get_nowait())
        s2 = cast("SequencedEvent", queue.get_nowait())
        first_seq = 1
        second_seq = 2
        assert s1.sequence == first_seq
        assert s2.sequence == second_seq

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

        sequenced_all = [cast("SequencedEvent", queue.get_nowait()) for _ in range(3)]
        a_events = [s for s in sequenced_all if s.event.thread_id == "thread-a"]
        b_events = [s for s in sequenced_all if s.event.thread_id == "thread-b"]

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

        await aggregator.process_langgraph_event(
            event_data={
                "event": "on_chat_model_stream",
                "run_id": "run-123",
                "metadata": {},
                "data": {"chunk": AIMessageChunk(content="Hello world")},
            },
            thread_id="thread-1",
            agent_id="agent-1",
        )

        # Event is buffered, not yet emitted
        assert queue.empty()

        # Wait for the 50ms flush timer
        await asyncio.sleep(domain_config.chunk_flush_interval_seconds + 0.02)

        sequenced = queue.get_nowait()
        event = sequenced.event
        assert isinstance(event, MessageChunk)
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
        large_content = "x" * (domain_config.chunk_buffer_max_bytes + 100)

        await aggregator.process_langgraph_event(
            event_data={
                "event": "on_chat_model_stream",
                "run_id": "run-big",
                "metadata": {},
                "data": {"chunk": AIMessageChunk(content=large_content)},
            },
            thread_id="thread-1",
            agent_id="agent-1",
        )

        # Should flush immediately (4KB threshold exceeded)
        sequenced = queue.get_nowait()
        event = sequenced.event
        assert isinstance(event, MessageChunk)
        assert len(event.content) > domain_config.chunk_buffer_max_bytes

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

        sequenced = queue.get_nowait()
        event = sequenced.event
        assert isinstance(event, ToolCallStart)
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

        sequenced = queue.get_nowait()
        event = sequenced.event
        assert isinstance(event, ToolCallUpdate)
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

        sequenced = queue.get_nowait()
        event = sequenced.event
        assert isinstance(event, AgentStatus)
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

        sequenced = queue.get_nowait()
        event = sequenced.event
        assert isinstance(event, AgentStatus)
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

        sequenced = queue.get_nowait()
        event = sequenced.event
        assert isinstance(event, ThoughtChunk)
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

        await aggregator.process_langgraph_event(
            event_data={
                "event": "on_chat_model_stream",
                "run_id": "run-000",
                "metadata": {},
                "data": {"chunk": AIMessageChunk(content="")},
            },
            thread_id="thread-1",
            agent_id="agent-1",
        )

        # Wait for potential flush
        await asyncio.sleep(domain_config.chunk_flush_interval_seconds + 0.02)
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
            await aggregator.process_langgraph_event(
                event_data={
                    "event": "on_chat_model_stream",
                    "run_id": "run-batch",
                    "metadata": {},
                    "data": {"chunk": AIMessageChunk(content=token)},
                },
                thread_id="thread-1",
                agent_id="agent-1",
            )

        # All buffered, nothing emitted yet
        assert queue.empty()

        # Wait for flush
        await asyncio.sleep(domain_config.chunk_flush_interval_seconds + 0.02)

        sequenced = queue.get_nowait()
        event = sequenced.event
        assert isinstance(event, MessageChunk)
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

        sequenced = queue.get_nowait()
        event = sequenced.event
        assert isinstance(event, MessageChunk)
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
        sequenced = queue.get_nowait()
        event = sequenced.event
        assert isinstance(event, ToolCallUpdate)
        assert event.status == ToolCallStatus.IN_PROGRESS


# ---------------------------------------------------------------------------
# Backpressure: drop-oldest strategy
# ---------------------------------------------------------------------------


class TestBackpressure:
    """Tests for the drop-oldest broadcast strategy when a client queue is full."""

    @pytest.mark.asyncio
    async def test_full_queue_drops_oldest_event(
        self, aggregator: EventAggregator
    ) -> None:
        """When the subscriber queue is full, the oldest event is dropped and
        the newest is inserted so _broadcast never blocks."""
        queue = aggregator.add_subscriber("client-1")
        aggregator.subscribe("client-1", ["thread-1"])

        # Fill the queue to capacity with distinct content
        for i in range(domain_config.event_queue_maxsize):
            await aggregator.emit_message_chunk(
                thread_id="thread-1",
                agent_id="agent-1",
                content=f"msg-{i}",
                message_id=f"id-{i}",
            )

        assert queue.full()

        # One more event: should drop the oldest (msg-0) and enqueue this one
        await aggregator.emit_message_chunk(
            thread_id="thread-1",
            agent_id="agent-1",
            content="newest",
            message_id="id-new",
        )

        # Queue remains at capacity (not exceeding maxsize)
        assert queue.qsize() == domain_config.event_queue_maxsize

        # First event dequeued is msg-1 (msg-0 was dropped)
        first = queue.get_nowait()
        assert isinstance(first, SequencedEvent)
        assert isinstance(first.event, MessageChunk)
        assert first.event.content == "msg-1"

        # Last event dequeued is the newly inserted one
        items = [queue.get_nowait() for _ in range(queue.qsize())]
        last = items[-1]
        assert isinstance(last, SequencedEvent)
        assert isinstance(last.event, MessageChunk)
        assert last.event.content == "newest"

    @pytest.mark.asyncio
    async def test_slow_client_does_not_block_fast_client(
        self, aggregator: EventAggregator
    ) -> None:
        """A full slow-client queue must not stall delivery to a fast client."""
        q_fast = aggregator.add_subscriber("fast")
        q_slow = aggregator.add_subscriber("slow")
        aggregator.subscribe("fast", ["thread-1"])
        aggregator.subscribe("slow", ["thread-1"])

        # Pre-fill the slow queue to capacity
        for i in range(domain_config.event_queue_maxsize):
            q_slow.put_nowait(_make_sequenced_event(aggregator, f"pre-{i}"))

        assert q_slow.full()

        # Broadcast one more event — must not block
        await aggregator.emit_message_chunk(
            thread_id="thread-1",
            agent_id="agent-1",
            content="new-event",
            message_id="id-new",
        )

        # Fast client received the event
        assert q_fast.qsize() == 1
        fast_sequenced = q_fast.get_nowait()
        assert isinstance(fast_sequenced, SequencedEvent)
        assert isinstance(fast_sequenced.event, MessageChunk)
        assert fast_sequenced.event.content == "new-event"

        # Slow client still at capacity (oldest was dropped, newest inserted)
        assert q_slow.qsize() == domain_config.event_queue_maxsize


def _make_sequenced_event(aggregator: EventAggregator, content: str) -> SequencedEvent:
    """Helper: return a SequencedEvent without broadcasting it."""
    return SequencedEvent(
        event=MessageChunk(
            thread_id="thread-1",
            agent_id="agent-1",
            timestamp=datetime.now(UTC).timestamp(),
            content=content,
            message_id="helper",
        ),
        sequence=aggregator.advance_sequence("thread-1"),
    )


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
        """streaming package re-exports EventAggregator and it is the same class."""
        assert CoreAggregator is EventAggregator


# ---------------------------------------------------------------------------
# Interrupt detection: _emit_interrupt_events
# ---------------------------------------------------------------------------


class _InterruptValue:
    """Minimal interrupt value carrier for _emit_interrupt_events testing.

    Policy exception: LangGraph's real interrupt objects are created internally
    by the graph runtime and are not publicly constructible outside a running
    graph execution. The aggregator only accesses `interrupt_obj.value` via
    getattr, so a plain dataclass-style object is sufficient to exercise the
    full interrupt-detection logic without requiring a live graph.
    """

    def __init__(self, value: object) -> None:
        self.value = value


class _GraphTask:
    """Minimal LangGraph task stub for _emit_interrupt_events testing.

    Policy exception: LangGraph's PregelTask is an internal dataclass populated
    by the graph runtime. The aggregator only reads `task.name` and
    `task.interrupts`, making a plain two-attribute object sufficient to test
    all interrupt-routing branches without a running graph or checkpointer.
    """

    def __init__(self, name: str, interrupts: list[_InterruptValue]) -> None:
        self.name = name
        self.interrupts = interrupts


class _GraphStateSnapshot:
    """Minimal LangGraph state snapshot for _emit_interrupt_events testing.

    Policy exception: LangGraph's StateSnapshot requires a full checkpointer
    and channel state. The aggregator only reads `state.tasks`, so a minimal
    one-attribute holder is sufficient to drive all branches of the interrupt
    detection logic without I/O or LangGraph infrastructure.
    """

    def __init__(self, tasks: list[_GraphTask]) -> None:
        self.tasks = tasks


class _SilentGraph:
    """Minimal graph stub: astream_events yields nothing, aget_state returns state.

    Policy exception: A real compiled LangGraph graph requires StateGraph
    definition, node functions, and checkpointer wiring. The ingest() tests
    only need to verify event routing and _emit_interrupt_events behaviour;
    a no-op async generator for astream_events and a direct aget_state return
    are sufficient to exercise those paths without LLM or I/O dependencies.
    """

    def __init__(self, state: object) -> None:
        self._state = state

    async def astream_events(
        self, graph_input: object, config: object, *, version: str
    ):
        return
        yield  # make it an async generator

    async def aget_state(self, config: object) -> object:
        return self._state


class _InterruptingGraph:
    """Graph stub that raises a real GraphInterrupt from astream_events.

    Policy exception: see _SilentGraph. This variant simulates the H4 guard
    path in ingest() — where astream_events raises GraphInterrupt — so that
    _emit_interrupt_events is triggered. Using a real GraphInterrupt (from
    langgraph.errors) ensures isinstance checks in the production code pass
    correctly without needing a full graph execution.
    """

    def __init__(self, state: object) -> None:
        self._state = state

    async def astream_events(
        self, graph_input: object, config: object, *, version: str
    ):
        # Raise a real GraphInterrupt to test the H4 guard in ingest().
        # GraphInterrupt takes a tuple of interrupt values.
        raise GraphInterrupt(())
        yield  # make it an async generator

    async def aget_state(self, config: object) -> object:
        return self._state


class TestEmitInterruptEvents:
    """Tests for _emit_interrupt_events called via ingest() finally block."""

    @pytest.mark.asyncio
    async def test_ingest_emits_permission_on_tool_interrupt(
        self, aggregator: EventAggregator
    ) -> None:
        """When graph suspends with a permission_request interrupt, events are
        emitted.

        Uses _InterruptingGraph which raises a real GraphInterrupt from
        astream_events, triggering the H4 guard so _emit_interrupt_events is
        called and PermissionRequestEvent is emitted.
        """
        queue = aggregator.add_subscriber("client-1")
        aggregator.subscribe("client-1", ["thread-interrupt"])

        interrupt_payload = {
            "type": "permission_request",
            "tool_name": "fs/write_text_file",
            "tool_input": {"path": "/tmp/test.py"},
            "options": [
                {"optionId": "allow_once", "label": "Allow"},
                {"optionId": "deny_once", "label": "Deny"},
            ],
        }
        state = _GraphStateSnapshot(
            tasks=[_GraphTask("vaultspec-coder", [_InterruptValue(interrupt_payload)])]
        )
        graph = _InterruptingGraph(state)

        config = {"configurable": {"thread_id": "thread-interrupt"}}
        await aggregator.ingest(
            thread_id="thread-interrupt",
            agent_id="supervisor",
            graph=graph,
            graph_input=None,
            config=config,
        )

        # Drain all events from the queue
        sequenced_events = []
        while not queue.empty():
            sequenced_events.append(queue.get_nowait())

        domain_events = [s.event for s in sequenced_events]

        # Must have at least a PermissionRequest and an AgentStatus
        perm_events = [e for e in domain_events if isinstance(e, PermissionRequest)]
        status_events = [e for e in domain_events if isinstance(e, AgentStatus)]

        assert len(perm_events) >= 1, (
            f"No PermissionRequest emitted; got: {domain_events}"
        )
        perm = perm_events[0]
        assert perm.thread_id == "thread-interrupt"
        assert perm.agent_id == "vaultspec-coder"
        assert "fs/write_text_file" in perm.description
        assert len(perm.options) == 2

        assert len(status_events) >= 1
        input_req = [
            s for s in status_events if s.state == AgentLifecycleState.INPUT_REQUIRED
        ]
        assert len(input_req) >= 1

    @pytest.mark.asyncio
    async def test_ingest_no_permission_on_normal_completion(
        self, aggregator: EventAggregator
    ) -> None:
        """When graph completes normally (empty tasks), no PermissionRequestEvent
        is emitted."""
        queue = aggregator.add_subscriber("client-1")
        aggregator.subscribe("client-1", ["thread-normal"])

        state = _GraphStateSnapshot(tasks=[])
        graph = _SilentGraph(state)

        config = {"configurable": {"thread_id": "thread-normal"}}
        await aggregator.ingest(
            thread_id="thread-normal",
            agent_id="supervisor",
            graph=graph,
            graph_input=None,
            config=config,
        )

        sequenced_all = []
        while not queue.empty():
            sequenced_all.append(queue.get_nowait())
        domain_events = [s.event for s in sequenced_all]

        perm_events = [e for e in domain_events if isinstance(e, PermissionRequest)]
        assert len(perm_events) == 0

    @pytest.mark.asyncio
    async def test_ingest_no_permission_on_empty_interrupt_tasks(
        self, aggregator: EventAggregator
    ) -> None:
        """When a task has an empty interrupts list, no PermissionRequestEvent
        is emitted."""
        queue = aggregator.add_subscriber("client-1")
        aggregator.subscribe("client-1", ["thread-empty-interrupts"])

        # Task exists but with no interrupts — uses _InterruptingGraph
        # so _emit_interrupt_events IS called, but no events emitted since
        # task.interrupts is empty.
        state = _GraphStateSnapshot(tasks=[_GraphTask("vaultspec-coder", [])])
        graph = _InterruptingGraph(state)

        config = {"configurable": {"thread_id": "thread-empty-interrupts"}}
        await aggregator.ingest(
            thread_id="thread-empty-interrupts",
            agent_id="supervisor",
            graph=graph,
            graph_input=None,
            config=config,
        )

        sequenced_all = []
        while not queue.empty():
            sequenced_all.append(queue.get_nowait())
        domain_events = [s.event for s in sequenced_all]

        perm_events = [e for e in domain_events if isinstance(e, PermissionRequest)]
        assert len(perm_events) == 0

    @pytest.mark.asyncio
    async def test_ingest_no_permission_on_non_permission_interrupt(
        self, aggregator: EventAggregator
    ) -> None:
        """Interrupts with type != 'permission_request' are silently skipped."""
        queue = aggregator.add_subscriber("client-1")
        aggregator.subscribe("client-1", ["thread-other-interrupt"])

        interrupt_payload = {"type": "some_other_type", "data": "irrelevant"}
        state = _GraphStateSnapshot(
            tasks=[_GraphTask("vaultspec-coder", [_InterruptValue(interrupt_payload)])]
        )
        # Uses _InterruptingGraph so GraphInterrupt is raised and
        # _emit_interrupt_events is triggered, but the payload type is not
        # "permission_request" so no PermissionRequestEvent should be emitted.
        graph = _InterruptingGraph(state)

        config = {"configurable": {"thread_id": "thread-other-interrupt"}}
        await aggregator.ingest(
            thread_id="thread-other-interrupt",
            agent_id="supervisor",
            graph=graph,
            graph_input=None,
            config=config,
        )

        sequenced_all = []
        while not queue.empty():
            sequenced_all.append(queue.get_nowait())
        domain_events = [s.event for s in sequenced_all]

        perm_events = [e for e in domain_events if isinstance(e, PermissionRequest)]
        assert len(perm_events) == 0

    @pytest.mark.asyncio
    async def test_ingest_uses_default_options_when_none_provided(
        self, aggregator: EventAggregator
    ) -> None:
        """When ACP provides no options, allow_once/deny_once defaults are used."""
        queue = aggregator.add_subscriber("client-1")
        aggregator.subscribe("client-1", ["thread-default-opts"])

        interrupt_payload = {
            "type": "permission_request",
            "tool_name": "shell_exec",
            "tool_input": {},
            "options": [],  # Empty options — should use defaults
        }
        state = _GraphStateSnapshot(
            tasks=[_GraphTask("vaultspec-coder", [_InterruptValue(interrupt_payload)])]
        )
        # Uses _InterruptingGraph so _emit_interrupt_events is called.
        graph = _InterruptingGraph(state)

        config = {"configurable": {"thread_id": "thread-default-opts"}}
        await aggregator.ingest(
            thread_id="thread-default-opts",
            agent_id="supervisor",
            graph=graph,
            graph_input=None,
            config=config,
        )

        sequenced_all = []
        while not queue.empty():
            sequenced_all.append(queue.get_nowait())
        domain_events = [s.event for s in sequenced_all]

        perm_events = [e for e in domain_events if isinstance(e, PermissionRequest)]
        assert len(perm_events) == 1
        perm = perm_events[0]
        option_ids = {opt["option_id"] for opt in perm.options}
        assert "allow_once" in option_ids
        assert "deny_once" in option_ids


# ---------------------------------------------------------------------------
# GraphRecursionError detection
# ---------------------------------------------------------------------------


class _RecursingGraph:
    """Graph stub that raises GraphRecursionError from astream_events."""

    async def astream_events(
        self, graph_input: object, config: object, *, version: str
    ):
        from langgraph.errors import GraphRecursionError

        raise GraphRecursionError("Recursion limit of 100 reached")
        yield  # make it an async generator

    async def aget_state(self, config: object) -> object:
        return type(
            "_State", (), {"tasks": [], "values": {}, "next": [], "config": {}}
        )()


class TestRecursionLimitDetection:
    """Tests for GraphRecursionError detection in ingest()."""

    @pytest.mark.asyncio
    async def test_ingest_emits_recursion_limit_error(
        self, aggregator: EventAggregator
    ) -> None:
        """GraphRecursionError produces ErrorEvent(code='RECURSION_LIMIT_EXCEEDED',
        recoverable=False)."""
        queue = aggregator.add_subscriber("client-1")
        aggregator.subscribe("client-1", ["thread-recurse"])

        graph = _RecursingGraph()
        config = {"configurable": {"thread_id": "thread-recurse"}}
        await aggregator.ingest(
            thread_id="thread-recurse",
            agent_id="supervisor",
            graph=graph,
            graph_input={"messages": []},
            config=config,
        )

        sequenced_all = []
        while not queue.empty():
            sequenced_all.append(queue.get_nowait())
        domain_events = [s.event for s in sequenced_all]

        error_events = [e for e in domain_events if isinstance(e, ErrorOccurred)]
        assert len(error_events) >= 1
        err = error_events[-1]
        assert err.code == "RECURSION_LIMIT_EXCEEDED"
        assert err.recoverable is False

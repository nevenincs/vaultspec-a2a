"""Central Event Aggregator — composition root.

Thin facade that delegates to focused sub-modules:

- ``subscribers.SubscriberManager`` — client connection state
- ``buffering.BufferingManager`` — chunk batching + debounce
- ``emitters.EventEmitters`` — event emission + state tracking
- ``ingest.IngestManager`` — graph consumption lifecycle

The public API is identical to the pre-decomposition monolith.
See ADR D-01, Phase 6 of the core-layer-boundary plan.
"""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, cast

from langgraph.types import Command

from ..graph.enums import AgentLifecycleState, ToolCallStatus, ToolKind
from ..graph.events import DomainEvent, PermissionRequest
from ..graph.protocols import NullTelemetryHook, TelemetryHook
from .buffering import BufferingManager
from .emitters import EventEmitters
from .ingest import IngestManager
from .subscribers import SubscriberManager
from .types import SequencedEvent, StreamableGraph, classify_tool_kind

__all__ = [
    "EventAggregator",
    "SequencedEvent",
    "StreamableGraph",
    "classify_tool_kind",
]


class EventAggregator:
    """Central event bus — composition root delegating to sub-components.

    Preserves the exact same public API as the pre-decomposition monolith.
    All callers continue to work unchanged.
    """

    def __init__(self, telemetry: TelemetryHook | None = None) -> None:
        _tel: TelemetryHook | NullTelemetryHook = telemetry or NullTelemetryHook()
        self._telemetry = _tel
        self._subscribers_mgr = SubscriberManager(self._telemetry)
        self._emitters = EventEmitters(
            self._subscribers_mgr,
            cast("BufferingManager", None),  # set below after buffering init
            self._telemetry,
        )
        self._buffering = BufferingManager(
            self._subscribers_mgr,
            self._telemetry,
            self._emitters.next_sequence,
        )
        # Wire up the circular reference: emitters needs buffering
        self._emitters._buffering = self._buffering
        self._ingest = IngestManager(self._emitters, self._buffering, self._telemetry)

    # -- Sequence management (delegates to emitters) --------------------

    def get_sequence(self, thread_id: str) -> int:
        return self._emitters.get_sequence(thread_id)

    def advance_sequence(self, thread_id: str) -> int:
        return self._emitters.advance_sequence(thread_id)

    def sequence_count(self) -> int:
        return self._emitters.sequence_count()

    def prune_sequences(self, active_thread_ids: set[str]) -> int:
        return self._emitters.prune_sequences(active_thread_ids)

    # -- Subscriber management (delegates to subscribers) ---------------

    def add_subscriber(self, client_id: str) -> asyncio.Queue[SequencedEvent]:
        return self._subscribers_mgr.add_subscriber(client_id)

    def get_subscriber_queue(
        self, client_id: str
    ) -> asyncio.Queue[SequencedEvent] | None:
        return self._subscribers_mgr.get_subscriber_queue(client_id)

    def remove_subscriber(self, client_id: str) -> None:
        self._subscribers_mgr.remove_subscriber(client_id)

    def subscribe(self, client_id: str, thread_ids: list[str]) -> None:
        self._subscribers_mgr.subscribe(client_id, thread_ids)

    def unsubscribe(self, client_id: str, thread_ids: list[str]) -> None:
        self._subscribers_mgr.unsubscribe(client_id, thread_ids)

    def add_broadcast_hook(
        self, hook: Callable[[SequencedEvent], Awaitable[None]]
    ) -> None:
        self._subscribers_mgr.add_broadcast_hook(hook)

    def subscriber_count(self) -> int:
        return self._subscribers_mgr.subscriber_count()

    def subscription_count(self) -> int:
        return self._subscribers_mgr.subscription_count()

    def get_subscriptions(self, client_id: str) -> frozenset[str]:
        return self._subscribers_mgr.get_subscriptions(client_id)

    def get_active_thread_ids(self) -> list[str]:
        return self._subscribers_mgr.get_active_thread_ids()

    def clear_thread_state(self, thread_id: str) -> None:
        """Purge all in-memory aggregator state scoped to ``thread_id``."""
        self._subscribers_mgr.remove_thread(thread_id)
        self._buffering.clear_thread_state(thread_id)
        self._ingest.clear_thread_state(thread_id)
        self._emitters.clear_thread_state(thread_id)

    def relay_payload(self, thread_id: str, payload: object) -> None:
        """Fan out a pre-serialized payload to all subscribers of ``thread_id``."""
        self._subscribers_mgr.enqueue_payload(thread_id, payload)

    def register_graph(self, graph: StreamableGraph) -> None:
        self._subscribers_mgr.register_graph(graph)

    def get_node_summaries(self) -> list[dict[str, str]]:
        return self._subscribers_mgr.get_node_summaries()

    # -- Buffering (delegates to buffering) -----------------------------

    async def buffer_message_chunk(
        self,
        thread_id: str,
        agent_id: str,
        content: str,
        message_id: str,
    ) -> None:
        await self._buffering.buffer_message_chunk(
            thread_id, agent_id, content, message_id
        )

    async def flush_chunk_buffer(self, thread_id: str) -> None:
        await self._buffering.flush_chunk_buffer(thread_id)

    # -- Event emission (delegates to emitters) -------------------------

    async def emit(self, event: DomainEvent) -> None:
        await self._emitters.emit(event)

    async def emit_agent_status(
        self,
        thread_id: str,
        agent_id: str,
        node_name: str,
        state: AgentLifecycleState,
        detail: str | None = None,
    ) -> None:
        await self._emitters.emit_agent_status(
            thread_id, agent_id, node_name, state, detail
        )

    async def emit_message_chunk(
        self,
        thread_id: str,
        agent_id: str,
        content: str,
        message_id: str,
        finish_reason: str | None = None,
    ) -> None:
        await self._emitters.emit_message_chunk(
            thread_id, agent_id, content, message_id, finish_reason
        )

    async def emit_thought_chunk(
        self,
        thread_id: str,
        agent_id: str,
        content: str,
        message_id: str,
    ) -> None:
        await self._emitters.emit_thought_chunk(
            thread_id, agent_id, content, message_id
        )

    async def emit_tool_call_start(
        self,
        thread_id: str,
        agent_id: str,
        tool_call_id: str,
        title: str,
        kind: ToolKind = ToolKind.OTHER,
        input_args: dict[str, Any] | None = None,
    ) -> None:
        await self._emitters.emit_tool_call_start(
            thread_id, agent_id, tool_call_id, title, kind, input_args
        )

    async def emit_tool_call_update(
        self,
        thread_id: str,
        agent_id: str,
        tool_call_id: str,
        status: ToolCallStatus | None = None,
        title: str | None = None,
        content: list[dict[str, str | None]] | None = None,
    ) -> None:
        await self._emitters.emit_tool_call_update(
            thread_id, agent_id, tool_call_id, status, title, content
        )

    async def emit_permission_request(
        self,
        thread_id: str,
        agent_id: str,
        request_id: str,
        description: str,
        options: list[dict[str, str]],
        tool_call: str | None = None,
        tool_kind: ToolKind | None = None,
    ) -> None:
        await self._emitters.emit_permission_request(
            thread_id,
            agent_id,
            request_id,
            description,
            options,
            tool_call,
            tool_kind,
        )

    def resolve_permission(self, request_id: str) -> None:
        self._emitters.resolve_permission(request_id)

    def prune_stale_permissions(self, max_age_seconds: float = 300.0) -> int:
        return self._emitters.prune_stale_permissions(max_age_seconds)

    def get_pending_permissions(
        self,
        thread_id: str | None = None,
    ) -> list[PermissionRequest]:
        return self._emitters.get_pending_permissions(thread_id)

    def get_agent_states(self) -> dict[str, AgentLifecycleState]:
        return self._emitters.get_agent_states()

    def get_tool_call_states(self, thread_id: str) -> dict[str, dict[str, str]]:
        return self._emitters.get_tool_call_states(thread_id)

    def sync_worker_event(
        self,
        thread_id: str,
        payload: dict[str, Any],
    ) -> None:
        self._emitters.sync_worker_event(thread_id, payload)

    async def emit_artifact_update(
        self,
        thread_id: str,
        artifact_id: str,
        filename: str,
        content: str,
        append: bool = False,
        last_chunk: bool = True,
    ) -> None:
        await self._emitters.emit_artifact_update(
            thread_id, artifact_id, filename, content, append, last_chunk
        )

    async def emit_plan_update(
        self,
        thread_id: str,
        entries: list[dict[str, str]],
    ) -> None:
        await self._emitters.emit_plan_update(thread_id, entries)

    async def emit_error(
        self,
        thread_id: str,
        code: str,
        message: str,
        recoverable: bool = True,
        agent_id: str | None = None,
    ) -> None:
        await self._emitters.emit_error(thread_id, code, message, recoverable, agent_id)

    async def emit_team_status(
        self,
        thread_id: str,
        agents: list[dict[str, Any]],
        active_thread_ids: list[str] | None = None,
    ) -> None:
        await self._emitters.emit_team_status(thread_id, agents, active_thread_ids)

    # -- LangGraph event processing (delegates to transformer/ingest) ---

    async def process_langgraph_event(
        self,
        event_data: dict[str, Any],
        thread_id: str,
        agent_id: str,
    ) -> None:
        from .transformer import process_langgraph_event

        await process_langgraph_event(
            event_data=event_data,
            thread_id=thread_id,
            agent_id=agent_id,
            emitters=self._emitters,
            buffering=self._buffering,
            telemetry=self._telemetry,
        )

    # -- Ingest (delegates to ingest manager) ---------------------------

    def cancel_thread(self, thread_id: str) -> None:
        self._ingest.cancel_thread(thread_id)

    async def ingest(
        self,
        thread_id: str,
        agent_id: str,
        graph: StreamableGraph,
        graph_input: dict[str, Any] | Command | None,
        config: dict[str, Any],
    ) -> str:
        return await self._ingest.ingest(
            thread_id, agent_id, graph, graph_input, config
        )

    # -- Shutdown -------------------------------------------------------

    async def shutdown(self) -> None:
        """Cancel all tasks and clear state."""
        await self._buffering.shutdown()
        await self._ingest.shutdown()
        self._subscribers_mgr.clear()
        self._emitters.clear()

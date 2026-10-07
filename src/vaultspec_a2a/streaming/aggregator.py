"""Central Event Aggregator — composition root.

Thin facade that delegates to focused sub-modules:

- ``subscribers.SubscriberManager`` — client connection state
- ``buffering.BufferingManager`` — chunk batching + debounce
- ``emitters.EventEmitters`` — event emission + state tracking
- ``ingest.IngestManager`` — graph consumption lifecycle

This module declares ``EventAggregator`` and nothing else. ``SequencedEvent`` and
``StreamableGraph`` moved to ``types`` in the decomposition and are imported here
only to annotate the aggregator; they are not re-published, so the decomposition
is what callers see rather than the shape it replaced.
"""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, TypedDict, Unpack, cast

from langgraph.types import Command

from ..graph.enums import AgentLifecycleState
from ..graph.protocols import NullTelemetryHook, TelemetryHook
from ..providers import ProviderCondition
from .buffering import BufferingManager
from .emitters import EventEmitters
from .ingest import GraphInvocation, IngestManager, IngestRequest
from .subscribers import AllocationSink, RunSequenceAllocator, SubscriberManager
from .transformer import project_run_progress
from .types import SequencedEvent, StreamableGraph

__all__ = ["EventAggregator"]


class _IngestOptions(TypedDict, total=False):
    graph_input: dict[str, Any] | Command[Any] | None
    config: dict[str, Any]
    on_graph_started: Callable[[], Awaitable[None]] | None
    context: object | None
    control: object | None


def _validate_ingest_arguments(
    args: tuple[object, ...], options: _IngestOptions
) -> None:
    unknown = set(options).difference(
        {"graph_input", "config", "on_graph_started", "context", "control"}
    )
    if unknown:
        unexpected = next(iter(unknown))
        raise TypeError(
            "EventAggregator.ingest() got an unexpected keyword argument "
            f"{unexpected!r}"
        )
    if len(args) > 2:
        raise TypeError(
            "EventAggregator.ingest() takes 5 positional arguments but "
            f"{len(args) + 4} were given"
        )
    if args and "graph_input" in options:
        raise TypeError(
            "EventAggregator.ingest() got multiple values for argument 'graph_input'"
        )
    if len(args) > 1 and "config" in options:
        raise TypeError(
            "EventAggregator.ingest() got multiple values for argument 'config'"
        )


class EventAggregator:  # pylint: disable=too-many-public-methods
    """Central event bus — composition root delegating to sub-components.

    Exposes only the operations the worker and the gateway actually call; the
    public method count is the union of those two surfaces. Everything else is
    reached on the composed manager that owns it.
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
        self._emitters.bind_buffering(self._buffering)
        self._ingest = IngestManager(self._emitters, self._buffering, self._telemetry)

    # -- Sequence management (delegates to emitters) --------------------

    def get_sequence(self, thread_id: str) -> int:
        return self._emitters.get_sequence(thread_id)

    def prune_sequences(self, active_thread_ids: set[str]) -> int:
        return self._emitters.prune_sequences(active_thread_ids)

    # -- Subscriber management (delegates to subscribers) ---------------

    def add_subscriber(self, client_id: str) -> asyncio.Queue[SequencedEvent]:
        return self._subscribers_mgr.add_subscriber(client_id)

    def remove_subscriber(self, client_id: str) -> None:
        self._subscribers_mgr.remove_subscriber(client_id)

    def take_dropped_count(self, client_id: str) -> int:
        return self._subscribers_mgr.take_dropped_count(client_id)

    def subscribe(self, client_id: str, thread_ids: list[str]) -> None:
        self._subscribers_mgr.subscribe(client_id, thread_ids)

    def add_broadcast_hook(
        self, hook: Callable[[SequencedEvent], Awaitable[None]]
    ) -> None:
        self._subscribers_mgr.add_broadcast_hook(hook)

    def subscriber_count(self) -> int:
        return self._subscribers_mgr.subscriber_count()

    def get_active_thread_ids(self) -> list[str]:
        return self._subscribers_mgr.get_active_thread_ids()

    def clear_thread_state(self, thread_id: str) -> None:
        """Purge all in-memory aggregator state scoped to ``thread_id``."""
        self._subscribers_mgr.remove_thread(thread_id)
        self._buffering.clear_thread_state(thread_id)
        self._ingest.clear_thread_state(thread_id)
        self._emitters.clear_thread_state(thread_id)

    def discard_run_replay(self, thread_id: str) -> None:
        """Drop the retained frames a DELETED run's recorder still holds.

        Called by the delete path only, and separately from
        :meth:`clear_thread_state`, which a terminal also calls while the
        frames it holds are still waiting to be written.
        """
        self._subscribers_mgr.discard_run_replay(thread_id)

    def relay_payload(self, thread_id: str, payload: object) -> None:
        """Fan out a pre-serialized payload to all subscribers of ``thread_id``.

        Worker run events enter the public progress edge here. Each is projected
        through the positive progress DTO before it reaches a subscriber queue, so
        prompts, document and artifact bodies, edit diffs, and raw provider
        payloads are dropped at the relay seam - a first enforcement the encode
        boundary independently repeats.

        Call :meth:`prepare_run` for the run first: this path is synchronous and
        cannot establish a number it has never read.
        """
        self._subscribers_mgr.enqueue_payload(thread_id, project_run_progress(payload))

    async def prepare_run(self, thread_id: str) -> None:
        """Establish *thread_id*'s event numbering before relaying its frames."""
        await self._subscribers_mgr.prepare_run(thread_id)

    def bind_sequence_allocator(
        self,
        allocator: RunSequenceAllocator | None,
        *,
        sink: AllocationSink | None = None,
    ) -> None:
        """Seat the authority that numbers this process's outgoing frames."""
        self._subscribers_mgr.bind_sequence_allocator(allocator, sink=sink)

    @property
    def sequence_allocator(self) -> RunSequenceAllocator | None:
        """The seated numbering authority, or ``None`` where none is bound."""
        return self._subscribers_mgr.sequence_allocator

    def register_graph(self, thread_id: str, graph: StreamableGraph) -> None:
        self._subscribers_mgr.register_graph(thread_id, graph)

    def get_node_summaries(self, thread_id: str) -> list[dict[str, str]]:
        return self._subscribers_mgr.get_node_summaries(thread_id)

    def remove_node_metadata(self, thread_id: str) -> None:
        self._subscribers_mgr.remove_node_metadata(thread_id)

    # -- Event emission (delegates to emitters) -------------------------

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

    def resolve_permission(self, request_id: str) -> None:
        self._emitters.resolve_permission(request_id)

    def prune_stale_permissions(self, max_age_seconds: float = 300.0) -> int:
        return self._emitters.prune_stale_permissions(max_age_seconds)

    def get_agent_states(self, thread_id: str) -> dict[str, AgentLifecycleState]:
        return self._emitters.get_agent_states(thread_id)

    def get_tool_call_states(self, thread_id: str) -> dict[str, dict[str, str]]:
        return self._emitters.get_tool_call_states(thread_id)

    def sync_worker_event(
        self,
        thread_id: str,
        payload: dict[str, Any],
    ) -> None:
        self._emitters.sync_worker_event(thread_id, payload)

    async def emit_error(
        self,
        thread_id: str,
        code: str,
        message: str,
        recoverable: bool = True,
        agent_id: str | None = None,
    ) -> None:
        await self._emitters.emit_error(thread_id, code, message, recoverable, agent_id)

    # -- Ingest (delegates to ingest manager) ---------------------------

    def cancel_thread(self, thread_id: str) -> None:
        self._ingest.cancel_thread(thread_id)

    def take_failure_reason(self, thread_id: str) -> str | None:
        """Pop and return the reason ``thread_id``'s last FAILED ingest ended with."""
        return self._ingest.take_failure_reason(thread_id)

    def take_failure_condition(self, thread_id: str) -> ProviderCondition | None:
        """Pop the provider condition ``thread_id``'s last FAILED ingest resolved."""
        return self._ingest.take_failure_condition(thread_id)

    async def ingest(
        self,
        thread_id: str,
        agent_id: str,
        graph: StreamableGraph,
        *args: object,
        **options: Unpack[_IngestOptions],
    ) -> str:
        _validate_ingest_arguments(args, options)
        if args:
            graph_input = cast("dict[str, Any] | Command[Any] | None", args[0])
        elif "graph_input" in options:
            graph_input = options["graph_input"]
        else:
            raise TypeError(
                "EventAggregator.ingest() missing required argument 'graph_input'"
            )
        if len(args) > 1:
            config = cast("dict[str, Any]", args[1])
        elif "config" in options:
            config = options["config"]
        else:
            raise TypeError(
                "EventAggregator.ingest() missing required argument 'config'"
            )
        return await self._ingest.ingest(
            IngestRequest(
                thread_id,
                agent_id,
                graph,
                GraphInvocation(
                    graph_input,
                    config,
                    options.get("context"),
                    options.get("control"),
                ),
                options.get("on_graph_started"),
            )
        )

    # -- Shutdown -------------------------------------------------------

    async def shutdown(self) -> None:
        """Cancel all tasks and clear state."""
        await self._buffering.shutdown()
        await self._ingest.shutdown()
        await self._subscribers_mgr.shutdown_allocation_sink()
        self._subscribers_mgr.clear()
        self._emitters.clear()

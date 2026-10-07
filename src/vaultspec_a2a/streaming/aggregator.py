"""The worker's event producer - composition root of a run's event stream.

:class:`RunEventProducer` turns a running graph into the domain events a worker
relays to its gateway. It composes the focused sub-modules:

- ``ingest.IngestManager`` - graph consumption lifecycle
- ``emitters.EventEmitters`` - event construction and pending permissions
- ``buffering.BufferingManager`` - chunk batching and debounce
- ``emitters.BroadcastChannel`` - ordering numbers and the relay hooks
- ``_run_state.RunLiveState`` - the run's agent, tool-call and node state

The gateway side of the stream is :class:`vaultspec_a2a.streaming.RelayHub`.
"""

import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypedDict, Unpack, cast

from langgraph.types import Command

from ..graph.enums import AgentLifecycleState
from ..graph.protocols import NullTelemetryHook, TelemetryHook
from ..providers import ProviderCondition
from ._run_state import RunLiveState
from .buffering import BufferingManager
from .emitters import BroadcastChannel, EventEmitters
from .ingest import GraphInvocation, IngestManager, IngestRequest
from .node_metadata import node_metadata_from_graph
from .types import SequencedEvent, StreamableGraph

logger = logging.getLogger(__name__)

__all__ = ["RunEventProducer"]


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
            "RunEventProducer.ingest() got an unexpected keyword argument "
            f"{unexpected!r}"
        )
    if len(args) > 2:
        raise TypeError(
            "RunEventProducer.ingest() takes 5 positional arguments but "
            f"{len(args) + 4} were given"
        )
    if args and "graph_input" in options:
        raise TypeError(
            "RunEventProducer.ingest() got multiple values for argument 'graph_input'"
        )
    if len(args) > 1 and "config" in options:
        raise TypeError(
            "RunEventProducer.ingest() got multiple values for argument 'config'"
        )


class RunEventProducer:
    """The worker's event producer: ingest, emission, buffering and relay hooks.

    Exposes only the operations the worker calls; everything else is reached
    on the composed manager that owns it. It holds no subscriber queue and
    allocates no number a stream is identified by: every event leaves through
    the broadcast hooks, and the gateway numbers it on arrival.
    """

    def __init__(self, telemetry: TelemetryHook | None = None) -> None:
        self._telemetry: TelemetryHook | NullTelemetryHook = (
            telemetry or NullTelemetryHook()
        )
        self._channel = BroadcastChannel(self._telemetry)
        self._state = RunLiveState()
        self._buffering = BufferingManager(self._channel, self._telemetry)
        self._emitters = EventEmitters(self._channel, self._buffering, self._state)
        self._ingest = IngestManager(self._emitters, self._buffering, self._telemetry)

    # -- Relay and run state --------------------------------------------

    def add_broadcast_hook(
        self, hook: Callable[[SequencedEvent], Awaitable[None]]
    ) -> None:
        """Register a hook every produced event is handed to (the worker relay)."""
        self._channel.add_hook(hook)

    def register_graph(self, thread_id: str, graph: StreamableGraph) -> None:
        """Cache a compiled graph's per-node team-status metadata for one run."""
        self._state.record_node_metadata(thread_id, node_metadata_from_graph(graph))
        logger.debug(
            "register_graph: cached metadata for %d nodes on %s",
            len(self._state.get_node_metadata(thread_id)),
            thread_id,
        )

    def prune_sequences(self, active_thread_ids: set[str]) -> None:
        """Drop the ordering counters and tool-call state of runs not executing."""
        self._channel.prune(active_thread_ids)
        self._state.prune_tool_calls(active_thread_ids)

    def prune_stale_permissions(self, max_age_seconds: float = 300.0) -> int:
        """Drop pending permission requests older than *max_age_seconds*."""
        return self._emitters.prune_stale_permissions(max_age_seconds)

    def clear_thread_state(self, thread_id: str) -> None:
        """Purge all in-memory producer state scoped to ``thread_id``."""
        self._channel.forget(thread_id)
        self._state.clear_thread_state(thread_id)
        self._emitters.expire_thread_permissions(thread_id)
        self._buffering.clear_thread_state(thread_id)
        self._ingest.clear_thread_state(thread_id)

    # -- Event emission -------------------------------------------------

    async def emit_agent_status(
        self,
        thread_id: str,
        agent_id: str,
        node_name: str,
        state: AgentLifecycleState,
        detail: str | None = None,
    ) -> None:
        """Emit an agent lifecycle state transition event."""
        await self._emitters.emit_agent_status(
            thread_id, agent_id, node_name, state, detail
        )

    async def emit_error(
        self,
        thread_id: str,
        code: str,
        message: str,
        recoverable: bool = True,
        agent_id: str | None = None,
    ) -> None:
        """Emit a server-side error notification."""
        await self._emitters.emit_error(thread_id, code, message, recoverable, agent_id)

    # -- Ingest ---------------------------------------------------------

    def cancel_thread(self, thread_id: str) -> None:
        """Ask ``thread_id``'s ingest to stop, including one not yet started."""
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
        """Consume one graph run and return the outcome it settled on."""
        _validate_ingest_arguments(args, options)
        if args:
            graph_input = cast("dict[str, Any] | Command[Any] | None", args[0])
        elif "graph_input" in options:
            graph_input = options["graph_input"]
        else:
            raise TypeError(
                "RunEventProducer.ingest() missing required argument 'graph_input'"
            )
        if len(args) > 1:
            config = cast("dict[str, Any]", args[1])
        elif "config" in options:
            config = options["config"]
        else:
            raise TypeError(
                "RunEventProducer.ingest() missing required argument 'config'"
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
        self._channel.clear()
        self._state.clear()

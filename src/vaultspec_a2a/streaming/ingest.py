"""Graph ingest lifecycle for the streaming event bus.

Manages graph consumption (``astream_events``), cancellation events, and
outcome classification.  Extracted from the monolithic ``aggregator.py``
during the aggregator decomposition.
"""

import asyncio
import logging
import time
from typing import Any

from langgraph.types import Command

from ..graph.enums import AgentLifecycleState
from ..graph.protocols import NullTelemetryHook, TelemetryHook
from ..thread.enums import ThreadStatus
from .buffering import BufferingManager
from .emitters import EventEmitters
from .transformer import (
    StreamableGraph,
    _GraphInterrupt,
    _GraphRecursionError,
    emit_interrupt_events,
    process_langgraph_event,
)

logger = logging.getLogger(__name__)


class IngestManager:
    """Graph consumption lifecycle: ingest, cancel, cleanup."""

    def __init__(
        self,
        emitters: EventEmitters,
        buffering: BufferingManager,
        telemetry: TelemetryHook | NullTelemetryHook,
    ) -> None:
        self._emitters = emitters
        self._buffering = buffering
        self._telemetry = telemetry

        # Per-thread cancellation events for ingest loops.
        self._cancel_events: dict[str, asyncio.Event] = {}
        # Per-thread ingest queues for backpressure (research §1.3)
        self._ingest_queues: dict[str, asyncio.Queue[dict[str, Any] | None]] = {}
        # Per-thread fan-out tasks
        self._fanout_tasks: dict[str, asyncio.Task[None]] = {}

    # ------------------------------------------------------------------
    # Thread cancellation
    # ------------------------------------------------------------------

    def cancel_thread(self, thread_id: str) -> None:
        """Signal cancellation for a running ingest on *thread_id*."""
        event = self._cancel_events.get(thread_id)
        if event is not None:
            event.set()
            logger.info("Cancellation requested for thread %s", thread_id)
        else:
            logger.debug(
                "No active cancel event for thread %s (may not be ingesting)",
                thread_id,
            )

    def _get_cancel_event(self, thread_id: str) -> asyncio.Event:
        """Return (or create) the cancellation event for *thread_id*."""
        if thread_id not in self._cancel_events:
            self._cancel_events[thread_id] = asyncio.Event()
        return self._cancel_events[thread_id]

    def _clear_cancel_event(self, thread_id: str) -> None:
        """Remove the cancellation event for *thread_id*."""
        self._cancel_events.pop(thread_id, None)

    def clear_thread_state(self, thread_id: str) -> None:
        """Purge ingest-owned state scoped to ``thread_id``."""
        self._cancel_events.pop(thread_id, None)
        self._ingest_queues.pop(thread_id, None)
        task = self._fanout_tasks.pop(thread_id, None)
        if task is not None:
            task.cancel()

    # ------------------------------------------------------------------
    # LangGraph graph ingest (research §1.3)
    # ------------------------------------------------------------------

    async def ingest(
        self,
        thread_id: str,
        agent_id: str,
        graph: StreamableGraph,
        graph_input: dict[str, Any] | Command | None,
        config: dict[str, Any],
    ) -> str:
        """Start consuming ``astream_events`` from a compiled graph.

        Returns one of ``"completed"``, ``"interrupted"``, or ``"failed"``.
        """
        start = time.monotonic()
        cancel_event = self._get_cancel_event(thread_id)
        _is_interrupt = False
        _outcome = ThreadStatus.COMPLETED
        with self._telemetry.start_span(
            "aggregator.ingest",
            thread_id=thread_id,
            agent_id=agent_id,
        ) as span:
            try:
                async for raw_event in graph.astream_events(
                    graph_input,
                    config,
                    version="v2",
                ):
                    if cancel_event.is_set():
                        logger.info("Ingest cancelled for thread %s", thread_id)
                        _outcome = ThreadStatus.CANCELLED
                        span.set_attribute("cancelled", True)
                        await self._emitters.emit_agent_status(
                            thread_id=thread_id,
                            agent_id=agent_id,
                            node_name="supervisor",
                            state=AgentLifecycleState.CANCELLED,
                            detail="Terminated by user",
                        )
                        break
                    await process_langgraph_event(
                        event_data=raw_event,
                        thread_id=thread_id,
                        agent_id=agent_id,
                        emitters=self._emitters,
                        buffering=self._buffering,
                        telemetry=self._telemetry,
                    )
            except BaseException as exc:
                _is_interrupt = (
                    _GraphInterrupt is not None and isinstance(exc, _GraphInterrupt)
                ) or exc.__class__.__name__ == "GraphInterrupt"
                _is_recursion_limit = (
                    _GraphRecursionError is not None
                    and isinstance(exc, _GraphRecursionError)
                ) or exc.__class__.__name__ == "GraphRecursionError"
                _is_step_timeout = isinstance(exc, TimeoutError)
                if _is_interrupt:
                    _outcome = "interrupted"
                    logger.info(
                        "Graph interrupted for thread %s (awaiting approval)",
                        thread_id,
                    )
                    span.set_attribute("interrupted", True)
                elif _is_recursion_limit:
                    _outcome = ThreadStatus.FAILED
                    logger.warning(
                        "Graph recursion limit reached for thread %s", thread_id
                    )
                    span.set_attribute("error.type", "recursion_limit")
                    await self._emitters.emit_error(
                        thread_id=thread_id,
                        agent_id=agent_id,
                        code="RECURSION_LIMIT_EXCEEDED",
                        message=(
                            "Graph recursion limit reached — check recursion_limit"
                            " configuration"
                        ),
                        recoverable=False,
                    )
                elif _is_step_timeout:
                    _outcome = ThreadStatus.FAILED
                    logger.warning("Graph step_timeout fired for thread %s", thread_id)
                    span.set_attribute("error.type", "step_timeout")
                    await self._emitters.emit_error(
                        thread_id=thread_id,
                        agent_id=agent_id,
                        code="STEP_TIMEOUT",
                        message=(
                            "A graph node exceeded the step timeout — "
                            "the operation may be retried"
                        ),
                        recoverable=True,
                    )
                else:
                    _outcome = ThreadStatus.FAILED
                    logger.exception(
                        "Error during graph ingest for thread %s", thread_id
                    )
                    span.set_attribute("error", True)
                    await self._emitters.emit_error(
                        thread_id=thread_id,
                        agent_id=agent_id,
                        code="INGEST_ERROR",
                        message="Graph event stream failed unexpectedly",
                        recoverable=False,
                    )
            finally:
                self._clear_cancel_event(thread_id)
                await self._buffering.flush_chunk_buffer(thread_id)
                self._buffering.prune_tool_debounce(thread_id)
                interrupt_emitted = await emit_interrupt_events(
                    thread_id, agent_id, graph, config, self._emitters
                )
                if _outcome == ThreadStatus.COMPLETED and interrupt_emitted:
                    _outcome = "interrupted"
                    span.set_attribute("interrupted_via_state", True)
                self._telemetry.record_histogram(
                    "aggregator.ingest_duration_seconds",
                    time.monotonic() - start,
                    thread_id=thread_id,
                )
        return _outcome

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    async def shutdown(self) -> None:
        """Cancel fan-out tasks and clear state."""
        for task in self._fanout_tasks.values():
            task.cancel()
        if self._fanout_tasks:
            await asyncio.gather(*self._fanout_tasks.values(), return_exceptions=True)
        self._fanout_tasks.clear()
        self._cancel_events.clear()

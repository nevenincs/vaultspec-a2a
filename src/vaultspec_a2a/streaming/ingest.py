"""Graph ingest lifecycle for the streaming event bus.

Manages graph consumption (``astream_events``), cancellation events, and
outcome classification.  Extracted from the monolithic ``aggregator.py``
during the aggregator decomposition.
"""

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from langgraph.types import Command

from ..domain_config import domain_config
from ..graph.enums import AgentLifecycleState
from ..graph.protocols import NullTelemetryHook, TelemetryHook
from ..providers import ProviderCondition
from ..providers.acp_exceptions import AcpPromptCancelledError
from ..providers.conditions import condition_is_retryable
from ..thread.enums import ThreadStatus
from ..thread.errors import describe_exception_chain
from .buffering import BufferingManager
from .emitters import EventEmitters
from .transformer import (
    EventProjectionServices,
    GraphInterrupt,
    GraphRecursionError,
    emit_interrupt_events,
    process_langgraph_event,
)
from .types import StreamableGraph

__all__ = ["IngestManager", "summarize_ingest_exception"]

logger = logging.getLogger(__name__)


class IngestStallTimeoutError(TimeoutError):
    """Raised when ``astream_events`` produces no new event within the stall budget.

    A run whose graph genuinely wedges mid-turn (observed live: the
    ground/clarification interrupt path, cause still under investigation)
    previously hung the ingest coroutine forever â€” no exception, no log line,
    no checkpoint, the thread stuck ``running`` indefinitely with nothing to
    show an operator or a reloaded panel why. LangGraph's own per-step
    ``step_timeout`` (``graph.step_timeout``, set from the team TOML) is
    supposed to bound exactly this, but did not fire across the observed
    incidents, so this is an independent, unconditional outer bound: it does
    not trust the graph's own internal timeout to save it. A ``TimeoutError``
    subclass so it is caught by the SAME ``isinstance(exc, TimeoutError)``
    branch below as LangGraph's own step_timeout by default; ``ingest()``
    checks for this MORE SPECIFIC type first so the reported reason names the
    stall (not a generic step_timeout) whenever this is the one that fired.

    "Unconditional" describes that it never trusts step_timeout to fire, not
    that it ignores step_timeout's VALUE: a run whose team preset legitimately
    permits a single step up to (say) 1800s -- a real incident, an ACP-backed
    node doing a long tool call or extended reasoning with no protocol frame
    to relay -- must never be preemptable by an outer bound narrower than that
    same run's own declared budget. ``_effective_stall_timeout`` below is what
    keeps this bound the wider of the two, so a node using exactly the silence
    its own configuration sanctions is never mistaken for a wedge.
    """


async def _cancel_event_read(
    event_read: "asyncio.Future[dict[str, Any]]",
    event_stream: AsyncIterator[dict[str, Any]],
) -> None:
    """Cancel a blocked next-event read and close a generator when it supports it."""
    if not event_read.done():
        event_read.cancel()
    await asyncio.gather(event_read, return_exceptions=True)
    close = getattr(event_stream, "aclose", None)
    if close is not None:
        await close()


async def _next_event_or_cancel(
    event_stream: AsyncIterator[dict[str, Any]],
    cancel_event: asyncio.Event,
    *,
    stall_timeout: float,
) -> tuple[dict[str, Any] | None, bool]:
    """Wait for one graph event, cancellation, or the independent stall bound."""
    next_event = asyncio.ensure_future(event_stream.__anext__())
    cancellation = asyncio.create_task(cancel_event.wait())
    try:
        done, _ = await asyncio.wait(
            (next_event, cancellation),
            timeout=stall_timeout,
            return_when=asyncio.FIRST_COMPLETED,
        )
        # Cancellation wins a simultaneous event race, matching the prior
        # post-read cancellation check while no longer requiring a blocked
        # graph to yield before a requested cancellation can take effect.
        if cancel_event.is_set():
            await _cancel_event_read(next_event, event_stream)
            return None, True
        if next_event in done:
            return next_event.result(), False
        await _cancel_event_read(next_event, event_stream)
        raise IngestStallTimeoutError(
            "Ingest stalled: astream_events produced no new "
            f"event for over {stall_timeout:.0f}s"
        )
    finally:
        if not cancellation.done():
            cancellation.cancel()
        await asyncio.gather(cancellation, return_exceptions=True)
        if not next_event.done():
            await _cancel_event_read(next_event, event_stream)


# Margin (seconds) added atop a run's own configured ``graph.step_timeout``
# when it is used to widen the stall bound below the global default. This
# outer watchdog exists BECAUSE step_timeout was observed to not always fire
# on its own, so once it is the wider budget for this run, the outer bound
# must still leave it room to fire (and be reported through its own, more
# specific STEP_TIMEOUT branch) before this one preempts it -- an outer bound
# equal to the inner one it backstops would race it, not back it up.
_STEP_TIMEOUT_STALL_MARGIN_SECONDS = 30.0


def _effective_stall_timeout(graph: StreamableGraph) -> float:
    """Return the stall budget for *graph*, never narrower than its own step budget.

    Live incident: a preset can legitimately declare ``step_timeout_seconds``
    in the hundreds or low thousands (a real ACP-backed authoring node doing a
    long tool call or extended reasoning between protocol frames), while the
    global ``ingest_event_stall_timeout_seconds`` default is a much smaller
    flat number meant to catch a genuinely wedged graph quickly. Reading only
    the global default made the "unconditional outer bound" DOCSTRING above
    strictly tighter than the very step budget it exists to back up, so any
    node using the silence its own configuration sanctioned was killed first
    by the outer watchdog, reporting a stall that never happened at the level
    the run's own operator would recognise as a fault.

    ``graph.step_timeout`` is the compiled Pregel attribute the compiler sets
    from the team TOML (``graph/compiler.py``); it is absent from the
    ``StreamableGraph`` protocol (a test double, or a graph compiled without a
    configured step_timeout, need not carry it), so it is read defensively
    and the global default is kept whenever it is missing or not the wider
    bound.
    """
    global_default = domain_config.ingest_event_stall_timeout_seconds
    node_step_timeout = getattr(graph, "step_timeout", None)
    if isinstance(node_step_timeout, int | float) and (
        node_step_timeout + _STEP_TIMEOUT_STALL_MARGIN_SECONDS > global_default
    ):
        return float(node_step_timeout) + _STEP_TIMEOUT_STALL_MARGIN_SECONDS
    return global_default


def summarize_ingest_exception(exc: BaseException) -> str:
    """A client-visible, single-line summary of an uncaught ingest exception.

    Ingest previously discarded the real exception here and always reported
    the generic "Graph event stream failed unexpectedly", leaving both
    run-status and the relay stream with no way to distinguish a transient
    infrastructure fault from something like an expired authoring credential
    on resume â€” the actual reason lived only in the worker's own log. Every
    other classified branch in this handler (recursion limit, step timeout)
    already reports a specific reason; this restores that for the catch-all.

    Naming only the caught exception was still not enough, because what reaches
    this handler is rarely the failure itself, so the whole ``__cause__`` chain is
    rendered by the shared chain describer. Every site that has to name a failure
    in one client-visible line uses that one renderer, so an ingest failure and a
    dispatch-level failure read alike; only the attribution prefix differs, and
    it is this function's whole remaining job.
    """
    return f"Graph event stream failed unexpectedly: {describe_exception_chain(exc)}"


def _pending_graph_started_signal(
    cancelled: bool,
    cancel_event: asyncio.Event,
    on_graph_started: Callable[[], Awaitable[None]] | None,
) -> bool:
    """Whether this event is the one that should fire the started callback."""
    return not cancelled and not cancel_event.is_set() and on_graph_started is not None


def _finalized_outcome(outcome: str, interrupt_emitted: bool, span: Any) -> str:
    """Fold a state-observed interrupt into the outcome that already completed."""
    if outcome == ThreadStatus.COMPLETED and interrupt_emitted:
        span.set_attribute("interrupted_via_state", True)
        return "interrupted"
    return outcome


def _resolve_provider_condition(exc: BaseException) -> ProviderCondition:
    """Read the provider condition off an uncaught ingest exception's chain.

    The lane that failed already resolved its own wire discriminator into a
    condition and attached it to the exception it raised, so this site recovers
    that decision rather than re-deriving one from the message text. Recovering
    it is the whole point: a classification inferred here from prose would break
    the moment a vendor reworded it, and would disagree with the lane that
    actually saw the wire.

    The ``__cause__`` chain is walked because what reaches this handler is
    almost never the failure itself - a provider fault raised inside a worker
    node arrives wrapped, and the wrapper carries no condition of its own. Only
    explicit causes are followed, on the same reasoning as the chain describer:
    implicit context records what happened to be in flight, not what explains
    the failure.

    A link whose condition is the unknown member is walked PAST rather than
    accepted, because that member states only that the link resolved nothing;
    a deeper link that did resolve something is the better answer, and taking
    the first link's silence for a verdict would discard it. When no link
    resolves anything the floor is returned, which is the honest report for a
    failure no lane classified - an infrastructure fault, or a provider whose
    wire carried no discriminator at all.
    """
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        condition = getattr(current, "condition", None)
        if (
            isinstance(condition, ProviderCondition)
            and condition is not ProviderCondition.UNKNOWN
        ):
            return condition
        current = current.__cause__
    return ProviderCondition.UNKNOWN


@dataclass(frozen=True, slots=True)
class IngestRequest:
    thread_id: str
    agent_id: str
    graph: StreamableGraph
    graph_input: dict[str, Any] | Command[Any] | None
    config: dict[str, Any]
    on_graph_started: Callable[[], Awaitable[None]] | None = None


@dataclass(slots=True)
class _FailureFacts:
    reasons: dict[str, str] = field(default_factory=dict)
    conditions: dict[str, ProviderCondition] = field(default_factory=dict)


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
        # Per-thread ingest queues for backpressure (research Â§1.3)
        self._ingest_queues: dict[str, asyncio.Queue[dict[str, Any] | None]] = {}
        # Per-thread fan-out tasks
        self._fanout_tasks: dict[str, asyncio.Task[None]] = {}
        # The capped, single-line reason the most recent FAILED ingest for a
        # thread ended with. Populated
        # alongside every FAILED outcome branch in ``ingest()``; the caller
        # (Executor._settle_run) consumes it via ``take_failure_reason`` right
        # after reading the outcome string, so it never outlives the run it
        # describes and never leaks across an unrelated later thread reusing
        # the same dict key.
        self._failures = _FailureFacts()
        # The provider condition the most recent FAILED ingest resolved, held
        # on the same terms as the reason beside it and popped by the same
        # caller. It is kept as well as emitted because the error frame is
        # droppable and the durable column is not: a reloading client recovers
        # the condition only if the terminal write carried it, and the terminal
        # is written from what this dict hands back.

    # ------------------------------------------------------------------
    # Thread cancellation
    # ------------------------------------------------------------------

    def cancel_thread(self, thread_id: str) -> None:
        """Persist cancellation so a concurrently starting ingest observes it."""
        self._get_cancel_event(thread_id).set()
        logger.info("Cancellation requested for thread %s", thread_id)

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
        self._failures.reasons.pop(thread_id, None)
        self._failures.conditions.pop(thread_id, None)
        task = self._fanout_tasks.pop(thread_id, None)
        if task is not None:
            task.cancel()

    def take_failure_reason(self, thread_id: str) -> str | None:
        """Pop and return the reason ``thread_id``'s last FAILED ingest ended with.

        ``None`` when the thread never failed (or its reason was already
        consumed) â€” the caller's default, never-durably-record-anything
        behaviour is unchanged when there is nothing to report.
        """
        return self._failures.reasons.pop(thread_id, None)

    def take_failure_condition(self, thread_id: str) -> ProviderCondition | None:
        """Pop the provider condition ``thread_id``'s last FAILED ingest resolved.

        ``None`` when no ingest classified a failure for this thread - it never
        failed, it failed on a branch that observed no provider, or the value
        was already consumed. The caller supplies the floor in that case, so an
        absent value here never becomes an absent condition on a failed run.
        """
        return self._failures.conditions.pop(thread_id, None)

    # ------------------------------------------------------------------
    # LangGraph graph ingest (research Â§1.3)
    # ------------------------------------------------------------------

    async def _next_ingest_event(
        self,
        event_stream: AsyncIterator[dict[str, Any]],
        cancel_event: asyncio.Event,
        stall_timeout: float,
    ) -> tuple[dict[str, Any] | None, bool, bool]:
        """Return ``(raw_event, cancelled, exhausted)`` for one loop iteration.

        ``exhausted`` is set only on a genuine end of stream (not a
        cancellation racing it), which is the caller's cue to end the ingest
        loop as a normal completion rather than a cancellation.
        """
        try:
            raw_event, cancelled = await _next_event_or_cancel(
                event_stream, cancel_event, stall_timeout=stall_timeout
            )
        except StopAsyncIteration:
            if not cancel_event.is_set():
                return None, False, True
            return None, True, False
        return raw_event, cancelled, False

    async def _handle_ingest_cancellation(
        self,
        event_stream: AsyncIterator[dict[str, Any]],
        thread_id: str,
        agent_id: str,
        span: Any,
    ) -> None:
        close = getattr(event_stream, "aclose", None)
        if close is not None:
            await close()
        logger.info("Ingest cancelled for thread %s", thread_id)
        span.set_attribute("cancelled", True)
        await self._emitters.emit_agent_status(
            thread_id=thread_id,
            agent_id=agent_id,
            node_name="supervisor",
            state=AgentLifecycleState.CANCELLED,
            detail="Terminated by user",
        )

    async def ingest(self, request: IngestRequest) -> str:
        """Start consuming ``astream_events`` from a compiled graph.

        Returns one of ``"completed"``, ``"interrupted"``, or ``"failed"``.
        """
        thread_id = request.thread_id
        agent_id = request.agent_id
        graph = request.graph
        graph_input = request.graph_input
        config = request.config
        on_graph_started = request.on_graph_started
        start = time.monotonic()
        cancel_event = self._get_cancel_event(thread_id)
        _outcome = ThreadStatus.COMPLETED
        stall_timeout = _effective_stall_timeout(graph)
        with self._telemetry.start_span(
            "aggregator.ingest",
            thread_id=thread_id,
            agent_id=agent_id,
        ) as span:
            try:
                # Bounded manual iteration, not `async for`: a plain `async for`
                # trusts astream_events to eventually yield, raise, or exhaust on
                # its own. Race every blocked next-event read against the local
                # cancellation event as well as the independent watchdog, so a
                # cancellation never depends on the graph yielding another frame.
                event_stream = graph.astream_events(
                    graph_input,
                    config,
                    version="v2",
                ).__aiter__()
                services = EventProjectionServices(
                    self._emitters, self._buffering, self._telemetry
                )
                while True:
                    raw_event, cancelled, exhausted = await self._next_ingest_event(
                        event_stream, cancel_event, stall_timeout
                    )
                    if exhausted:
                        break
                    if _pending_graph_started_signal(
                        cancelled, cancel_event, on_graph_started
                    ):
                        assert on_graph_started is not None
                        await on_graph_started()
                        on_graph_started = None
                    if cancelled or cancel_event.is_set():
                        await self._handle_ingest_cancellation(
                            event_stream, thread_id, agent_id, span
                        )
                        _outcome = ThreadStatus.CANCELLED
                        break
                    if raw_event is None:
                        raise RuntimeError("event read completed without an event")
                    await process_langgraph_event(
                        event_data=raw_event,
                        thread_id=thread_id,
                        agent_id=agent_id,
                        services=services,
                    )
            except BaseException as exc:
                _outcome = await self._handle_ingest_failure(
                    (thread_id, agent_id), exc, stall_timeout, span
                )
            finally:
                self._clear_cancel_event(thread_id)
                await self._buffering.flush_chunk_buffer(thread_id)
                self._buffering.prune_tool_debounce(thread_id)
                interrupt_emitted = await emit_interrupt_events(
                    thread_id, agent_id, graph, config, self._emitters
                )
                _outcome = _finalized_outcome(_outcome, interrupt_emitted, span)
                self._telemetry.record_histogram(
                    "aggregator.ingest_duration_seconds",
                    time.monotonic() - start,
                    thread_id=thread_id,
                )
        return _outcome

    async def _report_ingest_error(
        self,
        identity: tuple[str, str],
        span: Any,
        report: tuple[str, str, bool, str],
    ) -> str:
        thread_id, agent_id = identity
        reason, code, recoverable, error_type = report
        span.set_attribute("error.type", error_type)
        await self._emitters.emit_error(
            thread_id=thread_id,
            agent_id=agent_id,
            code=code,
            message=reason,
            recoverable=recoverable,
        )
        self._failures.reasons[thread_id] = reason
        return ThreadStatus.FAILED

    async def _report_provider_failure(
        self, identity: tuple[str, str], exc: BaseException, span: Any
    ) -> str:
        thread_id, agent_id = identity
        reason = summarize_ingest_exception(exc)
        condition = _resolve_provider_condition(exc)
        self._failures.conditions[thread_id] = condition
        logger.exception("Error during graph ingest for thread %s", thread_id)
        span.set_attribute("error", True)
        span.set_attribute("error.provider_condition", condition.value)
        await self._emitters.emit_error(
            thread_id=thread_id,
            agent_id=agent_id,
            code=condition.value,
            message=reason,
            recoverable=condition_is_retryable(condition),
        )
        self._failures.reasons[thread_id] = reason
        return ThreadStatus.FAILED

    async def _report_graph_failure(
        self,
        identity: tuple[str, str],
        exc: BaseException,
        stall_timeout: float,
        span: Any,
    ) -> str | None:
        thread_id, _ = identity
        if (
            GraphRecursionError is not None and isinstance(exc, GraphRecursionError)
        ) or (exc.__class__.__name__ == "GraphRecursionError"):
            logger.warning("Graph recursion limit reached for thread %s", thread_id)
            return await self._report_ingest_error(
                identity,
                span,
                (
                    "Graph recursion limit reached — check recursion_limit"
                    " configuration",
                    "RECURSION_LIMIT_EXCEEDED",
                    False,
                    "recursion_limit",
                ),
            )
        if isinstance(exc, IngestStallTimeoutError):
            logger.warning(
                "Ingest stall watchdog fired for thread %s (%.0fs, no "
                "LangGraph step_timeout caught it first)",
                thread_id,
                stall_timeout,
            )
            return await self._report_ingest_error(
                identity,
                span,
                (str(exc), "INGEST_STALL_TIMEOUT", True, "ingest_stall_timeout"),
            )
        if isinstance(exc, TimeoutError):
            logger.warning("Graph step_timeout fired for thread %s", thread_id)
            return await self._report_ingest_error(
                identity,
                span,
                (
                    "A graph node exceeded the step timeout — "
                    "the operation may be retried",
                    "STEP_TIMEOUT",
                    True,
                    "step_timeout",
                ),
            )
        return None

    async def _handle_ingest_failure(
        self,
        identity: tuple[str, str],
        exc: BaseException,
        stall_timeout: float,
        span: Any,
    ) -> str:
        """Classify cancellation, graph limits, and provider failures in order."""
        thread_id, agent_id = identity
        if isinstance(exc, AcpPromptCancelledError):
            logger.info("Provider cancelled the turn for thread %s", thread_id)
            span.set_attribute("cancelled", True)
            span.set_attribute("cancelled.by", "provider")
            await self._emitters.emit_agent_status(
                thread_id=thread_id,
                agent_id=agent_id,
                node_name="supervisor",
                state=AgentLifecycleState.CANCELLED,
                detail="Provider cancelled the turn",
            )
            return ThreadStatus.CANCELLED
        if (GraphInterrupt is not None and isinstance(exc, GraphInterrupt)) or (
            exc.__class__.__name__ == "GraphInterrupt"
        ):
            logger.info(
                "Graph interrupted for thread %s (awaiting approval)", thread_id
            )
            span.set_attribute("interrupted", True)
            return "interrupted"
        graph_outcome = await self._report_graph_failure(
            identity, exc, stall_timeout, span
        )
        if graph_outcome is not None:
            return graph_outcome
        return await self._report_provider_failure(identity, exc, span)

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

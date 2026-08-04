"""Graph ingest lifecycle for the streaming event bus.

Manages graph consumption (``astream_events``), cancellation events, and
outcome classification.  Extracted from the monolithic ``aggregator.py``
during the aggregator decomposition.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from langgraph.types import Command

from ..domain_config import domain_config
from ..graph.enums import AgentLifecycleState
from ..graph.protocols import NullTelemetryHook, TelemetryHook
from ..providers import ProviderCondition
from ..providers.conditions import condition_is_retryable
from ..thread.enums import ThreadStatus
from ..thread.errors import describe_exception_chain
from .buffering import BufferingManager
from .emitters import EventEmitters
from .transformer import (
    _GraphInterrupt,
    _GraphRecursionError,
    emit_interrupt_events,
    process_langgraph_event,
)
from .types import StreamableGraph

__all__ = ["IngestManager", "IngestStallTimeoutError"]

logger = logging.getLogger(__name__)


class IngestStallTimeoutError(TimeoutError):
    """Raised when ``astream_events`` produces no new event within the stall budget.

    A run whose graph genuinely wedges mid-turn (observed live: the
    ground/clarification interrupt path, cause still under investigation)
    previously hung the ingest coroutine forever — no exception, no log line,
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
    """


def _summarize_ingest_exception(exc: BaseException) -> str:
    """A client-visible, single-line summary of an uncaught ingest exception.

    Ingest previously discarded the real exception here and always reported
    the generic "Graph event stream failed unexpectedly", leaving both
    run-status and the relay stream with no way to distinguish a transient
    infrastructure fault from something like an expired authoring credential
    on resume — the actual reason lived only in the worker's own log. Every
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
        # The capped, single-line reason the most recent FAILED ingest for a
        # thread ended with. Populated
        # alongside every FAILED outcome branch in ``ingest()``; the caller
        # (Executor._settle_run) consumes it via ``take_failure_reason`` right
        # after reading the outcome string, so it never outlives the run it
        # describes and never leaks across an unrelated later thread reusing
        # the same dict key.
        self._failure_reasons: dict[str, str] = {}
        # The provider condition the most recent FAILED ingest resolved, held
        # on the same terms as the reason beside it and popped by the same
        # caller. It is kept as well as emitted because the error frame is
        # droppable and the durable column is not: a reloading client recovers
        # the condition only if the terminal write carried it, and the terminal
        # is written from what this dict hands back.
        self._failure_conditions: dict[str, ProviderCondition] = {}

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
        self._failure_reasons.pop(thread_id, None)
        self._failure_conditions.pop(thread_id, None)
        task = self._fanout_tasks.pop(thread_id, None)
        if task is not None:
            task.cancel()

    def take_failure_reason(self, thread_id: str) -> str | None:
        """Pop and return the reason ``thread_id``'s last FAILED ingest ended with.

        ``None`` when the thread never failed (or its reason was already
        consumed) — the caller's default, never-durably-record-anything
        behaviour is unchanged when there is nothing to report.
        """
        return self._failure_reasons.pop(thread_id, None)

    def take_failure_condition(self, thread_id: str) -> ProviderCondition | None:
        """Pop the provider condition ``thread_id``'s last FAILED ingest resolved.

        ``None`` when no ingest classified a failure for this thread - it never
        failed, it failed on a branch that observed no provider, or the value
        was already consumed. The caller supplies the floor in that case, so an
        absent value here never becomes an absent condition on a failed run.
        """
        return self._failure_conditions.pop(thread_id, None)

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
        *,
        on_graph_started: Callable[[], Awaitable[None]] | None = None,
    ) -> str:
        """Start consuming ``astream_events`` from a compiled graph.

        Returns one of ``"completed"``, ``"interrupted"``, or ``"failed"``.
        """
        start = time.monotonic()
        cancel_event = self._get_cancel_event(thread_id)
        _is_interrupt = False
        _outcome = ThreadStatus.COMPLETED
        stall_timeout = domain_config.ingest_event_stall_timeout_seconds
        with self._telemetry.start_span(
            "aggregator.ingest",
            thread_id=thread_id,
            agent_id=agent_id,
        ) as span:
            try:
                # Bounded manual iteration, not `async for`: a plain `async for`
                # trusts astream_events to eventually yield, raise, or exhaust on
                # its own. A real run was observed wedging silently inside this
                # exact loop — no event, no exception, no log line, forever — with
                # LangGraph's own per-step `step_timeout` never firing to save it.
                # Wrapping each `__anext__()` in `wait_for` makes "no progress for
                # stall_timeout seconds" itself a caught, classified, reported
                # failure instead of an invisible hang, regardless of whether that
                # root cause is ever found.
                event_stream = graph.astream_events(
                    graph_input,
                    config,
                    version="v2",
                ).__aiter__()
                while True:
                    try:
                        raw_event = await asyncio.wait_for(
                            event_stream.__anext__(), timeout=stall_timeout
                        )
                    except StopAsyncIteration:
                        break
                    except TimeoutError as exc:
                        raise IngestStallTimeoutError(
                            f"Ingest stalled: no event from the graph for over "
                            f"{stall_timeout:.0f}s"
                        ) from exc
                    if on_graph_started is not None:
                        await on_graph_started()
                        on_graph_started = None
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
                _is_ingest_stall = isinstance(exc, IngestStallTimeoutError)
                # Checked after the more specific IngestStallTimeoutError above:
                # LangGraph's own step_timeout is also a bare TimeoutError, and
                # the stall watchdog is deliberately a TimeoutError subclass so
                # it still lands here as a fallback classification if this branch
                # order is ever lost — but the specific check gives the truer,
                # more actionable reason whenever it is the one that fired.
                _is_step_timeout = not _is_ingest_stall and isinstance(
                    exc, TimeoutError
                )
                _reason: str | None = None
                if _is_interrupt:
                    _outcome = "interrupted"
                    logger.info(
                        "Graph interrupted for thread %s (awaiting approval)",
                        thread_id,
                    )
                    span.set_attribute("interrupted", True)
                elif _is_recursion_limit:
                    _outcome = ThreadStatus.FAILED
                    _reason = (
                        "Graph recursion limit reached — check recursion_limit"
                        " configuration"
                    )
                    logger.warning(
                        "Graph recursion limit reached for thread %s", thread_id
                    )
                    span.set_attribute("error.type", "recursion_limit")
                    await self._emitters.emit_error(
                        thread_id=thread_id,
                        agent_id=agent_id,
                        code="RECURSION_LIMIT_EXCEEDED",
                        message=_reason,
                        recoverable=False,
                    )
                elif _is_ingest_stall:
                    _outcome = ThreadStatus.FAILED
                    _reason = str(exc)
                    logger.warning(
                        "Ingest stall watchdog fired for thread %s (%.0fs, no "
                        "LangGraph step_timeout caught it first)",
                        thread_id,
                        stall_timeout,
                    )
                    span.set_attribute("error.type", "ingest_stall_timeout")
                    await self._emitters.emit_error(
                        thread_id=thread_id,
                        agent_id=agent_id,
                        code="INGEST_STALL_TIMEOUT",
                        message=_reason,
                        recoverable=True,
                    )
                elif _is_step_timeout:
                    _outcome = ThreadStatus.FAILED
                    _reason = (
                        "A graph node exceeded the step timeout — "
                        "the operation may be retried"
                    )
                    logger.warning("Graph step_timeout fired for thread %s", thread_id)
                    span.set_attribute("error.type", "step_timeout")
                    await self._emitters.emit_error(
                        thread_id=thread_id,
                        agent_id=agent_id,
                        code="STEP_TIMEOUT",
                        message=_reason,
                        recoverable=True,
                    )
                else:
                    _outcome = ThreadStatus.FAILED
                    _reason = _summarize_ingest_exception(exc)
                    # Every provider fault reaches this branch, and the three
                    # branches above never do: a recursion limit, a stalled
                    # stream and a step timeout are facts about the graph
                    # infrastructure, not statements a provider made, so their
                    # codes and recoverability stay as they are. Here the code
                    # becomes the resolved condition - the catalogued field a
                    # consumer already branches on, now carrying the one
                    # classification that tells it which remedy to offer, in
                    # place of a constant that told it only which handler caught
                    # the failure.
                    #
                    # Recoverability comes from that same condition, through the
                    # one predicate the node retry policy also consults. It used
                    # to be a hardcoded false, which made the flag a statement
                    # about WHICH except-branch caught the exception rather than
                    # about the failure: a transient overload and a revoked
                    # credential were reported identically unrecoverable, while
                    # a step timeout was reported recoverable. Reading the shared
                    # predicate is also what stops the graph quietly retrying a
                    # failure the client was told was permanent.
                    _condition = _resolve_provider_condition(exc)
                    self._failure_conditions[thread_id] = _condition
                    logger.exception(
                        "Error during graph ingest for thread %s", thread_id
                    )
                    span.set_attribute("error", True)
                    span.set_attribute("error.provider_condition", _condition.value)
                    await self._emitters.emit_error(
                        thread_id=thread_id,
                        agent_id=agent_id,
                        code=_condition.value,
                        message=_reason,
                        recoverable=condition_is_retryable(_condition),
                    )
                if _reason is not None:
                    self._failure_reasons[thread_id] = _reason
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

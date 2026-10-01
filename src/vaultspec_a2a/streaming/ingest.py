"""Graph ingest lifecycle for the streaming event bus.

Manages graph consumption through LangGraph's public ``astream`` stream modes,
cancellation events, and outcome classification. Extracted from the monolithic
``aggregator.py`` during the aggregator decomposition.
"""

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, cast

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.errors import GraphDrained, GraphRecursionError, NodeTimeoutError
from langgraph.types import Command

from ..domain_config import domain_config
from ..graph.enums import AgentLifecycleState
from ..graph.protocols import NullTelemetryHook, TelemetryHook
from ..providers import ProviderCondition
from ..providers.acp_exceptions import AcpPromptCancelledError
from ..providers.conditions import condition_is_retryable
from ..thread.enums import ThreadStatus
from ..thread.errors import describe_exception_chain
from ._run_callbacks import RunLifecycleCallbacks
from .buffering import BufferingManager
from .emitters import EventEmitters
from .transformer import (
    STREAM_MODES,
    EventProjectionServices,
    StreamFrame,
    durable_loop_checkpoint_id,
    emit_interrupt_events,
    frame_reports_interrupt,
    process_stream_frame,
)
from .types import StreamableGraph

#: One frame of a graph stream: the namespace it came from, the mode that
#: produced it, and that mode's payload.
type RawStreamFrame = tuple[Any, Any, Any]

__all__ = ["INGEST_DRAINED", "IngestManager", "summarize_ingest_exception"]

#: The outcome of a run that stopped at a superstep boundary because its worker
#: asked it to drain. Not terminal: the checkpoint is resumable and the run's
#: action stays open for recovery to deliver again.
INGEST_DRAINED = "drained"

#: Persist each superstep before the next one starts, rather than while it
#: runs. Recovery here is checkpoint-first: a redelivered action is judged
#: against the last committed checkpoint, and both the dispatch pre-flight and
#: the drain contract read that checkpoint as the record of what the run
#: already did. LangGraph's default, ``"async"``, persists a superstep while
#: the next one executes and so may lose the most recent one to a crash -
#: which would have this service re-run work its checkpoint never recorded,
#: or settle a run on a checkpoint that is one superstep behind the truth.
_RUN_DURABILITY = "sync"

logger = logging.getLogger(__name__)


class IngestStallTimeoutError(TimeoutError):
    """Raised when the graph stream produces no new frame within the stall budget.

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
    event_read: "asyncio.Future[RawStreamFrame]",
    event_stream: AsyncIterator[RawStreamFrame],
) -> None:
    """Cancel a blocked next-frame read and close a generator when it supports it."""
    if not event_read.done():
        event_read.cancel()
    await asyncio.gather(event_read, return_exceptions=True)
    close = getattr(event_stream, "aclose", None)
    if close is not None:
        await close()


async def _next_event_or_cancel(
    event_stream: AsyncIterator[RawStreamFrame],
    cancel_event: asyncio.Event,
    *,
    stall_timeout: float,
) -> tuple[RawStreamFrame | None, bool]:
    """Wait for one graph frame, cancellation, or the independent stall bound."""
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
            "Ingest stalled: the graph stream produced no new "
            f"frame for over {stall_timeout:.0f}s"
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
    from the team TOML (``graph/compiler.py``) as a backstop a grace above the
    per-node run budget, so this bound always sits outside both. It is absent
    from the ``StreamableGraph`` protocol (a test double, or a graph compiled
    without a configured step_timeout, need not carry it), so it is read
    defensively and the global default is kept whenever it is missing or not
    the wider bound.
    """
    global_default = domain_config.ingest_event_stall_timeout_seconds
    node_step_timeout = getattr(graph, "step_timeout", None)
    if isinstance(node_step_timeout, int | float) and (
        node_step_timeout + _STEP_TIMEOUT_STALL_MARGIN_SECONDS > global_default
    ):
        return float(node_step_timeout) + _STEP_TIMEOUT_STALL_MARGIN_SECONDS
    return global_default


def _run_durability(graph: StreamableGraph) -> str | None:
    """Ask for synchronous checkpoints only on a run that keeps any.

    LangGraph documents ``durability`` as having no effect without a
    checkpointer and warns when one is passed anyway, but 1.2's asynchronous
    stream then waits on a checkpoint future a run without a checkpointer
    never creates, so the run dies with an ``AttributeError`` instead of
    executing. A graph compiled without a checkpointer is therefore left on
    the library default, which is what the documented semantics say it would
    have got in any case.

    ``checkpointer`` is absent from the streamable-graph protocol - a graph
    need not carry one - so it is read defensively, and only a real saver
    counts: the attribute also takes ``False`` (checkpointing off) and ``True``
    (a subgraph inheriting its parent's), neither of which is a saver this run
    would be writing through.
    """
    checkpointer = getattr(graph, "checkpointer", None)
    return _RUN_DURABILITY if isinstance(checkpointer, BaseCheckpointSaver) else None


def _config_with_run_callbacks(
    config: dict[str, Any], handler: RunLifecycleCallbacks
) -> dict[str, Any]:
    """Seat this run's tool-lifecycle handler beside any callbacks it was given.

    A tool call is a LangChain run rather than a graph superstep, so its start,
    end and failure never appear in a graph stream mode; the callback surface
    is where the library publishes them, and the run's config is where the
    library documents seating one. Callbacks the caller already supplied are
    kept: this run adds an observer, it does not take the channel over.
    """
    existing: object = config.get("callbacks")
    if existing is None:
        callbacks: list[object] = []
    elif isinstance(existing, list):
        callbacks = list(cast("list[object]", existing))
    else:
        callbacks = [existing]
    return {**config, "callbacks": [*callbacks, handler]}


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
    """Whether this frame is the one that should fire the started callback."""
    return not cancelled and not cancel_event.is_set() and on_graph_started is not None


def _receipt_is_due(
    frame: StreamFrame,
    cancelled: bool,
    cancel_event: asyncio.Event,
    on_graph_started: Callable[[], Awaitable[None]] | None,
) -> bool:
    """Whether this frame is the first committed checkpoint of the run's loop.

    The application receipt reports that a dispatch was incorporated, and it
    proves it by reading the incorporation back off a committed checkpoint. It
    used to be triggered by the run's first event, which by construction
    precedes every checkpoint, so the read found nothing and returned silently
    and the receipt never reached the gateway before settle. A checkpoint
    frame of the run's own loop is the earliest moment the proof exists.
    """
    if not _pending_graph_started_signal(cancelled, cancel_event, on_graph_started):
        return False
    return durable_loop_checkpoint_id(frame) is not None


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
    # The graph's LangGraph Runtime context for this invocation.
    context: object | None = None
    # The RunControl its worker can ask to drain the run through.
    control: object | None = None


@dataclass(frozen=True, slots=True)
class _FinalizeInterrupt:
    """What settling an interrupted run's outcome needs to know."""

    thread_id: str
    agent_id: str
    graph: StreamableGraph
    config: dict[str, Any]
    outcome: str
    stream_interrupted: bool
    span: Any


def _stream_frame(raw_event: RawStreamFrame) -> StreamFrame | None:
    """Read one ``(namespace, mode, payload)`` frame off the graph stream.

    ``subgraphs=True`` with several stream modes is the only shape this ingest
    asks for, so every frame is that triple. A frame of any other shape is a
    contract break rather than a variant to interpret, and is dropped with a
    log instead of being guessed at.
    """
    if not isinstance(raw_event, tuple) or len(raw_event) != 3:
        logger.warning("Unrecognised graph stream frame shape: %r", type(raw_event))
        return None
    namespace, mode, payload = raw_event
    if not isinstance(mode, str):
        logger.warning("Graph stream frame carried no mode: %r", type(mode))
        return None
    return StreamFrame(
        namespace=tuple(cast("tuple[str, ...]", namespace))
        if isinstance(namespace, tuple)
        else (),
        mode=mode,
        payload=payload,
    )


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
        self._projection = EventProjectionServices(emitters, buffering, telemetry)

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

    def run_lifecycle_callbacks(
        self, thread_id: str, agent_id: str
    ) -> RunLifecycleCallbacks:
        """The tool and model-completion handler a run seats in its config."""
        return RunLifecycleCallbacks(
            thread_id, agent_id, self._emitters, self._buffering
        )

    async def project_frame(
        self, frame: StreamFrame, *, thread_id: str, agent_id: str
    ) -> None:
        """Project one graph stream frame onto the run's event channels."""
        await process_stream_frame(
            frame, thread_id=thread_id, agent_id=agent_id, services=self._projection
        )

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
        event_stream: AsyncIterator[RawStreamFrame],
        cancel_event: asyncio.Event,
        stall_timeout: float,
    ) -> tuple[RawStreamFrame | None, bool, bool]:
        """Return ``(raw_frame, cancelled, exhausted)`` for one loop iteration.

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
        event_stream: AsyncIterator[RawStreamFrame],
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
        """Consume a compiled graph through LangGraph's public stream modes.

        Returns one of ``"completed"``, ``"interrupted"``, ``"cancelled"``,
        ``"drained"`` or ``"failed"``.
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
        # Set only on the paths that re-raise, so the closing work below knows
        # not to await anything more on a run whose caller is unwinding.
        unwinding = False
        # Set the moment the stream says the run parked, so the outcome never
        # depends on a state read taken after the stream ended.
        stream_interrupted = False
        with self._telemetry.start_span(
            "aggregator.ingest",
            thread_id=thread_id,
            agent_id=agent_id,
        ) as span:
            try:
                # Bounded manual iteration, not `async for`: a plain `async for`
                # trusts the stream to eventually yield, raise, or exhaust on
                # its own. Race every blocked next-frame read against the local
                # cancellation event as well as the independent watchdog, so a
                # cancellation never depends on the graph yielding another frame.
                event_stream = graph.astream(
                    graph_input,
                    _config_with_run_callbacks(
                        config, self.run_lifecycle_callbacks(thread_id, agent_id)
                    ),
                    stream_mode=list(STREAM_MODES),
                    subgraphs=True,
                    context=request.context,
                    control=request.control,
                    durability=_run_durability(graph),
                ).__aiter__()
                while True:
                    raw_event, cancelled, exhausted = await self._next_ingest_event(
                        event_stream, cancel_event, stall_timeout
                    )
                    if exhausted:
                        break
                    if cancelled or cancel_event.is_set():
                        await self._handle_ingest_cancellation(
                            event_stream, thread_id, agent_id, span
                        )
                        _outcome = ThreadStatus.CANCELLED
                        break
                    if raw_event is None:
                        raise RuntimeError("frame read completed without a frame")
                    frame = _stream_frame(raw_event)
                    if frame is None:
                        continue
                    stream_interrupted = stream_interrupted or frame_reports_interrupt(
                        frame
                    )
                    if _receipt_is_due(
                        frame, cancelled, cancel_event, on_graph_started
                    ):
                        assert on_graph_started is not None
                        await on_graph_started()
                        on_graph_started = None
                    await self.project_frame(
                        frame, thread_id=thread_id, agent_id=agent_id
                    )
            except asyncio.CancelledError:
                # A cancelled run is not a failed run. The worker's own
                # lifespan cancels whatever is still mid-turn when the drain
                # budget runs out, and the drain contract says that run's open
                # action is delivered again; classifying the cancellation as a
                # provider failure instead persisted a FAILED terminal for a
                # run nothing had failed, and logged a provider error for it.
                # Swallowing it is also what let an outer timeout around
                # ingest return a settled-looking outcome, so it is re-raised
                # for whoever asked for the cancellation to observe.
                unwinding = True
                logger.info("Ingest cancelled for thread %s", thread_id)
                span.set_attribute("cancelled", True)
                span.set_attribute("cancelled.by", "task")
                raise
            except BaseException as exc:
                _outcome = await self._handle_ingest_failure(
                    (thread_id, agent_id), exc, stall_timeout, span
                )
                if not isinstance(exc, Exception):
                    # Outside Exception is a signal to whoever runs the ingest,
                    # not a failure of the run: viewers are told the run did
                    # not finish, and the signal reaches its owner without
                    # first waiting on the work that settles a served run.
                    unwinding = True
                    raise
            finally:
                self._clear_cancel_event(thread_id)
                self._buffering.prune_tool_debounce(thread_id)
                # Neither the buffer flush nor the state read is awaited on a
                # path that re-raises: under a cancel scope every await raises
                # at once, a signal must not wait behind a bounded read, and a
                # state read taken while the run is being torn down describes
                # nothing the outcome may rest on.
                if not unwinding:
                    await self._buffering.flush_chunk_buffer(thread_id)
                    _outcome = await self._finalize_interrupt(
                        _FinalizeInterrupt(
                            thread_id=thread_id,
                            agent_id=agent_id,
                            graph=graph,
                            config=config,
                            outcome=_outcome,
                            stream_interrupted=stream_interrupted,
                            span=span,
                        )
                    )
                self._telemetry.record_histogram(
                    "aggregator.ingest_duration_seconds",
                    time.monotonic() - start,
                    thread_id=thread_id,
                )
        return _outcome

    async def _finalize_interrupt(self, request: _FinalizeInterrupt) -> str:
        """Settle an interrupted run's outcome and project what it asked for.

        The stream is the authority on whether the run parked: it reports a
        park as it happens, so a state read that times out can no longer turn
        an interrupted run into a completed one. The read is still made, but
        only to recover the interrupts' payloads for the permission and
        clarification frames; when it fails, the run is still reported
        interrupted and the client recovers the questions from run-status,
        which projects them from the live checkpoint.
        """
        span = request.span
        if not request.stream_interrupted:
            return request.outcome
        span.set_attribute("interrupted", True)
        projected = await emit_interrupt_events(
            request.thread_id,
            request.agent_id,
            request.graph,
            request.config,
            self._emitters,
        )
        if not projected:
            logger.warning(
                "Thread %s parked on an interrupt whose payload could not be "
                "read back; the run is reported interrupted and its questions "
                "are recoverable from run status",
                request.thread_id,
            )
            span.set_attribute("interrupt.payload_projected", False)
        if request.outcome == ThreadStatus.COMPLETED:
            return "interrupted"
        return request.outcome

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
        if isinstance(exc, GraphRecursionError):
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
        if isinstance(exc, NodeTimeoutError):
            # Reported under the step-timeout code clients already know; the
            # message is what gains the node and the limit it hit.
            logger.warning(
                "Node %s exceeded its %s timeout after %.0fs for thread %s",
                exc.node,
                exc.kind,
                exc.elapsed,
                thread_id,
            )
            return await self._report_ingest_error(
                identity,
                span,
                (
                    f"Graph node {exc.node!r} exceeded its {exc.kind} timeout "
                    f"after {exc.elapsed:.0f}s - the operation may be retried",
                    "STEP_TIMEOUT",
                    True,
                    "node_timeout",
                ),
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
        if isinstance(exc, GraphDrained):
            logger.info(
                "Graph drained for thread %s at a superstep boundary (%s)",
                thread_id,
                exc.reason,
            )
            span.set_attribute("drained", True)
            return INGEST_DRAINED
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

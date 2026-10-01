"""Graph execution engine -- manages LangGraph run lifecycle.

Dispatch orchestration: routes ingest/resume/cancel requests, manages
concurrency gating.  Delegates graph compilation to ``GraphLifecycleManager``
and checkpoint/state projection to ``StateProjector``.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast, override

from langgraph.types import Command

from ..control.permission_dispatch import answered_permission_request
from ..domain_config import domain_config
from ..graph.run_context import RunContext
from ..ipc.serializers import sequenced_to_dict
from ..providers.team_selection import model_assignment_digest

# A cancelled dispatch settles on the same terms as a drained one, and for the
# same reason: both stop a run that is not over, leaving a resumable
# checkpoint and an open action for recovery to deliver again. Settling it as
# FAILED instead wrote a terminal for a run nothing had failed.
from ..streaming.ingest import INGEST_DRAINED
from ..streaming.node_metadata import node_metadata_from_graph
from ..telemetry import ws_span
from ..thread.constants import DEFAULT_SUPERVISOR_ID
from ..thread.enums import TERMINAL_STATUSES, ControlActionType, ThreadStatus
from ..utils.logging import log_context
from ._authoring_close import close_authoring_session_best_effort
from ._dispatch_contract import (
    _INGEST_GUARDS,
    _RESUME_GUARDS,
    _SLOT_OWNING_ACTIONS,
    CAPACITY_ACCEPTED,
    CAPACITY_DRAINING,
    CAPACITY_FULL,
    CAPACITY_THREAD_ACTIVE,
    DispatchCapacityReservation,
    _GuardWording,
)
from ._dispatch_settlement import SettlementMixin
from ._executor_state import (
    CheckpointAccess,
    DispatchCapacityState,
    RunControlRegistry,
    RunResources,
)
from .graph_lifecycle import (
    GraphCompilationError,
    GraphCompilationKey,
    GraphLifecycleManager,
    RegisteredCompiledGraph,
)
from .state_projection import (
    PreflightDecision,
    ResumeAdmission,
    ResumeRefusal,
    StateProjector,
)

if TYPE_CHECKING:
    from contextvars import ContextVar

    from opentelemetry.trace import Span

    from ..database.checkpoints import Checkpointer
    from ..ipc.schemas import DispatchRequest
    from ..streaming.aggregator import EventAggregator
    from ..streaming.types import SequencedEvent, StreamableGraph
    from ..thread.action_receipts import GraphActionReceipt
    from ._dispatch_receipts import DispatchReceiptReporter
    from ._dispatch_settlement import TerminalArbitration
    from .catalog_store import RunCatalogStore
    from .ipc import WorkerBridge
    from .token_store import RunTokenStore

# ``GraphCompilationError`` is imported to be CAUGHT here, not re-published:
# ``graph_lifecycle`` raises it and is where every handler imports it from.
__all__ = [
    "Executor",
]

logger = logging.getLogger(__name__)


def _invocation_config(req: DispatchRequest, *, action: str) -> dict[str, Any]:
    """The LangGraph config one ingest or resume runs under.

    The metadata and tags are what let a trace backend group every model and
    tool call of an invocation under the run and dispatch that caused it; with
    only the thread id, a resumed run's calls were indistinguishable from the
    ingest's.
    """
    return {
        "configurable": {"thread_id": req.thread_id},
        "recursion_limit": _recursion_limit(req),
        "run_name": f"vaultspec-a2a {action}",
        "metadata": {
            "thread_id": req.thread_id,
            "dispatch_id": req.dispatch_id,
            "action": action,
        },
        "tags": ["vaultspec-a2a", f"action:{action}"],
    }


def _recursion_limit(req: DispatchRequest) -> int:
    """The tighter of the operator's ceiling and the accepted preset's own budget.

    The gateway sends the operator-wide ceiling on every dispatch; the limit a
    preset declares rides its frozen graph definition, so a run is held to the
    preset's budget without ever exceeding the operator's.
    """
    definition = req.graph_definition
    if definition is None:
        return req.recursion_limit
    return min(req.recursion_limit, definition.recursion_limit)


def _addressed_resume(resume_value: object, admission: ResumeAdmission) -> object:
    """The resume value, addressed to its interrupt when it has to be.

    LangGraph matches a bare resume value to the run's single pending
    interrupt, and refuses one outright while several are pending: a bare value
    says nothing about which of them it answers. Keying the value by the
    interrupt it belongs to is the documented way to answer one of several,
    and it is used only then - a run waiting on one question takes the plain
    value, which is the shape every existing resume already sends.
    """
    if admission.interrupt_id is None:
        return resume_value
    return {admission.interrupt_id: resume_value}


def _answered_permission_update(resume_value: object) -> dict[str, Any]:
    """The state delta recording a tool-permission answer under its request.

    Carried alongside the resume rather than instead of it: the answer still
    re-enters through ``Command(resume=...)``, and this is what lets the
    worker turn that replays afterwards find the answer by the request it
    answered instead of by the position its interrupts fall in. A resume that
    is not a tool-permission answer contributes nothing.
    """
    answered = answered_permission_request(resume_value)
    if answered is None:
        return {}
    request_id, option_id = answered
    return {"permission_answers": {request_id: option_id}}


def _run_context(req: DispatchRequest, *, action: str) -> RunContext:
    """The Runtime context the graph's nodes read their run identity from."""
    return RunContext(
        thread_id=req.thread_id, dispatch_id=req.dispatch_id, action=action
    )


@dataclass(frozen=True, slots=True)
class _AdmittedRun:
    """A dispatch that got past admission, and everything executing it needs.

    The compiled graph, the config it runs under, and the wording of the mode
    it runs in are decided together at admission and consumed together by
    execution, so they travel as one value rather than as three arguments
    threaded through every arm.
    """

    graph: RegisteredCompiledGraph
    config: dict[str, Any]
    guards: _GuardWording


def _ingest_graph_input(
    req: DispatchRequest,
    graph: RegisteredCompiledGraph,
    receipt: GraphActionReceipt,
    preflight: PreflightDecision,
) -> dict[str, Any] | None:
    """The state one ingest delivers, or nothing when it continues part-way.

    A run whose own input is already committed to the checkpoint resumes from
    it with no input at all, so the message is not delivered twice and
    finished nodes do not re-run.
    """
    if preflight.resume_from_checkpoint:
        return None
    graph_input = GraphLifecycleManager.build_graph_input(
        req, is_first_ingest=preflight.is_first_ingest
    )
    graph_input["agent_descriptors"] = node_metadata_from_graph(graph)
    graph_input["graph_action_receipts"] = {
        req.dispatch_id: receipt.model_dump(mode="json")
    }
    graph_input["active_graph_action_receipt"] = receipt.model_dump(mode="json")
    return graph_input


def _resume_command(
    req: DispatchRequest,
    receipt: GraphActionReceipt,
    graph: RegisteredCompiledGraph,
    admission: ResumeAdmission,
) -> Command:
    """The answer one resume re-enters on, with the keys bound atomically to it.

    Every key here is bound atomically with the answer, which is what lets a
    run parked before checkpoint evidence existed acquire its digests without
    a separate state update that would invalidate the interrupt it is parked
    on. LangGraph holds a resume's input writes against that checkpoint and
    accumulates them until a superstep consumes them, so a turn needing a
    second approval, and a resume redelivered after its turn died, each write
    these keys twice in one step. Every one of them therefore reduces rather
    than holding a single value.
    """
    return Command(
        resume=_addressed_resume(req.option_id, admission),
        update={
            "graph_action_receipts": {req.dispatch_id: receipt.model_dump(mode="json")},
            "active_graph_action_receipt": receipt.model_dump(mode="json"),
            "agent_descriptors": node_metadata_from_graph(graph),
            "graph_definition_digest": req.require_graph_definition().digest(),
            "model_assignment_digest": model_assignment_digest(req.model_assignment),
            **_answered_permission_update(req.option_id),
        },
    )


class Executor(SettlementMixin):
    """Orchestrate graph runs, projections, events, and dispatch capacity."""

    def __init__(
        self,
        checkpointer: Checkpointer,
        bridge: WorkerBridge,
        *,
        checkpoint_read_timeout_seconds: float | None = None,
    ) -> None:
        self._checkpoint = CheckpointAccess(
            checkpointer=checkpointer,
            read_timeout_seconds=(
                checkpoint_read_timeout_seconds
                if checkpoint_read_timeout_seconds is not None
                else domain_config.aget_state_timeout_seconds
            ),
        )
        self._bridge = bridge
        self._resources = RunResources()
        # One drain handle per run executing here, so a shutdown can stop
        # every run at a superstep boundary and know when they have stopped.
        self._run_controls = RunControlRegistry()

        # Worker-scoped holder of per-run actor tokens. Registered when a
        # run's active window opens and dropped when it closes, so tokens live
        # only inside the owning worker for the run and never touch a checkpoint.

        # Worker-scoped cache of per-run engine catalog snapshots, dropped on the
        # same terminal boundary as the token store so a snapshot never outlives a
        # run. Shared with the graph lifecycle's authoring-bridge provider.

        # Delegates
        self._graph_lifecycle = GraphLifecycleManager(
            checkpointer=checkpointer,
            bridge=bridge,
            aggregator=self._aggregator,
            token_store=self._token_store,
            catalog_store=self._catalog_store,
            checkpoint_read_timeout_seconds=checkpoint_read_timeout_seconds,
        )
        self._state_projector = StateProjector(
            checkpointer=checkpointer,
            bridge=bridge,
            log_extra_fn=self._log_extra,
        )

        # Wire bridge relay: every broadcast event is forwarded to the control
        # surface via HTTP.  Closure captures bridge reference.
        _bridge_ref = bridge

        async def _relay_event(sequenced: SequencedEvent) -> None:
            thread_id = getattr(sequenced.event, "thread_id", "")
            if thread_id:
                await _bridge_ref.send_event(thread_id, sequenced_to_dict(sequenced))

        self._aggregator.add_broadcast_hook(_relay_event)

        self._capacity = DispatchCapacityState()

    @property
    def _checkpointer(self) -> Checkpointer:
        return self._checkpoint.checkpointer

    @property
    def _checkpoint_read_timeout_seconds(self) -> float:
        return self._checkpoint.read_timeout_seconds

    @property
    @override
    def _aggregator(self) -> EventAggregator:
        return self._resources.aggregator

    @property
    def _token_store(self) -> RunTokenStore:
        return self._resources.token_store

    @property
    def _catalog_store(self) -> RunCatalogStore:
        return self._resources.catalog_store

    @property
    def _receipts(self) -> DispatchReceiptReporter:
        """One incorporation report per dispatch.

        Whichever of a run's two chances to prove incorporation - its first
        committed checkpoint, or its settle - gets there first.
        """
        return self._resources.receipts

    @property
    @override
    def _terminal_arbitrations(self) -> dict[str, TerminalArbitration]:
        return self._capacity.terminal_arbitrations

    @property
    @override
    def _active_ingests(self) -> dict[str, DispatchCapacityReservation]:
        return self._capacity.active_ingests

    @property
    @override
    def _pending_cancellations(self) -> dict[str, str]:
        return self._capacity.pending_cancellations

    @property
    @override
    def _ingest_lock(self) -> asyncio.Lock:
        return self._capacity.lock

    @property
    def _next_capacity_generation(self) -> int:
        return self._capacity.next_generation

    @property
    @override
    def _dispatch_reservation(self) -> ContextVar[DispatchCapacityReservation | None]:
        return self._capacity.reservation

    @property
    def aggregator(self) -> EventAggregator:
        """Return the event aggregator (for subscriber wiring, if needed)."""
        return self._aggregator

    @property
    def token_store(self) -> RunTokenStore:
        """Return the worker-scoped actor token store.

        The per-run authoring binding reads each worker's own token from here
        when it assembles that worker's tool surface; the store holds a run's
        tokens only for its active dispatch window.
        """
        return self._token_store

    @property
    def graph_count(self) -> int:
        """Number of compiled graphs currently held."""
        return self._graph_lifecycle.graph_count

    @property
    def active_ingest_count(self) -> int:
        """Number of concurrently active graph ingests."""
        return len(self._active_ingests)

    def register_compiled_graph(
        self,
        thread_id: str,
        compilation_key: GraphCompilationKey,
        graph: RegisteredCompiledGraph,
    ) -> None:
        """Register a pre-compiled graph through the lifecycle's atomic seam."""
        self._graph_lifecycle.register_compiled_graph(thread_id, compilation_key, graph)

    def _log_extra(self, **fields: Any) -> dict[str, Any]:
        """Build bounded structured log fields for executor-owned events."""
        extra = {
            "worker_id": getattr(self._bridge, "_worker_id", None),
            "active_thread_count": self.active_ingest_count,
        }
        extra.update(fields)
        return {key: value for key, value in extra.items() if value is not None}

    @override
    def _dispatch_log_extra(
        self,
        req: DispatchRequest,
        **fields: Any,
    ) -> dict[str, Any]:
        """Build structured log fields for a dispatch-bound executor event."""
        return self._log_extra(
            thread_id=req.thread_id,
            dispatch_id=req.dispatch_id,
            dispatch_action=req.action,
            agent_id=req.agent_id,
            team_preset=req.team_preset,
            autonomous=req.autonomous,
            **fields,
        )

    @override
    async def _emit_dispatch_application_receipt(self, req: DispatchRequest) -> None:
        await self._receipts.report(
            req,
            self._checkpointer,
            self._bridge,
            self._checkpoint_read_timeout_seconds,
            self._dispatch_log_extra,
        )

    async def reserve_dispatch_capacity(
        self, thread_id: str
    ) -> tuple[DispatchCapacityReservation | None, str]:
        """Atomically reserve pre-compile capacity for one thread dispatch.

        Returns the reservation, or ``None`` with the bounded reason it was
        refused. The reason is part of the result because the two refusals mean
        opposite things to the caller: a thread that is already running is a
        semantic conflict about one run, while a full worker is backpressure
        about all of them.
        """
        return await self._reserve_dispatch_capacity(thread_id)

    async def _reserve_dispatch_capacity(
        self, thread_id: str
    ) -> tuple[DispatchCapacityReservation | None, str]:
        """Return the bounded reason for one atomic capacity decision."""
        async with self._terminal_arbitration(thread_id), self._ingest_lock:
            if self._run_controls.draining:
                return None, CAPACITY_DRAINING
            if thread_id in self._active_ingests:
                return None, CAPACITY_THREAD_ACTIVE
            if len(self._active_ingests) >= domain_config.max_concurrent_threads:
                return None, CAPACITY_FULL
            self._capacity.next_generation += 1
            reservation = DispatchCapacityReservation(
                thread_id=thread_id,
                generation=self._capacity.next_generation,
            )
            self._active_ingests[thread_id] = reservation
            return reservation, CAPACITY_ACCEPTED

    @override
    async def release_dispatch_capacity(
        self, reservation: DispatchCapacityReservation
    ) -> bool:
        """Release only the exact dispatch reservation supplied by its owner."""
        async with self._ingest_lock:
            if self._active_ingests.get(reservation.thread_id) is not reservation:
                return False
            self._active_ingests.pop(reservation.thread_id)
            return True

    @override
    async def _mark_ingest_done(
        self,
        thread_id: str,
        outcome: str,
        reservation: DispatchCapacityReservation | None = None,
    ) -> None:
        """Release the ingest slot, untrack thread, prune aggregator.

        Drops the run's actor tokens only on a TERMINAL *outcome*. An
        ``"interrupted"`` ingest means the run parked at a gate and will resume -
        a later document gate (the ADR gate) authors again through the submitter,
        which reads the run's bearer/actor tokens from the store at call time - so
        the tokens must survive park->resume and are dropped only when the run
        truly terminates (the token window closes at termination, not at an
        interrupt-park).
        """
        async with self._ingest_lock:
            active_snapshot = set(self._active_ingests).difference({thread_id})
        # Drop the run's actor tokens when its active window truly closes,
        # i.e. a terminal outcome - never on an interrupt-park that will resume.
        if outcome in TERMINAL_STATUSES:
            self._graph_lifecycle.release_thread(thread_id)
            self._token_store.drop(thread_id)
            self._catalog_store.drop(thread_id)
            self._aggregator.remove_node_metadata(thread_id)
            self._aggregator.clear_thread_state(thread_id)
        self._bridge.untrack_thread(thread_id)
        # Prune sequences for threads that are no longer actively executing.
        self._aggregator.prune_sequences(active_snapshot)
        # Prune permissions older than 5 minutes regardless of thread state.
        self._aggregator.prune_stale_permissions()
        reservation = reservation or self._dispatch_reservation.get()
        if reservation is not None:
            await self.release_dispatch_capacity(reservation)

    @override
    async def _close_authoring_session_best_effort(
        self, thread_id: str, graph: StreamableGraph, config: dict[str, Any]
    ) -> None:
        await close_authoring_session_best_effort(
            thread_id, graph, config, self._token_store
        )

    async def handle_dispatch(self, req: DispatchRequest) -> None:
        """Reserve capacity and route a direct ``DispatchRequest`` call."""
        owns_slot = req.action in _SLOT_OWNING_ACTIONS
        reservation, refusal_reason = (
            await self._reserve_dispatch_capacity(req.thread_id)
            if owns_slot
            else (None, CAPACITY_ACCEPTED)
        )
        if refusal_reason != CAPACITY_ACCEPTED:
            guards = (
                _INGEST_GUARDS
                if req.action == ControlActionType.INGEST
                else _RESUME_GUARDS
            )
            if refusal_reason == CAPACITY_THREAD_ACTIVE:
                action, wording = guards.slot_held_action, guards.slot_held
            elif refusal_reason == CAPACITY_DRAINING:
                action, wording = (
                    "dispatch_refused_draining",
                    "Worker is draining -- refused dispatch for thread %s",
                )
            else:
                action, wording = (
                    "dispatch_capacity_refused",
                    "Worker capacity refused dispatch for thread %s",
                )
            logger.warning(
                wording,
                req.thread_id,
                extra=self._dispatch_log_extra(
                    req, action=action, runtime_mode=guards.runtime_mode
                ),
            )
            return
        await self.handle_reserved_dispatch(req, reservation)

    async def handle_reserved_dispatch(
        self,
        req: DispatchRequest,
        reservation: DispatchCapacityReservation | None,
    ) -> None:
        """Route an endpoint-admitted dispatch and always release its reservation."""
        reservation_context = self._dispatch_reservation.set(reservation)
        try:
            # Every record of the run - provider, streaming and graph logs as
            # well as the executor's own - carries the run it belongs to.
            with log_context(
                thread_id=req.thread_id,
                dispatch_id=req.dispatch_id,
                action=str(req.action),
            ):
                async with ws_span(
                    f"executor.{req.action}",
                    thread_id=req.thread_id,
                    agent_id=req.agent_id or "supervisor",
                ) as span:
                    # Matched as `object`: the wildcard branch below is a real
                    # defense against a caller-constructed request carrying an
                    # action outside the declared Literal, not dead code.
                    match cast("object", req.action):
                        case "ingest":
                            await self._handle_ingest(req)
                        case "resume":
                            await self._handle_resume(req)
                        case "cancel":
                            span.add_event("thread_cancelled")
                            # `dispatch_id` is a required str field, but this guard
                            # defends against a caller-constructed request that
                            # bypassed the model's own validation.
                            if cast("object", req.dispatch_id) is None:
                                raise ValueError(
                                    "cancel dispatch requires a stable identity"
                                )
                            async with self._terminal_arbitration(req.thread_id):
                                await self._handle_cancel(req)
                        case _:
                            logger.warning(
                                "Unknown dispatch action: %s",
                                req.action,
                                extra=self._dispatch_log_extra(
                                    req,
                                    action="unknown_dispatch_action",
                                ),
                            )
                            span.set_attribute("error", True)
                            span.set_attribute(
                                "error.message", f"Unknown action: {req.action}"
                            )
        except Exception as exc:
            logger.exception(
                "Unhandled exception in handle_dispatch (action=%s, thread=%s); "
                "worker task group protected — failing the run",
                req.action,
                req.thread_id,
                extra=self._dispatch_log_extra(
                    req,
                    action="dispatch_unhandled_exception",
                ),
            )
            await self._fail_unhandled_dispatch(req, exc, reservation)
        finally:
            try:
                if reservation is not None:
                    await self.release_dispatch_capacity(reservation)
            finally:
                self._dispatch_reservation.reset(reservation_context)

    async def _handle_cancel(self, req: DispatchRequest) -> None:
        """Apply one cancel while holding the run's terminal arbitration lock."""
        self._pending_cancellations[req.thread_id] = req.dispatch_id
        self._aggregator.cancel_thread(req.thread_id)
        # Release the run's tokens and cached catalog on the
        # TERMINAL boundary only. When an ingest is still active
        # the cancel is not yet terminal: that ingest settles
        # (its finally calls _mark_ingest_done) and drops them
        # there, so an in-flight authoring call is never stranded
        # of its own token mid-run. Only a cancel with no active
        # ingest is itself terminal and releases here. (TOCTOU
        # safe: cancel flag set before the check; DB rejects
        # duplicate terminals.)
        async with self._ingest_lock:
            is_active = req.thread_id in self._active_ingests
        if not is_active:
            self._token_store.drop(req.thread_id)
            self._catalog_store.drop(req.thread_id)
            await self._state_projector.emit_terminal_status(
                req.thread_id,
                ThreadStatus.CANCELLED,
                evidence=self._take_cancellation_evidence(
                    req.thread_id, outcome="no_active_work"
                ),
            )
            self._graph_lifecycle.release_thread(req.thread_id)
            self._aggregator.remove_node_metadata(req.thread_id)
            self._aggregator.clear_thread_state(req.thread_id)

    async def _handle_ingest(self, req: DispatchRequest) -> None:
        """Compile graph on first use and execute a new user turn."""
        async with ws_span("executor.ingest", thread_id=req.thread_id) as span:
            try:
                receipt = req.require_graph_action_receipt()
            except ValueError as exc:
                await self._reject_with_condition(req, str(exc))
                return
            checkpoint_deadline = (
                asyncio.get_running_loop().time()
                + self._checkpoint_read_timeout_seconds
            )
            # Pre-flight: an ingest is delivered again after a worker restart,
            # so the checkpoint may already hold this action - finished, parked,
            # or part-way. It also grounds is_first_ingest in checkpoint truth
            # rather than the stale in-memory cache.
            preflight = await self._state_projector.pre_flight_checkpoint(
                receipt,
                timeout_seconds=max(
                    0.0,
                    checkpoint_deadline - asyncio.get_running_loop().time(),
                ),
            )
            if await self._preflight_settled_ingest(req, span, preflight):
                return

            span.set_attribute("is_first_ingest", preflight.is_first_ingest)
            span.set_attribute(
                "resume_from_checkpoint", preflight.resume_from_checkpoint
            )

            run = await self._admit_run(req, span, checkpoint_deadline, _INGEST_GUARDS)
            if run is None:
                return

            self._bridge.track_thread(req.thread_id)
            # Hold the run's per-role tokens for this active window only.
            self._token_store.register(req.thread_id, req.actor_tokens)

            await self._execute_run(
                req,
                span,
                run,
                _ingest_graph_input(req, run.graph, receipt, preflight),
            )

    async def _preflight_settled_ingest(
        self,
        req: DispatchRequest,
        span: Span,
        preflight: PreflightDecision,
    ) -> bool:
        """Whether the checkpoint already settled this ingest's fate.

        A redelivered ingest whose action the checkpoint already finished,
        failed or parked on must not run again; one whose checkpoint cannot
        say what running it would do must not run at all. Each of those is
        answered here, and ``True`` means the dispatch is done with.
        """
        if preflight.refusal is not None:
            span.set_attribute("pre_flight", "refused")
            await self._reject_with_condition(req, preflight.refusal)
            return True
        outcome = preflight.outcome
        if outcome == ThreadStatus.COMPLETED:
            await self._settle_completed_preflight(req, span)
            return True
        if outcome == ThreadStatus.FAILED:
            logger.warning(
                "Thread %s checkpoint shows error before crash"
                " — emitting failed without re-running",
                req.thread_id,
                extra=self._dispatch_log_extra(
                    req,
                    action="checkpoint_preflight_terminal",
                    outcome=ThreadStatus.FAILED,
                ),
            )
            span.set_attribute("pre_flight", "failed")
            await self._reject_with_condition(
                req,
                "The run's checkpoint records an unhandled error from an "
                "earlier attempt; it was not re-run",
            )
            return True
        if outcome == "interrupted":
            logger.info(
                "Thread %s checkpoint is paused at interrupt"
                " — skipping ingest; awaiting resume dispatch",
                req.thread_id,
                extra=self._dispatch_log_extra(
                    req,
                    action="checkpoint_preflight_interrupted",
                    outcome="interrupted",
                ),
            )
            span.set_attribute("pre_flight", "interrupted")
            return True
        return False

    async def _admit_run(
        self,
        req: DispatchRequest,
        span: Span,
        checkpoint_deadline: float,
        guards: _GuardWording,
    ) -> _AdmittedRun | None:
        """Compile the run's graph and bind the config it will run under.

        ``None`` means the dispatch was already rejected on the client's
        channel - the graph refused to compile, or there is no graph to run -
        so the caller has nothing left to do for it.
        """
        try:
            graph = await self._graph_lifecycle.get_or_compile_graph(
                req, checkpoint_deadline=checkpoint_deadline
            )
        except GraphCompilationError as exc:
            await self._reject_compile_failure(req, span, exc, guards)
            return None
        if graph is None:
            await self._reject_missing_graph(req, span, guards)
            return None
        return _AdmittedRun(
            graph=graph,
            config=_invocation_config(req, action=guards.runtime_mode),
            guards=guards,
        )

    async def _execute_run(
        self,
        req: DispatchRequest,
        span: Span,
        run: _AdmittedRun,
        graph_input: dict[str, Any] | Command | None,
    ) -> None:
        """Stream one admitted dispatch through its graph and settle it.

        Ingest and resume reach the graph with different input and part under
        different wording, but the window around the stream is one behaviour:
        every exit - a returned outcome, a drain, a fault, or a cancellation
        that bypasses ``except Exception`` entirely - settles the run exactly
        once and then closes its drain handle.
        """
        action = run.guards.runtime_mode
        # Stays None unless the catch-all below fires, so a run that settles
        # normally offers no fallback and keeps whatever ingest classified.
        execution_failure_reason: str | None = None
        # Pre-bound so `finally` always has a value to settle with, including
        # for a BaseException that bypasses the `except Exception` clause
        # below (e.g. cancellation) before `ingest` assigns its own outcome.
        outcome: str = ThreadStatus.FAILED
        try:
            span.add_event(f"{action}_graph_execution_started")
            outcome = await self._aggregator.ingest(
                req.thread_id,
                req.agent_id or DEFAULT_SUPERVISOR_ID,
                run.graph,
                graph_input,
                run.config,
                on_graph_started=lambda: self._emit_dispatch_application_receipt(req),
                context=_run_context(req, action=action),
                control=self._run_controls.open(req.thread_id),
            )
            span.set_attribute("outcome", outcome)
        except asyncio.CancelledError:
            outcome = INGEST_DRAINED
            span.set_attribute("outcome", outcome)
            raise
        except Exception:
            outcome = ThreadStatus.FAILED
            execution_failure_reason = run.guards.execution_failure_detail
            logger.exception(
                run.guards.execution_failure,
                req.thread_id,
                extra=self._dispatch_log_extra(
                    req,
                    action=run.guards.execution_failure_action,
                    runtime_mode=action,
                ),
            )
            span.record_exception(Exception(f"Graph {action} failed"))
        finally:
            try:
                await self._settle_run(
                    req, run.graph, run.config, outcome, execution_failure_reason
                )
            finally:
                self._close_run_control(req.thread_id)

    async def _handle_resume(self, req: DispatchRequest) -> None:
        """Resume a graph from a LangGraph interrupt via ``Command(resume=...)``."""
        async with ws_span("executor.resume", thread_id=req.thread_id) as span:
            try:
                receipt = req.require_graph_action_receipt()
            except ValueError as exc:
                await self._reject_with_condition(req, str(exc))
                return
            checkpoint_deadline = (
                asyncio.get_running_loop().time()
                + self._checkpoint_read_timeout_seconds
            )
            # Record resume option (cast to str for span attribute)
            val = str(req.option_id) if req.option_id else "none"
            span.set_attribute("option_id", val)

            run = await self._admit_run(req, span, checkpoint_deadline, _RESUME_GUARDS)
            if run is None:
                return

            admission = await self._state_projector.pre_flight_resume(
                run.graph,
                run.config,
                receipt,
                resume_value=req.option_id,
                timeout_seconds=max(
                    0.0, checkpoint_deadline - asyncio.get_running_loop().time()
                ),
            )
            if isinstance(admission, ResumeRefusal):
                await self._refuse_resume(req, span, run, admission)
                return

            self._bridge.track_thread(req.thread_id)
            # A resumed turn re-provisions the run's tokens for its window.
            self._token_store.register(req.thread_id, req.actor_tokens)

            await self._execute_run(
                req,
                span,
                run,
                _resume_command(req, receipt, run.graph, admission),
            )

    async def _refuse_resume(
        self,
        req: DispatchRequest,
        span: Span,
        run: _AdmittedRun,
        refusal: ResumeRefusal,
    ) -> None:
        """Turn an answer away without settling the run it was meant for.

        A refused answer is not a failed run: the run is still executing, or
        still waiting on the question it really asked, and settling it here
        would end a run on a client's mistake. The client is told on the coded
        channel, and the run's current execution state is projected after it so
        a reader that acts on the frame re-reads authoritative state rather
        than the frame's own wording.
        """
        logger.warning(
            "Resume for thread %s refused as %s; the run is waiting on %s",
            req.thread_id,
            refusal.cause.value,
            ", ".join(refusal.pending_request_ids) or "no request",
            extra=self._dispatch_log_extra(
                req,
                action="resume_refused_unparked",
                runtime_mode=_RESUME_GUARDS.runtime_mode,
                refusal=refusal.cause.value,
            ),
        )
        span.set_attribute("pre_flight", "refused")
        span.set_attribute("refusal", refusal.cause.value)
        await self._aggregator.emit_error(
            req.thread_id,
            refusal.cause.value,
            refusal.detail,
            recoverable=True,
        )
        await self._state_projector.emit_execution_state_projection(
            req.thread_id, run.graph, run.config
        )

    def _close_run_control(self, thread_id: str) -> None:
        self._run_controls.close(thread_id)
        self._receipts.forget(thread_id)

    @property
    def draining(self) -> bool:
        """Whether a drain has been requested of this executor."""
        return self._run_controls.draining

    async def drain(self, reason: str) -> None:
        """Stop every run executing here at its next superstep boundary.

        Returns once none is left running.

        The request sticks: it holds for runs opened after this call as well
        as the ones already executing, and refuses any further dispatch, so
        returning here means no run is executing *and* none can start.
        """
        await self._run_controls.drain(reason)

    async def shutdown(self) -> None:
        """Release held resources (aggregator debounce tasks, etc.)."""
        await self._aggregator.shutdown()
        self._pending_cancellations.clear()
        self._graph_lifecycle.clear()

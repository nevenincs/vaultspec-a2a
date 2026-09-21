"""Graph execution engine -- manages LangGraph run lifecycle.

Dispatch orchestration: routes ingest/resume/cancel requests, manages
concurrency gating.  Delegates graph compilation to ``GraphLifecycleManager``
and checkpoint/state projection to ``StateProjector``.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, cast

from langgraph.types import Command

from ..domain_config import domain_config
from ..graph.enums import AgentLifecycleState
from ..ipc.serializers import sequenced_to_dict
from ..providers.team_selection import model_assignment_digest
from ..streaming.node_metadata import node_metadata_from_graph
from ..telemetry import ws_span
from ..thread.cancellation_evidence import CancellationEvidence
from ..thread.constants import DEFAULT_SUPERVISOR_ID
from ..thread.enums import TERMINAL_STATUSES, ControlActionType, ThreadStatus
from ..thread.errors import describe_exception_chain
from ._authoring_close import close_authoring_session_best_effort
from ._dispatch_contract import (
    _CAPACITY_ACCEPTED,
    _CAPACITY_FULL,
    _CAPACITY_THREAD_ACTIVE,
    _EXECUTOR_CONDITION,
    _INGEST_GUARDS,
    _RESUME_GUARDS,
    _SLOT_OWNING_ACTIONS,
    DispatchCapacityReservation,
    _GuardWording,
    failure_evidence,
)
from ._dispatch_receipts import emit_dispatch_application_receipt
from ._executor_state import DispatchCapacityState, RunResources
from .graph_lifecycle import (
    GraphCacheKey,
    GraphCompilationError,
    GraphLifecycleManager,
    RegisteredCompiledGraph,
)
from .state_projection import StateProjector

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from contextvars import ContextVar

    from opentelemetry.trace import Span

    from ..database.checkpoints import Checkpointer
    from ..ipc.schemas import DispatchRequest
    from ..providers import ProviderCondition
    from ..streaming.aggregator import EventAggregator
    from ..streaming.types import SequencedEvent, StreamableGraph
    from .catalog_store import RunCatalogStore
    from .ipc import WorkerBridge
    from .token_store import RunTokenStore

# ``GraphCompilationError`` is imported to be CAUGHT here, not re-published:
# ``graph_lifecycle`` raises it and is where every handler imports it from.
__all__ = [
    "Executor",
]

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _TerminalArbitration:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    users: int = 0


class Executor:
    """Orchestrate graph runs, projections, events, and dispatch capacity."""

    def __init__(
        self,
        checkpointer: Checkpointer,
        bridge: WorkerBridge,
        *,
        checkpoint_read_timeout_seconds: float | None = None,
    ) -> None:
        self._checkpointer = checkpointer
        self._checkpoint_read_timeout_seconds = (
            checkpoint_read_timeout_seconds
            if checkpoint_read_timeout_seconds is not None
            else domain_config.aget_state_timeout_seconds
        )
        self._bridge = bridge
        self._resources = RunResources()

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
        self._terminal_arbitrations: dict[str, _TerminalArbitration] = {}

    @asynccontextmanager
    async def _terminal_arbitration(self, thread_id: str) -> AsyncIterator[None]:
        """Serialize receipt selection, terminal emission and active-slot cleanup."""
        arbitration = self._terminal_arbitrations.setdefault(
            thread_id, _TerminalArbitration()
        )
        arbitration.users += 1
        try:
            async with arbitration.lock:
                yield
        finally:
            arbitration.users -= 1
            if arbitration.users == 0:
                self._terminal_arbitrations.pop(thread_id)

    @property
    def _aggregator(self) -> EventAggregator:
        return self._resources.aggregator

    @property
    def _token_store(self) -> RunTokenStore:
        return self._resources.token_store

    @property
    def _catalog_store(self) -> RunCatalogStore:
        return self._resources.catalog_store

    @property
    def _active_ingests(self) -> dict[str, DispatchCapacityReservation]:
        return self._capacity.active_ingests

    @property
    def _pending_cancellations(self) -> dict[str, str]:
        return self._capacity.pending_cancellations

    @property
    def _ingest_lock(self) -> asyncio.Lock:
        return self._capacity.lock

    @property
    def _next_capacity_generation(self) -> int:
        return self._capacity.next_generation

    @property
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
        cache_key: GraphCacheKey,
        graph: RegisteredCompiledGraph,
    ) -> None:
        """Register a pre-compiled graph through the lifecycle's atomic seam."""
        self._graph_lifecycle.register_compiled_graph(thread_id, cache_key, graph)

    def _log_extra(self, **fields: Any) -> dict[str, Any]:
        """Build bounded structured log fields for executor-owned events."""
        extra = {
            "worker_id": getattr(self._bridge, "_worker_id", None),
            "active_thread_count": self.active_ingest_count,
        }
        extra.update(fields)
        return {key: value for key, value in extra.items() if value is not None}

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

    def _take_cancellation_evidence(
        self,
        thread_id: str,
        *,
        outcome: Literal["ceased", "no_active_work"],
    ) -> CancellationEvidence | None:
        """Consume the accepted cancel identity that produced one outcome."""
        dispatch_id = self._pending_cancellations.pop(thread_id, None)
        if dispatch_id is None:
            return None
        return CancellationEvidence(
            schema_version="cancellation-evidence-v1",
            dispatch_id=dispatch_id,
            outcome=outcome,
        )

    async def _emit_dispatch_application_receipt(self, req: DispatchRequest) -> None:
        await emit_dispatch_application_receipt(
            req,
            self._checkpointer,
            self._bridge,
            self._checkpoint_read_timeout_seconds,
            self._dispatch_log_extra,
        )

    async def reserve_dispatch_capacity(
        self, thread_id: str
    ) -> DispatchCapacityReservation | None:
        """Atomically reserve pre-compile capacity for one thread dispatch."""
        reservation, _reason = await self._reserve_dispatch_capacity(thread_id)
        return reservation

    async def _reserve_dispatch_capacity(
        self, thread_id: str
    ) -> tuple[DispatchCapacityReservation | None, str]:
        """Return the bounded reason for one atomic capacity decision."""
        async with self._terminal_arbitration(thread_id), self._ingest_lock:
            if thread_id in self._active_ingests:
                return None, _CAPACITY_THREAD_ACTIVE
            if len(self._active_ingests) >= domain_config.max_concurrent_threads:
                return None, _CAPACITY_FULL
            self._capacity.next_generation += 1
            reservation = DispatchCapacityReservation(
                thread_id=thread_id,
                generation=self._capacity.next_generation,
            )
            self._active_ingests[thread_id] = reservation
            return reservation, _CAPACITY_ACCEPTED

    async def release_dispatch_capacity(
        self, reservation: DispatchCapacityReservation
    ) -> bool:
        """Release only the exact dispatch reservation supplied by its owner."""
        async with self._ingest_lock:
            if self._active_ingests.get(reservation.thread_id) is not reservation:
                return False
            self._active_ingests.pop(reservation.thread_id)
            return True

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

    async def _close_authoring_session_best_effort(
        self, thread_id: str, graph: StreamableGraph, config: dict[str, Any]
    ) -> None:
        await close_authoring_session_best_effort(
            thread_id, graph, config, self._token_store
        )

    async def _reject_compile_failure(
        self,
        req: DispatchRequest,
        span: Span,
        exc: GraphCompilationError,
        guards: _GuardWording,
    ) -> None:
        """Journal an uncompilable graph and drive the run to FAILED.

        A compile refusal was the one pre-run rejection that spoke on a single
        channel: it carried the compiler's own message as the terminal's detail
        but emitted no error frame, so a consumer that branches on the frame's
        code could not see the failure at all while every sibling refusal gave it
        both. It now takes the same epilogue as the rest of them.
        """
        logger.warning(
            guards.compile_failure,
            req.thread_id,
            exc,
            extra=self._dispatch_log_extra(
                req,
                action="compile_graph_failed",
                runtime_mode=guards.runtime_mode,
                error_type=type(exc).__name__,
            ),
        )
        span.set_attribute("error", True)
        span.set_attribute("error.message", str(exc))
        await self._reject_with_condition(req, str(exc))

    async def _reject_with_condition(self, req: DispatchRequest, reason: str) -> None:
        async with self._terminal_arbitration(req.thread_id):
            await self._reject_with_condition_locked(req, reason)

    async def _reject_with_condition_locked(
        self, req: DispatchRequest, reason: str
    ) -> None:
        """Fail a run before it ran, on both the coded and the durable channel.

        Every pre-run refusal knows why it refused, and a client needs that on
        two channels for two different reasons: the error frame's code is the
        machine-readable one a consumer branches on, and the terminal's detail is
        what the gateway persists so a reload recovers it without the live
        stream. Emitting only one leaves a consumer that keys on the other unable
        to see the failure at all.

        The condition is the vocabulary's floor at every one of these sites, and
        that is a decision: the run was refused before any provider was engaged,
        so there is no provider condition to report and inventing one would send
        the reader after a remedy the failure never called for.
        """
        await self._aggregator.emit_error(
            req.thread_id,
            _EXECUTOR_CONDITION.value,
            reason,
            recoverable=False,
        )
        evidence = failure_evidence(req, detail=reason, condition=_EXECUTOR_CONDITION)
        if evidence is not None or req.thread_id in self._pending_cancellations:
            await self._emit_terminal_outcome(
                req, ThreadStatus.FAILED, reason, _EXECUTOR_CONDITION
            )
        else:
            logger.warning(
                "Refusing terminal settlement without accepted graph authority",
                extra=self._dispatch_log_extra(
                    req, action="dispatch_rejected_without_authority"
                ),
            )
        self._graph_lifecycle.release_thread(req.thread_id)
        self._aggregator.remove_node_metadata(req.thread_id)
        self._aggregator.clear_thread_state(req.thread_id)
        reservation = self._dispatch_reservation.get()
        if reservation is not None:
            await self.release_dispatch_capacity(reservation)

    async def _reject_missing_graph(
        self,
        req: DispatchRequest,
        span: Span,
        guards: _GuardWording,
    ) -> None:
        """Journal a dispatch with no graph to run and drive the run to FAILED.

        The cause is known here - the dispatch named no preset, or the run has no
        graph to resume - yet the terminal used to carry no detail and no code at
        all, so a client saw a bare ``failed`` for a refusal the worker could name
        precisely. Both channels now carry it: the condition floor as the error
        frame's code, and the mode's own wording as the terminal's detail.
        """
        logger.warning(
            guards.graph_missing,
            req.thread_id,
            extra=self._dispatch_log_extra(
                req,
                action="graph_missing",
                runtime_mode=guards.runtime_mode,
            ),
        )
        span.set_attribute("error", True)
        span.set_attribute("error.message", "No team preset")
        await self._reject_with_condition(req, guards.graph_missing_detail)

    def _reject_slot_held(
        self,
        req: DispatchRequest,
        span: Span,
        guards: _GuardWording,
    ) -> None:
        """Journal a dispatch dropped because the thread's ingest slot is held.

        Emits nothing beyond the trace and log record: the run that owns the slot
        settles on its own and would be corrupted by a terminal emitted here.
        """
        logger.warning(
            guards.slot_held,
            req.thread_id,
            extra=self._dispatch_log_extra(
                req,
                action=guards.slot_held_action,
                runtime_mode=guards.runtime_mode,
            ),
        )
        span.set_attribute("error", True)
        span.set_attribute("error.message", "Ingest already active")

    async def _settle_run(
        self,
        req: DispatchRequest,
        graph: StreamableGraph,
        config: dict[str, Any],
        outcome: str,
        fallback_reason: str | None = None,
    ) -> None:
        """Settle a finished graph run; the call order here is load-bearing.

        The execution-state projection and the run's terminal status land first.
        The benign engine session close runs on SUCCESS only, AFTER that terminal
        status has landed and BEFORE ``_mark_ingest_done`` drops the run's tokens,
        which the close needs to authenticate. Cancel and failure outcomes emit
        their own terminal above and never reach the close arm.

        Both the ingest and the resume settle route through here: a gated
        research_adr run completes on its FINAL gate resume, so the close must
        cover the resume path too.
        """
        await self._emit_dispatch_application_receipt(req)
        await self._state_projector.emit_execution_state_projection(
            req.thread_id, graph, config
        )
        # ingest() classifies and stashes a reason for every FAILED outcome
        # (recursion limit, LangGraph's own step_timeout, the ingest-stall
        # watchdog, or the catch-all summary); threading it through here is what
        # lets the gateway durably record it
        # (control/event_handlers.py._handle_terminal_event), composing with the
        # SAME error_detail channel _reject_compile_failure already uses for a
        # compile-time refusal.
        #
        # The read is a pop, but that alone does NOT make a stale entry
        # impossible: a settle that dies before reaching it would leave the entry
        # for the next run reusing this thread id. The guarantee therefore sits
        # outside this function, in the dispatch backstop that catches whatever
        # killed the settle - see ``_fail_unhandled_dispatch``.
        failure_reason = self._aggregator.take_failure_reason(req.thread_id)
        # The condition ingest resolved from the failing lane. Both stashes are
        # drained on every settle, not only on a failure, so a completed run
        # cannot inherit a condition stranded by an earlier one on this key.
        failure_condition = self._aggregator.take_failure_condition(req.thread_id)
        if failure_reason is None and fallback_reason is not None:
            # No stashed reason on a failure means ingest never classified it:
            # the exception escaped around its own reporting rather than through
            # it, so it emitted no error frame either. Without this arm the run
            # settles as a bare "failed" on both channels - the exact blank
            # terminal this campaign exists to remove. The condition is the
            # floor because nothing here observed a provider.
            failure_reason = fallback_reason
            failure_condition = failure_condition or _EXECUTOR_CONDITION
            await self._aggregator.emit_error(
                req.thread_id,
                failure_condition.value,
                fallback_reason,
                recoverable=False,
            )
        async with self._terminal_arbitration(req.thread_id):
            await self._settle_terminal(
                req, graph, config, outcome, failure_reason, failure_condition
            )

    async def _settle_terminal(
        self,
        req: DispatchRequest,
        graph: StreamableGraph,
        config: dict[str, Any],
        outcome: str,
        failure_reason: str | None,
        failure_condition: ProviderCondition | None,
    ) -> None:
        outcome = await self._emit_terminal_outcome(
            req, outcome, failure_reason, failure_condition
        )
        if outcome == ThreadStatus.COMPLETED:
            await self._close_authoring_session_best_effort(
                req.thread_id, graph, config
            )
        await self._mark_ingest_done(req.thread_id, outcome)

    async def _emit_terminal_outcome(
        self,
        req: DispatchRequest,
        outcome: str,
        failure_reason: str | None = None,
        failure_condition: ProviderCondition | None = None,
    ) -> str:
        """Choose one receipt-aware outcome under the terminal arbitration lock."""
        cancellation_evidence = self._take_cancellation_evidence(
            req.thread_id, outcome="ceased"
        )
        if cancellation_evidence is not None:
            if outcome != ThreadStatus.CANCELLED:
                await self._aggregator.emit_agent_status(
                    req.thread_id,
                    req.agent_id or DEFAULT_SUPERVISOR_ID,
                    "supervisor",
                    AgentLifecycleState.CANCELLED,
                    "Terminated by user",
                )
            outcome = ThreadStatus.CANCELLED
            failure_reason = None
            failure_condition = None
        await self._state_projector.emit_terminal_status(
            req.thread_id,
            outcome,
            error_detail=failure_reason,
            # Carrying the LANE's condition rather than the executor floor is the
            # whole point: a rate limit, a revoked credential and an unclassified
            # fault demand different actions, and the terminal is what the gateway
            # persists. Left as None when ingest resolved nothing, so a completed
            # or cancelled run is never stamped with a condition it never had.
            provider_condition=failure_condition,
            evidence=cancellation_evidence
            if cancellation_evidence is not None
            else (
                failure_evidence(
                    req,
                    detail=failure_reason,
                    condition=failure_condition or _EXECUTOR_CONDITION,
                )
                if outcome == ThreadStatus.FAILED
                else None
            ),
        )
        return outcome

    async def handle_dispatch(self, req: DispatchRequest) -> None:
        """Reserve capacity and route a direct ``DispatchRequest`` call."""
        owns_slot = req.action in _SLOT_OWNING_ACTIONS
        reservation, refusal_reason = (
            await self._reserve_dispatch_capacity(req.thread_id)
            if owns_slot
            else (None, _CAPACITY_ACCEPTED)
        )
        if refusal_reason != _CAPACITY_ACCEPTED:
            guards = (
                _INGEST_GUARDS
                if req.action == ControlActionType.INGEST
                else _RESUME_GUARDS
            )
            action = (
                guards.slot_held_action
                if refusal_reason == _CAPACITY_THREAD_ACTIVE
                else "dispatch_capacity_refused"
            )
            logger.warning(
                guards.slot_held
                if refusal_reason == _CAPACITY_THREAD_ACTIVE
                else "Worker capacity refused dispatch for thread %s",
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

    async def _fail_unhandled_dispatch(
        self,
        req: DispatchRequest,
        exc: BaseException,
        reservation: DispatchCapacityReservation | None = None,
    ) -> None:
        async with self._terminal_arbitration(req.thread_id):
            await self._fail_unhandled_dispatch_locked(req, exc, reservation)

    async def _fail_unhandled_dispatch_locked(
        self,
        req: DispatchRequest,
        exc: BaseException,
        reservation: DispatchCapacityReservation | None = None,
    ) -> None:
        """Terminate a run whose dispatch died outside every inner handler.

        The task group deliberately swallows this exception so one bad run cannot
        take the worker down with it. But the gateway acked the dispatch the
        moment it was scheduled, so with nothing emitted here it believes the
        dispatch succeeded while the run sits RUNNING forever - the failure with
        the least information of any in the system, and the one an operator is
        least able to diagnose. A terminal and a condition-coded error frame
        replace that silence.

        By the time this runs the exception has propagated out of the inner
        handler, so nothing is left executing for THIS dispatch. An ingest or a
        resume therefore still owns the thread's ingest slot and must give it
        back, or the thread can never be dispatched again. A cancel or an
        unrecognised action never owned that slot: when it is held, a concurrent
        ingest owns the run's terminal and will emit its own on settle, so this
        arm stays silent there rather than racing a legitimate outcome with a
        fabricated failure.

        This is also where the run's failure stash is guaranteed to be drained.
        The settle path pops it, and that pop is the only other drain, so a
        settle that died before reaching it would strand both entries under a key
        the NEXT run on this thread id reuses. A stranded condition is the worse
        half: a client BRANCHES on it, so the following run would be told to
        re-authenticate or wait out a rate limit because its predecessor hit one.
        The drain runs before anything here that can fail, and is unconditional
        past the guard above - the one arm that returns early leaves a live
        ingest owning both the run and the stash it will drain itself.
        """
        owns_slot = req.action in _SLOT_OWNING_ACTIONS
        if not owns_slot:
            async with self._ingest_lock:
                if req.thread_id in self._active_ingests:
                    return
        stranded_reason = self._aggregator.take_failure_reason(req.thread_id)
        stranded_condition = self._aggregator.take_failure_condition(req.thread_id)
        # A surviving entry is the run's OWN account of why it failed, and it is
        # preferred over this arm's wording: the exception handled here killed
        # the SETTLE, which is a fault in the machinery rather than the reason
        # the run failed. The operator loses nothing, since that exception is
        # logged above with its full traceback, while the client gets the answer
        # its lane actually resolved instead of the floor. Only a slot-owning
        # dispatch may adopt it, because only an ingest or a resume produced it;
        # any other action drains without speaking for a run that is not its own.
        adopted_reason = stranded_reason if owns_slot else None
        reason = adopted_reason or (
            f"Worker dispatch failed unexpectedly: {describe_exception_chain(exc)}"
        )
        condition = (
            stranded_condition
            if owns_slot and stranded_condition is not None
            else _EXECUTOR_CONDITION
        )
        try:
            await self._aggregator.emit_error(
                req.thread_id,
                condition.value,
                reason,
                recoverable=False,
            )
            evidence = failure_evidence(req, detail=reason, condition=condition)
            outcome = ThreadStatus.FAILED
            if evidence is not None or req.thread_id in self._pending_cancellations:
                outcome = await self._emit_terminal_outcome(
                    req, outcome, reason, condition
                )
            if owns_slot:
                await self._mark_ingest_done(req.thread_id, outcome, reservation)
        except Exception:
            # This runs from the handler that keeps one bad run from taking the
            # worker's task group down with it, so it may not raise in turn - a
            # backstop that can itself fail is not one. There is nowhere left to
            # report to at this point, so the log is the last word.
            logger.exception(
                "Could not settle a run whose dispatch failed unexpectedly",
                extra=self._dispatch_log_extra(
                    req,
                    action="dispatch_unhandled_settle_failed",
                ),
            )

    async def _settle_completed_preflight(
        self, req: DispatchRequest, span: Span
    ) -> None:
        async with self._terminal_arbitration(req.thread_id):
            await self._settle_completed_preflight_locked(req, span)

    async def _settle_completed_preflight_locked(
        self, req: DispatchRequest, span: Span
    ) -> None:
        logger.info(
            "Thread %s checkpoint shows completion before crash"
            " — emitting completed without re-running",
            req.thread_id,
            extra=self._dispatch_log_extra(
                req,
                action="checkpoint_preflight_terminal",
                outcome=ThreadStatus.COMPLETED,
            ),
        )
        span.set_attribute("pre_flight", "completed")
        await self._emit_terminal_outcome(req, ThreadStatus.COMPLETED)
        self._graph_lifecycle.release_thread(req.thread_id)
        self._aggregator.remove_node_metadata(req.thread_id)
        self._aggregator.clear_thread_state(req.thread_id)
        reservation = self._dispatch_reservation.get()
        if reservation is not None:
            await self.release_dispatch_capacity(reservation)

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
            # Pre-flight: detect threads that already reached a terminal or
            # interrupted state before a crash.  Also grounds is_first_ingest
            # in checkpoint truth rather than the stale in-memory cache.
            (
                pre_flight_outcome,
                is_first_ingest,
            ) = await self._state_projector.pre_flight_checkpoint(
                req.thread_id,
                thread_known=self._graph_lifecycle.has_thread(req.thread_id),
                timeout_seconds=max(
                    0.0,
                    checkpoint_deadline - asyncio.get_running_loop().time(),
                ),
            )
            if pre_flight_outcome == ThreadStatus.COMPLETED:
                await self._settle_completed_preflight(req, span)
                return
            if pre_flight_outcome == ThreadStatus.FAILED:
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
                return
            if pre_flight_outcome == "interrupted":
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
                return

            span.set_attribute("is_first_ingest", is_first_ingest)

            try:
                graph = await self._graph_lifecycle.get_or_compile_graph(
                    req, checkpoint_deadline=checkpoint_deadline
                )
            except GraphCompilationError as exc:
                await self._reject_compile_failure(req, span, exc, _INGEST_GUARDS)
                return

            if graph is None:
                await self._reject_missing_graph(req, span, _INGEST_GUARDS)
                return

            config = {
                "configurable": {"thread_id": req.thread_id},
                "recursion_limit": req.recursion_limit,
            }
            self._bridge.track_thread(req.thread_id)
            # Hold the run's per-role tokens for this active window only.
            self._token_store.register(req.thread_id, req.actor_tokens)

            graph_input = GraphLifecycleManager.build_graph_input(
                req, is_first_ingest=is_first_ingest
            )
            graph_input["agent_descriptors"] = node_metadata_from_graph(graph)
            graph_input["graph_action_receipts"] = {
                req.dispatch_id: receipt.model_dump(mode="json")
            }
            graph_input["active_graph_action_receipt"] = receipt.model_dump(mode="json")

            agent_id = req.agent_id or DEFAULT_SUPERVISOR_ID

            # Stays None unless the catch-all below fires, so a run that settles
            # normally offers no fallback and keeps whatever ingest classified.
            execution_failure_reason: str | None = None
            # Pre-bound so `finally` always has a value to settle with, including
            # for a BaseException that bypasses the `except Exception` clause
            # below (e.g. cancellation) before `ingest` assigns its own outcome.
            outcome: str = ThreadStatus.FAILED

            try:
                span.add_event("starting_graph_execution")
                outcome = await self._aggregator.ingest(
                    req.thread_id,
                    agent_id,
                    graph,
                    graph_input,
                    config,
                    on_graph_started=lambda: self._emit_dispatch_application_receipt(
                        req
                    ),
                )
                span.set_attribute("outcome", outcome)
            except Exception:
                outcome = ThreadStatus.FAILED
                execution_failure_reason = _INGEST_GUARDS.execution_failure_detail
                logger.exception(
                    _INGEST_GUARDS.execution_failure,
                    req.thread_id,
                    extra=self._dispatch_log_extra(
                        req,
                        action=_INGEST_GUARDS.execution_failure_action,
                        runtime_mode=_INGEST_GUARDS.runtime_mode,
                    ),
                )
                span.record_exception(Exception("Graph execution failed"))
            finally:
                await self._settle_run(
                    req, graph, config, outcome, execution_failure_reason
                )

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
            try:
                graph = await self._graph_lifecycle.get_or_compile_graph(
                    req, checkpoint_deadline=checkpoint_deadline
                )
            except GraphCompilationError as exc:
                await self._reject_compile_failure(req, span, exc, _RESUME_GUARDS)
                return

            if graph is None:
                await self._reject_missing_graph(req, span, _RESUME_GUARDS)
                return

            self._bridge.track_thread(req.thread_id)
            # A resumed turn re-provisions the run's tokens for its window.
            self._token_store.register(req.thread_id, req.actor_tokens)

            config = {
                "configurable": {"thread_id": req.thread_id},
                "recursion_limit": req.recursion_limit,
            }
            agent_id = req.agent_id or DEFAULT_SUPERVISOR_ID

            # Stays None unless the catch-all below fires, so a resume that
            # settles normally keeps whatever ingest classified.
            execution_failure_reason: str | None = None
            # Pre-bound so `finally` always has a value to settle with, including
            # for a BaseException that bypasses the `except Exception` clause
            # below (e.g. cancellation) before `ingest` assigns its own outcome.
            outcome: str = ThreadStatus.FAILED

            try:
                span.add_event("resuming_graph_execution")
                # Command(resume=...) is accepted by astream_events in place of
                # a dict graph_input -- LangGraph handles the type internally.
                outcome = await self._aggregator.ingest(
                    req.thread_id,
                    agent_id,
                    graph,
                    Command(
                        resume=req.option_id,
                        update={
                            "graph_action_receipts": {
                                req.dispatch_id: receipt.model_dump(mode="json")
                            },
                            "active_graph_action_receipt": receipt.model_dump(
                                mode="json"
                            ),
                            "agent_descriptors": node_metadata_from_graph(graph),
                            "graph_definition_digest": (
                                req.require_graph_definition().digest()
                            ),
                            "model_assignment_digest": model_assignment_digest(
                                req.model_assignment
                            ),
                        },
                    ),
                    config,
                    on_graph_started=lambda: self._emit_dispatch_application_receipt(
                        req
                    ),
                )
                span.set_attribute("outcome", outcome)
            except Exception:
                outcome = ThreadStatus.FAILED
                execution_failure_reason = _RESUME_GUARDS.execution_failure_detail
                logger.exception(
                    _RESUME_GUARDS.execution_failure,
                    req.thread_id,
                    extra=self._dispatch_log_extra(
                        req,
                        action=_RESUME_GUARDS.execution_failure_action,
                        runtime_mode=_RESUME_GUARDS.runtime_mode,
                    ),
                )
                span.record_exception(Exception("Graph resume failed"))
            finally:
                await self._settle_run(
                    req, graph, config, outcome, execution_failure_reason
                )

    async def shutdown(self) -> None:
        """Release held resources (aggregator debounce tasks, etc.)."""
        await self._aggregator.shutdown()
        self._pending_cancellations.clear()
        self._graph_lifecycle.clear()

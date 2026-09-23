"""Terminal arbitration, pre-run rejection, and run settlement.

Extracted from ``executor.py``: every path that resolves one run's terminal
outcome -- a pre-run refusal, a normal settle, or the backstop that catches
whatever escaped every inner handler -- shares the same per-thread terminal
arbitration lock and the same receipt-aware outcome choice, so it moves as
one cohesive unit.  ``SettlementMixin`` is mixed into ``Executor``, not used
standalone: its methods read the collaborators (aggregator, state projector,
graph lifecycle, dispatch capacity bookkeeping) that ``Executor.__init__``
assembles, declared below only so the type checker can see this file's
methods in isolation from the class they are mixed into.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Protocol

from ..graph.enums import AgentLifecycleState
from ..thread.cancellation_evidence import CancellationEvidence
from ..thread.constants import DEFAULT_SUPERVISOR_ID
from ..thread.enums import ThreadStatus
from ..thread.errors import describe_exception_chain
from ._dispatch_contract import (
    _EXECUTOR_CONDITION,
    _SLOT_OWNING_ACTIONS,
    DispatchCapacityReservation,
    _GuardWording,
    failure_evidence,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from contextvars import ContextVar

    from opentelemetry.trace import Span

    from ..ipc.schemas import DispatchRequest
    from ..providers import ProviderCondition
    from ..streaming.aggregator import EventAggregator
    from ..streaming.types import StreamableGraph
    from .graph_lifecycle import GraphCompilationError, GraphLifecycleManager
    from .state_projection import StateProjector

__all__ = [
    "FailureDisposition",
    "SettlementMixin",
    "TerminalArbitration",
]

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class TerminalArbitration:
    """One thread's arbitration lock and its live waiter count.

    Public: ``Executor.__init__`` holds the registry of these keyed by
    thread id, so the type crosses into ``executor.py``.
    """

    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    users: int = 0


@dataclass(slots=True, frozen=True)
class FailureDisposition:
    """A run's classified failure reason paired with its provider condition.

    Bundles the pair ``_settle_terminal`` and the unhandled-dispatch backstop
    both thread through, so a settle site that needs both takes one argument
    instead of two.
    """

    reason: str | None
    condition: ProviderCondition | None


def _resolve_unhandled_failure(
    *,
    owns_slot: bool,
    stranded_reason: str | None,
    stranded_condition: ProviderCondition | None,
    exc: BaseException,
) -> tuple[str, ProviderCondition]:
    """Prefer a run's own stranded account of its failure over this backstop's.

    Only a slot-owning dispatch may adopt a stranded reason or condition,
    because only an ingest or a resume produced one; any other action drains
    the stash without speaking for a run that is not its own. Both halves are
    always resolved to a concrete value here -- unlike ``FailureDisposition``,
    which also carries the "nothing to report" case a completed or cancelled
    settle needs -- so the pair is a plain tuple rather than that type.
    """
    adopted_reason = stranded_reason if owns_slot else None
    reason = adopted_reason or (
        f"Worker dispatch failed unexpectedly: {describe_exception_chain(exc)}"
    )
    condition = (
        stranded_condition
        if owns_slot and stranded_condition is not None
        else _EXECUTOR_CONDITION
    )
    return reason, condition


class _SettlementHost(Protocol):
    """Structural surface ``SettlementMixin``'s methods read through ``self``.

    Declares exactly the attributes ``Executor.__init__`` assigns and the
    methods ``Executor`` defines itself, so ``SettlementMixin`` -- which
    inherits this Protocol only for its declarations, not for structural
    typing -- type-checks in isolation from the class it is mixed into.
    """

    _state_projector: StateProjector
    _graph_lifecycle: GraphLifecycleManager
    _terminal_arbitrations: dict[str, TerminalArbitration]

    # Declared as properties, matching ``Executor``'s own declarations: a
    # plain-attribute stand-in here would make ``Executor``'s property an
    # incompatible override instead of the matching one it actually is.
    @property
    def _aggregator(self) -> EventAggregator: ...

    @property
    def _pending_cancellations(self) -> dict[str, str]: ...

    @property
    def _dispatch_reservation(
        self,
    ) -> ContextVar[DispatchCapacityReservation | None]: ...

    @property
    def _ingest_lock(self) -> asyncio.Lock: ...

    @property
    def _active_ingests(self) -> dict[str, DispatchCapacityReservation]: ...

    def _dispatch_log_extra(
        self, req: DispatchRequest, **fields: Any
    ) -> dict[str, Any]: ...

    async def _emit_dispatch_application_receipt(
        self, req: DispatchRequest
    ) -> None: ...

    async def _close_authoring_session_best_effort(
        self, thread_id: str, graph: StreamableGraph, config: dict[str, Any]
    ) -> None: ...

    async def release_dispatch_capacity(
        self, reservation: DispatchCapacityReservation
    ) -> bool: ...

    async def _mark_ingest_done(
        self,
        thread_id: str,
        outcome: str,
        reservation: DispatchCapacityReservation | None = None,
    ) -> None: ...


class SettlementMixin(_SettlementHost):
    """Terminal arbitration, pre-run rejection, and run settlement.

    Mixed into ``Executor``, not used standalone: inherits ``_SettlementHost``
    only to pick up its attribute and method declarations so this file
    type-checks; at runtime ``Executor`` supplies the real attributes.
    """

    @asynccontextmanager
    async def _terminal_arbitration(self, thread_id: str) -> AsyncGenerator[None]:
        """Serialize receipt selection, terminal emission and active-slot cleanup."""
        arbitration = self._terminal_arbitrations.setdefault(
            thread_id, TerminalArbitration()
        )
        arbitration.users += 1
        try:
            async with arbitration.lock:
                yield
        finally:
            arbitration.users -= 1
            if arbitration.users == 0:
                self._terminal_arbitrations.pop(thread_id)

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
                req,
                graph,
                config,
                outcome,
                FailureDisposition(reason=failure_reason, condition=failure_condition),
            )

    async def _settle_terminal(
        self,
        req: DispatchRequest,
        graph: StreamableGraph,
        config: dict[str, Any],
        outcome: str,
        failure: FailureDisposition,
    ) -> None:
        outcome = await self._emit_terminal_outcome(
            req, outcome, failure.reason, failure.condition
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
        # A surviving entry is the run's OWN account of why it failed, and it is
        # preferred over this arm's wording: the exception handled here killed
        # the SETTLE, which is a fault in the machinery rather than the reason
        # the run failed. The operator loses nothing, since that exception is
        # logged above with its full traceback, while the client gets the answer
        # its lane actually resolved instead of the floor.
        reason, condition = _resolve_unhandled_failure(
            owns_slot=owns_slot,
            stranded_reason=self._aggregator.take_failure_reason(req.thread_id),
            stranded_condition=self._aggregator.take_failure_condition(req.thread_id),
            exc=exc,
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

"""Graph execution engine -- manages LangGraph run lifecycle.

Dispatch orchestration: routes ingest/resume/cancel requests, manages
concurrency gating.  Delegates graph compilation to ``GraphLifecycleManager``
and checkpoint/state projection to ``StateProjector``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, cast, override

from langgraph.types import Command

from ..domain_config import domain_config
from ..ipc.serializers import sequenced_to_dict
from ..providers.team_selection import model_assignment_digest
from ..streaming.node_metadata import node_metadata_from_graph
from ..telemetry import ws_span
from ..thread.constants import DEFAULT_SUPERVISOR_ID
from ..thread.enums import TERMINAL_STATUSES, ControlActionType, ThreadStatus
from ._authoring_close import close_authoring_session_best_effort
from ._dispatch_contract import (
    _CAPACITY_ACCEPTED,
    _CAPACITY_FULL,
    _CAPACITY_THREAD_ACTIVE,
    _INGEST_GUARDS,
    _RESUME_GUARDS,
    _SLOT_OWNING_ACTIONS,
    DispatchCapacityReservation,
)
from ._dispatch_receipts import emit_dispatch_application_receipt
from ._dispatch_settlement import SettlementMixin, TerminalArbitration
from ._executor_state import CheckpointAccess, DispatchCapacityState, RunResources
from .graph_lifecycle import (
    GraphCacheKey,
    GraphCompilationError,
    GraphLifecycleManager,
    RegisteredCompiledGraph,
)
from .state_projection import StateProjector

if TYPE_CHECKING:
    from contextvars import ContextVar

    from ..database.checkpoints import Checkpointer
    from ..ipc.schemas import DispatchRequest
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
        self._terminal_arbitrations: dict[str, TerminalArbitration] = {}

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

"""Graph execution engine -- manages LangGraph run lifecycle.

Dispatch orchestration: routes ingest/resume/cancel requests, manages
concurrency gating.  Delegates graph compilation to ``GraphLifecycleManager``
and checkpoint/state projection to ``StateProjector``.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from langgraph.types import Command

from ..domain_config import domain_config
from ..ipc.schemas import DispatchApplicationReceiptPayload
from ..ipc.serializers import sequenced_to_dict
from ..providers import ProviderCondition
from ..streaming.aggregator import EventAggregator, SequencedEvent, StreamableGraph
from ..team.team_config import load_team_config
from ..telemetry import ws_span
from ..thread.constants import DEFAULT_SUPERVISOR_ID
from ..thread.enums import TERMINAL_STATUSES, ControlActionType, ThreadStatus
from ..thread.errors import describe_exception_chain
from .catalog_store import RunCatalogStore
from .graph_lifecycle import (
    GraphCacheKey,
    GraphCompilationError,
    GraphLifecycleManager,
    RegisteredCompiledGraph,
)
from .state_projection import StateProjector
from .token_store import RunTokenStore

if TYPE_CHECKING:
    from opentelemetry.trace import Span

    from ..database.checkpoints import Checkpointer
    from ..ipc.schemas import DispatchRequest
    from .ipc import WorkerBridge

__all__ = ["ConcurrentCapError", "Executor", "GraphCompilationError"]

# The document-authoring role whose actor token closes the run's engine session.
# It is the session's owner: the submitter's constant create_session key opens the
# session once, in the research phase, under this role. The benign close is
# dual-auth (ResolvedCommand principal), so the owner token is the right principal.
_CLOSE_SESSION_ROLE = "vaultspec-synthesist"


@dataclass(frozen=True, slots=True)
class _GuardWording:
    """Per-runtime-mode wording for the guard arms ingest and resume share.

    The pre-run guards (compile failure, missing graph, ingest slot already held)
    are one behaviour each, reached from two dispatch modes. Only the operator-
    facing wording and the slot-rejection log action differ between the modes, so
    they are data here and the guard itself has a single implementation.

    ``graph_missing`` is the operator's log line and carries the thread id;
    ``graph_missing_detail`` is the client's, and deliberately does not - the run
    it describes is the one the reader is already looking at, and repeating the
    identifier spends a capped reason on something the frame already carries.
    """

    runtime_mode: str
    compile_failure: str
    graph_missing: str
    graph_missing_detail: str
    slot_held: str
    slot_held_action: str


_INGEST_GUARDS = _GuardWording(
    runtime_mode="ingest",
    compile_failure="Graph compilation failed for thread %s: %s",
    graph_missing="No graph for thread %s -- no team preset provided",
    graph_missing_detail="No graph to run: the dispatch named no team preset",
    slot_held="Ingest already active for thread %s -- dropping",
    slot_held_action="ingest_rejected_active",
)

_RESUME_GUARDS = _GuardWording(
    runtime_mode="resume",
    compile_failure="Graph recompile failed for thread %s: %s",
    graph_missing="No graph for thread %s -- cannot resume",
    graph_missing_detail="No graph to resume: the run has no compiled graph",
    slot_held="Ingest already active for thread %s -- cannot resume",
    slot_held_action="resume_rejected_active",
)

# The provider condition every executor-side rejection resolves to, and it is a
# decision rather than an omission: a graph that refused to compile, a dispatch
# that named no preset, and a fault in the executor's own machinery all failed
# BEFORE any provider was engaged, so there is no provider condition to report
# and claiming one would send the reader after a remedy the run never needed.
# The floor is what keeps such a run from carrying no condition at all.
_EXECUTOR_CONDITION = ProviderCondition.UNKNOWN

# The two dispatch actions that take the thread's ingest slot. A failure in
# either is that dispatch's own to settle; a cancel or an unrecognised action
# never held the slot, so a held slot there belongs to a concurrent run.
_SLOT_OWNING_ACTIONS = frozenset({ControlActionType.INGEST, ControlActionType.RESUME})


class ConcurrentCapError(RuntimeError):
    """Raised when the worker concurrent thread cap is reached."""


logger = logging.getLogger(__name__)


class Executor:
    """Dispatch orchestrator for LangGraph graph runs.

    Delegates graph compilation/caching to ``GraphLifecycleManager`` and
    checkpoint inspection/terminal events to ``StateProjector``.  Owns
    the ``EventAggregator`` and concurrency gating (``_active_ingests``).
    """

    def __init__(
        self,
        checkpointer: Checkpointer,
        bridge: WorkerBridge,
    ) -> None:
        self._checkpointer = checkpointer
        self._bridge = bridge
        self._aggregator = EventAggregator()

        # Worker-scoped holder of per-run actor tokens. Registered when a
        # run's active window opens and dropped when it closes, so tokens live
        # only inside the owning worker for the run and never touch a checkpoint.
        self._token_store = RunTokenStore()

        # Worker-scoped cache of per-run engine catalog snapshots, dropped on the
        # same terminal boundary as the token store so a snapshot never outlives a
        # run. Shared with the graph lifecycle's authoring-bridge provider.
        self._catalog_store = RunCatalogStore()

        # Delegates
        self._graph_lifecycle = GraphLifecycleManager(
            checkpointer=checkpointer,
            bridge=bridge,
            aggregator=self._aggregator,
            token_store=self._token_store,
            catalog_store=self._catalog_store,
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

        self._active_ingests: set[str] = set()
        self._ingest_lock = asyncio.Lock()

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

    def at_capacity(self) -> bool:
        """Return True if the concurrent thread cap has been reached."""
        cap = domain_config.max_concurrent_threads
        return len(self._active_ingests) >= cap

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

    async def _emit_dispatch_application_receipt(self, req: DispatchRequest) -> None:
        """Queue private proof that an ingest or resume entered graph execution."""
        if req.action not in {"ingest", "resume"}:
            return
        try:
            await self._bridge.send_event(
                req.thread_id,
                DispatchApplicationReceiptPayload(
                    dispatch_id=req.dispatch_id,
                    action=req.action,
                ).model_dump(mode="json"),
            )
        except Exception:
            # The journal lease and worker dispatch-ID admission retain recovery
            # authority. Receipt transport must never abort graph execution after
            # the graph already began.
            logger.warning(
                "Could not queue dispatch application receipt",
                exc_info=True,
                extra=self._dispatch_log_extra(
                    req,
                    action="dispatch_application_receipt_failed",
                ),
            )

    async def _mark_ingest_active(self, thread_id: str) -> bool:
        """Acquire the ingest slot for *thread_id*; ``False`` if already held."""
        async with self._ingest_lock:
            if thread_id in self._active_ingests:
                return False
            self._active_ingests.add(thread_id)
            return True

    async def _mark_ingest_done(self, thread_id: str, outcome: str) -> None:
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
            self._active_ingests.discard(thread_id)
            active_snapshot = set(self._active_ingests)
        # Drop the run's actor tokens when its active window truly closes,
        # i.e. a terminal outcome - never on an interrupt-park that will resume.
        if outcome in TERMINAL_STATUSES:
            self._token_store.drop(thread_id)
            self._catalog_store.drop(thread_id)
        self._bridge.untrack_thread(thread_id)
        # Prune sequences for threads that are no longer actively executing.
        self._aggregator.prune_sequences(active_snapshot)
        # Prune permissions older than 5 minutes regardless of thread state.
        self._aggregator.prune_stale_permissions()

    async def _close_authoring_session_best_effort(
        self, thread_id: str, graph: StreamableGraph, config: dict[str, Any]
    ) -> None:
        """Close the run's engine authoring session on a SUCCESSFUL settle.

        An a2a document-authoring run opens an engine session (``create_session``
        -> Active) and never closes it: it proposes directly and never starts a
        run, so the engine's run lifecycle never reaps the session. On the run's
        terminal SUCCESS this closes it benignly (``session.closed``). Called AFTER
        the run's own terminal status has landed, so a slow or failing close can
        neither delay nor contaminate the run's settle.

        Best-effort by contract: a missing session id (non-authoring run), missing
        credentials, an unreachable engine, or a close fault all degrade to a
        logged no-op - a completion-time housekeeping call must NEVER fail an
        already-succeeded run. Idempotent per the route; the route's active-run
        guard never fires because a2a-driven work creates no engine run. Runs the
        state read before the token store is dropped (this is invoked ahead of
        ``_mark_ingest_done``), so the session owner's actor token is still held.
        """
        from ..authoring import (
            AuthoringClient,
            close_authoring_session,
            resolve_engine,
        )
        from ..authoring._ids import derive_idempotency_key

        try:
            snapshot = await asyncio.wait_for(
                graph.aget_state(config),
                timeout=domain_config.aget_state_timeout_seconds,
            )
            values = getattr(snapshot, "values", None)
            session_id = (
                values.get("authoring_session_id") if isinstance(values, dict) else None
            )
            if not isinstance(session_id, str) or not session_id:
                return  # non-authoring run — no engine session to close
            actor_token = self._token_store.actor_token(thread_id, _CLOSE_SESSION_ROLE)
            engine = resolve_engine()
            if not actor_token or engine is None:
                return  # no credentials or no reachable engine — degrade silently
            # The run's own bearer when the dispatch carried one, else the bearer
            # the SAME resolution paired with ``engine.base_url`` below. Falling
            # back is sound only here: origin and bearer arrive from one
            # ``resolve_engine()`` call, so the credential can never be aimed at
            # an origin it was not minted for.
            bearer = self._token_store.engine_bearer(thread_id) or engine.bearer_token
            async with AuthoringClient(
                engine.base_url,
                bearer,
                actor_token=actor_token,
                bearer_resolver=resolve_engine,
            ) as client:
                await close_authoring_session(
                    client,
                    session_id,
                    idempotency_key=derive_idempotency_key(thread_id, "close_session"),
                )
        except Exception:
            # Best-effort housekeeping AFTER a successful settle: never propagate.
            # A benign session close is not run-lifecycle-critical (the engine's
            # session retention is the backstop), so any fault degrades to a log.
            logger.warning(
                "best-effort close of the authoring session for run %s failed",
                thread_id,
                exc_info=True,
            )

    async def _reject_compile_failure(
        self,
        req: DispatchRequest,
        span: Span,
        exc: GraphCompilationError,
        guards: _GuardWording,
    ) -> None:
        """Journal an uncompilable graph and drive the run to FAILED."""
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
        await self._state_projector.emit_terminal_status(
            req.thread_id, ThreadStatus.FAILED, error_detail=str(exc)
        )

    async def _reject_with_condition(self, req: DispatchRequest, reason: str) -> None:
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
        await self._state_projector.emit_terminal_status(
            req.thread_id, ThreadStatus.FAILED, error_detail=reason
        )

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
        await self._state_projector.emit_execution_state_projection(
            req.thread_id, graph, config
        )
        # S37/failure-reason persistence: ingest() classifies and stashes a
        # reason for every FAILED outcome (recursion limit, LangGraph's own
        # step_timeout, the ingest-stall watchdog, or the catch-all summary);
        # threading it through here is what lets the gateway durably record it
        # (control/event_handlers.py._handle_terminal_event), composing with
        # the SAME error_detail channel _reject_compile_failure already uses
        # for a compile-time refusal. take_failure_reason is a pop — a stale
        # reason from an earlier run can never leak onto a later one reusing
        # this dict's key.
        failure_reason = self._aggregator.take_failure_reason(req.thread_id)
        await self._state_projector.emit_terminal_status(
            req.thread_id, outcome, error_detail=failure_reason
        )
        if outcome == ThreadStatus.COMPLETED:
            await self._close_authoring_session_best_effort(
                req.thread_id, graph, config
            )
        await self._mark_ingest_done(req.thread_id, outcome)

    async def handle_dispatch(self, req: DispatchRequest) -> None:
        """Route a ``DispatchRequest``; top-level guard protects the task group."""
        try:
            async with ws_span(
                f"executor.{req.action}",
                thread_id=req.thread_id,
                agent_id=req.agent_id or "supervisor",
            ) as span:
                match req.action:
                    case ControlActionType.INGEST:
                        await self._handle_ingest(req)
                    case ControlActionType.RESUME:
                        await self._handle_resume(req)
                    case ControlActionType.CANCEL:
                        span.add_event("thread_cancelled")
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
                                req.thread_id, ThreadStatus.CANCELLED
                            )
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
            await self._fail_unhandled_dispatch(req, exc)

    async def _fail_unhandled_dispatch(
        self, req: DispatchRequest, exc: BaseException
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
        """
        owns_slot = req.action in _SLOT_OWNING_ACTIONS
        if not owns_slot:
            async with self._ingest_lock:
                if req.thread_id in self._active_ingests:
                    return
        reason = f"Worker dispatch failed unexpectedly: {describe_exception_chain(exc)}"
        try:
            await self._aggregator.emit_error(
                req.thread_id,
                _EXECUTOR_CONDITION.value,
                reason,
                recoverable=False,
            )
            await self._state_projector.emit_terminal_status(
                req.thread_id, ThreadStatus.FAILED, error_detail=reason
            )
            if owns_slot:
                await self._mark_ingest_done(req.thread_id, ThreadStatus.FAILED)
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

    async def _handle_ingest(self, req: DispatchRequest) -> None:
        """Compile graph on first use and execute a new user turn."""
        async with ws_span("executor.ingest", thread_id=req.thread_id) as span:
            # Pre-flight: detect threads that already reached a terminal or
            # interrupted state before a crash.  Also grounds is_first_ingest
            # in checkpoint truth rather than the stale in-memory cache.
            (
                pre_flight_outcome,
                is_first_ingest,
            ) = await self._state_projector.pre_flight_checkpoint(
                req.thread_id,
                thread_known=self._graph_lifecycle.has_thread(req.thread_id),
            )
            if pre_flight_outcome == ThreadStatus.COMPLETED:
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
                await self._state_projector.emit_terminal_status(
                    req.thread_id, ThreadStatus.COMPLETED
                )
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
                graph = await self._graph_lifecycle.get_or_compile_graph(req)
            except GraphCompilationError as exc:
                await self._reject_compile_failure(req, span, exc, _INGEST_GUARDS)
                return

            if graph is None:
                await self._reject_missing_graph(req, span, _INGEST_GUARDS)
                return

            if not await self._mark_ingest_active(req.thread_id):
                self._reject_slot_held(req, span, _INGEST_GUARDS)
                return

            self._bridge.track_thread(req.thread_id)
            # Hold the run's per-role tokens for this active window only.
            self._token_store.register(req.thread_id, req.actor_tokens)

            graph_input = GraphLifecycleManager.build_graph_input(
                req, is_first_ingest=is_first_ingest
            )
            config = {
                "configurable": {"thread_id": req.thread_id},
                "recursion_limit": (
                    req.recursion_limit or domain_config.graph_recursion_limit
                ),
            }

            agent_id = req.agent_id or DEFAULT_SUPERVISOR_ID

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
                logger.exception(
                    "Ingest failed for thread %s",
                    req.thread_id,
                    extra=self._dispatch_log_extra(
                        req,
                        action="ingest_failed",
                        runtime_mode="ingest",
                    ),
                )
                span.record_exception(Exception("Graph execution failed"))
            finally:
                await self._settle_run(req, graph, config, outcome)

    async def _handle_resume(self, req: DispatchRequest) -> None:
        """Resume a graph from a LangGraph interrupt via ``Command(resume=...)``."""
        async with ws_span("executor.resume", thread_id=req.thread_id) as span:
            # Record resume option (cast to str for span attribute)
            val = str(req.option_id) if req.option_id else "none"
            span.set_attribute("option_id", val)
            try:
                graph = await self._graph_lifecycle.get_or_compile_graph(req)
            except GraphCompilationError as exc:
                await self._reject_compile_failure(req, span, exc, _RESUME_GUARDS)
                return

            if graph is None:
                await self._reject_missing_graph(req, span, _RESUME_GUARDS)
                return

            if not await self._mark_ingest_active(req.thread_id):
                self._reject_slot_held(req, span, _RESUME_GUARDS)
                return

            self._bridge.track_thread(req.thread_id)
            # A resumed turn re-provisions the run's tokens for its window.
            self._token_store.register(req.thread_id, req.actor_tokens)

            # Resolve recursion_limit: explicit request > team TOML > global default.
            cache_key = self._graph_lifecycle.cache_key_for_thread(req.thread_id)
            team_preset = cache_key[0] if cache_key else req.team_preset

            # Resolve workspace_root from cache or request.
            ws_root_path = cache_key[1] if cache_key else req.workspace_root
            ws_root = Path(ws_root_path).resolve() if ws_root_path else None

            team_recursion_limit: int | None = None
            if team_preset:
                try:
                    team_cfg = load_team_config(team_preset, workspace_root=ws_root)
                    team_recursion_limit = team_cfg.graph.recursion_limit
                except Exception:
                    logger.debug(
                        "Could not load team config for recursion_limit fallback",
                        exc_info=True,
                        extra=self._dispatch_log_extra(
                            req,
                            action="team_config_fallback",
                            runtime_mode="resume",
                        ),
                    )
            effective_recursion_limit = (
                req.recursion_limit
                or team_recursion_limit
                or domain_config.graph_recursion_limit
            )
            config = {
                "configurable": {"thread_id": req.thread_id},
                "recursion_limit": effective_recursion_limit,
            }
            agent_id = req.agent_id or DEFAULT_SUPERVISOR_ID

            try:
                span.add_event("resuming_graph_execution")
                # Command(resume=...) is accepted by astream_events in place of
                # a dict graph_input -- LangGraph handles the type internally.
                outcome = await self._aggregator.ingest(
                    req.thread_id,
                    agent_id,
                    graph,
                    Command(resume=req.option_id),
                    config,
                    on_graph_started=lambda: self._emit_dispatch_application_receipt(
                        req
                    ),
                )
                span.set_attribute("outcome", outcome)
            except Exception:
                outcome = ThreadStatus.FAILED
                logger.exception(
                    "Resume failed for thread %s",
                    req.thread_id,
                    extra=self._dispatch_log_extra(
                        req,
                        action="resume_failed",
                        runtime_mode="resume",
                    ),
                )
                span.record_exception(Exception("Graph resume failed"))
            finally:
                await self._settle_run(req, graph, config, outcome)

    async def shutdown(self) -> None:
        """Release held resources (aggregator debounce tasks, etc.)."""
        await self._aggregator.shutdown()
        self._graph_lifecycle.clear()

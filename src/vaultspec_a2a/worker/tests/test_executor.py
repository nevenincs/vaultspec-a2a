"""Tests for Executor, GraphLifecycleManager, and StateProjector.

Validates the Executor's ingest gating logic, dispatch routing, and
shutdown behaviour; GraphLifecycleManager's input construction; using a real
``AsyncSqliteSaver`` and a real ``WorkerBridge`` backed by a real FastAPI
ASGI app via ASGITransport.

No mock libraries.  No tautological tests.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any, cast

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import Response
from httpx import ASGITransport
from langchain_core.messages import AIMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import interrupt
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, Span, TracerProvider
from pydantic import ValidationError

from ...api.tests.clarification_harness import new_state_graph
from ...ipc.schemas import DispatchRequest
from ...providers import ProviderCondition
from ...thread.actor_tokens import ActorTokenBundle
from ...thread.enums import ThreadStatus
from ..executor import _INGEST_GUARDS, _RESUME_GUARDS, Executor
from ..graph_lifecycle import (
    GraphCompilationError,
    GraphLifecycleManager,
    RegisteredCompiledGraph,
)
from ..ipc import WorkerBridge

if TYPE_CHECKING:
    from ...thread.state import TeamState

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_bridge(
    *,
    api_url: str = "http://control:8000",
    worker_id: str = "test-worker",
) -> WorkerBridge:
    """Create a WorkerBridge backed by a real in-process FastAPI ASGI gateway.

    Real HTTP serialisation is exercised on every request — no MockTransport.
    """
    _app = FastAPI()

    @_app.post("/internal/events/batch")
    async def _batch(request: Request) -> Response:
        return Response(content='{"status":"ok"}', media_type="application/json")

    @_app.post("/internal/heartbeat")
    async def _heartbeat(request: Request) -> Response:
        return Response(content='{"status":"ok"}', media_type="application/json")

    bridge = WorkerBridge(api_url=api_url, worker_id=worker_id)
    bridge._client = httpx.AsyncClient(
        transport=ASGITransport(app=_app),
        base_url=api_url,
    )
    return bridge


# Default cache key for test graphs.
_TEST_CACHE_KEY = ("test-preset", None, False)


def _inject_graph(
    executor: Executor, thread_id: str, *, cache_key=_TEST_CACHE_KEY
) -> None:
    """Register a real terminal graph through the public executor seam."""

    def finish_node(state: TeamState) -> dict[str, object]:
        del state
        return {}

    builder = new_state_graph()
    builder.add_node("finish", finish_node)
    builder.add_edge("__start__", "finish")
    builder.add_edge("finish", "__end__")
    graph: RegisteredCompiledGraph = builder.compile(
        checkpointer=executor._checkpointer
    )
    executor.register_compiled_graph(thread_id, cache_key, graph)


def _terminal_graph(executor: Executor) -> RegisteredCompiledGraph:
    """A real compiled graph, returned rather than registered.

    The settle path takes the graph as an argument, so a test driving it needs
    the object itself; :func:`_inject_graph` registers one but hands back
    nothing.
    """

    def finish_node(state: TeamState) -> dict[str, object]:
        del state
        return {}

    builder = new_state_graph()
    builder.add_node("finish", finish_node)
    builder.add_edge("__start__", "finish")
    builder.add_edge("finish", "__end__")
    return builder.compile(checkpointer=executor._checkpointer)


# ---------------------------------------------------------------------------
# Ingest gating (_mark_ingest_active / _mark_ingest_done)
# ---------------------------------------------------------------------------


class TestIngestGating:
    """Verify the concurrent-ingest protection mechanism.

    These tests exercise real asyncio.Lock-guarded gating logic and verify
    that the executor properly prevents concurrent graph execution on the
    same thread while allowing parallel execution on different threads.
    """

    @pytest.mark.asyncio(loop_scope="function")
    async def test_first_mark_returns_true(self) -> None:
        async with AsyncSqliteSaver.from_conn_string(":memory:") as cp:
            await cp.setup()
            bridge = _make_bridge()
            try:
                executor = Executor(checkpointer=cp, bridge=bridge)
                result = await executor._mark_ingest_active("t-1")
                assert result is True
            finally:
                await bridge.close()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_second_mark_same_thread_returns_false(self) -> None:
        async with AsyncSqliteSaver.from_conn_string(":memory:") as cp:
            await cp.setup()
            bridge = _make_bridge()
            try:
                executor = Executor(checkpointer=cp, bridge=bridge)
                await executor._mark_ingest_active("t-1")
                result = await executor._mark_ingest_active("t-1")
                assert result is False
            finally:
                await bridge.close()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_different_threads_both_succeed(self) -> None:
        async with AsyncSqliteSaver.from_conn_string(":memory:") as cp:
            await cp.setup()
            bridge = _make_bridge()
            try:
                executor = Executor(checkpointer=cp, bridge=bridge)
                assert await executor._mark_ingest_active("t-1") is True
                assert await executor._mark_ingest_active("t-2") is True
            finally:
                await bridge.close()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_mark_done_releases_slot(self) -> None:
        async with AsyncSqliteSaver.from_conn_string(":memory:") as cp:
            await cp.setup()
            bridge = _make_bridge()
            try:
                executor = Executor(checkpointer=cp, bridge=bridge)
                await executor._mark_ingest_active("t-1")
                await executor._mark_ingest_done("t-1", ThreadStatus.COMPLETED)
                # Slot is now free -- can re-acquire
                result = await executor._mark_ingest_active("t-1")
                assert result is True
            finally:
                await bridge.close()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_mark_done_untracks_thread_in_bridge(self) -> None:
        """mark_done must call bridge.untrack_thread -- verify via bridge state."""
        async with AsyncSqliteSaver.from_conn_string(":memory:") as cp:
            await cp.setup()
            bridge = _make_bridge()
            try:
                executor = Executor(checkpointer=cp, bridge=bridge)
                # Simulate what _handle_ingest does: track before ingest
                bridge.track_thread("t-1")
                assert "t-1" in bridge.active_threads

                await executor._mark_ingest_done("t-1", ThreadStatus.COMPLETED)
                assert "t-1" not in bridge.active_threads
            finally:
                await bridge.close()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_mark_done_for_nonexistent_slot_is_safe(self) -> None:
        async with AsyncSqliteSaver.from_conn_string(":memory:") as cp:
            await cp.setup()
            bridge = _make_bridge()
            try:
                executor = Executor(checkpointer=cp, bridge=bridge)
                # Should not raise -- discard on empty set
                await executor._mark_ingest_done("nonexistent", ThreadStatus.COMPLETED)
            finally:
                await bridge.close()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_mark_done_keeps_tokens_on_interrupt_drops_on_terminal(self) -> None:
        """Actor tokens survive an interrupt-park and drop only on termination.

        A document run parks at its first gate (``"interrupted"``) and later
        resumes to author the ADR document, which needs the run's tokens; the
        active-window close that drops them is the run's TERMINAL outcome, not the
        interrupt-park.
        """
        async with AsyncSqliteSaver.from_conn_string(":memory:") as cp:
            await cp.setup()
            bridge = _make_bridge()
            try:
                executor = Executor(checkpointer=cp, bridge=bridge)
                executor.token_store.register(
                    "t-doc",
                    ActorTokenBundle(
                        tokens={"vaultspec-synthesist": "tok-s"},
                        engine_bearer="bearer-x",
                    ),
                )
                # Parked at a gate: tokens must persist for the resume.
                await executor._mark_ingest_done("t-doc", "interrupted")
                assert executor.token_store.engine_bearer("t-doc") == "bearer-x"
                assert (
                    executor.token_store.actor_token("t-doc", "vaultspec-synthesist")
                    == "tok-s"
                )
                # Terminal: the active window closes and tokens are dropped.
                await executor._mark_ingest_done("t-doc", ThreadStatus.COMPLETED)
                assert executor.token_store.engine_bearer("t-doc") is None
            finally:
                await bridge.close()


# ---------------------------------------------------------------------------
# handle_dispatch -- action routing
# ---------------------------------------------------------------------------


class TestHandleDispatch:
    """Verify dispatch routing exercises real code paths."""

    def test_unknown_action_is_rejected_by_schema(self) -> None:
        """Invalid dispatch actions are rejected before they reach the worker."""
        with pytest.raises(ValidationError):
            DispatchRequest(
                action=cast("Any", "delete_everything"),
                thread_id="t-1",
                recursion_limit=25,
            )

    @pytest.mark.asyncio(loop_scope="function")
    async def test_cancel_sets_event_on_aggregator(self) -> None:
        """Verify cancel action sets the cancellation event in the aggregator.

        EventAggregator.cancel_thread() calls ``.set()`` on the thread's
        ``asyncio.Event``.  We pre-register a cancel event via the
        aggregator's internal API and verify it transitions from
        unset → set after dispatch.
        """
        import asyncio as _asyncio

        async with AsyncSqliteSaver.from_conn_string(":memory:") as cp:
            await cp.setup()
            bridge = _make_bridge()
            try:
                executor = Executor(checkpointer=cp, bridge=bridge)

                # Pre-register a cancel event (as ingest would create one)
                cancel_event = _asyncio.Event()
                executor.aggregator._ingest._cancel_events["t-cancel-me"] = cancel_event
                assert not cancel_event.is_set()

                req = DispatchRequest(
                    action="cancel",
                    thread_id="t-cancel-me",
                    recursion_limit=25,
                )
                await executor.handle_dispatch(req)

                # The event should now be set
                assert cancel_event.is_set()
            finally:
                await bridge.close()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_ingest_without_graph_or_preset_logs_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Ingest on a thread with no compiled graph and no preset logs a warning."""
        async with AsyncSqliteSaver.from_conn_string(":memory:") as cp:
            await cp.setup()
            bridge = _make_bridge()
            try:
                executor = Executor(checkpointer=cp, bridge=bridge)
                req = DispatchRequest(
                    action="ingest",
                    thread_id="t-no-graph",
                    content="Hello",
                    recursion_limit=25,
                )
                with caplog.at_level(
                    logging.WARNING, logger="vaultspec_a2a.worker.executor"
                ):
                    await executor.handle_dispatch(req)

                record = next(
                    rec
                    for rec in caplog.records
                    if "No graph for thread" in rec.message
                )
                assert record.__dict__["thread_id"] == "t-no-graph"
                assert record.__dict__["dispatch_id"] == req.dispatch_id
                assert record.__dict__["dispatch_action"] == "ingest"
                assert record.__dict__["runtime_mode"] == "ingest"
                assert record.__dict__["worker_id"] == "test-worker"
                assert record.__dict__["action"] == "graph_missing"
            finally:
                await bridge.close()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_resume_without_graph_logs_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Resume on a thread with no compiled graph logs a warning."""
        async with AsyncSqliteSaver.from_conn_string(":memory:") as cp:
            await cp.setup()
            bridge = _make_bridge()
            try:
                executor = Executor(checkpointer=cp, bridge=bridge)
                req = DispatchRequest(
                    action="resume",
                    thread_id="t-no-graph",
                    option_id="opt-1",
                    recursion_limit=25,
                )
                with caplog.at_level(
                    logging.WARNING, logger="vaultspec_a2a.worker.executor"
                ):
                    await executor.handle_dispatch(req)

                record = next(
                    rec
                    for rec in caplog.records
                    if "No graph for thread" in rec.message
                )
                assert record.__dict__["thread_id"] == "t-no-graph"
                assert record.__dict__["dispatch_id"] == req.dispatch_id
                assert record.__dict__["dispatch_action"] == "resume"
                assert record.__dict__["runtime_mode"] == "resume"
                assert record.__dict__["worker_id"] == "test-worker"
                assert record.__dict__["action"] == "graph_missing"
            finally:
                await bridge.close()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_ingest_prevents_concurrent_same_thread(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A second ingest for the same thread is dropped while first is active.

        The ingest gating check happens AFTER the graph lookup, so we must
        pre-populate a graph entry for the thread before testing concurrency
        rejection.
        """
        async with AsyncSqliteSaver.from_conn_string(":memory:") as cp:
            await cp.setup()
            bridge = _make_bridge()
            try:
                executor = Executor(checkpointer=cp, bridge=bridge)
                # Inject a placeholder graph so the code reaches the gating check
                _inject_graph(executor, "t-1")
                # Pre-occupy the slot (simulates a running ingest)
                await executor._mark_ingest_active("t-1")

                req = DispatchRequest(
                    action="ingest",
                    thread_id="t-1",
                    content="Hello",
                    recursion_limit=25,
                )
                with caplog.at_level(
                    logging.WARNING, logger="vaultspec_a2a.worker.executor"
                ):
                    await executor.handle_dispatch(req)

                record = next(
                    rec
                    for rec in caplog.records
                    if "Ingest already active" in rec.message
                )
                assert record.__dict__["thread_id"] == "t-1"
                assert record.__dict__["dispatch_id"] == req.dispatch_id
                assert record.__dict__["dispatch_action"] == "ingest"
                assert record.__dict__["runtime_mode"] == "ingest"
                assert record.__dict__["worker_id"] == "test-worker"
                assert record.__dict__["active_thread_count"] == 1
                assert record.__dict__["action"] == "ingest_rejected_active"
            finally:
                await bridge.close()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_resume_hard_rejects_when_ingest_active(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A resume for a thread with an active ingest is hard-rejected, not queued.

        The load-bearing guard for the live-lane composition: the resume
        claim TTL deliberately does not cover a live authoring turn, so when the
        parked-run reconcile re-drives a run whose claim expired mid-authoring, the
        worker's ingest-active lock is what stops a second ``Command(resume=...)``
        from being injected into the active step. This pins that the reject returns
        BEFORE any ingest and emits nothing: the pre-held slot stays held (no
        ``_mark_ingest_done`` ran) and the bridge never tracked the thread
        (``track_thread`` is past the reject), so the resume is dropped, never
        queued or injected.
        """
        async with AsyncSqliteSaver.from_conn_string(":memory:") as cp:
            await cp.setup()
            bridge = _make_bridge()
            try:
                executor = Executor(checkpointer=cp, bridge=bridge)
                # Inject a placeholder graph so the code reaches the gating check.
                _inject_graph(executor, "t-resume")
                # Pre-occupy the slot (simulates the active authoring ingest).
                await executor._mark_ingest_active("t-resume")

                req = DispatchRequest(
                    action="resume",
                    thread_id="t-resume",
                    option_id={"verdict": "rejected", "notes": None},
                    recursion_limit=25,
                )
                with caplog.at_level(
                    logging.WARNING, logger="vaultspec_a2a.worker.executor"
                ):
                    await executor.handle_dispatch(req)

                record = next(
                    rec for rec in caplog.records if "cannot resume" in rec.message
                )
                assert record.__dict__["action"] == "resume_rejected_active"
                assert record.__dict__["runtime_mode"] == "resume"
                assert record.__dict__["dispatch_action"] == "resume"
                # Returned before ingest, emitted nothing: the pre-held slot is
                # intact (no finally / _mark_ingest_done ran) and the resume never
                # reached bridge.track_thread.
                assert "t-resume" in executor._active_ingests
                assert "t-resume" not in bridge.active_threads
            finally:
                await bridge.close()


# ---------------------------------------------------------------------------
# graph_input construction -- tested via _build_graph_input (T13)
# ---------------------------------------------------------------------------


class TestGraphInputBuilding:
    """Verify _build_graph_input produces the correct dict for all scenarios.

    Calls the pure helper method directly -- no aggregator, no graph
    compilation, no async I/O.  Tests the dict-building logic in isolation.
    """

    def test_first_ingest_contains_all_required_state_fields(self) -> None:
        """On first ingest, graph_input supplies every
        non-NotRequired TeamState field.
        """
        req = DispatchRequest(
            action="ingest",
            thread_id="t-init",
            content="Hello",
            team_preset="vaultspec-solo-coder",
            recursion_limit=25,
        )
        inp = GraphLifecycleManager.build_graph_input(req, is_first_ingest=True)

        required_fields = {
            "messages",
            "active_agent",
            "artifacts",
            "current_plan",
            "thread_id",
            "token_usage",
        }
        assert required_fields <= inp.keys(), (
            f"Missing required fields: {required_fields - inp.keys()}"
        )
        assert inp["active_agent"] == ""
        assert inp["artifacts"] == []
        assert inp["current_plan"] == []
        assert inp["thread_id"] == "t-init"
        assert inp["token_usage"] == {}

    def test_followup_ingest_omits_plan_fields(self) -> None:
        """On follow-up ingest, graph_input omits current_plan/active_agent/artifacts
        so LangGraph preserves checkpoint values and _replace_plan is not triggered."""
        req = DispatchRequest(
            action="ingest",
            thread_id="t-followup",
            content="Follow-up question",
            recursion_limit=25,
        )
        inp = GraphLifecycleManager.build_graph_input(req, is_first_ingest=False)

        # These keys must NOT be present -- their absence lets LangGraph
        # preserve checkpoint values rather than triggering reducers.
        assert "current_plan" not in inp
        assert "active_agent" not in inp
        assert "artifacts" not in inp
        assert "token_usage" not in inp
        # These keys must still be present.
        assert inp["thread_id"] == "t-followup"
        assert len(inp["messages"]) == 1

    def test_thread_id_matches_request(self) -> None:
        """thread_id in graph_input must match the request thread_id."""
        req = DispatchRequest(
            action="ingest",
            thread_id="thread-xyz",
            content="test",
            recursion_limit=25,
        )
        inp = GraphLifecycleManager.build_graph_input(req, is_first_ingest=False)
        assert inp["thread_id"] == "thread-xyz"

    def test_sdd_fields_included_on_first_ingest_when_provided(self) -> None:
        """SDD blackboard fields are included in graph_input on first ingest."""
        req = DispatchRequest(
            action="ingest",
            thread_id="t-sdd",
            content="Hello",
            team_preset="vaultspec-solo-coder",
            active_feature="auth-flow",
            feedback_batch_id="feedback-batch:deadbeef",
            pipeline_phase="implement",
            vault_index={"specs": ["auth.md"]},
            validation_errors=["missing tests"],
            recursion_limit=25,
        )
        inp = GraphLifecycleManager.build_graph_input(req, is_first_ingest=True)

        assert inp["active_feature"] == "auth-flow"
        # feedback-loop: the opaque batch id rides the SDD blackboard the same way.
        assert inp["feedback_batch_id"] == "feedback-batch:deadbeef"
        assert inp["pipeline_phase"] == "implement"
        assert inp["vault_index"] == {"specs": ["auth.md"]}
        assert inp["validation_errors"] == ["missing tests"]

    def test_empty_sdd_fields_materialized_on_first_ingest(self) -> None:
        """Fresh checkpoints carry every restart-required SDD field."""
        req = DispatchRequest(
            action="ingest",
            thread_id="t-sdd-empty",
            content="Hello",
            team_preset="vaultspec-solo-coder",
            recursion_limit=25,
        )
        inp = GraphLifecycleManager.build_graph_input(req, is_first_ingest=True)

        assert inp["active_feature"] is None
        assert inp["feedback_batch_id"] is None
        assert inp["pipeline_phase"] is None
        assert inp["vault_index"] == {}
        assert inp["validation_errors"] == []

    def test_context_preamble_prepended_as_system_message(self) -> None:
        """context_preamble is prepended as a SystemMessage before HumanMessage."""
        from langchain_core.messages import HumanMessage, SystemMessage

        req = DispatchRequest(
            action="ingest",
            thread_id="t-preamble",
            content="User question",
            context_preamble="You are a helpful assistant.",
            recursion_limit=25,
        )
        inp = GraphLifecycleManager.build_graph_input(req, is_first_ingest=False)

        msgs = inp["messages"]
        assert len(msgs) == 2
        assert isinstance(msgs[0], SystemMessage)
        assert isinstance(msgs[1], HumanMessage)
        assert msgs[0].content == "You are a helpful assistant."
        assert msgs[1].content == "User question"

    def test_no_content_yields_empty_messages(self) -> None:
        """When both content and context_preamble are absent, messages is empty."""
        req = DispatchRequest(
            action="ingest",
            thread_id="t-empty",
            recursion_limit=25,
        )
        inp = GraphLifecycleManager.build_graph_input(req, is_first_ingest=False)
        assert inp["messages"] == []

    def test_sdd_fields_not_included_on_followup_even_if_provided(self) -> None:
        """SDD fields are silently ignored on follow-up ingests
        (is_first_ingest=False).
        """
        req = DispatchRequest(
            action="ingest",
            thread_id="t-sdd-followup",
            content="Follow up",
            active_feature="auth-flow",
            pipeline_phase="implement",
            recursion_limit=25,
        )
        inp = GraphLifecycleManager.build_graph_input(req, is_first_ingest=False)

        assert "active_feature" not in inp
        assert "pipeline_phase" not in inp


# ---------------------------------------------------------------------------
# T17 — lazy graph recompilation on resume
# ---------------------------------------------------------------------------


class TestLazyRecompilation:
    """Verify graph cache and thread mapping behaviour (T17)."""

    @pytest.mark.asyncio(loop_scope="function")
    async def test_compiled_graph_registration_tracks_the_thread(self) -> None:
        """Registration atomically makes a graph available for one thread."""
        async with AsyncSqliteSaver.from_conn_string(":memory:") as cp:
            await cp.setup()
            bridge = _make_bridge()
            try:
                executor = Executor(checkpointer=cp, bridge=bridge)
                cache_key = ("vaultspec-solo-coder", None, False)
                _inject_graph(executor, "t-cache", cache_key=cache_key)
                assert executor.graph_count == 1
            finally:
                await bridge.close()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_resume_without_graph_or_preset_logs_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Resume drops with warning when graph is missing and no preset available."""
        async with AsyncSqliteSaver.from_conn_string(":memory:") as cp:
            await cp.setup()
            bridge = _make_bridge()
            try:
                executor = Executor(checkpointer=cp, bridge=bridge)
                req = DispatchRequest(
                    action="resume",
                    thread_id="t-no-graph",
                    option_id="allow_once",
                    recursion_limit=25,
                )
                with caplog.at_level(
                    logging.WARNING, logger="vaultspec_a2a.worker.executor"
                ):
                    await executor.handle_dispatch(req)
                record = next(
                    rec
                    for rec in caplog.records
                    if "No graph for thread" in rec.message
                )
                assert record.__dict__["thread_id"] == "t-no-graph"
                assert record.__dict__["dispatch_id"] == req.dispatch_id
                assert record.__dict__["dispatch_action"] == "resume"
                assert record.__dict__["runtime_mode"] == "resume"
                assert record.__dict__["worker_id"] == "test-worker"
                assert record.__dict__["action"] == "graph_missing"
            finally:
                await bridge.close()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_registration_keeps_one_cached_graph(self) -> None:
        """The public registration seam avoids exposing cache dictionaries."""
        async with AsyncSqliteSaver.from_conn_string(":memory:") as cp:
            await cp.setup()
            bridge = _make_bridge()
            try:
                executor = Executor(checkpointer=cp, bridge=bridge)
                cache_key = ("vaultspec-solo-coder", "/some/path", False)
                _inject_graph(executor, "t-preset", cache_key=cache_key)
                assert executor.graph_count == 1
            finally:
                await bridge.close()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_shutdown_clears_registered_graph(self) -> None:
        """Shutdown removes a graph that entered through the public seam."""
        async with AsyncSqliteSaver.from_conn_string(":memory:") as cp:
            await cp.setup()
            bridge = _make_bridge()
            try:
                executor = Executor(checkpointer=cp, bridge=bridge)
                _inject_graph(executor, "t-1")
                assert executor.graph_count == 1

                await executor.shutdown()
                assert executor.graph_count == 0
            finally:
                await bridge.close()


# ---------------------------------------------------------------------------
# shutdown
# ---------------------------------------------------------------------------


class TestShutdown:
    """Verify that shutdown() clears internal state via observable effects."""

    @pytest.mark.asyncio(loop_scope="function")
    async def test_shutdown_clears_graph_count_to_zero(self) -> None:
        """Shutdown should reset graph_count (public property) to 0."""
        async with AsyncSqliteSaver.from_conn_string(":memory:") as cp:
            await cp.setup()
            bridge = _make_bridge()
            try:
                executor = Executor(checkpointer=cp, bridge=bridge)
                # Inject a graph entry -- this is the only way to pre-populate
                # without running a full team config compilation.
                _inject_graph(executor, "thread-1")
                assert executor.graph_count == 1

                await executor.shutdown()
                assert executor.graph_count == 0
            finally:
                await bridge.close()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_shutdown_is_idempotent(self) -> None:
        """Calling shutdown twice doesn't raise."""
        async with AsyncSqliteSaver.from_conn_string(":memory:") as cp:
            await cp.setup()
            bridge = _make_bridge()
            try:
                executor = Executor(checkpointer=cp, bridge=bridge)
                await executor.shutdown()
                await executor.shutdown()
            finally:
                await bridge.close()


# ---------------------------------------------------------------------------
# Shared pre-run guards — trace fidelity
# ---------------------------------------------------------------------------


def _recording_span() -> Span:
    """Start a real, recording SDK span the production guard can write to.

    A real ``TracerProvider`` and a real span, per the pattern the telemetry
    tests use. ``InMemorySpanExporter`` is banned repo-wide and the Jaeger-backed
    alternative is a ``service`` test, so the assertion reads the live recording
    span rather than an intercepted export of it.
    """
    provider = TracerProvider(resource=Resource.create({"service.name": "guard-test"}))
    tracer = provider.get_tracer(__name__)
    span = tracer.start_span("executor.guard-test")
    assert isinstance(span, Span), "the SDK tracer must hand back a recording span"
    assert span.is_recording()
    return span


def _span_attributes(span: ReadableSpan) -> dict[str, Any]:
    return dict(span.attributes or {})


class TestPreRunGuardTraceFidelity:
    """Both dispatch modes mark the run's span when a pre-run guard rejects it.

    The three pre-run guards are one behaviour each, reached from two dispatch
    modes. The resume arms used to log the rejection but leave the span clean, so
    the same failure was visible in logs and invisible in traces depending on
    which mode hit it. These pin the trace side for both modes.

    Reaching each guard from a real ``handle_dispatch`` is covered by
    ``TestHandleDispatch`` and ``TestLazyRecompilation``, which assert the log
    record's exact fields; the guard writes the log record and the span
    attributes in one straight line, so those tests pin the wiring and these pin
    the payload.
    """

    @pytest.mark.asyncio(loop_scope="function")
    @pytest.mark.parametrize("guards", [_INGEST_GUARDS, _RESUME_GUARDS])
    async def test_missing_graph_marks_the_span_failed(self, guards: Any) -> None:
        async with AsyncSqliteSaver.from_conn_string(":memory:") as cp:
            await cp.setup()
            bridge = _make_bridge()
            try:
                executor = Executor(checkpointer=cp, bridge=bridge)
                req = DispatchRequest(
                    action=guards.runtime_mode,
                    thread_id="t-guard-no-graph",
                    content="hello",
                    option_id="allow_once",
                    recursion_limit=25,
                )
                span = _recording_span()
                await executor._reject_missing_graph(req, span, guards)

                attributes = _span_attributes(span)
                assert attributes["error"] is True
                assert attributes["error.message"] == "No team preset"
            finally:
                await bridge.close()

    @pytest.mark.asyncio(loop_scope="function")
    @pytest.mark.parametrize("guards", [_INGEST_GUARDS, _RESUME_GUARDS])
    async def test_slot_held_marks_the_span_failed(self, guards: Any) -> None:
        async with AsyncSqliteSaver.from_conn_string(":memory:") as cp:
            await cp.setup()
            bridge = _make_bridge()
            try:
                executor = Executor(checkpointer=cp, bridge=bridge)
                req = DispatchRequest(
                    action=guards.runtime_mode,
                    thread_id="t-guard-slot",
                    content="hello",
                    option_id="allow_once",
                    recursion_limit=25,
                )
                span = _recording_span()
                executor._reject_slot_held(req, span, guards)

                attributes = _span_attributes(span)
                assert attributes["error"] is True
                assert attributes["error.message"] == "Ingest already active"
            finally:
                await bridge.close()

    @pytest.mark.asyncio(loop_scope="function")
    @pytest.mark.parametrize("guards", [_INGEST_GUARDS, _RESUME_GUARDS])
    async def test_compile_failure_marks_the_span_with_the_reason(
        self, guards: Any
    ) -> None:
        async with AsyncSqliteSaver.from_conn_string(":memory:") as cp:
            await cp.setup()
            bridge = _make_bridge()
            try:
                executor = Executor(checkpointer=cp, bridge=bridge)
                req = DispatchRequest(
                    action=guards.runtime_mode,
                    thread_id="t-guard-compile",
                    content="hello",
                    option_id="allow_once",
                    recursion_limit=25,
                )
                span = _recording_span()
                exc = GraphCompilationError("engine unreachable")
                await executor._reject_compile_failure(req, span, exc, guards)

                attributes = _span_attributes(span)
                assert attributes["error"] is True
                assert attributes["error.message"] == "engine unreachable"
            finally:
                await bridge.close()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_resume_slot_reject_keeps_its_distinct_log_action(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Unifying the guards must not flatten the two modes' log identities.

        ``ingest_rejected_active`` and ``resume_rejected_active`` are distinct
        operator-facing actions; a shared implementation that collapsed them
        would erase which mode was dropped.
        """
        async with AsyncSqliteSaver.from_conn_string(":memory:") as cp:
            await cp.setup()
            bridge = _make_bridge()
            try:
                executor = Executor(checkpointer=cp, bridge=bridge)
                ingest_req = DispatchRequest(
                    action="ingest",
                    thread_id="t-actions",
                    content="hello",
                    recursion_limit=25,
                )
                resume_req = DispatchRequest(
                    action="resume",
                    thread_id="t-actions",
                    option_id="allow_once",
                    recursion_limit=25,
                )
                with caplog.at_level(
                    logging.WARNING, logger="vaultspec_a2a.worker.executor"
                ):
                    executor._reject_slot_held(
                        ingest_req, _recording_span(), _INGEST_GUARDS
                    )
                    executor._reject_slot_held(
                        resume_req, _recording_span(), _RESUME_GUARDS
                    )

                actions = [
                    rec.__dict__["action"]
                    for rec in caplog.records
                    if "action" in rec.__dict__
                ]
                assert actions == ["ingest_rejected_active", "resume_rejected_active"]
            finally:
                await bridge.close()


# ---------------------------------------------------------------------------
# Shared settle epilogue — ordering
# ---------------------------------------------------------------------------


def _make_observing_bridge(
    observations: list[dict[str, Any]],
    holder: dict[str, Any],
) -> WorkerBridge:
    """A real bridge whose in-process gateway records each event as it arrives.

    The gateway handler runs inside the worker's own flush, so what it reads off
    the executor is the executor's state at the instant the event was relayed —
    a live observation of settle ordering, not a reconstruction after the fact.
    """
    app = FastAPI()

    @app.post("/internal/events/batch")
    async def _batch(request: Request) -> Response:
        body = await request.json()
        executor = holder.get("executor")
        thread_id = holder.get("thread_id", "")
        for item in body.get("events", []):
            payload = item.get("payload", {})
            observations.append(
                {
                    "kind": payload.get("type") or payload.get("event_type"),
                    "dispatch_id": payload.get("dispatch_id"),
                    "dispatch_action": payload.get("action"),
                    "status": payload.get("status"),
                    "tokens_held": (
                        executor.token_store.has(thread_id)
                        if executor is not None
                        else None
                    ),
                    "tracked": thread_id in holder["bridge"].active_threads,
                }
            )
        return Response(content='{"status":"ok"}', media_type="application/json")

    @app.post("/internal/heartbeat")
    async def _heartbeat(request: Request) -> Response:
        return Response(content='{"status":"ok"}', media_type="application/json")

    bridge = WorkerBridge(api_url="http://control:8000", worker_id="settle-worker")
    bridge._client = httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://control:8000",
    )
    holder["bridge"] = bridge
    return bridge


def _install_completing_graph(executor: Executor, thread_id: str) -> None:
    """Compile a real one-node graph that runs straight to a COMPLETED outcome."""

    async def worker_node(state: Any) -> dict[str, Any]:
        return {"messages": [AIMessage(content="done")], "next": "FINISH"}

    builder = new_state_graph()
    builder.add_node("worker", worker_node)
    builder.add_edge("__start__", "worker")
    builder.add_edge("worker", "__end__")
    graph: RegisteredCompiledGraph = builder.compile(
        checkpointer=executor._checkpointer
    )

    cache_key = ("settle-preset", None, False)
    executor.register_compiled_graph(thread_id, cache_key, graph)


def _install_gated_graph(executor: Executor, thread_id: str) -> None:
    """Compile a real one-node graph that parks on an interrupt, then completes."""

    async def gate_node(state: Any) -> dict[str, Any]:
        decision = interrupt({"type": "plan_approval_request", "prompt": "ok?"})
        return {
            "messages": [AIMessage(content=f"resumed:{decision}")],
            "next": "FINISH",
        }

    builder = new_state_graph()
    builder.add_node("gate", gate_node)
    builder.add_edge("__start__", "gate")
    builder.add_edge("gate", "__end__")
    graph: RegisteredCompiledGraph = builder.compile(
        checkpointer=executor._checkpointer
    )

    cache_key = ("settle-gated-preset", None, False)
    executor.register_compiled_graph(thread_id, cache_key, graph)


class TestSettleOrdering:
    """The settle epilogue keeps its load-bearing order on both dispatch paths.

    The order is a contract, not a style: the execution-state projection and the
    run's terminal status land first, and only then may the run's tokens be
    dropped — the benign engine session close sits in that window and
    authenticates with those tokens. A settle that dropped the tokens first would
    strand the close, and one that dropped the thread's tracking before the
    terminal event would relay the terminal for an untracked thread.
    """

    @pytest.mark.asyncio(loop_scope="function")
    async def test_ingest_emits_one_application_receipt_for_stable_dispatch(
        self,
    ) -> None:
        thread_id = "message-application-receipt"
        observations: list[dict[str, Any]] = []
        holder: dict[str, Any] = {"thread_id": thread_id, "executor": None}
        async with AsyncSqliteSaver.from_conn_string(":memory:") as cp:
            await cp.setup()
            bridge = _make_observing_bridge(observations, holder)
            executor = Executor(checkpointer=cp, bridge=bridge)
            holder["executor"] = executor
            try:
                _install_completing_graph(executor, thread_id)
                await executor.handle_dispatch(
                    DispatchRequest(
                        dispatch_id="stable-message-dispatch",
                        action="ingest",
                        thread_id=thread_id,
                        content="continue",
                        team_preset="settle-preset",
                        recursion_limit=10,
                    )
                )

                receipts = [
                    observation
                    for observation in observations
                    if observation["kind"] == "dispatch_applied"
                ]
                assert receipts == [
                    {
                        "kind": "dispatch_applied",
                        "dispatch_id": "stable-message-dispatch",
                        "dispatch_action": "ingest",
                        "status": None,
                        "tokens_held": False,
                        "tracked": True,
                    }
                ]
            finally:
                await bridge.close()
                await executor.shutdown()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_ingest_settle_lands_terminal_before_dropping_tokens(self) -> None:
        thread_id = "settle-ingest"
        observations: list[dict[str, Any]] = []
        holder: dict[str, Any] = {"thread_id": thread_id, "executor": None}
        async with AsyncSqliteSaver.from_conn_string(":memory:") as cp:
            await cp.setup()
            bridge = _make_observing_bridge(observations, holder)
            executor = Executor(checkpointer=cp, bridge=bridge)
            holder["executor"] = executor
            try:
                _install_completing_graph(executor, thread_id)
                req = DispatchRequest(
                    action="ingest",
                    thread_id=thread_id,
                    content="build it",
                    team_preset="settle-preset",
                    recursion_limit=10,
                    actor_tokens=ActorTokenBundle(
                        tokens={"vaultspec-synthesist": "settle-token"},
                        engine_bearer="settle-bearer",
                    ),
                )
                await executor.handle_dispatch(req)

                kinds = [obs["kind"] for obs in observations]
                assert "execution_state_projection" in kinds
                assert "thread_terminal" in kinds
                assert kinds.index("execution_state_projection") < kinds.index(
                    "thread_terminal"
                )

                terminal = observations[kinds.index("thread_terminal")]
                assert terminal["status"] == ThreadStatus.COMPLETED
                # The close's window: terminal has landed, tokens are still held.
                assert terminal["tokens_held"] is True
                assert terminal["tracked"] is True
                # And the window closes once the settle finishes.
                assert executor.token_store.has(thread_id) is False
                assert thread_id not in bridge.active_threads
            finally:
                await bridge.close()
                await executor.shutdown()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_resume_settle_lands_terminal_before_dropping_tokens(self) -> None:
        """The resume path settles through the same epilogue as ingest.

        A gated run completes on its FINAL resume, so the resume settle — not the
        ingest one — is what closes an authoring run's engine session.
        """
        thread_id = "settle-resume"
        observations: list[dict[str, Any]] = []
        holder: dict[str, Any] = {"thread_id": thread_id, "executor": None}
        async with AsyncSqliteSaver.from_conn_string(":memory:") as cp:
            await cp.setup()
            bridge = _make_observing_bridge(observations, holder)
            executor = Executor(checkpointer=cp, bridge=bridge)
            holder["executor"] = executor
            try:
                _install_gated_graph(executor, thread_id)
                bundle = ActorTokenBundle(
                    tokens={"vaultspec-synthesist": "settle-token"},
                    engine_bearer="settle-bearer",
                )
                await executor.handle_dispatch(
                    DispatchRequest(
                        action="ingest",
                        thread_id=thread_id,
                        content="build it",
                        team_preset="settle-gated-preset",
                        recursion_limit=10,
                        actor_tokens=bundle,
                    )
                )
                # Parked at the gate: not terminal, so the tokens survive.
                assert executor.token_store.has(thread_id) is True
                observations.clear()

                await executor.handle_dispatch(
                    DispatchRequest(
                        action="resume",
                        thread_id=thread_id,
                        option_id="approve",
                        team_preset="settle-gated-preset",
                        recursion_limit=10,
                        actor_tokens=bundle,
                    )
                )

                kinds = [obs["kind"] for obs in observations]
                assert "execution_state_projection" in kinds
                assert "thread_terminal" in kinds
                assert kinds.index("execution_state_projection") < kinds.index(
                    "thread_terminal"
                )

                terminal = observations[kinds.index("thread_terminal")]
                assert terminal["status"] == ThreadStatus.COMPLETED
                assert terminal["tokens_held"] is True
                assert terminal["tracked"] is True
                assert executor.token_store.has(thread_id) is False
                assert thread_id not in bridge.active_threads
            finally:
                await bridge.close()
                await executor.shutdown()


class TestAuthoringBridgeFailClosed:
    """An armed authoring_bridge run fails closed when no engine is reachable.

    Mirrors the submitter's fail-closed contract: the per-run binding provider is
    built at compile time, and a run that cannot reach the engine to fetch its
    catalog must never start vague - the typed EngineUnavailableError is what the
    compile guard turns into a GraphCompilationError.
    """

    @pytest.mark.asyncio(loop_scope="function")
    async def test_build_provider_raises_without_reachable_engine(
        self, tmp_path: Any
    ) -> None:
        from ...authoring import EngineUnavailableError

        async with AsyncSqliteSaver.from_conn_string(":memory:") as cp:
            await cp.setup()
            bridge = _make_bridge()
            try:
                manager = Executor(checkpointer=cp, bridge=bridge)._graph_lifecycle
                # Deterministic no-engine via the discovery contract's own env: a
                # bogus explicit service.json path plus an empty HOME so the
                # ~/.vaultspec/service.json fallback resolves nothing either.
                empty_home = tmp_path / "home"
                empty_home.mkdir()
                keys = ("VAULTSPEC_ENGINE_SERVICE_JSON", "USERPROFILE", "HOME")
                saved = {k: os.environ.get(k) for k in keys}
                os.environ["VAULTSPEC_ENGINE_SERVICE_JSON"] = str(
                    tmp_path / "nope.json"
                )
                os.environ["USERPROFILE"] = str(empty_home)
                os.environ["HOME"] = str(empty_home)
                try:
                    with pytest.raises(EngineUnavailableError):
                        await manager._build_authoring_binding_provider()
                finally:
                    for k, v in saved.items():
                        if v is None:
                            os.environ.pop(k, None)
                        else:
                            os.environ[k] = v
            finally:
                await bridge.close()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_engine_discovery_retry_is_offloaded_not_blocking_the_worker(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """resolve_engine_with_retry's blocking time.sleep must not freeze the
        worker's event loop while it runs.

        S37: before this fix, this call ran directly on the worker's single
        event loop — heartbeats, every other thread's dispatch, everything —
        was frozen solid for the full retry window on every first compile of
        a preset+workspace cache key. Proven here by racing a fast
        asyncio.sleep task against a stand-in for the blocking discovery
        call: if the call is genuinely offloaded (asyncio.to_thread), the
        fast task finishes first; if it were still blocking the loop
        in-place, the fast task could not even be scheduled until the slow
        call returned.
        """
        import asyncio
        import time as time_module

        from ... import authoring as authoring_pkg
        from ...authoring import EngineUnavailableError

        def _slow_blocking_resolve(*args: object, **kwargs: object) -> None:
            time_module.sleep(0.3)
            return None

        monkeypatch.setattr(
            authoring_pkg, "resolve_engine_with_retry", _slow_blocking_resolve
        )

        async with AsyncSqliteSaver.from_conn_string(":memory:") as cp:
            await cp.setup()
            bridge = _make_bridge()
            try:
                manager = Executor(checkpointer=cp, bridge=bridge)._graph_lifecycle

                events: list[str] = []

                async def _fast_concurrent_task() -> None:
                    await asyncio.sleep(0.05)
                    events.append("fast_task")

                ticker = asyncio.create_task(_fast_concurrent_task())
                with pytest.raises(EngineUnavailableError):
                    await manager._build_authoring_binding_provider()
                events.append("slow_build")
                await ticker

                assert events == ["fast_task", "slow_build"]
            finally:
                await bridge.close()


# ---------------------------------------------------------------------------
# Blank terminals — every failing dispatch reports a condition
# ---------------------------------------------------------------------------


def _make_recording_bridge(relayed: list[dict[str, Any]]) -> WorkerBridge:
    """A real bridge whose in-process gateway keeps every relayed payload.

    The payloads are read off a real HTTP batch POST, so what the assertions see
    is what the gateway would see - not the executor's intent before it crossed
    the IPC boundary, which is where a frame with no wire type silently loses
    everything that made it meaningful.
    """
    app = FastAPI()

    @app.post("/internal/events/batch")
    async def _batch(request: Request) -> Response:
        body = await request.json()
        for item in body.get("events", []):
            relayed.append(item.get("payload", {}))
        return Response(content='{"status":"ok"}', media_type="application/json")

    @app.post("/internal/heartbeat")
    async def _heartbeat(request: Request) -> Response:
        return Response(content='{"status":"ok"}', media_type="application/json")

    bridge = WorkerBridge(api_url="http://control:8000", worker_id="blank-worker")
    bridge._client = httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://control:8000",
    )
    return bridge


def _frames_of(relayed: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    """Select the relayed payloads of one wire kind, in arrival order."""
    return [
        payload
        for payload in relayed
        if (payload.get("type") or payload.get("event_type")) == kind
    ]


def _wrapped_failure() -> BaseException:
    """A real wrapped exception, raised and caught rather than assembled.

    What reaches a reporting site in production is a wrapper around the fault
    that actually happened, and only a genuine ``raise ... from`` produces the
    ``__cause__`` link the reason renderer follows. Setting the attribute by hand
    would prove the renderer walks a field the interpreter fills differently.
    """
    try:
        try:
            raise ValueError("bad workspace root")
        except ValueError as cause:
            raise RuntimeError("relay exploded") from cause
    except RuntimeError as exc:
        return exc


class TestUnhandledDispatchTerminal:
    """A dispatch that dies outside every inner handler still settles the run.

    The worker's task group swallows the exception so one bad run cannot take the
    process down, and the gateway acked the dispatch the moment it was scheduled.
    Without a terminal the run therefore sits RUNNING forever while the gateway
    believes the dispatch succeeded - the failure carrying the least information
    of any in the system.

    The backstop's own trigger is not inducible from ``handle_dispatch`` with a
    well-formed dispatch, and deliberately so: every inner path already guards
    itself, which is why the arm is a backstop rather than a branch. So these
    drive its target directly, over a real bridge, a real HTTP relay and the
    executor's real ingest-slot state - the assertions read what the gateway
    would receive, not what the executor meant to send.
    """

    @pytest.mark.asyncio(loop_scope="function")
    async def test_slot_owning_dispatch_fails_the_run_and_returns_its_slot(
        self,
    ) -> None:
        thread_id = "t-unhandled-dispatch"
        relayed: list[dict[str, Any]] = []
        async with AsyncSqliteSaver.from_conn_string(":memory:") as cp:
            await cp.setup()
            bridge = _make_recording_bridge(relayed)
            executor = Executor(checkpointer=cp, bridge=bridge)
            try:
                # The slot the ingest took before it died, taken through the
                # executor's own gate rather than by reaching into its state.
                assert await executor._mark_ingest_active(thread_id) is True
                await executor._fail_unhandled_dispatch(
                    DispatchRequest(
                        action="ingest",
                        thread_id=thread_id,
                        content="build it",
                        recursion_limit=10,
                    ),
                    _wrapped_failure(),
                )
                await bridge.flush_events()

                terminals = _frames_of(relayed, "thread_terminal")
                assert len(terminals) == 1, "the run must settle exactly once"
                assert terminals[0]["status"] == ThreadStatus.FAILED
                # The whole cause chain, not just the outermost wrapper: the
                # wrapper says where the run died, the cause says why.
                assert "RuntimeError: relay exploded" in terminals[0]["error_detail"]
                assert "ValueError: bad workspace root" in terminals[0]["error_detail"]

                errors = _frames_of(relayed, "error")
                assert len(errors) == 1, (
                    "the failure must carry a machine-readable code"
                )
                assert errors[0]["code"] == ProviderCondition.UNKNOWN.value
                assert errors[0]["recoverable"] is False

                # The slot the dispatch took is given back, or the thread could
                # never be dispatched again.
                assert executor.active_ingest_count == 0
            finally:
                await bridge.close()
                await executor.shutdown()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_cancel_fault_stays_silent_while_an_ingest_owns_the_terminal(
        self,
    ) -> None:
        """A cancel arm must not fabricate a failure over a live run's outcome.

        The cancel path never holds the ingest slot, so a held slot means a
        concurrent ingest owns the run's terminal. Emitting one here would race a
        legitimate settle with an invented failure.
        """
        thread_id = "t-cancel-fault"
        relayed: list[dict[str, Any]] = []
        async with AsyncSqliteSaver.from_conn_string(":memory:") as cp:
            await cp.setup()
            bridge = _make_recording_bridge(relayed)
            executor = Executor(checkpointer=cp, bridge=bridge)
            try:
                # The slot a live ingest would hold, taken through the executor's
                # own gate rather than by reaching into its state.
                assert await executor._mark_ingest_active(thread_id) is True
                await executor._fail_unhandled_dispatch(
                    DispatchRequest(
                        action="cancel",
                        thread_id=thread_id,
                        recursion_limit=10,
                    ),
                    RuntimeError("cancel relay exploded"),
                )
                await bridge.flush_events()

                assert _frames_of(relayed, "thread_terminal") == []
                assert _frames_of(relayed, "error") == []
                # The concurrent ingest still owns its slot.
                assert executor.active_ingest_count == 1
            finally:
                await bridge.close()
                await executor.shutdown()


class TestPreRunRefusalsCarryTheirReason:
    """A run refused before it started says why, on both channels.

    These refusals always knew their cause - no preset was named, or the run's
    checkpoint already records an unhandled error - yet the terminal carried no
    detail and no error frame preceded it, so a client saw a bare ``failed`` for
    a refusal the worker could describe precisely. A consumer branching on the
    frame's code could not see the failure at all.
    """

    @pytest.mark.asyncio(loop_scope="function")
    async def test_a_dispatch_with_no_preset_names_the_missing_graph(self) -> None:
        thread_id = "t-no-preset"
        relayed: list[dict[str, Any]] = []
        async with AsyncSqliteSaver.from_conn_string(":memory:") as cp:
            await cp.setup()
            bridge = _make_recording_bridge(relayed)
            executor = Executor(checkpointer=cp, bridge=bridge)
            try:
                # No graph registered and no preset on the dispatch, so the
                # missing-graph guard is reached through a real handle_dispatch.
                await executor.handle_dispatch(
                    DispatchRequest(
                        action="ingest",
                        thread_id=thread_id,
                        content="build it",
                        recursion_limit=10,
                    )
                )
                await bridge.flush_events()

                terminals = _frames_of(relayed, "thread_terminal")
                assert len(terminals) == 1
                assert terminals[0]["status"] == ThreadStatus.FAILED
                assert terminals[0]["error_detail"] == (
                    "No graph to run: the dispatch named no team preset"
                )

                errors = _frames_of(relayed, "error")
                assert len(errors) == 1
                assert errors[0]["code"] == ProviderCondition.UNKNOWN.value
                assert errors[0]["recoverable"] is False
            finally:
                await bridge.close()
                await executor.shutdown()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_an_unclassified_execution_failure_still_names_itself(self) -> None:
        """A failure ingest never classified settles with a reason, not blank.

        The executor's execution catch-all fires when an exception escapes
        AROUND ingest's own reporting rather than through it. Ingest therefore
        stashed no reason and emitted no error frame, and before this arm the run
        settled as a bare "failed" on both channels. Driven through the real
        settle path with a thread ingest never saw, which is exactly the state
        the catch-all hands it.
        """
        thread_id = "t-unclassified-failure"
        relayed: list[dict[str, Any]] = []
        async with AsyncSqliteSaver.from_conn_string(":memory:") as cp:
            await cp.setup()
            bridge = _make_recording_bridge(relayed)
            executor = Executor(checkpointer=cp, bridge=bridge)
            try:
                graph = _terminal_graph(executor)
                config = {"configurable": {"thread_id": thread_id}}

                await executor._settle_run(
                    DispatchRequest(
                        action="ingest",
                        thread_id=thread_id,
                        content="build it",
                        recursion_limit=10,
                    ),
                    graph,
                    config,
                    ThreadStatus.FAILED,
                    "Graph execution failed unexpectedly",
                )
                await bridge.flush_events()

                terminals = _frames_of(relayed, "thread_terminal")
                assert len(terminals) == 1
                assert terminals[0]["status"] == ThreadStatus.FAILED
                assert terminals[0]["error_detail"] == (
                    "Graph execution failed unexpectedly"
                )

                # Both channels, not one: a consumer keying on the frame's code
                # could not see this failure at all when only the terminal spoke.
                errors = _frames_of(relayed, "error")
                assert len(errors) == 1
                assert errors[0]["code"] == ProviderCondition.UNKNOWN.value
                assert errors[0]["recoverable"] is False
            finally:
                await bridge.close()
                await executor.shutdown()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_a_settle_with_no_fallback_invents_no_failure(self) -> None:
        """The fallback arm stays shut when the caller offers none.

        The companion to the case above, and the reason it matters: if settling
        emitted an error frame unconditionally, every ordinary completion would
        report a failure that never happened.
        """
        thread_id = "t-settle-no-fallback"
        relayed: list[dict[str, Any]] = []
        async with AsyncSqliteSaver.from_conn_string(":memory:") as cp:
            await cp.setup()
            bridge = _make_recording_bridge(relayed)
            executor = Executor(checkpointer=cp, bridge=bridge)
            try:
                graph = _terminal_graph(executor)

                await executor._settle_run(
                    DispatchRequest(
                        action="ingest",
                        thread_id=thread_id,
                        content="build it",
                        recursion_limit=10,
                    ),
                    graph,
                    {"configurable": {"thread_id": thread_id}},
                    ThreadStatus.COMPLETED,
                )
                await bridge.flush_events()

                assert _frames_of(relayed, "error") == []
                terminals = _frames_of(relayed, "thread_terminal")
                assert len(terminals) == 1
                assert terminals[0]["status"] == ThreadStatus.COMPLETED
                assert not terminals[0].get("error_detail")
            finally:
                await bridge.close()
                await executor.shutdown()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_a_resume_with_no_graph_names_what_it_cannot_resume(self) -> None:
        """The two modes keep distinct client wording, not one flattened line."""
        thread_id = "t-no-graph-resume"
        relayed: list[dict[str, Any]] = []
        async with AsyncSqliteSaver.from_conn_string(":memory:") as cp:
            await cp.setup()
            bridge = _make_recording_bridge(relayed)
            executor = Executor(checkpointer=cp, bridge=bridge)
            try:
                await executor.handle_dispatch(
                    DispatchRequest(
                        action="resume",
                        thread_id=thread_id,
                        option_id="allow_once",
                        recursion_limit=10,
                    )
                )
                await bridge.flush_events()

                terminals = _frames_of(relayed, "thread_terminal")
                assert len(terminals) == 1
                assert terminals[0]["error_detail"] == (
                    "No graph to resume: the run has no compiled graph"
                )
            finally:
                await bridge.close()
                await executor.shutdown()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_a_checkpoint_that_already_failed_reports_why_it_is_not_rerun(
        self,
    ) -> None:
        """The pre-flight failed arm shares the missing-graph blank shape.

        The checkpoint is made to record an unhandled error the only honest way:
        by running a real graph whose node raises, so LangGraph writes the error
        channel itself. A hand-written checkpoint row would prove the pre-flight
        reads a shape the framework may not produce.
        """
        thread_id = "t-preflight-failed"
        relayed: list[dict[str, Any]] = []
        async with AsyncSqliteSaver.from_conn_string(":memory:") as cp:
            await cp.setup()
            bridge = _make_recording_bridge(relayed)
            executor = Executor(checkpointer=cp, bridge=bridge)
            try:

                def exploding_node(state: TeamState) -> dict[str, object]:
                    del state
                    raise RuntimeError("node exploded")

                builder = new_state_graph()
                builder.add_node("boom", exploding_node)
                builder.add_edge("__start__", "boom")
                builder.add_edge("boom", "__end__")
                graph: RegisteredCompiledGraph = builder.compile(checkpointer=cp)
                executor.register_compiled_graph(
                    thread_id, ("boom-preset", None, False), graph
                )

                first = DispatchRequest(
                    action="ingest",
                    thread_id=thread_id,
                    content="build it",
                    team_preset="boom-preset",
                    recursion_limit=10,
                )
                await executor.handle_dispatch(first)
                await bridge.flush_events()
                relayed.clear()

                # A second dispatch: the pre-flight reads the error the failed
                # run left in the checkpoint and refuses to re-run it.
                await executor.handle_dispatch(first)
                await bridge.flush_events()

                terminals = _frames_of(relayed, "thread_terminal")
                assert len(terminals) == 1
                assert terminals[0]["status"] == ThreadStatus.FAILED
                assert "earlier attempt" in terminals[0]["error_detail"]

                errors = _frames_of(relayed, "error")
                assert len(errors) == 1
                assert errors[0]["code"] == ProviderCondition.UNKNOWN.value
            finally:
                await bridge.close()
                await executor.shutdown()

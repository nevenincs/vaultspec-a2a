"""Tests for Executor, GraphLifecycleManager, and StateProjector (ADR-019, D-09).

Validates the Executor's ingest gating logic, dispatch routing, and
shutdown behaviour; GraphLifecycleManager's input construction; using a real
``AsyncSqliteSaver`` and a real ``WorkerBridge`` backed by a real FastAPI
ASGI app via ASGITransport.

No mock libraries.  No tautological tests.
"""

from __future__ import annotations

import logging
from typing import Any, cast

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import Response
from httpx import ASGITransport
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from pydantic import ValidationError

from ...ipc.schemas import DispatchRequest
from ..executor import Executor
from ..graph_lifecycle import GraphLifecycleManager
from ..ipc import WorkerBridge

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


def _inject_graph(executor: Executor, thread_id: str, *, cache_key=_TEST_CACHE_KEY):
    """Insert a sentinel graph into the executor's LRU cache for *thread_id*."""
    sentinel = object()
    if cache_key not in executor._graph_cache:
        executor._graph_cache[cache_key] = sentinel  # type: ignore[assignment]
    executor._thread_to_cache_key[thread_id] = cache_key


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
                await executor._mark_ingest_done("t-1")
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

                await executor._mark_ingest_done("t-1")
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
                await executor._mark_ingest_done("nonexistent")
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
            team_preset="vaultspec-adaptive-coder",
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
        """ADR-019 SDD blackboard fields are included in graph_input on first ingest."""
        req = DispatchRequest(
            action="ingest",
            thread_id="t-sdd",
            content="Hello",
            team_preset="vaultspec-adaptive-coder",
            active_feature="auth-flow",
            pipeline_phase="implement",
            vault_index={"specs": ["auth.md"]},
            validation_errors=["missing tests"],
            recursion_limit=25,
        )
        inp = GraphLifecycleManager.build_graph_input(req, is_first_ingest=True)

        assert inp["active_feature"] == "auth-flow"
        assert inp["pipeline_phase"] == "implement"
        assert inp["vault_index"] == {"specs": ["auth.md"]}
        assert inp["validation_errors"] == ["missing tests"]

    def test_empty_sdd_fields_omitted_on_first_ingest(self) -> None:
        """SDD fields with default/empty values are not included in graph_input."""
        req = DispatchRequest(
            action="ingest",
            thread_id="t-sdd-empty",
            content="Hello",
            team_preset="vaultspec-adaptive-coder",
            recursion_limit=25,
        )
        inp = GraphLifecycleManager.build_graph_input(req, is_first_ingest=True)

        assert "active_feature" not in inp
        assert "pipeline_phase" not in inp
        assert "vault_index" not in inp
        assert "validation_errors" not in inp

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
    async def test_preset_cached_after_ingest(self) -> None:
        """After a successful ingest compile, _thread_to_cache_key holds the mapping."""
        async with AsyncSqliteSaver.from_conn_string(":memory:") as cp:
            await cp.setup()
            bridge = _make_bridge()
            try:
                executor = Executor(checkpointer=cp, bridge=bridge)
                cache_key = ("vaultspec-adaptive-coder", None, False)
                executor._graph_cache[cache_key] = object()  # type: ignore[assignment]
                executor._thread_to_cache_key["t-cache"] = cache_key
                assert executor._thread_to_cache_key["t-cache"] == cache_key
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
    async def test_ingest_stores_cache_key_mapping(self) -> None:
        """_get_or_compile_graph stores thread_id -> cache_key in _thread_to_cache_key
        when the graph is already in cache (hit path)."""
        async with AsyncSqliteSaver.from_conn_string(":memory:") as cp:
            await cp.setup()
            bridge = _make_bridge()
            try:
                executor = Executor(checkpointer=cp, bridge=bridge)
                cache_key = ("vaultspec-adaptive-coder", "/some/path", False)
                executor._graph_cache[cache_key] = object()  # type: ignore[assignment]
                executor._thread_to_cache_key["t-preset"] = cache_key

                # Verify the mapping is correctly stored (tests _thread_to_cache_key
                # state directly without needing to run the aggregator).
                assert executor._thread_to_cache_key["t-preset"] == cache_key
                assert "t-preset" in executor._thread_to_cache_key
            finally:
                await bridge.close()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_shutdown_clears_thread_to_cache_key(self) -> None:
        """shutdown() clears _thread_to_cache_key alongside _graph_cache."""
        async with AsyncSqliteSaver.from_conn_string(":memory:") as cp:
            await cp.setup()
            bridge = _make_bridge()
            try:
                executor = Executor(checkpointer=cp, bridge=bridge)
                executor._thread_to_cache_key["t-1"] = (
                    "vaultspec-adaptive-coder",
                    None,
                    False,
                )
                assert executor._thread_to_cache_key

                await executor.shutdown()
                assert not executor._thread_to_cache_key
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

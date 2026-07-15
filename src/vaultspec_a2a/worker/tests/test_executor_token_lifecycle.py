"""Live proof of actor-token threading through a real Executor dispatch (R7).

Drives a genuine ingest through the real ``Executor``, a real
``AsyncSqliteSaver`` checkpointer, a real ``WorkerBridge`` over an in-process
ASGI gateway, and a real compiled ``StateGraph`` — no mock libraries. A probe
node reads the worker-scoped store from inside the running graph, so the
assertions observe what a worker actually sees mid-run rather than a
reconstruction:

- the run's token reaches the owning role while the graph executes (injection);
- a role only reads its own token, and an unheld role reads ``None`` (isolation);
- no token string survives into the durable checkpoint (never checkpointed);
- no token string appears on any log record emitted during the dispatch;
- the store holds nothing for the run once the dispatch completes (disposal).
"""

from __future__ import annotations

import json
import logging
from typing import Any, cast

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import Response
from httpx import ASGITransport
from langchain_core.messages import AIMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph

from ...ipc.schemas import DispatchRequest
from ...thread.actor_tokens import ActorTokenBundle
from ...thread.state import TeamState
from ..executor import Executor
from ..ipc import WorkerBridge

_CODER_TOKEN = "secret-coder-token"
_REVIEWER_TOKEN = "secret-reviewer-token"
_BEARER = "secret-machine-bearer"


def _make_bridge() -> WorkerBridge:
    """A real WorkerBridge whose HTTP client speaks to an in-process gateway."""
    app = FastAPI()

    @app.post("/internal/events/batch")
    async def _batch(request: Request) -> Response:
        return Response(content='{"status":"ok"}', media_type="application/json")

    @app.post("/internal/heartbeat")
    async def _heartbeat(request: Request) -> Response:
        return Response(content='{"status":"ok"}', media_type="application/json")

    bridge = WorkerBridge(api_url="http://control:8000", worker_id="token-worker")
    bridge._client = httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://control:8000",
    )
    return bridge


def _install_probe_graph(
    executor: Executor,
    thread_id: str,
    observed: dict[str, Any],
) -> None:
    """Compile a real one-node graph that records what the store hands the role."""

    async def coder_node(state: TeamState) -> dict[str, Any]:
        store = executor.token_store
        observed["coder_token"] = store.actor_token(thread_id, "coder")
        observed["unheld_role"] = store.actor_token(thread_id, "no-such-role")
        observed["bearer"] = store.engine_bearer(thread_id)
        observed["held_during_run"] = store.has(thread_id)
        return {"messages": [AIMessage(content="done")], "next": "FINISH"}

    builder = StateGraph(cast("Any", TeamState))
    builder.add_node("coder", coder_node)
    builder.add_edge(START, "coder")
    builder.add_edge("coder", END)
    graph = builder.compile(checkpointer=executor._checkpointer)

    cache_key = ("token-preset", None, False)
    executor._graph_cache[cache_key] = graph
    executor._thread_to_cache_key[thread_id] = cache_key
    executor.aggregator.register_graph(cast("Any", graph))


@pytest.mark.asyncio(loop_scope="function")
async def test_tokens_injected_during_run_and_dropped_after() -> None:
    thread_id = "run-lifecycle"
    observed: dict[str, Any] = {}
    async with AsyncSqliteSaver.from_conn_string(":memory:") as cp:
        await cp.setup()
        bridge = _make_bridge()
        try:
            executor = Executor(checkpointer=cp, bridge=bridge)
            _install_probe_graph(executor, thread_id, observed)

            bundle = ActorTokenBundle(
                tokens={"coder": _CODER_TOKEN, "reviewer": _REVIEWER_TOKEN},
                engine_bearer=_BEARER,
            )
            req = DispatchRequest(
                action="ingest",
                thread_id=thread_id,
                content="build it",
                team_preset="token-preset",
                recursion_limit=10,
                actor_tokens=bundle,
            )
            await executor.handle_dispatch(req)

            # Injection: the owning role received its own token while running.
            assert observed["coder_token"] == _CODER_TOKEN
            assert observed["bearer"] == _BEARER
            assert observed["held_during_run"] is True
            # Isolation: a role the run does not hold reads nothing.
            assert observed["unheld_role"] is None
            # Disposal: the active window closed, so the run holds nothing now.
            assert executor.token_store.has(thread_id) is False
            assert executor.token_store.actor_token(thread_id, "coder") is None
        finally:
            await bridge.close()
            await executor.shutdown()


@pytest.mark.asyncio(loop_scope="function")
async def test_tokens_absent_from_durable_checkpoint() -> None:
    thread_id = "run-checkpoint"
    observed: dict[str, Any] = {}
    async with AsyncSqliteSaver.from_conn_string(":memory:") as cp:
        await cp.setup()
        bridge = _make_bridge()
        try:
            executor = Executor(checkpointer=cp, bridge=bridge)
            _install_probe_graph(executor, thread_id, observed)

            bundle = ActorTokenBundle(
                tokens={"coder": _CODER_TOKEN, "reviewer": _REVIEWER_TOKEN},
                engine_bearer=_BEARER,
            )
            req = DispatchRequest(
                action="ingest",
                thread_id=thread_id,
                content="build it",
                team_preset="token-preset",
                recursion_limit=10,
                actor_tokens=bundle,
            )
            await executor.handle_dispatch(req)

            # The run produced a durable checkpoint; no token may appear in it.
            tuple_ = await cp.aget_tuple({"configurable": {"thread_id": thread_id}})
            assert tuple_ is not None, "the run must have written a checkpoint"
            serialized = json.dumps(str(tuple_))
            for secret in (_CODER_TOKEN, _REVIEWER_TOKEN, _BEARER):
                assert secret not in serialized
        finally:
            await bridge.close()
            await executor.shutdown()


@pytest.mark.asyncio(loop_scope="function")
async def test_tokens_absent_from_logs_during_dispatch(
    caplog: pytest.LogCaptureFixture,
) -> None:
    thread_id = "run-logs"
    observed: dict[str, Any] = {}
    async with AsyncSqliteSaver.from_conn_string(":memory:") as cp:
        await cp.setup()
        bridge = _make_bridge()
        try:
            executor = Executor(checkpointer=cp, bridge=bridge)
            _install_probe_graph(executor, thread_id, observed)

            bundle = ActorTokenBundle(
                tokens={"coder": _CODER_TOKEN, "reviewer": _REVIEWER_TOKEN},
                engine_bearer=_BEARER,
            )
            req = DispatchRequest(
                action="ingest",
                thread_id=thread_id,
                content="build it",
                team_preset="token-preset",
                recursion_limit=10,
                actor_tokens=bundle,
            )
            with caplog.at_level(logging.DEBUG):
                await executor.handle_dispatch(req)

            # Scan every field of every captured record: rendered message, raw
            # args, and structured extras all must be token-free.
            for record in caplog.records:
                blob = " ".join(
                    [
                        record.getMessage(),
                        repr(record.args),
                        repr(dict(record.__dict__)),
                    ]
                )
                for secret in (_CODER_TOKEN, _REVIEWER_TOKEN, _BEARER):
                    assert secret not in blob, f"token leaked in log: {record.name}"
        finally:
            await bridge.close()
            await executor.shutdown()

"""The clarification-respond loop through a real worker, no mocks.

The sibling of ``control/tests/test_verdict_loop_live.py``: that test closes
the engine-verdict half of the cross-process resume loop; this one closes the
a2a-internal clarification half, entirely self-contained
(no live engine dependency).

``test_clarification_endpoint.py`` already proves the real pieces up to the
dispatch boundary: a real ``StateGraph`` built on the real
``create_clarification_node()`` parks a genuine ``interrupt()``, ``GET
/v1/runs/{run_id}`` discloses it authoritatively off the checkpoint, and
``POST .../clarifications/{request_id}/respond`` dispatches a real HTTP POST
to the worker. But that suite's worker is ``api/tests/conftest.py``'s
``_InProcessWorker`` — a stub that records the dispatch body and returns
"dispatched" WITHOUT ever running a real ``Executor`` or resuming a real
graph. This test closes that specific gap: the SAME parked graph is wired
into a real ``Executor``/``worker.app.create_worker_app()``, and the
gateway's ``app.state.worker_client`` is pointed at that real worker instead
of the stub, so ``/respond`` drives a genuine ``Command(resume=answers)``
through the real dispatch/executor path. The assertion is on the graph's OWN
state (``clarification_answers`` actually written by the real node), not a
recorded stub call.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import anyio
import httpx
import pytest
from httpx import ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ...worker.app import create_worker_app
from ...worker.executor import Executor
from .clarification_harness import loopback_callback_bridge, park_clarification
from .conftest import make_app

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from fastapi import FastAPI
    from langchain_core.runnables import RunnableConfig
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    from ...worker.graph_lifecycle import GraphCacheKey

_BUNDLE_FREE_PRESET = "mock-success-single"
_CACHE_KEY: GraphCacheKey = ("clarification-loop-live", None, False)

type SessionFactory = async_sessionmaker[AsyncSession]


@asynccontextmanager
async def _worker_test_lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    """No-op: ``httpx.ASGITransport`` never runs FastAPI's real lifespan
    protocol, so state/task-group wiring is done explicitly by the caller."""
    yield


@pytest.mark.asyncio
async def test_respond_resumes_through_a_real_worker_and_executor(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """POST .../respond drives a real Command(resume=...) through a real worker.

    Reuses the shared real graph/parking harness.  The only substitution is the
    worker behind ``app.state.worker_client`` — a real one instead of the
    recording receiver — so the resumed graph's own state is the proof, not a
    recorded dispatch body.
    """
    app, _agg, _stub_worker, _cp = make_app(session_factory, checkpointer)

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://gateway"
    ) as gateway_client:
        create_resp = await gateway_client.post(
            "/v1/runs",
            json={"team_preset": _BUNDLE_FREE_PRESET, "message": "plan it"},
        )
        assert create_resp.status_code == 201
        thread_id = create_resp.json()["run_id"]

        parked = await park_clarification(checkpointer, thread_id=thread_id)
        request_id = parked.request.request_id

        # Disclosure still works normally (unaffected by the worker swap below).
        status_resp = await gateway_client.get(f"/v1/runs/{thread_id}")
        assert status_resp.status_code == 200
        disclosed = status_resp.json()["pending_clarification"]
        assert disclosed is not None
        assert disclosed["request_id"] == request_id

        # --- swap the recording receiver for a real Executor + real worker app,
        # wired to the SAME parked graph through the public atomic registration
        # seam and a real ephemeral loopback callback server. ---
        async with loopback_callback_bridge() as bridge:
            executor = Executor(checkpointer=checkpointer, bridge=bridge)
            executor.register_compiled_graph(thread_id, _CACHE_KEY, parked.graph)

            worker_app = create_worker_app(lifespan=_worker_test_lifespan)
            worker_app.state.executor = executor

            async with (
                httpx.AsyncClient(
                    transport=ASGITransport(app=worker_app), base_url="http://worker"
                ) as worker_client,
                anyio.create_task_group() as tg,
            ):
                # ASGITransport never runs FastAPI's lifespan protocol, so the
                # dispatch route's fire-and-forget scheduling needs its task
                # group wired explicitly, matching the real worker's lifespan.
                worker_app.state.task_group = tg
                app.state.worker_client = worker_client

                respond_resp = await gateway_client.post(
                    f"/v1/runs/{thread_id}/clarifications/{request_id}/respond",
                    json={"answers": {"provider": "codex"}},
                )
                assert respond_resp.status_code == 200
                body = respond_resp.json()
                assert body["accepted"] is True

                # The dispatch is fire-and-forget inside the worker; poll the
                # REAL graph's own state (not a recorded receiver call) until
                # the real clarification node observes the resume.
                config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
                with anyio.fail_after(15.0):
                    while True:
                        snap = await parked.graph.aget_state(config)
                        if snap.values.get("clarification_answers"):
                            break
                        await anyio.sleep(0.05)

                assert snap.values["clarification_answers"] == {
                    request_id: {"provider": "codex"}
                }
                assert snap.next == (), "the graph did not reach its terminal state"

            await executor.shutdown()


@pytest.mark.asyncio
async def test_reject_short_circuits_before_touching_the_real_worker(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """A rejected respond (missing required answer) never reaches the worker.

    The real worker records nothing to prove a negative against, so this
    reuses the sibling suite's ``worker.dispatches == []`` shape via the
    stub, over the real gateway app and the real parked graph - the fast,
    load-bearing companion to the resume-path proof above: the same route
    that CAN drive a real resume must not do so on a rejected respond.
    """
    app, _agg, worker, _cp = make_app(session_factory, checkpointer)

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://gateway"
    ) as gateway_client:
        create_resp = await gateway_client.post(
            "/v1/runs",
            json={"team_preset": _BUNDLE_FREE_PRESET, "message": "plan it"},
        )
        thread_id = create_resp.json()["run_id"]
        worker.dispatches.clear()

        parked = await park_clarification(checkpointer, thread_id=thread_id)
        request_id = parked.request.request_id

        resp = await gateway_client.post(
            f"/v1/runs/{thread_id}/clarifications/{request_id}/respond",
            json={"answers": {"scope": "graph/nodes/clarification.py"}},
        )

    assert resp.status_code == 422
    assert "provider" in resp.json()["detail"]
    assert worker.dispatches == []

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

import asyncio
import itertools
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, cast

import anyio
import httpx
import pytest
from httpx import ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ...control.action_lease import (
    CONTROL_ACTION_LEASE_TTL,
    claim_control_action,
)
from ...control.circuit_breaker import WorkerCircuitBreaker
from ...control.clarification_service import redrive_clarification_actions
from ...control.worker_management import LazyWorkerSpawner
from ...database import create_thread, get_control_action_by_idempotency_key
from ...thread.clarification import (
    CLARIFICATION_DECLINE_MARKER,
    ClarificationAnswers,
)
from ...thread.enums import ControlActionType, ThreadStatus
from ...worker.app import create_worker_app
from ...worker.executor import Executor
from .clarification_harness import loopback_callback_bridge, park_clarification
from .conftest import async_catalog_run_fields, make_app

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from fastapi import FastAPI
    from langchain_core.messages import BaseMessage
    from langchain_core.runnables import RunnableConfig
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    from ...worker.graph_lifecycle import GraphCacheKey

_BUNDLE_FREE_PRESET = "mock-success-single"
_RUN_SEQ = itertools.count(1)
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
            json={
                "team_preset": _BUNDLE_FREE_PRESET,
                "message": "plan it",
                "run_id": f"clarify-loop-{next(_RUN_SEQ):02d}",
                **await async_catalog_run_fields(gateway_client),
            },
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

                # Race replay reads against the real worker's application
                # receipt.  The lease helper may roll back a losing transaction;
                # every response must remain an ordinary durable replay rather
                # than dereferencing rollback-expired ORM state and returning
                # MissingGreenlet/HTTP 500.
                replay_path = (
                    f"/v1/runs/{thread_id}/clarifications/{request_id}/respond"
                )
                replays = await asyncio.gather(
                    *(
                        gateway_client.post(
                            replay_path,
                            json={"answers": {"provider": "codex"}},
                        )
                        for _ in range(6)
                    )
                )
                assert [response.status_code for response in replays] == [200] * 6

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
                # The answered questionnaire also reaches the transcript - the
                # one state downstream model turns actually read.
                transcript = cast("list[BaseMessage]", snap.values["messages"])
                assert transcript[-1].type == "human"
                assert transcript[-1].content == (
                    "Answers to the clarification questionnaire:\n"
                    "- Which provider should author the plan?: codex"
                )

            await executor.shutdown()


@pytest.mark.asyncio
async def test_new_prompt_resumes_the_parked_graph_as_a_real_human_turn(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """A submitted prompt, unlike the local composer switch, resumes the run.

    The graph is first proven parked from its own checkpoint. The prompt then
    crosses the real gateway, worker app, Executor, ``Command(resume=...)``, and
    clarification gate. The final assertions read the graph's durable state, so
    they cannot pass from a route that merely formats or records a dispatch.
    """
    app, _agg, _recording_worker, _cp = make_app(session_factory, checkpointer)

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://gateway"
    ) as gateway_client:
        create_resp = await gateway_client.post(
            "/v1/runs",
            json={
                "team_preset": _BUNDLE_FREE_PRESET,
                "message": "plan it",
                "run_id": f"clarify-loop-{next(_RUN_SEQ):02d}",
                **await async_catalog_run_fields(gateway_client),
            },
        )
        assert create_resp.status_code == 201
        thread_id = create_resp.json()["run_id"]

        parked = await park_clarification(checkpointer, thread_id=thread_id)
        request_id = parked.request.request_id
        config: RunnableConfig = {"configurable": {"thread_id": thread_id}}

        before = await parked.graph.aget_state(config)
        assert before.next == ("clarification_gate",)
        assert before.values["clarification_request_id"] == request_id
        initial_messages = cast("list[BaseMessage]", before.values["messages"])

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
                worker_app.state.task_group = tg
                app.state.worker_client = worker_client

                prompt = "Use your own judgement and compare both provider paths."
                respond = await gateway_client.post(
                    f"/v1/runs/{thread_id}/clarifications/{request_id}/respond",
                    json={"prompt": prompt},
                )
                assert respond.status_code == 200, respond.text

                with anyio.fail_after(15.0):
                    while True:
                        settled = await parked.graph.aget_state(config)
                        messages = cast("list[BaseMessage]", settled.values["messages"])
                        if settled.next == () and len(messages) > len(initial_messages):
                            break
                        await anyio.sleep(0.05)

                appended = messages[len(initial_messages) :]
                assert len(appended) == 1
                assert appended[0].type == "human"
                assert appended[0].content == prompt
                assert settled.values.get("clarification_request") is None
                assert settled.values.get("clarification_request_id") is None
                recorded_answers = cast(
                    "dict[str, dict[str, str]]",
                    settled.values.get("clarification_answers", {}),
                )
                assert request_id not in recorded_answers

            await executor.shutdown()


@pytest.mark.asyncio
async def test_decline_resumes_the_parked_graph_with_the_fixed_marker(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """A submitted decline resumes the run with no answer given.

    The refusal crosses the real gateway, worker app, Executor,
    ``Command(resume=...)``, and clarification gate. The durable graph state
    proves the outcome: the run reached its terminal state, exactly one fixed
    marker turn was appended, and no answer was fabricated for the declined
    request.
    """
    app, _agg, _recording_worker, _cp = make_app(session_factory, checkpointer)

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://gateway"
    ) as gateway_client:
        create_resp = await gateway_client.post(
            "/v1/runs",
            json={
                "team_preset": _BUNDLE_FREE_PRESET,
                "message": "plan it",
                "run_id": f"clarify-loop-{next(_RUN_SEQ):02d}",
                **await async_catalog_run_fields(gateway_client),
            },
        )
        assert create_resp.status_code == 201
        thread_id = create_resp.json()["run_id"]

        parked = await park_clarification(checkpointer, thread_id=thread_id)
        request_id = parked.request.request_id
        config: RunnableConfig = {"configurable": {"thread_id": thread_id}}

        before = await parked.graph.aget_state(config)
        assert before.next == ("clarification_gate",)
        initial_messages = cast("list[BaseMessage]", before.values["messages"])

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
                worker_app.state.task_group = tg
                app.state.worker_client = worker_client

                respond = await gateway_client.post(
                    f"/v1/runs/{thread_id}/clarifications/{request_id}/respond",
                    json={"decline": True},
                )
                assert respond.status_code == 200, respond.text

                with anyio.fail_after(15.0):
                    while True:
                        settled = await parked.graph.aget_state(config)
                        messages = cast("list[BaseMessage]", settled.values["messages"])
                        if settled.next == () and len(messages) > len(initial_messages):
                            break
                        await anyio.sleep(0.05)

                appended = messages[len(initial_messages) :]
                assert len(appended) == 1
                assert appended[0].type == "human"
                assert appended[0].content == CLARIFICATION_DECLINE_MARKER
                assert settled.values.get("clarification_request") is None
                assert settled.values.get("clarification_request_id") is None
                recorded_answers = cast(
                    "dict[str, dict[str, str]]",
                    settled.values.get("clarification_answers", {}),
                )
                assert request_id not in recorded_answers

            await executor.shutdown()


@pytest.mark.asyncio
async def test_restart_redrives_an_expired_committed_clarification_lease(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """Startup recovery resumes a parked graph after claim-before-dispatch loss.

    The database and checkpointer are both file-backed.  The first process is
    represented by the production lease claim committed with an already-expired
    ownership window, then disappearing before dispatch.  A new recovery pass
    uses the stored typed payload and stable dispatch identity to drive the real
    worker and Executor.  A second pass settles from checkpoint truth without
    dispatching again.
    """
    async with session_factory() as db:
        thread = await create_thread(
            db,
            status=ThreadStatus.RUNNING,
            team_preset=_BUNDLE_FREE_PRESET,
        )
        await db.commit()
        thread_id = thread.id

    parked = await park_clarification(checkpointer, thread_id=thread_id)
    request_id = parked.request.request_id
    resolution = ClarificationAnswers(
        request_id=request_id,
        answers={"provider": "codex"},
    )
    idempotency_key = f"clarification-response:{request_id}"

    async with session_factory() as db:
        lost_claim = await claim_control_action(
            db,
            thread_id=thread_id,
            action_type=ControlActionType.RESUME,
            idempotency_key=idempotency_key,
            request_id=request_id,
            payload=resolution.as_resume_value(),
            worker_generation=thread.repair_generation,
            now=datetime.now(UTC) - CONTROL_ACTION_LEASE_TTL - timedelta(seconds=1),
        )
    assert lost_claim.acquired is True

    async with loopback_callback_bridge() as bridge:
        executor = Executor(checkpointer=checkpointer, bridge=bridge)
        executor.register_compiled_graph(thread_id, _CACHE_KEY, parked.graph)
        worker_app = create_worker_app(lifespan=_worker_test_lifespan)
        worker_app.state.executor = executor
        circuit_breaker = WorkerCircuitBreaker(
            failure_threshold=3,
            recovery_timeout=30.0,
        )
        worker_spawner = LazyWorkerSpawner(
            worker_url="http://worker",
            worker_port=8001,
            auto_spawn=False,
        )
        worker_spawner.replace_process(None)

        async with (
            httpx.AsyncClient(
                transport=ASGITransport(app=worker_app), base_url="http://worker"
            ) as worker_client,
            anyio.create_task_group() as tg,
        ):
            worker_app.state.task_group = tg
            first = await redrive_clarification_actions(
                session_factory,
                checkpointer=checkpointer,
                worker_client=worker_client,
                circuit_breaker=circuit_breaker,
                worker_spawner=worker_spawner,
                recursion_limit=100,
                trace_headers=None,
            )
            assert first.examined == 1
            assert first.dispatched == 1

            config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
            with anyio.fail_after(15.0):
                while True:
                    settled = await parked.graph.aget_state(config)
                    if settled.next == ():
                        break
                    await anyio.sleep(0.05)

            assert settled.values["clarification_answers"] == {
                request_id: {"provider": "codex"}
            }

            second = await redrive_clarification_actions(
                session_factory,
                checkpointer=checkpointer,
                worker_client=worker_client,
                circuit_breaker=circuit_breaker,
                worker_spawner=worker_spawner,
                recursion_limit=100,
                trace_headers=None,
            )
            assert second.examined == 1
            assert second.applied == 1
            assert second.dispatched == 0

        await executor.shutdown()

    async with session_factory() as db:
        action = await get_control_action_by_idempotency_key(
            db,
            thread_id=thread_id,
            idempotency_key=idempotency_key,
        )
    assert action is not None
    assert action.dispatch_id == lost_claim.dispatch_id
    assert action.applied_at is not None

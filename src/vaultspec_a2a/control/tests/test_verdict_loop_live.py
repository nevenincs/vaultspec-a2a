"""The full cross-process verdict loop, stitched into one live test.

``test_verdict_subscriber_live.py`` proves engine verdict -> subscriber
correlation, but dispatches its resume against an UNREACHABLE worker by
design - its own docstring names the remaining gap explicitly: "the
worker-side landing of the resumed graph belongs to the phase-gate topology
and the service harness, not this subscriber unit." No test in this repo
closes that gap in one process: nothing drives a dispatch through the
REAL worker's bearer-checked ``/dispatch`` HTTP route into a REAL
``Executor`` running a REAL, checkpointed LangGraph and observes the graph
actually resume past its interrupt.

This test closes it. No mocks in the loop under test:

* the engine is live (the same ``live_engine``/``client`` fixtures and
  ``_submit_proposal``/``_decide`` helpers already proven in
  ``test_verdict_subscriber_live.py``, imported rather than duplicated);
* the ``VerdictSubscriber`` is real (unmodified production class);
* the worker is a real ``worker.app.create_worker_app()`` FastAPI app served
  over ``httpx.ASGITransport`` - its actual bearer check, its actual
  background-task dispatch scheduling (``TaskGroup.start_soon``), not a
  hand-rolled stand-in;
* the ``Executor`` is real, backed by a real ``AsyncSqliteSaver``;
* the resumed graph is real and checkpointed. Its SHAPE is a minimal,
  purpose-built two-decision graph (seed -> the production
  ``create_phase_gate_node`` -> finish) rather than the full research_adr
  topology, so the proof is self-contained and fast; the full-topology proof
  under the same live engine remains ``service_tests/test_pw7_acceptance.py``'s
  job when its three-process runbook stack is booted. Reusing the production
  gate node (not a hand-rolled interrupt) keeps the interrupt/resume wire
  shape - ``{"type": "document_approval_request", ...}`` /
  ``{"verdict", "notes"}`` - identical to what a real phase gate emits.

Service-marked; skips when no reachable engine is configured, exactly like
its sibling.
"""

from __future__ import annotations

import pathlib
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

import anyio
import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI, Request
from fastapi.responses import Response
from httpx import ASGITransport
from langchain_core.messages import AIMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ...api.tests.clarification_harness import new_state_graph
from ...authoring import (
    AuthoringClient,
    AuthoringResponse,
    AuthoringSession,
    EngineEndpoint,
    LifecycleEvent,
    mint_actor_token,
)
from ...conftest import materialize_schema
from ...database import (
    create_thread,
    get_permission_request,
    get_thread,
    record_permission_request,
    update_thread_status,
)
from ...graph.nodes.phase_gate import create_phase_gate_node
from ...ipc.schemas import DispatchRequest
from ...thread.actor_tokens import ActorTokenBundle
from ...thread.enums import PermissionRequestStatus, ThreadStatus
from ...worker.app import create_worker_app
from ...worker.executor import Executor
from ...worker.ipc import WorkerBridge
from ..circuit_breaker import WorkerCircuitBreaker
from ..verdict_subscriber import VerdictSubscriber
from ..worker_management import LazyWorkerSpawner
from .test_verdict_subscriber_live import _decide, _submit_proposal

if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig

    from ...thread.state import TeamState
    from ...worker.graph_lifecycle import RegisteredCompiledGraph

_CACHE_KEY = ("verdict-loop-live", None, False)

# Every dispatch names an active project, as a real one does. This package's own
# directory is real, absolute, and present on either platform.
_WORKSPACE = str(pathlib.Path(__file__).resolve().parent)


@pytest_asyncio.fixture
async def client(live_engine: EngineEndpoint):
    """Same fixture shape as ``test_verdict_subscriber_live.py``'s - pytest
    fixtures are module-local, so this is duplicated rather than shared."""
    async with AuthoringClient(
        live_engine.base_url, live_engine.bearer_token
    ) as authoring_client:
        yield authoring_client


def _bridge_stub() -> WorkerBridge:
    """A real ASGI-backed bridge whose gateway target just accepts callbacks.

    What is under test is engine -> subscriber -> worker -> graph, not the
    worker -> gateway event relay (already proven in ``worker/tests/test_executor.py``'s
    settle-ordering suite), so the callback target only needs to be real and
    accept the calls, not assert on them.
    """
    app = FastAPI()

    @app.post("/internal/events/batch")
    async def _batch(request: Request) -> Response:
        return Response(content='{"status":"ok"}', media_type="application/json")

    @app.post("/internal/heartbeat")
    async def _heartbeat(request: Request) -> Response:
        return Response(content='{"status":"ok"}', media_type="application/json")

    bridge = WorkerBridge(
        api_url="http://control:8000", worker_id="verdict-loop-worker"
    )
    bridge._client = httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://control:8000"
    )
    return bridge


def _install_verdict_loop_graph(
    executor: Executor, thread_id: str, proposal_id: str
) -> RegisteredCompiledGraph:
    """Compile+cache a real, minimal seed -> phase-gate -> finish graph.

    ``seed`` commits ``gate_pending_proposal_id`` (the REAL proposal id
    already submitted+decided against the live engine by the caller) so the
    production gate node has something to correlate; the gate node is the
    unmodified ``create_phase_gate_node``, so the interrupt/resume wire shape
    is the real one. ``finish`` stamps the resumed verdict into a message so
    the test can observe genuine post-resume progress.
    """

    async def seed_node(state: TeamState) -> dict[str, Any]:
        return {
            "gate_pending_proposal_id": proposal_id,
            "authoring_proposal_ids": [proposal_id],
        }

    gate_node = create_phase_gate_node(
        "verdict-loop-test", approved_target="finish", revision_target="finish"
    )

    async def finish_node(state: TeamState) -> dict[str, Any]:
        return {
            "messages": [AIMessage(content=f"resumed:{state.get('gate_verdict')}")],
        }

    builder = new_state_graph()
    builder.add_node("seed", seed_node)
    builder.add_node("gate", gate_node)
    builder.add_node("finish", finish_node)
    builder.add_edge("__start__", "seed")
    builder.add_edge("seed", "gate")
    builder.add_edge("finish", "__end__")
    graph: RegisteredCompiledGraph = builder.compile(
        checkpointer=executor._checkpointer
    )

    executor.register_compiled_graph(thread_id, _CACHE_KEY, graph)
    return graph


@asynccontextmanager
async def _worker_test_lifespan(app: FastAPI):
    """No-op lifespan: ``httpx.ASGITransport`` never runs FastAPI's real
    lifespan protocol, so production wiring (state, task group) is done
    explicitly by the caller before any request is sent. This exists only so
    ``create_worker_app`` does not fall back to the production ``_lifespan``
    (which needs real registration/telemetry infra this test has no use for).
    """
    yield


@pytest.mark.service
@pytest.mark.asyncio
async def test_live_engine_verdict_resumes_a_real_graph_through_the_real_worker(
    client: AuthoringClient, tmp_path: Any
) -> None:
    """Engine verdict -> subscriber -> real worker HTTP -> real graph resume.

    One proposal, submitted and approved for real against the live engine.
    The subscriber correlates the real decision event and dispatches
    ``Command(resume=...)`` over a REAL bearer-checked HTTP POST to a REAL
    worker app, whose REAL Executor resumes a REAL checkpointed graph past
    its interrupt. The test asserts the graph's own state (not a recording
    stub) shows the resume landed, and that the durable gate row + thread
    status resolved the same way the engine-side reconcile tests already
    proved for a stubbed worker.
    """
    run_id = f"vl-{uuid.uuid4().hex[:8]}"
    minted = await mint_actor_token(client, actor_id=f"agent:{run_id}", kind="agent")
    assert isinstance(minted, AuthoringResponse)
    client._actor_token = minted.data["raw_token"]

    baseline_snapshot = await client.recovery_snapshot(last_seq=0)
    assert isinstance(baseline_snapshot.data, dict)
    baseline = baseline_snapshot.data["latest_outbox_seq"]

    session = AuthoringSession(client, run_id)
    await session.create_session(scope="repo", title=run_id)
    reviewer = await mint_actor_token(client, actor_id=f"human:{run_id}", kind="human")
    assert isinstance(reviewer, AuthoringResponse)
    reviewer_token = reviewer.data["raw_token"]

    info = await _submit_proposal(session, run_id, "vl")
    await _decide(client, reviewer_token, info, "approve", "ship it", run_id, "vl")

    # --- a2a side: real DB, real checkpointer, real worker, real graph ---
    db_file = tmp_path / "vl.db"
    materialize_schema(Path(db_file))
    db_engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    session_factory = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )
    checkpoints = tmp_path / "vl-cp.db"
    thread_id = f"thread-{run_id}"

    async with AsyncSqliteSaver.from_conn_string(str(checkpoints)) as checkpointer:
        await checkpointer.setup()
        bridge = _bridge_stub()
        executor = Executor(checkpointer=checkpointer, bridge=bridge)
        graph = _install_verdict_loop_graph(executor, thread_id, info["proposal_id"])

        worker_app = create_worker_app(lifespan=_worker_test_lifespan)
        worker_app.state.executor = executor

        async with (
            httpx.AsyncClient(
                transport=ASGITransport(app=worker_app),
                base_url="http://worker",
            ) as worker_client,
            anyio.create_task_group() as tg,
        ):
            # ASGITransport never runs FastAPI's lifespan protocol, so the
            # production dispatch route's ``app.state.task_group`` (which its
            # ``TaskGroup.start_soon`` fire-and-forget scheduling depends on)
            # is wired explicitly, matching what the real ``_lifespan`` does.
            worker_app.state.task_group = tg

            # --- real ingest through the real worker HTTP route ---
            ingest = DispatchRequest(
                action="ingest",
                workspace_root=_WORKSPACE,
                thread_id=thread_id,
                content="drive to the gate",
                team_preset="verdict-loop-live",
                recursion_limit=10,
                actor_tokens=ActorTokenBundle(
                    tokens={"vaultspec-synthesist": "vl-token"},
                    engine_bearer="vl-bearer",
                ),
            )
            resp = await worker_client.post(
                "/dispatch", json=ingest.model_dump(mode="json")
            )
            assert resp.status_code == 200, resp.text

            # Fire-and-forget: poll the REAL graph's own state (not a
            # recording stub) until the seed node has landed and the run is
            # parked at the interrupt.
            config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
            with anyio.fail_after(15.0):
                while True:
                    snap = await graph.aget_state(config)
                    if snap.values.get("gate_pending_proposal_id") == info[
                        "proposal_id"
                    ] and snap.next == ("gate",):
                        break
                    await anyio.sleep(0.05)

            # Seed the durable gate row the subscriber correlates against -
            # the same shape the engine-side reconcile tests seed, now
            # AFTER a genuine interrupt (not a hand-typed checkpoint).
            async with session_factory() as db:
                await create_thread(
                    db, thread_id=thread_id, team_preset="verdict-loop-live"
                )
                await update_thread_status(db, thread_id, ThreadStatus.INPUT_REQUIRED)
                await record_permission_request(
                    db,
                    request_id=f"{thread_id}:verdict-loop-gate",
                    thread_id=thread_id,
                    pause_reason_type="document_approval_request",
                    description="Approve the test document",
                    allowed_options=[
                        {
                            "option_id": "approve",
                            "name": "Approve",
                            "kind": "allow_once",
                        }
                    ],
                )
                await db.commit()

            subscriber = VerdictSubscriber(
                session_factory=session_factory,
                checkpointer=checkpointer,
                worker_client=worker_client,
                circuit_breaker=WorkerCircuitBreaker(
                    failure_threshold=3, recovery_timeout=30.0
                ),
                worker_spawner=LazyWorkerSpawner(
                    worker_url="http://worker", worker_port=1, auto_spawn=False
                ),
                endpoint_provider=lambda: None,
                recursion_limit=10,
            )

            frames = [f async for f in client.stream_lifecycle(last_seq=baseline)]
            lifecycle = [f for f in frames if isinstance(f, LifecycleEvent)]
            decided = [
                f
                for f in lifecycle
                if info["proposal_id"] in f.correlation_ids()
                and f.event_kind == "approval.resolved"
            ]
            assert decided, (
                f"no approval.resolved frame correlates to {info['proposal_id']}"
            )

            # The real end-to-end dispatch: subscriber -> real worker HTTP
            # -> real Executor -> real graph resume.
            await subscriber._process_event(decided[0])

            # The dispatch is fire-and-forget inside the worker; poll the
            # REAL graph's own state until it reaches its terminal END.
            with anyio.fail_after(15.0):
                while True:
                    snap = await graph.aget_state(config)
                    if snap.next == ():
                        break
                    await anyio.sleep(0.05)

            assert snap.values["gate_verdict"] == "approved"
            messages = snap.values["messages"]
            assert isinstance(messages, list)
            assert any(
                getattr(m, "content", "") == "resumed:approved" for m in messages
            ), "the finish node never observed the real resume"

            # The durable gate row resolved and the thread left
            # INPUT_REQUIRED — the same observable proof the engine-side
            # reconcile tests assert against a stubbed worker.
            async with session_factory() as db:
                gate_row = await get_permission_request(
                    db, f"{thread_id}:verdict-loop-gate"
                )
                assert gate_row is not None
                assert gate_row.request_status == PermissionRequestStatus.APPLIED.value
                thread = await get_thread(db, thread_id)
                assert thread is not None
                assert thread.status != ThreadStatus.INPUT_REQUIRED.value

    await db_engine.dispose()

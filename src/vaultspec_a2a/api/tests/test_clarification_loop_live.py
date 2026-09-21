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
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, cast

import anyio
import httpx
import pytest
from httpx import ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ...control.accepted_input import freeze_accepted_input
from ...control.action_lease import (
    CONTROL_ACTION_LEASE_TTL,
    ControlActionClaim,
    ControlActionClaimRequest,
    finalize_control_action_acceptance,
    prepare_control_action_claim,
)
from ...control.circuit_breaker import WorkerCircuitBreaker
from ...control.clarification_service import (
    ClarificationRecoverySummary,
    ClarificationRuntime,
    redrive_clarification_actions,
)
from ...control.dispatch_receipts import prepare_graph_action_receipt
from ...control.execution_authority import resolve_execution_authority
from ...control.graph_definition import read_accepted_graph_definition
from ...control.tests._catalog_authority import current_execution_metadata
from ...control.worker_management import LazyWorkerSpawner
from ...database import (
    create_control_action,
    create_thread,
    get_control_action_by_idempotency_key,
    get_thread_metadata,
    thread_write_expectation,
)
from ...ipc.schemas import DispatchRequest
from ...team.team_config import load_team_config
from ...tests._write_authority import make_test_write_authority
from ...thread.clarification import (
    CLARIFICATION_DECLINE_MARKER,
    ClarificationAnswers,
)
from ...thread.enums import ControlActionType, ThreadStatus
from ...thread.executable_graph import freeze_graph_definition
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

    from ...database.models import ThreadModel
    from ...worker.graph_lifecycle import (
        GraphCacheKey,
        GraphStateSnapshot,
        RegisteredCompiledGraph,
    )
    from .clarification_harness import ParkedClarification

_BUNDLE_FREE_PRESET = "mock-success-single"
_RUN_SEQ = itertools.count(1)

type SessionFactory = async_sessionmaker[AsyncSession]


async def _cache_key_for_thread(
    session_factory: SessionFactory, thread_id: str
) -> GraphCacheKey:
    """Bind the registered real graph to the run's exact durable authority."""
    async with session_factory() as db:
        metadata_json = await get_thread_metadata(db, thread_id)
        graph_definition = await read_accepted_graph_definition(db, thread_id)
    authority = resolve_execution_authority(metadata_json)
    return (
        _BUNDLE_FREE_PRESET,
        None,
        False,
        authority.model_assignment_digest,
        graph_definition.digest(),
    )


@asynccontextmanager
async def _worker_test_lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    """No-op: ``httpx.ASGITransport`` never runs FastAPI's real lifespan
    protocol, so state/task-group wiring is done explicitly by the caller."""
    yield


async def _wait_for_answered_clarification(
    graph: RegisteredCompiledGraph, config: RunnableConfig
) -> GraphStateSnapshot:
    """Wait until the real graph records answers for the parked request."""
    with anyio.fail_after(15.0):
        while True:
            snap = await graph.aget_state(config)
            if snap.values.get("clarification_answers"):
                return snap
            await anyio.sleep(0.05)


async def _wait_for_terminal_graph(
    graph: RegisteredCompiledGraph,
    config: RunnableConfig,
    initial_messages: list[BaseMessage],
) -> tuple[GraphStateSnapshot, list[BaseMessage]]:
    """Wait for terminal graph state and return its durable transcript."""
    with anyio.fail_after(15.0):
        while True:
            settled = await graph.aget_state(config)
            messages = cast("list[BaseMessage]", settled.values["messages"])
            if settled.next == () and len(messages) > len(initial_messages):
                return settled, messages
            await anyio.sleep(0.05)


@dataclass(frozen=True, slots=True)
class _ParkedRun:
    """Gateway and checkpoint values for one parked clarification graph."""

    thread_id: str
    cache_key: GraphCacheKey
    parked: ParkedClarification
    config: RunnableConfig


@dataclass(frozen=True, slots=True)
class _ExpiredClaim:
    """An accepted clarification resume whose lease has already expired."""

    request_id: str
    idempotency_key: str
    claim: ControlActionClaim


@dataclass(frozen=True, slots=True)
class _RecoveryOutcome:
    """The two recovery summaries and settled graph snapshot."""

    first: ClarificationRecoverySummary
    settled: GraphStateSnapshot
    second: ClarificationRecoverySummary


async def _create_parked_run(
    gateway_client: httpx.AsyncClient,
    session_factory: SessionFactory,
    checkpointer: AsyncSqliteSaver,
) -> _ParkedRun:
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
    cache_key = await _cache_key_for_thread(session_factory, thread_id)
    parked = await park_clarification(
        checkpointer,
        thread_id=thread_id,
        model_assignment_digest=cache_key[3],
        graph_definition_digest=cache_key[4],
    )
    return _ParkedRun(
        thread_id=thread_id,
        cache_key=cache_key,
        parked=parked,
        config={"configurable": {"thread_id": thread_id}},
    )


async def _load_parked_run(
    session_factory: SessionFactory,
    checkpointer: AsyncSqliteSaver,
    thread_id: str,
) -> _ParkedRun:
    cache_key = await _cache_key_for_thread(session_factory, thread_id)
    parked = await park_clarification(checkpointer, thread_id=thread_id)
    return _ParkedRun(
        thread_id=thread_id,
        cache_key=cache_key,
        parked=parked,
        config={"configurable": {"thread_id": thread_id}},
    )


async def _initial_messages(run: _ParkedRun) -> list[BaseMessage]:
    before = await run.parked.graph.aget_state(run.config)
    assert before.next == ("clarification_gate",)
    assert before.values["clarification_request_id"] == run.parked.request.request_id
    return cast("list[BaseMessage]", before.values["messages"])


@asynccontextmanager
async def _real_worker(
    app: FastAPI | None,
    run: _ParkedRun,
    checkpointer: AsyncSqliteSaver,
) -> AsyncGenerator[httpx.AsyncClient]:
    """Attach a real worker client and shut its executor down on every exit."""
    async with loopback_callback_bridge() as bridge:
        executor = Executor(checkpointer=checkpointer, bridge=bridge)
        executor.register_compiled_graph(run.thread_id, run.cache_key, run.parked.graph)
        worker_app = create_worker_app(lifespan=_worker_test_lifespan)
        worker_app.state.executor = executor
        try:
            async with (
                httpx.AsyncClient(
                    transport=ASGITransport(app=worker_app), base_url="http://worker"
                ) as worker_client,
                anyio.create_task_group() as tg,
            ):
                worker_app.state.task_group = tg
                if app is not None:
                    app.state.worker_client = worker_client
                yield worker_client
        finally:
            await executor.shutdown()


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
        run = await _create_parked_run(gateway_client, session_factory, checkpointer)
        request_id = run.parked.request.request_id

        # Disclosure still works normally (unaffected by the worker swap below).
        status_resp = await gateway_client.get(f"/v1/runs/{run.thread_id}")
        assert status_resp.status_code == 200
        disclosed = status_resp.json()["pending_clarification"]
        assert disclosed is not None
        assert disclosed["request_id"] == request_id

        # --- swap the recording receiver for a real Executor + real worker app,
        # wired to the SAME parked graph through the public atomic registration
        # seam and a real ephemeral loopback callback server. ---
        async with _real_worker(app, run, checkpointer):
            respond_resp = await gateway_client.post(
                f"/v1/runs/{run.thread_id}/clarifications/{request_id}/respond",
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
                f"/v1/runs/{run.thread_id}/clarifications/{request_id}/respond"
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
            assert [response.status_code for response in replays] == [200] * 6, [
                response.text for response in replays
            ]

            # The dispatch is fire-and-forget inside the worker; poll the
            # REAL graph's own state (not a recorded receiver call) until
            # the real clarification node observes the resume.
            snap = await _wait_for_answered_clarification(run.parked.graph, run.config)

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
        run = await _create_parked_run(gateway_client, session_factory, checkpointer)
        request_id = run.parked.request.request_id
        initial_messages = await _initial_messages(run)

        async with _real_worker(app, run, checkpointer):
            prompt = "Use your own judgement and compare both provider paths."
            respond = await gateway_client.post(
                f"/v1/runs/{run.thread_id}/clarifications/{request_id}/respond",
                json={"prompt": prompt},
            )
            assert respond.status_code == 200, respond.text

            settled, messages = await _wait_for_terminal_graph(
                run.parked.graph,
                run.config,
                initial_messages,
            )

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
        run = await _create_parked_run(gateway_client, session_factory, checkpointer)
        request_id = run.parked.request.request_id
        initial_messages = await _initial_messages(run)

        async with _real_worker(app, run, checkpointer):
            respond = await gateway_client.post(
                f"/v1/runs/{run.thread_id}/clarifications/{request_id}/respond",
                json={"decline": True},
            )
            assert respond.status_code == 200, respond.text

            settled, messages = await _wait_for_terminal_graph(
                run.parked.graph,
                run.config,
                initial_messages,
            )

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


async def _seed_clarification_run(
    session_factory: SessionFactory,
) -> tuple[ThreadModel, str]:
    async with session_factory() as db:
        authority = make_test_write_authority()
        metadata = current_execution_metadata(Path.cwd())
        thread = await create_thread(
            db,
            write_authority=authority,
            status=ThreadStatus.RUNNING,
            team_preset=_BUNDLE_FREE_PRESET,
            metadata=metadata,
        )
        dispatch = DispatchRequest(
            action="ingest",
            thread_id=thread.id,
            content="initial clarification run",
            workspace_root=str(Path.cwd()),
            recursion_limit=25,
            team_preset=_BUNDLE_FREE_PRESET,
            graph_definition=freeze_graph_definition(
                load_team_config(_BUNDLE_FREE_PRESET, workspace_root=Path.cwd()),
                workspace_root=Path.cwd(),
            ),
            model_assignment=resolve_execution_authority(metadata).model_assignment,
        )
        await create_control_action(
            db,
            thread_id=thread.id,
            action_type=authority.action_type,
            idempotency_key=f"thread-create:{thread.id}",
            dispatch_id=authority.action_receipt_id,
            recovery_deadline_at=datetime.now(UTC) + timedelta(minutes=5),
            payload=freeze_accepted_input(
                dispatch, intent={"content": "initial clarification run"}
            ),
        )
        assert (
            await prepare_graph_action_receipt(
                db, thread_id=thread.id, dispatch_id=authority.action_receipt_id
            )
            is not None
        )
        await db.commit()
        return thread, metadata


async def _prepare_expired_claim(
    session_factory: SessionFactory,
    thread: ThreadModel,
    metadata: str,
    run: _ParkedRun,
) -> _ExpiredClaim:
    request_id = run.parked.request.request_id
    resolution = ClarificationAnswers(
        request_id=request_id,
        answers={"provider": "codex"},
    )
    idempotency_key = f"clarification-response:{request_id}"
    async with session_factory() as db:
        definition = await read_accepted_graph_definition(db, run.thread_id)
        resume = DispatchRequest(
            action="resume",
            thread_id=run.thread_id,
            option_id=resolution.as_resume_value(),
            workspace_root=str(Path.cwd()),
            recursion_limit=100,
            team_preset=_BUNDLE_FREE_PRESET,
            graph_definition=definition,
            model_assignment=resolve_execution_authority(metadata).model_assignment,
        )
        claim = await prepare_control_action_claim(
            db,
            request=ControlActionClaimRequest(
                thread_id=run.thread_id,
                action_type=ControlActionType.RESUME,
                idempotency_key=idempotency_key,
                request_id=request_id,
                payload=freeze_accepted_input(
                    resume, intent=resolution.as_resume_value()
                ),
                dispatch_id=idempotency_key,
                write_expectation=thread_write_expectation(thread),
                worker_generation=thread.repair_generation,
                now=datetime.now(UTC) - CONTROL_ACTION_LEASE_TTL - timedelta(seconds=1),
                recovery_timeout_seconds=300,
            ),
        )
        assert claim.acquired is True
        await finalize_control_action_acceptance(db, claim)
        await db.commit()
    assert claim.acquired is True
    return _ExpiredClaim(
        request_id=request_id,
        idempotency_key=idempotency_key,
        claim=claim,
    )


async def _wait_for_terminal_state(
    graph: RegisteredCompiledGraph, config: RunnableConfig
) -> GraphStateSnapshot:
    """Wait until a recovery resume reaches the graph's terminal state."""
    with anyio.fail_after(15.0):
        while True:
            settled = await graph.aget_state(config)
            if settled.next == ():
                return settled
            await anyio.sleep(0.05)


async def _redrive_expired_claim(
    session_factory: SessionFactory,
    checkpointer: AsyncSqliteSaver,
    run: _ParkedRun,
    claim: _ExpiredClaim,
) -> _RecoveryOutcome:
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
    async with _real_worker(None, run, checkpointer) as worker_client:
        runtime = ClarificationRuntime(
            checkpointer,
            worker_client,
            circuit_breaker,
            worker_spawner,
            100,
            None,
        )
        first = await redrive_clarification_actions(
            session_factory,
            runtime=runtime,
        )
        settled = await _wait_for_terminal_state(run.parked.graph, run.config)
        second = await redrive_clarification_actions(
            session_factory,
            runtime=runtime,
        )
    return _RecoveryOutcome(first=first, settled=settled, second=second)


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
    thread, metadata = await _seed_clarification_run(session_factory)
    run = await _load_parked_run(session_factory, checkpointer, thread.id)
    # This current-schema run predates checkpoint evidence. The production
    # resume command must bind the exact durable digest atomically with the
    # interrupt response, without an update_state call that invalidates it.
    claim = await _prepare_expired_claim(session_factory, thread, metadata, run)
    outcome = await _redrive_expired_claim(
        session_factory,
        checkpointer,
        run,
        claim,
    )
    assert outcome.first.examined == 1
    assert outcome.first.dispatched == 1
    assert outcome.settled.values["clarification_answers"] == {
        claim.request_id: {"provider": "codex"}
    }
    assert outcome.settled.values["model_assignment_digest"] == run.cache_key[3]
    assert outcome.second.examined == 1
    assert outcome.second.applied == 1
    assert outcome.second.dispatched == 0

    async with session_factory() as db:
        action = await get_control_action_by_idempotency_key(
            db,
            thread_id=run.thread_id,
            idempotency_key=claim.idempotency_key,
        )
    assert action is not None
    assert action.dispatch_id == claim.claim.dispatch_id
    assert action.applied_at is not None

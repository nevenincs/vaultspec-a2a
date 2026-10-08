"""A run that asks one tool permission again must be answerable again.

A worker that parks again under a request id the run has already answered is
asking the SAME question a second time: the request id is derived from the call
and its namespace, so the same call asked again names the same request. The
journal keyed every answer to a request under one identity, so a second answer
replayed the first instead of resuming the run, and the request row stayed
settled while the run was parked on it again.

The exercise here is the real thing end to end: a real graph that re-asks
through the worker's own permission callback, a real checkpointer, the real
respond verb, a real served worker applying each resume, and the real relay
handling the worker's own frames. The frames are relayed in BOTH orders,
because the application receipt and the re-ask's park frame can reach the relay
in one batch and the request must end up answerable either way.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any, cast

import anyio
import pytest
from fastapi import FastAPI, Request
from langgraph.graph import END, START

from ...control._permission_response_contract import PermissionInput
from ...control.accepted_input import read_accepted_input, restore_accepted_dispatch
from ...control.circuit_breaker import WorkerCircuitBreaker
from ...control.dispatch_receipts import bind_graph_action_receipt
from ...control.event_handlers import RelayServices, relay_event
from ...control.leased_dispatch import DispatchTransport
from ...control.permission_service import respond_to_permission
from ...database import (
    decode_allowed_options,
    get_control_action_by_idempotency_key,
    get_permission_request,
)
from ...graph.acp_options import valid_option_ids
from ...graph.nodes._worker_permissions import (
    permission_callback_for,
    recorded_permission_answers,
)
from ...testing import (
    add_test_node,
    adopted_spawner,
    compile_test_graph,
    new_state_graph,
    seed_accepted_thread,
    serve_on_loopback,
    served_worker,
    supervised_graph_cache_key,
)
from ...thread.enums import PermissionRequestStatus, ThreadStatus
from ...thread.idempotency import (
    permission_response_action_key,
    thread_create_action_key,
)
from ...thread.snapshots import project_checkpoint_tuple
from ...thread.state import TeamState
from ...worker.ipc import WorkerBridge

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Mapping
    from pathlib import Path

    import httpx
    from langchain_core.runnables import RunnableConfig
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from ...control.action_lease import ControlActionOutcome
    from ...providers import JsonObject
    from ...testing import ServedWorker

_TOOL = "bash"
_TOOL_INPUT: dict[str, Any] = {"command": "ls"}

#: What the provider offers for the call on each successive ask. It narrows its
#: offer every time the answer it is given cannot be used, which a real one does
#: when the scope it may ask for changes between retries of one tool call. The
#: offers share no option id, so the recorded answer to one ask is never an
#: option of the next and the callback puts the call to a human again.
_OFFERS: tuple[list[dict[str, Any]], ...] = (
    [
        {"optionId": "allow_broad", "name": "Allow anywhere", "kind": "allow_once"},
        {"optionId": "deny_broad", "name": "Deny", "kind": "reject_once"},
    ],
    [
        {"optionId": "allow_project", "name": "Allow in project", "kind": "allow_once"},
        {"optionId": "deny_project", "name": "Deny", "kind": "reject_once"},
    ],
    [
        {"optionId": "allow_here", "name": "Allow here only", "kind": "allow_once"},
        {"optionId": "deny_here", "name": "Deny", "kind": "reject_once"},
    ],
)
#: The approval a human gives on each ask: the approving option of that offer.
_ANSWERS: tuple[str, ...] = ("allow_broad", "allow_project", "allow_here")


def _offer(answers: Mapping[str, str]) -> list[dict[str, Any]]:
    """The offer the provider makes for the call, given what the turn holds.

    Keyed on the answer the turn has recorded rather than on a counter, so the
    offer is a function of the run's own durable state and the chain replays the
    same way however many times the turn is replayed.
    """
    recorded = next(iter(answers.values()), None)
    asked = _ANSWERS.index(recorded) + 1 if recorded in _ANSWERS else 0
    return _OFFERS[min(asked, len(_OFFERS) - 1)]


def _reasking_graph(checkpointer: AsyncSqliteSaver) -> Any:
    """Compile a graph that puts one tool call to a human three times.

    Every decision is the worker's own: the call goes through the shipped
    permission callback, which names the request from the call and its namespace
    - so all three asks name ONE request - and parks the run whenever the
    answers it holds cannot settle the call. The callback finds each recorded
    answer naming an option the next ask does not offer, refuses to force it
    through, and parks again. The final offer carries the last answer, so the
    third answer resolves the call and the run goes on.
    """

    async def ask(state: TeamState) -> dict[str, Any]:
        answers = recorded_permission_answers(state)
        option_id = await permission_callback_for(answers)(
            _TOOL, _TOOL_INPUT, _offer(answers)
        )
        return {"artifacts": [{"id": "answered", "path": option_id}]}

    builder = new_state_graph()
    add_test_node(builder, "ask", ask)
    builder.add_edge(START, "ask")
    builder.add_edge("ask", END)
    return compile_test_graph(builder, checkpointer=checkpointer)


async def _held_request_ids(
    checkpointer: AsyncSqliteSaver, config: RunnableConfig, thread_id: str
) -> list[str]:
    """The request ids the run's stored checkpoint is holding right now."""
    stored = await checkpointer.aget_tuple(config)
    assert stored is not None, "the graph wrote no checkpoint"
    projection = project_checkpoint_tuple(stored, thread_id=thread_id)
    return [held.interrupt_id for held in projection.pending_interrupts]


@contextlib.asynccontextmanager
async def _capturing_bridge() -> AsyncGenerator[tuple[WorkerBridge, list[JsonObject]]]:
    """A real worker bridge whose batches reach a real loopback listener.

    The worker posts its own event batches over loopback exactly as it does to a
    gateway, and the listener keeps every frame instead of relaying it: this
    exercise feeds the frames to the production relay itself, in the order it
    chooses, to stand in for the interleaving a batch can arrive in.
    """
    captured: list[JsonObject] = []
    app = FastAPI()

    async def accept(request: Request) -> dict[str, str]:
        body = cast("JsonObject", await request.json())
        events = body.get("events")
        if isinstance(events, list):
            captured.extend(
                cast("JsonObject", cast("JsonObject", entry)["payload"])
                for entry in cast("list[object]", events)
            )
        return {"status": "ok"}

    for path in ("/internal/events/batch", "/internal/heartbeat"):
        app.add_api_route(path, accept, methods=["POST"])
    async with serve_on_loopback(app) as base_url:
        bridge = WorkerBridge(base_url, "reask-capture")
        try:
            yield bridge, captured
        finally:
            await bridge.close()


async def _deliver_accepted_ingest(
    session_factory: async_sessionmaker[AsyncSession],
    worker_client: httpx.AsyncClient,
    thread_id: str,
) -> None:
    """Hand the run's own accepted ingest to the worker, as a redispatch does.

    Rebuilt from the journal through the production restore and receipt binding,
    so the worker runs the program this run was accepted under and the park it
    reaches is its own.
    """
    async with session_factory() as db:
        action = await get_control_action_by_idempotency_key(
            db,
            thread_id=thread_id,
            idempotency_key=thread_create_action_key(thread_id),
        )
        assert action is not None
        assert action.dispatch_id is not None
        dispatch = restore_accepted_dispatch(
            read_accepted_input(action), dispatch_id=action.dispatch_id
        )
        bound = await bind_graph_action_receipt(db, dispatch)
    assert bound.graph_action_receipt is not None
    delivered = await worker_client.post(
        "/dispatch", json=bound.model_dump(mode="json")
    )
    assert delivered.is_success, delivered.text


async def _relay_captured_frames(
    worker: ServedWorker,
    captured: list[JsonObject],
    services: RelayServices,
    *,
    thread_id: str,
    reversed_order: bool,
) -> None:
    """Relay every frame one finished dispatch produced, in the chosen order.

    The dispatch is finished when the worker holds no active ingest, which is
    also when it is ready to take the next one. Its frames are then handed to
    the production relay as the worker produced them, optionally back to front:
    an application receipt and the park frame of the question asked next can
    reach a relay in one batch either way round, and the journal has to reach
    the same state for both.
    """
    with anyio.fail_after(30.0):
        while worker.executor.active_ingest_count or not captured:
            await anyio.sleep(0.02)
        await worker.bridge.flush_events()
        while not any(
            frame.get("type") in {"dispatch_applied", "permission_request"}
            for frame in captured
        ):
            await worker.bridge.flush_events()
            await anyio.sleep(0.02)
    frames = captured[:]
    del captured[: len(frames)]
    for frame in reversed(frames) if reversed_order else frames:
        await relay_event(thread_id, cast("dict[str, object]", frame), services)


async def _answer(
    session_factory: async_sessionmaker[AsyncSession],
    checkpointer: AsyncSqliteSaver,
    worker_client: httpx.AsyncClient,
    *,
    thread_id: str,
    request_id: str,
    option_id: str,
    idempotency_key: str,
) -> ControlActionOutcome:
    """Answer the request through the real respond verb, dispatching for real."""
    async with session_factory() as session:
        return await respond_to_permission(
            session,
            thread_id=thread_id,
            response=PermissionInput(request_id, option_id, idempotency_key),
            checkpointer=checkpointer,
            transport=DispatchTransport(
                worker_client=worker_client,
                circuit_breaker=WorkerCircuitBreaker(
                    failure_threshold=2, recovery_timeout=1
                ),
                worker_spawner=adopted_spawner(),
            ),
        )


async def _accepted_dispatch(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    thread_id: str,
    request_id: str,
    generation: int,
) -> str:
    """The dispatch the answer journaled under one ask of *request_id* carries."""
    async with session_factory() as session:
        action = await get_control_action_by_idempotency_key(
            session,
            thread_id=thread_id,
            idempotency_key=permission_response_action_key(request_id, generation),
        )
    assert action is not None, f"no accepted answer under ask {generation}"
    assert action.dispatch_id is not None
    return action.dispatch_id


@pytest.mark.asyncio
@pytest.mark.parametrize("reversed_frames", [False, True])
async def test_a_reasked_permission_is_answerable_and_resumes_the_graph(
    session_factory: async_sessionmaker[AsyncSession],
    checkpointer: AsyncSqliteSaver,
    tmp_path: Path,
    *,
    reversed_frames: bool,
) -> None:
    """Each ask of one request takes an answer of its own and resumes the run.

    Three asks, one request id. Each answer is accepted under its own journal
    identity, each re-ask returns the request row to pending with the offer it
    now makes, and the third answer carries the run to its end.

    *reversed_frames* hands the worker's frames to the relay back to front,
    which is the interleaving one batch can produce. The request has to end up
    open and answerable either way, because the journal's settled state decides
    that and the arrival order does not.
    """
    graph = _reasking_graph(checkpointer)
    async with session_factory() as session:
        thread_id, _ingest_receipt = await seed_accepted_thread(
            session,
            status=ThreadStatus.RUNNING,
            title="re-asked permission",
            workspace=tmp_path,
        )
        await session.commit()
    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
    cache_key = await supervised_graph_cache_key(session_factory, thread_id)
    services = RelayServices(session_factory=session_factory, checkpointer=checkpointer)
    async with (
        _capturing_bridge() as (bridge, captured),
        served_worker(
            checkpointer,
            bridge=bridge,
            graphs={thread_id: (cache_key, graph)},
            drain_dispatches=True,
        ) as worker,
    ):
        # The run's own accepted ingest, executed by the worker: the first ask
        # and its park frame are the worker's, and the journal row and creation
        # action for the request are written by the relay rather than seeded.
        await _deliver_accepted_ingest(session_factory, worker.client, thread_id)
        await _relay_captured_frames(
            worker,
            captured,
            services,
            thread_id=thread_id,
            reversed_order=reversed_frames,
        )
        held = await _held_request_ids(checkpointer, config, thread_id)
        assert len(held) == 1, held
        request_id = held[0]
        async with session_factory() as session:
            journaled = await get_permission_request(session, request_id)
        assert journaled is not None
        assert journaled.request_status == PermissionRequestStatus.PENDING.value

        dispatches: list[str] = []
        for ask, option_id in enumerate(_ANSWERS):
            last = ask + 1 == len(_ANSWERS)
            outcome = await _answer(
                session_factory,
                checkpointer,
                worker.client,
                thread_id=thread_id,
                request_id=request_id,
                option_id=option_id,
                idempotency_key=f"answer-{ask}",
            )
            assert outcome.dispatched is True, (ask, outcome.error_detail)
            # Each ask's answer is a journal row of its own, so the next answer
            # is accepted instead of replaying the one before it.
            dispatch_id = await _accepted_dispatch(
                session_factory,
                thread_id=thread_id,
                request_id=request_id,
                generation=ask,
            )
            assert dispatch_id not in dispatches
            dispatches.append(dispatch_id)

            await _relay_captured_frames(
                worker,
                captured,
                services,
                thread_id=thread_id,
                reversed_order=reversed_frames,
            )
            if last:
                continue

            # The worker asked again, under the request id it was answered on,
            # and the row is open again with the offer this ask makes.
            assert await _held_request_ids(checkpointer, config, thread_id) == [
                request_id
            ]
            async with session_factory() as session:
                reopened = await get_permission_request(session, request_id)
            assert reopened is not None, ask
            assert reopened.request_status == PermissionRequestStatus.PENDING.value, ask
            assert valid_option_ids(
                decode_allowed_options(reopened.allowed_options_json)
            ) == valid_option_ids(_OFFERS[ask + 1]), ask

        with anyio.fail_after(30.0):
            while True:
                settled_state = await graph.aget_state(config)
                if settled_state.next == ():
                    break
                await anyio.sleep(0.02)

    # The last answer is the one the run took, and it ran past the question.
    assert await _held_request_ids(checkpointer, config, thread_id) == []
    artifacts = cast("list[dict[str, str]]", settled_state.values["artifacts"])
    assert [artifact["path"] for artifact in artifacts] == [_ANSWERS[-1]]

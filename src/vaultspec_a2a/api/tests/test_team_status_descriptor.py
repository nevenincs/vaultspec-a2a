"""The team status must report each agent's resolved model assignment.

These exercise the whole chain the descriptor travels — team config resolution,
graph compilation, the aggregator's node-metadata cache, and the team-status
service — because the field loss they guard against was invisible at every
individual layer: every model in the chain *declared* ``provider``/``model``,
and only the seam between them dropped the values.

They stop at the SERVICE rather than a route. The versioned team-status verb is
a deliberately narrow operational projection - agent id, display name, state -
and carries neither field, so the route can no longer express what these cases
are about while the service still resolves it. Asserting there would have meant
deleting the very assertions this module exists for.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import httpx
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from ...control.config import settings
from ...control.team_service import build_team_status
from ...database import create_thread
from ...graph.compiler import compile_team_graph
from ...graph.enums import AgentLifecycleState, Provider
from ...providers.factory import ProviderFactory
from ...providers.team_selection import FrozenLaneAssignment
from ...streaming.aggregator import EventAggregator
from ...team.team_config import (
    TeamConfig,
    TopologyConfig,
    TopologyType,
    WorkerRef,
    load_agent_config,
)
from ...testing import SseReader
from ...tests._checkpoint_seeding import real_checkpoint
from ...tests._write_authority import make_test_write_authority
from ...thread.enums import ThreadStatus
from ...worker.executor import Executor
from ...worker.ipc import WorkerBridge
from .conftest import SessionFactory, _live_server, make_app, seed_run_with_status

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from langchain_core.runnables import RunnableConfig

    from ...streaming.types import StreamableGraph

_WORKER_ID = "vaultspec-coder"


@pytest_asyncio.fixture
async def graph_checkpointer() -> AsyncGenerator[AsyncSqliteSaver]:
    """An in-memory SQLite checkpointer for the compiled team graph."""
    async with AsyncSqliteSaver.from_conn_string(":memory:") as saver:
        await saver.setup()
        yield saver


def _deterministic_team() -> TeamConfig:
    return TeamConfig(
        id="team-status-descriptor",
        display_name="team-status-descriptor",
        topology=TopologyConfig(type=TopologyType.PIPELINE, order=[_WORKER_ID]),
        workers=[WorkerRef(agent_id=_WORKER_ID)],
    )


def _exact_assignment() -> dict[str, FrozenLaneAssignment]:
    lane = FrozenLaneAssignment.model_validate(
        {
            "schema_version": 1,
            "provider_id": "deterministic",
            "execution_mode": "in-process-deterministic",
            "catalog_revision": "test-revision",
            "entry_id": "test-entry",
            "model_name": "deterministic",
            "controls": [],
            "defaulted_control_ids": [],
            "provenance": {"selection_source": "team_selection"},
        }
    )
    return {_WORKER_ID: lane}


@pytest.mark.asyncio
async def test_team_status_reports_the_resolved_provider_and_model(
    session_factory: SessionFactory,
    checkpointer: AsyncSqliteSaver,
    graph_checkpointer: AsyncSqliteSaver,
) -> None:
    """A compiled agent's provider and capability reach the REST response.

    Fails on the previous behaviour: the compiler resolved both values and then
    dropped them when writing node metadata, so the route emitted ``null`` for
    every agent no matter how the team was configured.
    """
    team = _deterministic_team()
    graph = compile_team_graph(
        team_config=team,
        agent_configs={_WORKER_ID: load_agent_config(_WORKER_ID)},
        checkpointer=graph_checkpointer,
        provider_factory=ProviderFactory(),
        model_assignment=_exact_assignment(),
        step_timeout=60.0,
    )

    aggregator = EventAggregator()
    aggregator.register_graph("thread-team-status", cast("StreamableGraph", graph))

    async with session_factory() as db:
        status = await build_team_status(
            db=db, aggregator=aggregator, heartbeat_threads=["thread-team-status"]
        )
    agents = {agent.agent_id: agent for agent in status.agents}
    assert _WORKER_ID in agents, f"compiled worker missing from {list(agents)}"
    worker = agents[_WORKER_ID]
    assert worker.provider == Provider.DETERMINISTIC.value
    assert worker.model_name == "deterministic"


@pytest.mark.asyncio
async def test_thread_state_snapshot_reports_the_resolved_assignment(
    session_factory: SessionFactory,
    checkpointer: AsyncSqliteSaver,
    graph_checkpointer: AsyncSqliteSaver,
) -> None:
    """The snapshot route carries the assignment too, not just ``/team/status``.

    ``control/team_service.py`` and ``control/snapshot.py`` read the same
    ``get_node_summaries()`` seam, so both should be fixed by populating node
    metadata once — but that is a call-graph inference, and this asserts it
    against the real ``GET /threads/{id}/state`` response instead.
    """
    thread_id = "thread-descriptor-snapshot"
    team = _deterministic_team()
    graph = compile_team_graph(
        team_config=team,
        agent_configs={_WORKER_ID: load_agent_config(_WORKER_ID)},
        checkpointer=graph_checkpointer,
        provider_factory=ProviderFactory(),
        model_assignment=_exact_assignment(),
        step_timeout=60.0,
    )
    aggregator = EventAggregator()
    aggregator.register_graph(thread_id, cast("StreamableGraph", graph))

    app, _agg, _worker, _cp = make_app(
        session_factory, checkpointer, aggregator=aggregator
    )

    await checkpointer.setup()
    config: RunnableConfig = {
        "configurable": {"thread_id": thread_id, "checkpoint_ns": ""}
    }
    checkpoint = await real_checkpoint()
    checkpoint["id"] = f"cp-{thread_id}"
    await checkpointer.aput(
        config,
        checkpoint,
        {"source": "loop", "step": 1, "parents": {}},
        {},
    )
    async with session_factory() as session:
        await create_thread(
            session,
            write_authority=make_test_write_authority(),
            thread_id=thread_id,
            status="input_required",
            repair_status="healthy",
            execution_readiness="healthy",
        )
        await session.commit()

    with TestClient(app, raise_server_exceptions=True) as client:
        resp = client.get(f"/v1/runs/{thread_id}/history")

    assert resp.status_code == 200
    agents = {a["agent_id"]: a for a in resp.json()["state"]["agents"]}
    assert agents[_WORKER_ID]["thread_id"] == thread_id
    assert agents[_WORKER_ID]["provider"] == Provider.DETERMINISTIC.value
    assert agents[_WORKER_ID]["model_name"] == "deterministic"


@pytest.mark.asyncio(loop_scope="function")
async def test_team_status_broadcast_carries_the_resolved_assignment(
    session_factory: SessionFactory,
    checkpointer: AsyncSqliteSaver,
    graph_checkpointer: AsyncSqliteSaver,
) -> None:
    """The ``team_status`` frame a client reads carries the resolved assignment.

    Drives the worker's own executor, its real bridge and the gateway's real
    relay route over a socket, then reads the frame off the served stream. The
    event path builds each agent entry from plain dicts rather than from the
    descriptor, so it could silently drop the fields the REST route carries, and
    the stream's closed field catalog drops anything it does not name - only the
    frame as delivered shows that the fields survived both.
    """
    thread_id = "thread-descriptor-broadcast"
    team = _deterministic_team()
    graph = compile_team_graph(
        team_config=team,
        agent_configs={_WORKER_ID: load_agent_config(_WORKER_ID)},
        checkpointer=graph_checkpointer,
        provider_factory=ProviderFactory(),
        model_assignment=_exact_assignment(),
        step_timeout=60.0,
    )
    app, _agg, _worker, _cp = make_app(session_factory, checkpointer, EventAggregator())
    await seed_run_with_status(session_factory, thread_id, ThreadStatus.RUNNING)

    async with (
        _live_server(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
    ):
        bridge = WorkerBridge(
            api_url=base,
            worker_id="descriptor-worker",
            internal_token=settings.internal_token,
        )
        executor = Executor(checkpointer=graph_checkpointer, bridge=bridge)
        try:
            executor.aggregator.register_graph(
                thread_id, cast("StreamableGraph", graph)
            )
            async with client.stream("GET", f"/v1/runs/{thread_id}/stream") as response:
                assert response.status_code == 200
                reader = SseReader(response.aiter_lines())
                assert (await reader.next_frame()).type == "stream_snapshot"

                # Only agent_id/node_name/state, exactly as the lifecycle
                # emitter supplies them; the assignment must be merged in from
                # the registered node metadata.
                await executor.aggregator._emitters.emit_team_status(
                    thread_id,
                    [
                        {
                            "agent_id": _WORKER_ID,
                            "node_name": _WORKER_ID,
                            "state": AgentLifecycleState.WORKING.value,
                        }
                    ],
                )
                assert await bridge.flush_events()
                frame = (await reader.until("team_status"))[-1]
        finally:
            await executor.shutdown()
            await bridge.close()

    assert frame.data["thread_id"] == thread_id
    agents = cast("list[dict[str, str]]", frame.data["agents"])
    summary = next(a for a in agents if a["agent_id"] == _WORKER_ID)
    assert summary["provider"] == Provider.DETERMINISTIC.value
    assert summary["model_name"] == "deterministic"


@pytest.mark.asyncio
async def test_aggregator_agent_states_are_enum_members_not_strings() -> None:
    """``get_agent_states()`` yields real enum members at runtime.

    ``control/snapshot.py`` used to wrap this value in ``str()``.  That was not
    protecting against a string arriving where an enum was expected — it was
    downgrading a well-typed enum into a bare string, which is what let the
    stringly-typed descriptor persist.  Dropping the call removes a coercion
    rather than swapping one silent coercion for another, and this pins it.
    """
    aggregator = EventAggregator()
    await aggregator.emit_agent_status(
        thread_id="thread-agent-state-type",
        agent_id=_WORKER_ID,
        node_name=_WORKER_ID,
        state=AgentLifecycleState.WORKING,
    )

    states = aggregator.get_agent_states("thread-agent-state-type")
    observed = states[_WORKER_ID]
    assert isinstance(observed, AgentLifecycleState)
    assert observed is AgentLifecycleState.WORKING


@pytest.mark.asyncio
async def test_team_status_reports_unknown_assignment_as_null(
    session_factory: SessionFactory,
) -> None:
    """An agent registered without a resolved assignment reports null, not a guess.

    The aggregator also caches node metadata relayed from the worker process,
    which may predate model resolution; that path must not fabricate a provider.
    """
    aggregator = EventAggregator()
    aggregator._subscribers_mgr.set_node_metadata(
        "thread-unresolved",
        {
            "unresolved-agent": {
                "role": "coder",
                "display_name": "Unresolved",
                "description": "Registered before its model resolved.",
            },
        },
    )

    async with session_factory() as db:
        status = await build_team_status(
            db=db, aggregator=aggregator, heartbeat_threads=["thread-unresolved"]
        )

    agent = status.agents[0]
    assert agent.thread_id == "thread-unresolved"
    assert agent.provider is None
    assert agent.model_name is None

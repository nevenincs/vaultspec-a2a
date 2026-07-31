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

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from langgraph.checkpoint.base import empty_checkpoint
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from ...control.team_service import build_team_status
from ...database import create_thread
from ...graph.compiler import compile_team_graph
from ...graph.enums import AgentLifecycleState, Model, Provider
from ...providers.factory import ProviderFactory
from ...streaming.aggregator import EventAggregator
from ...streaming.sse_frames import enforce_progress_allowlist
from ...team.team_config import (
    TeamConfig,
    TeamDefaultsConfig,
    TopologyConfig,
    TopologyType,
    WorkerOverrideConfig,
    WorkerRef,
    load_agent_config,
)
from ..event_adapter import domain_to_wire
from ..schemas.events import TeamStatusEvent
from .conftest import make_app

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from ...streaming.types import StreamableGraph

_WORKER_ID = "vaultspec-coder"


@pytest_asyncio.fixture
async def graph_checkpointer() -> AsyncGenerator[AsyncSqliteSaver]:
    """An in-memory SQLite checkpointer for the compiled team graph."""
    async with AsyncSqliteSaver.from_conn_string(":memory:") as saver:
        await saver.setup()
        yield saver


def _deterministic_team(capability: Model = Model.LOW) -> TeamConfig:
    """A single-worker team pinned to the in-process deterministic provider.

    ``Provider.DETERMINISTIC`` is a real, always-ready provider that runs
    in-process with no credential and no network, so the graph compiles through
    the production ``ProviderFactory`` rather than a substitute.

    The assignment rides the ``[[team.workers]]`` override, which outranks the
    agent TOML.  That matters: ``vaultspec-coder.toml`` declares
    ``provider = "claude"``, so a response reporting ``deterministic`` can only
    have come from the real precedence chain — it cannot be the agent's own
    default leaking through, and it cannot be a constant.
    """
    return TeamConfig(
        id="team-status-descriptor",
        display_name="team-status-descriptor",
        topology=TopologyConfig(type=TopologyType.PIPELINE, order=[_WORKER_ID]),
        workers=[
            WorkerRef(
                agent_id=_WORKER_ID,
                model=WorkerOverrideConfig(
                    provider=Provider.DETERMINISTIC,
                    capability=capability,
                ),
            )
        ],
        defaults=TeamDefaultsConfig(provider=Provider.DETERMINISTIC),
    )


@pytest.mark.asyncio
async def test_team_status_reports_the_resolved_provider_and_model(
    session_factory,
    checkpointer,
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
    )

    aggregator = EventAggregator()
    aggregator.register_graph(cast("StreamableGraph", graph))

    async with session_factory() as db:
        status = await build_team_status(
            db=db, aggregator=aggregator, heartbeat_threads=[]
        )
    agents = {agent.agent_id: agent for agent in status.agents}
    assert _WORKER_ID in agents, f"compiled worker missing from {list(agents)}"
    worker = agents[_WORKER_ID]
    assert worker.provider == Provider.DETERMINISTIC.value
    assert worker.model == Model.LOW.value
    # The agent's own TOML declares "claude"; seeing it here would mean the
    # route reported a configured default rather than the resolved assignment.
    assert load_agent_config(_WORKER_ID).model.provider == Provider.CLAUDE


@pytest.mark.asyncio
async def test_team_status_honours_a_per_worker_model_override(
    session_factory,
    checkpointer,
    graph_checkpointer: AsyncSqliteSaver,
) -> None:
    """The reported capability tracks the override, so it cannot be a constant.

    The sibling test pins the same worker to ``LOW``; only the override differs,
    so a fix that hardcoded a capability or echoed the agent TOML would pass one
    of these two and fail the other.
    """
    team = _deterministic_team(capability=Model.MAX)

    graph = compile_team_graph(
        team_config=team,
        agent_configs={_WORKER_ID: load_agent_config(_WORKER_ID)},
        checkpointer=graph_checkpointer,
        provider_factory=ProviderFactory(),
    )

    aggregator = EventAggregator()
    aggregator.register_graph(cast("StreamableGraph", graph))

    async with session_factory() as db:
        status = await build_team_status(
            db=db, aggregator=aggregator, heartbeat_threads=[]
        )
    agents = {agent.agent_id: agent for agent in status.agents}
    assert agents[_WORKER_ID].model == Model.MAX.value


@pytest.mark.asyncio
async def test_thread_state_snapshot_reports_the_resolved_assignment(
    session_factory,
    checkpointer,
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
    )
    aggregator = EventAggregator()
    aggregator.register_graph(cast("StreamableGraph", graph))

    app, _agg, _worker, _cp = make_app(
        session_factory, checkpointer, aggregator=aggregator
    )

    await checkpointer.setup()
    checkpoint = empty_checkpoint()
    checkpoint["id"] = f"cp-{thread_id}"
    await checkpointer.aput(
        {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}},
        checkpoint,
        {"source": "loop", "step": 1, "parents": {}},
        {},
    )
    async with session_factory() as session:
        await create_thread(
            session,
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
    assert agents[_WORKER_ID]["provider"] == Provider.DETERMINISTIC.value
    assert agents[_WORKER_ID]["model"] == Model.LOW.value


@pytest.mark.asyncio
async def test_team_status_broadcast_carries_the_resolved_assignment(
    graph_checkpointer: AsyncSqliteSaver,
) -> None:
    """The ``team_status`` broadcast carries the assignment through to the wire.

    Drives the real emitter and the real ``domain_to_wire`` adapter, because the
    event path builds ``AgentSummary`` from plain dicts rather than from the
    descriptor and so could silently drop the fields the REST route now carries.
    """
    team = _deterministic_team()
    graph = compile_team_graph(
        team_config=team,
        agent_configs={_WORKER_ID: load_agent_config(_WORKER_ID)},
        checkpointer=graph_checkpointer,
        provider_factory=ProviderFactory(),
    )
    aggregator = EventAggregator()
    aggregator.register_graph(cast("StreamableGraph", graph))

    thread_id = "thread-descriptor-broadcast"
    queue = aggregator.add_subscriber("descriptor-client")
    aggregator.subscribe("descriptor-client", [thread_id])

    # Only agent_id/node_name/state, exactly as the lifecycle emitter supplies
    # them; the assignment must be merged in from the registered node metadata.
    await aggregator.emit_team_status(
        thread_id,
        [
            {
                "agent_id": _WORKER_ID,
                "node_name": _WORKER_ID,
                "state": AgentLifecycleState.WORKING.value,
            }
        ],
    )

    sequenced = queue.get_nowait()
    wire = domain_to_wire(sequenced.event, sequenced.sequence)
    assert isinstance(wire, TeamStatusEvent)
    summary = next(a for a in wire.agents if a.agent_id == _WORKER_ID)
    assert summary.provider is Provider.DETERMINISTIC
    assert summary.model is Model.LOW

    # The SSE catalog is a closed allowlist that drops anything it does not
    # name, so the fields must survive that projection to reach a client.
    payload = enforce_progress_allowlist(
        {"type": "team_status", **wire.model_dump(mode="json")}
    )
    projected = cast("list[dict[str, str]]", payload["agents"])
    assert projected[0]["provider"] == Provider.DETERMINISTIC.value
    assert projected[0]["model"] == Model.LOW.value


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

    states = aggregator.get_agent_states()
    observed = states[_WORKER_ID]
    assert isinstance(observed, AgentLifecycleState)
    assert observed is AgentLifecycleState.WORKING


@pytest.mark.asyncio
async def test_team_status_reports_unknown_assignment_as_null(
    session_factory,
) -> None:
    """An agent registered without a resolved assignment reports null, not a guess.

    The aggregator also caches node metadata relayed from the worker process,
    which may predate model resolution; that path must not fabricate a provider.
    """
    aggregator = EventAggregator()
    aggregator._subscribers_mgr.set_node_metadata(
        {
            "unresolved-agent": {
                "role": "coder",
                "display_name": "Unresolved",
                "description": "Registered before its model resolved.",
            },
        }
    )

    async with session_factory() as db:
        status = await build_team_status(
            db=db, aggregator=aggregator, heartbeat_threads=[]
        )

    agent = status.agents[0]
    assert agent.provider is None
    assert agent.model is None

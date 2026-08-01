"""The clarification stage inside the real ``research_adr`` topology.

Compiled from REAL shipped presets over a real ``AsyncSqliteSaver``, and armed
the only way production arms it: a ``[team.clarification]`` block in the preset.
There is no injected producer here and no override parameter to inject one
through - if these tests pass, the live dispatch chain reaches the same node by
the same route, because it compiles the same presets through the same function.

Two properties carry the design. A preset that declares questions stops for them
BEFORE any researcher spends a turn, so the answer can still steer the work. A
preset that declares none compiles to the graph it compiled before the capability
existed, node for node.
"""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, Any

import pytest
import pytest_asyncio
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command

from ...team.team_config import (
    ResearchThreadSpec,
    TopologyType,
    load_agent_config,
    load_team_config,
)
from ...thread.clarification import CLARIFICATION_TOPOLOGIES
from ...thread.errors import ConfigError
from ..compiler import _clarification_request_id, compile_team_graph

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from ..protocols import ProviderFactoryProtocol

# The preset that declares a questionnaire, and a sibling that declares none.
_ASKING_PRESET = "vaultspec-adr-research-clarify"
_SILENT_PRESET = "vaultspec-adr-research-mock"


class _FakeSubmitter:
    """Idempotent proposal submitter recording the phases it was asked to gate."""

    def __init__(self) -> None:
        self.phases: list[str] = []

    async def __call__(self, state: Any, phase: str) -> str:
        self.phases.append(phase)
        return f"prop-{phase}"


@pytest_asyncio.fixture
async def checkpointer() -> AsyncGenerator[AsyncSqliteSaver]:
    async with AsyncSqliteSaver.from_conn_string(":memory:") as saver:
        await saver.setup()
        yield saver


def _team(preset_id: str) -> Any:
    """Load a real preset, narrowed to one researcher branch for speed."""
    team = load_team_config(preset_id)
    topo = team.topology.model_copy(
        update={"research_threads": [ResearchThreadSpec(thread_id="codebase")]}
    )
    return team.model_copy(update={"topology": topo})


def _agent_configs(team: Any) -> dict[str, Any]:
    return {w.agent_id: load_agent_config(w.agent_id) for w in team.workers}


def _compile(team: Any, checkpointer: Any, pf: Any, submitter: Any) -> Any:
    return compile_team_graph(
        team_config=team,
        agent_configs=_agent_configs(team),
        checkpointer=checkpointer,
        provider_factory=pf,
        proposal_submitter=submitter,
    )


def _seed_state(thread_id: str) -> dict[str, Any]:
    return {
        "active_agent": "clarification_request",
        "artifacts": [],
        "current_plan": [],
        "messages": [HumanMessage(content="Plan the right-side monitor panel.")],
        "next": "",
        "thread_id": thread_id,
        "active_feature": "agent-panel",
        "token_usage": {},
    }


def test_the_preset_is_the_only_way_to_arm_the_stage() -> None:
    """No override parameter exists, so production cannot miss the arming path.

    This is what makes the reachability argument airtight rather than inferred.
    The live dispatch chain compiles through ``compile_team_graph`` with a loaded
    preset; if that function also accepted an injected producer, a reader could
    not tell whether the node was reachable in production or only from a test
    holding a producer it built itself. With the parameter gone, arming is a pure
    function of the preset, so "the preset declares questions" and "a real run can
    park" are the same statement.
    """
    parameters = set(inspect.signature(compile_team_graph).parameters)

    assert "clarification_producer" not in parameters
    assert not [name for name in parameters if "clarification" in name]
    # The preset does reach the compiler - that is the channel the arming rides.
    assert "team_config" in parameters


@pytest.mark.asyncio
async def test_a_preset_declaring_nothing_compiles_the_unchanged_topology(
    checkpointer: AsyncSqliteSaver,
    pf: ProviderFactoryProtocol,
) -> None:
    """No declaration, no stage - and therefore no extra superstep on any run."""
    graph = _compile(_team(_SILENT_PRESET), checkpointer, pf, _FakeSubmitter())

    node_keys = {key for key in graph.nodes if not key.startswith("__")}
    assert "clarification_request" not in node_keys
    assert "clarification_gate" not in node_keys


@pytest.mark.asyncio
async def test_a_declaring_preset_wires_the_stage_ahead_of_the_fan_out(
    checkpointer: AsyncSqliteSaver,
    pf: ProviderFactoryProtocol,
) -> None:
    """The preset alone arms it - nothing is passed to the compiler."""
    graph = _compile(_team(_ASKING_PRESET), checkpointer, pf, _FakeSubmitter())

    node_keys = {key for key in graph.nodes if not key.startswith("__")}
    assert {"clarification_request", "clarification_gate"} <= node_keys
    # The existing machine is untouched beside it.
    assert {"research_dispatch", "synthesis", "research_gate", "adr_gate"} <= node_keys


@pytest.mark.parametrize(
    "topology_type",
    [t for t in TopologyType if t.value not in CLARIFICATION_TOPOLOGIES],
    ids=lambda t: t.value,
)
def test_compiling_a_questionnaire_onto_a_topology_that_never_asks_is_refused(
    topology_type: TopologyType,
    pf: ProviderFactoryProtocol,
) -> None:
    """Compile refuses the graph that would accept questions and never ask them.

    Preset load refuses this pairing first, but load is not the only door into the
    compiler: a validated config can be moved onto another topology afterwards -
    ``model_copy`` re-runs no validator, and this test walks in through exactly
    that door with a REAL declaring preset. Without the compile-time refusal the
    call below returns a perfectly usable graph with no clarification node in it,
    which is the silent-skip failure in its finished form: a run that was told to
    ask, that never asks, and that reports success.

    The topology is asserted by name in the message because the two halves of the
    contradiction live in different blocks of the preset, and the author needs to
    be told which one the compiler read.
    """
    team = _team(_ASKING_PRESET)
    moved = team.model_copy(
        update={"topology": team.topology.model_copy(update={"type": topology_type})}
    )
    assert moved.clarification is not None, "the probe must still declare questions"

    with pytest.raises(ConfigError, match=topology_type.value) as raised:
        compile_team_graph(
            team_config=moved,
            agent_configs=_agent_configs(moved),
            checkpointer=None,
            provider_factory=pf,
            proposal_submitter=_FakeSubmitter(),
        )

    assert "clarification" in str(raised.value)


@pytest.mark.asyncio
async def test_the_run_parks_for_its_question_before_any_researcher_spends_a_turn(
    checkpointer: AsyncSqliteSaver,
    pf: ProviderFactoryProtocol,
) -> None:
    """Asking before diverging is the entire point of the stage's position.

    A question answered after the fan-out would arrive too late to steer it, so
    the assertion is not merely that the run parked but that it parked with no
    research findings accumulated and no document submitted yet.
    """
    submitter = _FakeSubmitter()
    graph = _compile(_team(_ASKING_PRESET), checkpointer, pf, submitter)

    config: Any = {"configurable": {"thread_id": "ra-clarify-run"}}
    parked = await graph.ainvoke(_seed_state("ra-clarify-thread"), config=config)

    assert "__interrupt__" in parked
    payload = parked["__interrupt__"][0].value
    assert payload["type"] == "clarification_request"
    # Served verbatim from the preset - the declaration IS the questionnaire.
    assert [q["id"] for q in payload["questions"]] == ["scope", "constraints"]
    assert payload["questions"][0]["options"] == ["frontend", "backend", "both"]
    assert payload["questions"][1]["required"] is False

    assert not parked.get("research_findings")
    assert submitter.phases == []


@pytest.mark.asyncio
async def test_the_request_id_is_derived_from_the_run(
    checkpointer: AsyncSqliteSaver,
    pf: ProviderFactoryProtocol,
) -> None:
    """Two runs of the same preset park on distinguishable questionnaires.

    A preset-constant id would make two concurrent runs of the same preset
    indistinguishable to anything correlating on the handle alone.
    """
    graph = _compile(_team(_ASKING_PRESET), checkpointer, pf, _FakeSubmitter())

    first = await graph.ainvoke(
        _seed_state("run-alpha"), config={"configurable": {"thread_id": "run-alpha"}}
    )
    second = await graph.ainvoke(
        _seed_state("run-beta"), config={"configurable": {"thread_id": "run-beta"}}
    )

    assert first["__interrupt__"][0].value["request_id"] == _clarification_request_id(
        "run-alpha"
    )
    assert second["__interrupt__"][0].value["request_id"] == _clarification_request_id(
        "run-beta"
    )
    assert (
        first["__interrupt__"][0].value["request_id"]
        != second["__interrupt__"][0].value["request_id"]
    )


@pytest.mark.asyncio
async def test_answering_releases_the_run_into_the_diverge_stage(
    checkpointer: AsyncSqliteSaver,
    pf: ProviderFactoryProtocol,
) -> None:
    """The answer resumes the real pipeline, which then runs on to its first gate."""
    submitter = _FakeSubmitter()
    graph = _compile(_team(_ASKING_PRESET), checkpointer, pf, submitter)

    config: Any = {"configurable": {"thread_id": "ra-clarify-resume"}}
    parked = await graph.ainvoke(_seed_state("ra-clarify-resume"), config=config)
    request_id = parked["__interrupt__"][0].value["request_id"]

    resumed = await graph.ainvoke(
        Command(
            resume={
                "type": "clarification_response",
                "request_id": request_id,
                "answers": {"scope": "both", "constraints": "keep it collapsible"},
            }
        ),
        config=config,
    )

    # The human's answer is durable state the rest of the run can read.
    assert resumed["clarification_answers"] == {
        request_id: {"scope": "both", "constraints": "keep it collapsible"}
    }
    # And the pipeline genuinely continued: the fan-out produced its finding and
    # the run advanced to the first document gate.
    assert [f["source_thread"] for f in resumed["research_findings"]] == ["codebase"]
    assert submitter.phases == ["research"]
    assert resumed["__interrupt__"][0].value["type"] == "document_approval_request"


@pytest.mark.asyncio
async def test_a_resumed_run_does_not_ask_again(
    checkpointer: AsyncSqliteSaver,
    pf: ProviderFactoryProtocol,
) -> None:
    """Ask once. The question set is committed before parking, so the resume
    replays the pure gate node and never re-derives a questionnaire.

    Asserted through the checkpoint rather than a call counter, because the
    property that matters is that the run stops offering the question - a counter
    would still pass if the answered questionnaire were re-parked.
    """
    graph = _compile(_team(_ASKING_PRESET), checkpointer, pf, _FakeSubmitter())

    config: Any = {"configurable": {"thread_id": "ra-ask-once"}}
    parked = await graph.ainvoke(_seed_state("ra-ask-once"), config=config)
    request_id = parked["__interrupt__"][0].value["request_id"]

    # While parked, the committed question set is durable in the checkpoint.
    state = await graph.aget_state(config)
    assert state.values["clarification_request"]["request_id"] == request_id

    resumed = await graph.ainvoke(
        Command(
            resume={
                "type": "clarification_response",
                "request_id": request_id,
                "answers": {"scope": "frontend"},
            }
        ),
        config=config,
    )

    # The pending question is cleared, and the next interrupt is the document
    # gate - not a second questionnaire.
    assert resumed.get("clarification_request") is None
    assert resumed["__interrupt__"][0].value["type"] == "document_approval_request"

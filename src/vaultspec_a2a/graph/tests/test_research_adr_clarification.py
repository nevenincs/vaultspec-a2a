"""The clarification stage inside the real ``research_adr`` topology.

Compiled from the real ``vaultspec-adr-research`` preset over a real
``AsyncSqliteSaver``, so what is asserted is the shape and behaviour of the
topology the product actually ships - not a purpose-built graph that happens to
contain the node.

Two properties carry the design: with a producer injected, a run stops for its
question BEFORE any researcher spends a turn on a guess; without one, the graph
is byte-for-byte the graph it was, so a run that has nobody to ask pays nothing
for the capability existing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
import pytest_asyncio
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command

from ...team.team_config import ResearchThreadSpec, load_agent_config, load_team_config
from ...thread.clarification import (
    ClarificationKind,
    ClarificationQuestion,
    ClarificationRequest,
)
from ..compiler import compile_team_graph

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from ..protocols import ProviderFactoryProtocol


class _FakeSubmitter:
    """Idempotent proposal submitter recording the phases it was asked to gate."""

    def __init__(self) -> None:
        self.phases: list[str] = []

    async def __call__(self, state: Any, phase: str) -> str:
        self.phases.append(phase)
        return f"prop-{phase}"


class _ScopeProducer:
    """Asks one bounded scoping question, and records the state it saw."""

    def __init__(self) -> None:
        self.calls = 0
        self.seen_thread_ids: list[str | None] = []

    async def __call__(self, state: Any) -> ClarificationRequest | None:
        self.calls += 1
        self.seen_thread_ids.append(state.get("thread_id"))
        return ClarificationRequest(
            request_id="clarify-scope",
            questions=[
                ClarificationQuestion(
                    id="depth",
                    prompt="How deep should the grounding sweep go?",
                    kind=ClarificationKind.CHOICE,
                    options=["shallow", "thorough"],
                )
            ],
        )


@pytest_asyncio.fixture
async def checkpointer() -> AsyncGenerator[AsyncSqliteSaver]:
    async with AsyncSqliteSaver.from_conn_string(":memory:") as saver:
        await saver.setup()
        yield saver


def _team() -> Any:
    team = load_team_config("vaultspec-adr-research")
    topo = team.topology.model_copy(
        update={"research_threads": [ResearchThreadSpec(thread_id="codebase")]}
    )
    return team.model_copy(update={"topology": topo})


def _agent_configs(team: Any) -> dict[str, Any]:
    return {w.agent_id: load_agent_config(w.agent_id) for w in team.workers}


def _seed_state() -> dict[str, Any]:
    return {
        "active_agent": "clarification_request",
        "artifacts": [],
        "current_plan": [],
        "messages": [HumanMessage(content="Plan the right-side monitor panel.")],
        "next": "",
        "thread_id": "ra-clarify-thread",
        "active_feature": "agent-panel",
        "token_usage": {},
    }


@pytest.mark.asyncio
async def test_without_a_producer_the_topology_is_unchanged(
    checkpointer: AsyncSqliteSaver,
    pf: ProviderFactoryProtocol,
) -> None:
    """No producer, no stage - and therefore no extra superstep on any run."""
    team = _team()
    graph = compile_team_graph(
        team_config=team,
        agent_configs=_agent_configs(team),
        checkpointer=checkpointer,
        provider_factory=pf,
        proposal_submitter=_FakeSubmitter(),
    )

    node_keys = {key for key in graph.nodes if not key.startswith("__")}
    assert "clarification_request" not in node_keys
    assert "clarification_gate" not in node_keys


@pytest.mark.asyncio
async def test_a_producer_wires_the_stage_ahead_of_the_fan_out(
    checkpointer: AsyncSqliteSaver,
    pf: ProviderFactoryProtocol,
) -> None:
    team = _team()
    graph = compile_team_graph(
        team_config=team,
        agent_configs=_agent_configs(team),
        checkpointer=checkpointer,
        provider_factory=pf,
        proposal_submitter=_FakeSubmitter(),
        clarification_producer=_ScopeProducer(),
    )

    node_keys = {key for key in graph.nodes if not key.startswith("__")}
    assert {"clarification_request", "clarification_gate"} <= node_keys
    # The existing machine is untouched beside it.
    assert {"research_dispatch", "synthesis", "research_gate", "adr_gate"} <= node_keys


@pytest.mark.asyncio
async def test_the_run_parks_for_its_question_before_any_researcher_spends_a_turn(
    checkpointer: AsyncSqliteSaver,
    pf: ProviderFactoryProtocol,
) -> None:
    """Asking before diverging is the entire point of the stage's position.

    A question answered after the fan-out would arrive too late to steer it, so
    the assertion is not merely that the run parked but that it parked with no
    research findings accumulated yet.
    """
    producer, submitter = _ScopeProducer(), _FakeSubmitter()
    team = _team()
    graph = compile_team_graph(
        team_config=team,
        agent_configs=_agent_configs(team),
        checkpointer=checkpointer,
        provider_factory=pf,
        proposal_submitter=submitter,
        clarification_producer=producer,
    )

    config: Any = {"configurable": {"thread_id": "ra-clarify-run"}}
    parked = await graph.ainvoke(_seed_state(), config=config)

    assert "__interrupt__" in parked
    assert parked["__interrupt__"][0].value == {
        "type": "clarification_request",
        "request_id": "clarify-scope",
        "questions": [
            {
                "id": "depth",
                "prompt": "How deep should the grounding sweep go?",
                "kind": "choice",
                "options": ["shallow", "thorough"],
                "required": True,
            }
        ],
    }
    assert not parked.get("research_findings")
    assert submitter.phases == []
    assert producer.seen_thread_ids == ["ra-clarify-thread"]


@pytest.mark.asyncio
async def test_answering_releases_the_run_into_the_diverge_stage(
    checkpointer: AsyncSqliteSaver,
    pf: ProviderFactoryProtocol,
) -> None:
    """The answer resumes the real pipeline, which then runs on to its first gate."""
    producer, submitter = _ScopeProducer(), _FakeSubmitter()
    team = _team()
    graph = compile_team_graph(
        team_config=team,
        agent_configs=_agent_configs(team),
        checkpointer=checkpointer,
        provider_factory=pf,
        proposal_submitter=submitter,
        clarification_producer=producer,
    )

    config: Any = {"configurable": {"thread_id": "ra-clarify-resume"}}
    await graph.ainvoke(_seed_state(), config=config)

    resumed = await graph.ainvoke(
        Command(
            resume={
                "type": "clarification_response",
                "request_id": "clarify-scope",
                "answers": {"depth": "thorough"},
            }
        ),
        config=config,
    )

    # The human's answer is durable state the rest of the run can read.
    assert resumed["clarification_answers"] == {"clarify-scope": {"depth": "thorough"}}
    # And the pipeline genuinely continued: the fan-out produced its finding and
    # the run advanced to the first document gate.
    assert [f["source_thread"] for f in resumed["research_findings"]] == ["codebase"]
    assert submitter.phases == ["research"]
    assert resumed["__interrupt__"][0].value["type"] == "document_approval_request"
    # The producer was consulted once, not again on resume.
    assert producer.calls == 1

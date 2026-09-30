"""Review loops end: by their budget in a document phase, by verdict in a loop.

Real graphs are compiled from shipped presets through ``compile_team_graph``
and driven with scripted models. A document reviewer that never passes must
hand the phase to its human gate once the preset's revision budget is spent,
and a human revision at that gate must earn the phase a fresh budget. A
``pipeline_loop`` must stop as soon as its loop node stops asking for revision
rather than always running to ``max_loops``.
"""

from __future__ import annotations

from typing import Any, cast

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from ...team.team_config import (
    ResearchThreadSpec,
    load_agent_config,
    load_team_config,
)
from ...thread.action_receipts import (
    GraphActionReceipt,
    control_action_payload_fingerprint,
)
from ...thread.enums import ControlActionType
from ..compiler import compile_team_graph
from .conftest import deterministic_model_assignment

_REVISION = "REVISION REQUIRED\n1. The claims need re-fetchable locators."


class _RoleScriptedFactory:
    """Hands each agent a fixed reply, and chosen agents a scripted one."""

    def __init__(self, replies: dict[str, str]) -> None:
        self._replies = replies

    def create(
        self,
        provider: Any,
        *,
        model: Any | None = None,
        agent_config: Any | None = None,
        workspace_root: Any | None = None,
        **kwargs: Any,
    ) -> FakeListChatModel:
        del provider, model, workspace_root, kwargs
        agent_id = getattr(agent_config, "id", "")
        reply = self._replies.get(agent_id, f"{agent_id} did its part")
        return FakeListChatModel(responses=[reply])


class _Submitter:
    async def __call__(self, state: Any, phase: str) -> str:
        del state
        return f"prop-{phase}"


def _receipt_input(thread_id: str) -> dict[str, Any]:
    receipt = GraphActionReceipt(
        schema_version="graph-action-v1",
        thread_id=thread_id,
        action_id="ingest",
        action_type=ControlActionType.INGEST,
        payload_fingerprint=control_action_payload_fingerprint({"run": thread_id}),
        dispatch_id="ingest",
        run_revision=1,
        writer_generation=1,
    ).model_dump(mode="json")
    return {
        "messages": [HumanMessage(content="Carry the feature forward.")],
        "thread_id": thread_id,
        "active_agent": "",
        "artifacts": [],
        "current_plan": [],
        "token_usage": {},
        "next": "",
        "active_feature": "review-budget",
        "active_graph_action_receipt": receipt,
        "graph_action_receipts": {"ingest": receipt},
    }


async def _updates(graph: Any, graph_input: Any, thread_id: str) -> list[str]:
    visited: list[str] = []
    config = {"configurable": {"thread_id": thread_id}}
    async for update in graph.astream(graph_input, config, stream_mode="updates"):
        visited.extend(cast("dict[str, Any]", update))
    return visited


def _research_graph(max_review_revisions: int) -> Any:
    team = load_team_config("vaultspec-adr-research")
    topology = team.topology.model_copy(
        update={
            "research_threads": [ResearchThreadSpec(thread_id="primary")],
            "max_review_revisions": max_review_revisions,
        }
    )
    team = team.model_copy(update={"topology": topology})
    return compile_team_graph(
        team_config=team,
        agent_configs={w.agent_id: load_agent_config(w.agent_id) for w in team.workers},
        checkpointer=InMemorySaver(),
        provider_factory=_RoleScriptedFactory({"vaultspec-doc-reviewer": _REVISION}),
        proposal_submitter=_Submitter(),
        model_assignment=deterministic_model_assignment(team),
    )


@pytest.mark.asyncio
async def test_a_reviewer_that_never_passes_hands_the_phase_to_its_gate() -> None:
    graph = _research_graph(max_review_revisions=2)

    visited = await _updates(graph, _receipt_input("budget"), "budget")

    # The first draft plus the two revisions the budget allows, then the gate.
    assert visited.count("synthesis") == 3
    assert visited.count("research_review") == 3
    assert "research_submit" in visited
    state = await graph.aget_state({"configurable": {"thread_id": "budget"}})
    assert state.next == ("research_gate",)
    # Reaching the gate gives the phase a fresh budget for a human revision.
    assert state.values["review_revisions"]["research"] == 0


@pytest.mark.asyncio
async def test_a_human_revision_at_the_gate_earns_a_fresh_review_budget() -> None:
    graph = _research_graph(max_review_revisions=1)
    await _updates(graph, _receipt_input("fresh"), "fresh")

    visited = await _updates(
        graph,
        Command(resume={"verdict": "request_changes", "notes": "Tighten it."}),
        "fresh",
    )

    # Back to the writer, then the full budget of one revision again.
    assert visited.count("synthesis") == 2
    assert visited.count("research_review") == 2
    state = await graph.aget_state({"configurable": {"thread_id": "fresh"}})
    assert state.next == ("research_gate",)


@pytest.mark.asyncio
async def test_a_zero_budget_goes_straight_to_the_gate() -> None:
    graph = _research_graph(max_review_revisions=0)

    visited = await _updates(graph, _receipt_input("zero"), "zero")

    assert visited.count("synthesis") == 1
    state = await graph.aget_state({"configurable": {"thread_id": "zero"}})
    assert state.next == ("research_gate",)


def _loop_graph(reviewer_reply: str) -> Any:
    team = load_team_config("mock-autonomous")
    return compile_team_graph(
        team_config=team,
        agent_configs={w.agent_id: load_agent_config(w.agent_id) for w in team.workers},
        checkpointer=InMemorySaver(),
        provider_factory=_RoleScriptedFactory({"mock-reviewer": reviewer_reply}),
        model_assignment=deterministic_model_assignment(team),
    )


@pytest.mark.asyncio
async def test_a_loop_ends_when_its_loop_node_asks_for_nothing_more() -> None:
    graph = _loop_graph("PASS\nThe change does what it says.")

    visited = await _updates(graph, _receipt_input("loop-pass"), "loop-pass")

    assert visited.count("mock-reviewer") == 1
    assert visited.count("mock-coder-success") == 1


@pytest.mark.asyncio
async def test_a_loop_that_keeps_asking_for_revision_stops_at_its_ceiling() -> None:
    graph = _loop_graph(_REVISION)
    max_loops = load_team_config("mock-autonomous").topology.max_loops

    visited = await _updates(graph, _receipt_input("loop-revise"), "loop-revise")

    assert visited.count("mock-reviewer") == max_loops

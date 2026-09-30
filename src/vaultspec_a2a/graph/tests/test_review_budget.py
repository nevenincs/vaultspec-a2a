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
from ...thread.errors import DocumentConformanceError
from ..compiler import compile_team_graph
from ..nodes.phase_gate import ProposalRevisionRequiredError
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
        Command(
            resume={
                "verdict": "request_changes",
                "notes": "Tighten it.",
                "request_id": "prop-research",
            }
        ),
        "fresh",
    )

    # Back to the writer, then the full budget of one revision again.
    assert visited.count("synthesis") == 2
    assert visited.count("research_review") == 2
    state = await graph.aget_state({"configurable": {"thread_id": "fresh"}})
    assert state.next == ("research_gate",)


@pytest.mark.asyncio
async def test_an_approved_phase_stops_showing_its_revision_notes() -> None:
    """Notes from a phase's gate do not follow the run into the next phase.

    The notes are appended to ``validation_errors``, which anchoring renders to
    every later worker as "active" errors, and only an explicit empty write
    clears the channel. Nothing made that write, so an ADR author was still
    being told to fix a research document the human had since approved.
    """
    graph = _research_graph(max_review_revisions=1)
    thread: Any = {"configurable": {"thread_id": "clears"}}
    await _updates(graph, _receipt_input("clears"), "clears")

    await _updates(
        graph,
        Command(
            resume={
                "verdict": "request_changes",
                "notes": "Fix the sources.",
                "request_id": "prop-research",
            }
        ),
        "clears",
    )
    revising = await graph.aget_state(thread)
    # The writer must still see the note it has to address.
    assert revising.values["validation_errors"] == ["Fix the sources."]

    await _updates(
        graph,
        Command(
            resume={
                "verdict": "approved",
                "notes": None,
                "request_id": "prop-research",
            }
        ),
        "clears",
    )
    advanced = await graph.aget_state(thread)

    assert advanced.values["validation_errors"] == []
    # The run really did advance past the research phase.
    assert advanced.next == ("adr_gate",)


@pytest.mark.asyncio
async def test_a_zero_budget_goes_straight_to_the_gate() -> None:
    graph = _research_graph(max_review_revisions=0)

    visited = await _updates(graph, _receipt_input("zero"), "zero")

    assert visited.count("synthesis") == 1
    state = await graph.aget_state({"configurable": {"thread_id": "zero"}})
    assert state.next == ("research_gate",)


class _RefusingSubmitter:
    """Refuses every body on conformance, as a writer that never complies would."""

    def __init__(self) -> None:
        self.attempts = 0

    async def __call__(self, state: Any, phase: str) -> str:
        del state
        self.attempts += 1
        raise ProposalRevisionRequiredError(
            [f"leftover template placeholder in the {phase} body"]
        )


def _refusing_research_graph(
    max_review_revisions: int, submitter: _RefusingSubmitter
) -> Any:
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
        provider_factory=_RoleScriptedFactory({}),
        proposal_submitter=submitter,
        model_assignment=deterministic_model_assignment(team),
    )


@pytest.mark.asyncio
async def test_a_submitter_that_never_accepts_a_body_ends_the_run_typed() -> None:
    """A conformance refusal costs a revision, and a spent budget ends the run.

    The refusal routes the phase's writer round again, exactly as a human
    ``request_changes`` does, so it spends the same per-phase budget. Costing
    nothing, it looped writer -> review -> submit until the recursion limit -
    an anonymous failure after a full budget of wasted model turns.

    The bounded end is a typed error rather than a park at the human gate:
    the refusal happens BEFORE any proposal exists, so a parked gate would
    name no proposal and nothing out of run could resume it.
    """
    submitter = _RefusingSubmitter()
    graph = _refusing_research_graph(2, submitter)

    with pytest.raises(DocumentConformanceError) as raised:
        await _updates(graph, _receipt_input("refusing"), "refusing")

    assert raised.value.phase == "research"
    assert raised.value.revision_notes == [
        "leftover template placeholder in the research body"
    ]
    # The first submit plus the budget's revisions, then the refusal that ends
    # it - not the recursion limit's worth.
    assert submitter.attempts == 4
    assert raised.value.attempts == 3


@pytest.mark.asyncio
async def test_a_zero_budget_refusal_ends_on_its_first_retry() -> None:
    """A phase with no revision budget still gets one corrective pass.

    A budget of zero means the inner reviewer gets no revision, and the same
    reading applies here: the writer is told once what the submitter refused,
    and a second refusal ends the run.
    """
    submitter = _RefusingSubmitter()
    graph = _refusing_research_graph(0, submitter)

    with pytest.raises(DocumentConformanceError):
        await _updates(graph, _receipt_input("refusing-zero"), "refusing-zero")

    assert submitter.attempts == 2


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

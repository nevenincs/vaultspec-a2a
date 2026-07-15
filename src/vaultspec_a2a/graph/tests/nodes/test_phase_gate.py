"""Tests for the generalized phase-gate node (adr-authoring-orchestration S05).

The gate is exercised over a real ``StateGraph`` with an ``InMemorySaver``
checkpointer so the interrupt/resume and the replay-on-resume are real, not
simulated. The propose-and-submit work is a small counting submitter so the test
isolates the gate's determinism, routing, and state recording from any engine.
"""

from __future__ import annotations

from typing import Any, cast

import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from vaultspec_a2a.graph.nodes.phase_gate import create_phase_gate_node
from vaultspec_a2a.thread.state import TeamState


class _CountingSubmitter:
    """Idempotent submitter that returns a fixed proposal id and counts calls.

    Records every ``(phase)`` it is invoked with so tests can assert the gate
    calls it again on resume (replay) and that the returned proposal id is stable.
    """

    def __init__(self, proposal_id: str) -> None:
        self.proposal_id = proposal_id
        self.calls: list[str] = []

    async def __call__(self, state: TeamState, phase: str) -> str:
        self.calls.append(phase)
        return self.proposal_id


def _base_state() -> TeamState:
    return {
        "active_agent": "gate",
        "artifacts": [],
        "current_plan": [],
        "messages": [HumanMessage(content="Gate the research document.")],
        "next": "",
        "thread_id": "gate-thread",
        "active_feature": "adr-authoring-orchestration",
        "token_usage": {},
    }


def _gate_graph(submitter: _CountingSubmitter) -> Any:
    """Build START -> gate -> {approved_end | revise_end} -> END."""
    builder: StateGraph = StateGraph(cast("Any", TeamState))

    async def approved_end(state: TeamState) -> dict[str, Any]:
        return {}

    async def revise_end(state: TeamState) -> dict[str, Any]:
        return {}

    gate = create_phase_gate_node(
        "research",
        submitter,
        approved_target="approved_end",
        revision_target="revise_end",
    )
    builder.add_node("gate", gate)
    builder.add_node("approved_end", approved_end)
    builder.add_node("revise_end", revise_end)
    builder.add_edge(START, "gate")
    builder.add_edge("approved_end", END)
    builder.add_edge("revise_end", END)
    return builder.compile(checkpointer=InMemorySaver())


@pytest.mark.asyncio
async def test_gate_interrupts_with_document_approval_payload() -> None:
    submitter = _CountingSubmitter("prop-1")
    graph = _gate_graph(submitter)
    config = {"configurable": {"thread_id": "gate-interrupt"}}

    first = await graph.ainvoke(_base_state(), config=config)

    assert "__interrupt__" in first
    payload = first["__interrupt__"][0].value
    assert payload == {
        "type": "document_approval_request",
        "phase": "research",
        "proposal_id": "prop-1",
        "feature": "adr-authoring-orchestration",
    }


@pytest.mark.asyncio
async def test_gate_approved_advances_and_records_verdict() -> None:
    submitter = _CountingSubmitter("prop-approve")
    graph = _gate_graph(submitter)
    config = {"configurable": {"thread_id": "gate-approve"}}

    await graph.ainvoke(_base_state(), config=config)
    resumed = await graph.ainvoke(
        Command(resume={"verdict": "approved", "notes": None}), config=config
    )

    assert resumed["next"] == "approved_end"
    assert resumed["gate_phase"] == "research"
    assert resumed["gate_verdict"] == "approved"
    assert resumed["authoring_proposal_ids"] == ["prop-approve"]
    # No revise signal on approval.
    assert not resumed.get("validation_errors")


@pytest.mark.asyncio
async def test_gate_rejected_routes_to_writer_with_notes() -> None:
    submitter = _CountingSubmitter("prop-reject")
    graph = _gate_graph(submitter)
    config = {"configurable": {"thread_id": "gate-reject"}}

    await graph.ainvoke(_base_state(), config=config)
    resumed = await graph.ainvoke(
        Command(
            resume={"verdict": "rejected", "notes": "Frontmatter is missing a date."}
        ),
        config=config,
    )

    assert resumed["next"] == "revise_end"
    assert resumed["gate_verdict"] == "rejected"
    assert resumed["validation_errors"] == ["Frontmatter is missing a date."]


@pytest.mark.asyncio
async def test_gate_request_changes_is_a_revision_verdict() -> None:
    submitter = _CountingSubmitter("prop-rc")
    graph = _gate_graph(submitter)
    config = {"configurable": {"thread_id": "gate-rc"}}

    await graph.ainvoke(_base_state(), config=config)
    resumed = await graph.ainvoke(
        Command(resume={"verdict": "request_changes", "notes": "Compare the options."}),
        config=config,
    )

    assert resumed["next"] == "revise_end"
    assert resumed["gate_verdict"] == "request_changes"
    assert resumed["validation_errors"] == ["Compare the options."]


@pytest.mark.asyncio
async def test_gate_unknown_verdict_fails_closed_to_revision() -> None:
    submitter = _CountingSubmitter("prop-unknown")
    graph = _gate_graph(submitter)
    config = {"configurable": {"thread_id": "gate-unknown"}}

    await graph.ainvoke(_base_state(), config=config)
    resumed = await graph.ainvoke(
        Command(resume={"verdict": "maybe-later", "notes": None}), config=config
    )

    # An unrecognised verdict must not silently advance.
    assert resumed["next"] == "revise_end"
    assert resumed["gate_verdict"] == "rejected"
    assert resumed["validation_errors"]


@pytest.mark.asyncio
async def test_gate_resubmits_idempotently_on_resume() -> None:
    """The submitter runs before the interrupt on every pass, replay included.

    A resumed node re-runs from its start, so the gate calls the submitter again
    on resume; the submitter is idempotent (same proposal id), which is what makes
    the pre-interrupt propose+submit replay-safe.
    """
    submitter = _CountingSubmitter("prop-idem")
    graph = _gate_graph(submitter)
    config = {"configurable": {"thread_id": "gate-idem"}}

    await graph.ainvoke(_base_state(), config=config)
    assert submitter.calls == ["research"]  # first pass, pre-interrupt

    resumed = await graph.ainvoke(
        Command(resume={"verdict": "approved", "notes": None}), config=config
    )
    # Replayed on resume: called a second time, same stable proposal id.
    assert submitter.calls == ["research", "research"]
    assert resumed["authoring_proposal_ids"] == ["prop-idem"]

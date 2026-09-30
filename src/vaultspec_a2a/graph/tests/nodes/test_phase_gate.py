"""Tests for the generalized phase-gate node.

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

from ....graph.nodes.phase_gate import (
    DocumentProposalSubmitter,
    ProposalRevisionRequiredError,
    create_phase_gate_node,
    create_phase_submit_node,
)
from ....thread.state import TeamState
from .._state_graph_helpers import add_test_node, compile_test_graph


class _RefusingSubmitter:
    """A submitter that refuses the body with a conformance revision signal."""

    def __init__(self, notes: list[str]) -> None:
        self.notes = notes
        self.calls: list[str] = []

    async def __call__(self, state: TeamState, phase: str) -> str:
        self.calls.append(phase)
        raise ProposalRevisionRequiredError(self.notes)


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


def _gate_graph(submitter: DocumentProposalSubmitter, *, max_revisions: int = 2) -> Any:
    """Build START -> submit -> gate -> {approved_end | revise_end} -> END.

    The gate is split: a submit node commits the proposal id before the
    pure gate node parks at its interrupt, so the correlation id is durable in the
    checkpoint while parked.
    """
    builder: StateGraph[Any, None, Any, Any] = StateGraph(cast("Any", TeamState))

    async def approved_end(state: TeamState) -> dict[str, Any]:
        return {}

    async def revise_end(state: TeamState) -> dict[str, Any]:
        return {}

    submit = create_phase_submit_node(
        "research",
        submitter,
        gate_target="gate",
        revision_target="revise_end",
        max_revisions=max_revisions,
    )
    gate = create_phase_gate_node(
        "research",
        approved_target="approved_end",
        revision_target="revise_end",
    )
    add_test_node(builder, "submit", submit)
    add_test_node(builder, "gate", gate)
    add_test_node(builder, "approved_end", approved_end)
    add_test_node(builder, "revise_end", revise_end)
    builder.add_edge(START, "submit")
    builder.add_edge("approved_end", END)
    builder.add_edge("revise_end", END)
    return compile_test_graph(builder, checkpointer=InMemorySaver())


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
        # The proposal is also the request identity a verdict must name.
        "request_id": "prop-1",
    }


@pytest.mark.asyncio
async def test_gate_approved_advances_and_records_verdict() -> None:
    submitter = _CountingSubmitter("prop-approve")
    graph = _gate_graph(submitter)
    config = {"configurable": {"thread_id": "gate-approve"}}

    await graph.ainvoke(_base_state(), config=config)
    resumed = await graph.ainvoke(
        Command(
            resume={"verdict": "approved", "notes": None, "request_id": "prop-approve"}
        ),
        config=config,
    )

    assert resumed["next"] == "approved_end"
    assert resumed["gate_phase"] == "research"
    assert resumed["gate_verdict"] == "approved"
    assert resumed["authoring_proposal_ids"] == ["prop-approve"]
    # No revise signal on approval.
    assert not resumed.get("validation_errors")


@pytest.mark.asyncio
async def test_submit_conformance_refusal_routes_to_writer_without_parking() -> None:
    # A submitter that refuses a non-conformant body (raising
    # ProposalRevisionRequiredError BEFORE proposing) must route to the writer as
    # REVISION REQUIRED with the check notes — never park the gate on a proposal
    # that was never submitted.
    notes = [
        "wiki-link in body text: [[some-adr]] - move to related: frontmatter",
        "document must begin with a `---` frontmatter fence",
    ]
    submitter = _RefusingSubmitter(notes)
    graph = _gate_graph(submitter)
    config = {"configurable": {"thread_id": "gate-conformance"}}

    result = await graph.ainvoke(_base_state(), config=config)

    # The run flowed straight through to the writer target (no interrupt), so the
    # invoke returns terminal state rather than an interrupt payload.
    assert result["next"] == "revise_end"
    assert result["gate_verdict"] == "request_changes"
    assert result["validation_errors"] == notes
    # Nothing was committed as a pending proposal — the body never reached submit.
    assert not result.get("gate_pending_proposal_id")
    assert not result.get("authoring_proposal_ids")
    assert submitter.calls == ["research"]


@pytest.mark.asyncio
async def test_gate_rejected_routes_to_writer_with_notes() -> None:
    submitter = _CountingSubmitter("prop-reject")
    graph = _gate_graph(submitter)
    config = {"configurable": {"thread_id": "gate-reject"}}

    await graph.ainvoke(_base_state(), config=config)
    resumed = await graph.ainvoke(
        Command(
            resume={
                "verdict": "rejected",
                "notes": "Frontmatter is missing a date.",
                "request_id": "prop-reject",
            }
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
        Command(
            resume={
                "verdict": "request_changes",
                "notes": "Compare the options.",
                "request_id": "prop-rc",
            }
        ),
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
        Command(
            resume={
                "verdict": "maybe-later",
                "notes": None,
                "request_id": "prop-unknown",
            }
        ),
        config=config,
    )

    # An unrecognised verdict must not silently advance.
    assert resumed["next"] == "revise_end"
    assert resumed["gate_verdict"] == "rejected"
    assert resumed["validation_errors"]


@pytest.mark.asyncio
async def test_submit_commits_ids_before_parking_and_no_resubmit_on_resume() -> None:
    """The split gate commits the proposal id BEFORE the run parks.

    The submit node commits ``authoring_proposal_ids`` as its own superstep, so
    the correlation id is durable in the checkpoint WHILE the gate node is parked
    at its interrupt - this is what lets the out-of-run verdict subscriber
    correlate a verdict to the parked run. Because the resume restarts at the pure
    gate node, the submit node does NOT re-run: the submitter is called exactly
    once across park and resume.
    """
    submitter = _CountingSubmitter("prop-idem")
    graph = _gate_graph(submitter)
    config: Any = {"configurable": {"thread_id": "gate-idem"}}

    await graph.ainvoke(_base_state(), config=config)
    assert submitter.calls == ["research"]  # submit ran once, pre-interrupt

    # While parked, the checkpoint already carries the committed correlation id.
    parked = await graph.aget_state(config)
    assert parked.values.get("authoring_proposal_ids") == ["prop-idem"]
    assert parked.values.get("gate_pending_proposal_id") == "prop-idem"

    resumed = await graph.ainvoke(
        Command(
            resume={"verdict": "approved", "notes": None, "request_id": "prop-idem"}
        ),
        config=config,
    )
    # Resume restarts at the pure gate node; the submit node does NOT re-run.
    assert submitter.calls == ["research"]
    assert resumed["authoring_proposal_ids"] == ["prop-idem"]


@pytest.mark.asyncio
async def test_a_verdict_for_another_request_does_not_approve_this_gate() -> None:
    """An approval that names a different proposal is not this gate's approval.

    LangGraph hands a resume value to whichever ``interrupt()`` asks for one
    next, so a verdict dispatched for a gate the run has already left - or for
    a run that never parked - would otherwise be consumed here as a human
    decision nobody made about this document. The gate asks again, so the
    phase's revision budget is not spent on it, and the verdict the human does
    give on this proposal is the one that decides.
    """
    submitter = _CountingSubmitter("prop-current")
    graph = _gate_graph(submitter)
    config: Any = {"configurable": {"thread_id": "gate-mismatch"}}

    await graph.ainvoke(_base_state(), config=config)
    parked_again = await graph.ainvoke(
        Command(
            resume={
                "verdict": "approved",
                "notes": None,
                "request_id": "prop-superseded",
            }
        ),
        config=config,
    )

    [interrupt] = parked_again["__interrupt__"]
    assert interrupt.value["request_id"] == "prop-current"
    assert parked_again.get("gate_verdict") is None

    resumed = await graph.ainvoke(
        Command(
            resume={"verdict": "approved", "notes": None, "request_id": "prop-current"}
        ),
        config=config,
    )

    assert resumed["next"] == "approved_end"
    assert resumed["gate_verdict"] == "approved"


@pytest.mark.asyncio
async def test_a_verdict_naming_no_request_does_not_approve_this_gate() -> None:
    """An unbound approval is refused rather than trusted.

    It is exactly the answer the run cannot attribute to anyone, which is how
    an approval arrives with no human behind it.
    """
    submitter = _CountingSubmitter("prop-unbound")
    graph = _gate_graph(submitter)
    config: Any = {"configurable": {"thread_id": "gate-unbound"}}

    await graph.ainvoke(_base_state(), config=config)
    parked_again = await graph.ainvoke(
        Command(resume={"verdict": "approved", "notes": None}), config=config
    )

    [interrupt] = parked_again["__interrupt__"]
    assert interrupt.value["request_id"] == "prop-unbound"
    assert parked_again.get("gate_verdict") is None


@pytest.mark.asyncio
async def test_a_gate_with_no_committed_proposal_revises_instead_of_parking() -> None:
    """A gate that has no proposal to name asks no one; it sends the writer back.

    Every answer a client can send names the request it decides, and a gate
    with no committed proposal has no request, so the resume preflight turns
    every answer away. Parking there would leave the run waiting on a question
    nothing can answer.
    """
    builder: StateGraph[Any, None, Any, Any] = StateGraph(cast("Any", TeamState))

    async def approved_end(state: TeamState) -> dict[str, Any]:
        return {}

    async def revise_end(state: TeamState) -> dict[str, Any]:
        return {}

    gate = create_phase_gate_node(
        "research", approved_target="approved_end", revision_target="revise_end"
    )
    add_test_node(builder, "gate", gate)
    add_test_node(builder, "approved_end", approved_end)
    add_test_node(builder, "revise_end", revise_end)
    builder.add_edge(START, "gate")
    builder.add_edge("approved_end", END)
    builder.add_edge("revise_end", END)
    graph = compile_test_graph(builder, checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "gate-no-proposal"}}

    result = await graph.ainvoke(_base_state(), config=config)

    assert "__interrupt__" not in result
    assert result["next"] == "revise_end"
    assert result["gate_verdict"] == "rejected"
    assert any("no committed proposal" in note for note in result["validation_errors"])

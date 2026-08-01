"""Tests for the mid-run clarification node pair.

The pair is exercised over a real ``StateGraph`` with a real ``InMemorySaver``
checkpointer, so the ``interrupt()``, the ``Command(resume=...)``, and the
replay-on-resume are the genuine LangGraph mechanics rather than a simulation of
them. The producer is a small counting object so the tests isolate the node's
determinism, routing, and state recording from any model.

The checkpoint assertions matter as much as the routing ones: the whole point of
committing the question set before parking is that an out-of-process reader can
recover the questionnaire from the checkpoint while the run waits, so the tests
read it back the same way the recovery snapshot does.
"""

from __future__ import annotations

from typing import Any, cast

import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from ....graph.nodes.clarification import (
    ClarificationQuestionProducer,
    create_clarification_gate_node,
    create_clarification_request_node,
)
from ....thread.clarification import (
    ClarificationKind,
    ClarificationQuestion,
    ClarificationRequest,
    pending_clarification,
)
from ....thread.state import TeamState


def _request(request_id: str = "clarify-1") -> ClarificationRequest:
    return ClarificationRequest(
        request_id=request_id,
        questions=[
            ClarificationQuestion(
                id="scope",
                prompt="Which surface should the monitor panel dock to?",
                kind=ClarificationKind.CHOICE,
                options=["right", "left", "bottom"],
            ),
            ClarificationQuestion(
                id="constraints",
                prompt="Any constraints the panel must respect?",
                kind=ClarificationKind.TEXT,
                required=False,
            ),
        ],
    )


class _CountingProducer:
    """Producer returning a fixed request and counting how often it is asked.

    The call count is the evidence for the split: the producer must be consulted
    exactly once across park and resume, because a second consultation would let
    the question a human answers differ from the question they were shown.
    """

    def __init__(self, request: ClarificationRequest | None) -> None:
        self.request = request
        self.calls = 0

    async def __call__(self, state: TeamState) -> ClarificationRequest | None:
        self.calls += 1
        return self.request


class _RaisingProducer:
    """A producer that fails, to prove the failure is not swallowed."""

    async def __call__(self, state: TeamState) -> ClarificationRequest | None:
        msg = "producer could not reach its model"
        raise RuntimeError(msg)


def _base_state() -> TeamState:
    return {
        "active_agent": "clarify",
        "artifacts": [],
        "current_plan": [],
        "messages": [HumanMessage(content="Plan the right-side monitor panel.")],
        "next": "",
        "thread_id": "clarify-thread",
        "active_feature": "agent-panel",
        "token_usage": {},
    }


def _clarify_graph(producer: ClarificationQuestionProducer) -> Any:
    """Build START -> clarify_request -> clarify_gate -> proceed -> END."""
    builder: StateGraph = StateGraph(cast("Any", TeamState))

    async def proceed(state: TeamState) -> dict[str, Any]:
        return {}

    builder.add_node(
        "clarify_request",
        create_clarification_request_node(
            producer, gate_target="clarify_gate", proceed_target="proceed"
        ),
    )
    builder.add_node(
        "clarify_gate", create_clarification_gate_node(proceed_target="proceed")
    )
    builder.add_node("proceed", proceed)
    builder.add_edge(START, "clarify_request")
    builder.add_edge("proceed", END)
    return builder.compile(checkpointer=InMemorySaver())


@pytest.mark.asyncio
async def test_gate_interrupts_with_the_bounded_clarification_payload() -> None:
    graph = _clarify_graph(_CountingProducer(_request()))
    config = {"configurable": {"thread_id": "clarify-interrupt"}}

    first = await graph.ainvoke(_base_state(), config=config)

    assert "__interrupt__" in first
    assert first["__interrupt__"][0].value == {
        "type": "clarification_request",
        "request_id": "clarify-1",
        "questions": [
            {
                "id": "scope",
                "prompt": "Which surface should the monitor panel dock to?",
                "kind": "choice",
                "options": ["right", "left", "bottom"],
                "required": True,
            },
            {
                "id": "constraints",
                "prompt": "Any constraints the panel must respect?",
                "kind": "text",
                "options": None,
                "required": False,
            },
        ],
    }


@pytest.mark.asyncio
async def test_answers_resume_the_run_and_are_recorded_under_the_request_id() -> None:
    graph = _clarify_graph(_CountingProducer(_request()))
    config = {"configurable": {"thread_id": "clarify-resume"}}

    await graph.ainvoke(_base_state(), config=config)
    resumed = await graph.ainvoke(
        Command(
            resume={
                "type": "clarification_response",
                "request_id": "clarify-1",
                "answers": {"scope": "right", "constraints": "must survive a reload"},
            }
        ),
        config=config,
    )

    assert resumed["next"] == "proceed"
    assert resumed["clarification_answers"] == {
        "clarify-1": {"scope": "right", "constraints": "must survive a reload"}
    }
    # The questionnaire is answered, so a later status read must not re-offer it.
    assert resumed.get("clarification_request") is None
    assert resumed.get("clarification_request_id") is None


@pytest.mark.asyncio
async def test_question_set_is_committed_before_parking_and_producer_runs_once() -> (
    None
):
    """The split commits the question set BEFORE the run parks.

    The request node commits as its own superstep, so the questionnaire is
    durable in the checkpoint WHILE the gate node is parked - which is what lets
    an out-of-run reader (the recovery snapshot) re-render it. Because the resume
    restarts at the pure gate node, the producer is NOT consulted a second time.
    """
    producer = _CountingProducer(_request())
    graph = _clarify_graph(producer)
    config: Any = {"configurable": {"thread_id": "clarify-commit"}}

    await graph.ainvoke(_base_state(), config=config)
    assert producer.calls == 1  # consulted once, pre-interrupt

    parked = await graph.aget_state(config)
    assert parked.values.get("clarification_request_id") == "clarify-1"
    assert parked.values["clarification_request"]["questions"][0]["id"] == "scope"

    await graph.ainvoke(
        Command(
            resume={
                "type": "clarification_response",
                "request_id": "clarify-1",
                "answers": {"scope": "left"},
            }
        ),
        config=config,
    )
    assert producer.calls == 1


@pytest.mark.asyncio
async def test_parked_questionnaire_is_readable_from_the_real_checkpoint() -> None:
    """The recovery read finds the parked question set in the run's checkpoint.

    This is the (a) disclosure contract at its source: the same projection the
    run-status route uses is pointed at a genuinely parked graph's checkpoint
    tuple, so what a reloaded client would re-render is proven to be what the
    graph is actually waiting on.
    """
    saver = InMemorySaver()
    builder: StateGraph = StateGraph(cast("Any", TeamState))

    async def proceed(state: TeamState) -> dict[str, Any]:
        return {}

    builder.add_node(
        "clarify_request",
        create_clarification_request_node(
            _CountingProducer(_request("clarify-recover")),
            gate_target="clarify_gate",
            proceed_target="proceed",
        ),
    )
    builder.add_node(
        "clarify_gate", create_clarification_gate_node(proceed_target="proceed")
    )
    builder.add_node("proceed", proceed)
    builder.add_edge(START, "clarify_request")
    builder.add_edge("proceed", END)
    graph = builder.compile(checkpointer=saver)

    config: Any = {"configurable": {"thread_id": "clarify-checkpoint"}}
    await graph.ainvoke(_base_state(), config=config)

    tuple_ = await saver.aget_tuple(config)
    recovered = pending_clarification(tuple_, thread_id="clarify-checkpoint")

    assert recovered is not None
    assert recovered.request_id == "clarify-recover"
    assert [q.id for q in recovered.questions] == ["scope", "constraints"]

    # Once answered, the run is no longer parked and nothing is disclosed.
    await graph.ainvoke(
        Command(
            resume={
                "type": "clarification_response",
                "request_id": "clarify-recover",
                "answers": {"scope": "bottom"},
            }
        ),
        config=config,
    )
    settled = await saver.aget_tuple(config)
    assert pending_clarification(settled, thread_id="clarify-checkpoint") is None


@pytest.mark.asyncio
async def test_producer_with_nothing_to_ask_never_parks_the_run() -> None:
    producer = _CountingProducer(None)
    graph = _clarify_graph(producer)
    config = {"configurable": {"thread_id": "clarify-silent"}}

    result = await graph.ainvoke(_base_state(), config=config)

    # No interrupt at all: the run flowed straight through to the next stage.
    assert "__interrupt__" not in result
    assert result["next"] == "proceed"
    assert result.get("clarification_request") is None
    assert producer.calls == 1


@pytest.mark.asyncio
async def test_answers_for_undeclared_questions_are_dropped() -> None:
    """A resume that never went through the answering verb cannot smuggle keys.

    The verb validates at the boundary; this is the node's own guard for a resume
    that arrived by some other route. An entry naming a question nobody asked has
    nowhere to be routed, so it is dropped rather than recorded.
    """
    graph = _clarify_graph(_CountingProducer(_request()))
    config = {"configurable": {"thread_id": "clarify-undeclared"}}

    await graph.ainvoke(_base_state(), config=config)
    resumed = await graph.ainvoke(
        Command(
            resume={
                "type": "clarification_response",
                "request_id": "clarify-1",
                "answers": {"scope": "right", "not_a_question": "ignored", "n": 5},
            }
        ),
        config=config,
    )

    assert resumed["clarification_answers"] == {"clarify-1": {"scope": "right"}}


@pytest.mark.asyncio
async def test_producer_failure_is_not_swallowed() -> None:
    """A broken producer fails the run rather than silently asking nothing.

    "Ask nothing" already has an explicit representation, so absorbing an
    exception would make a wiring fault indistinguishable from a deliberate
    silence - the failure mode hardest to notice.
    """
    graph = _clarify_graph(_RaisingProducer())
    config = {"configurable": {"thread_id": "clarify-broken"}}

    with pytest.raises(RuntimeError, match="could not reach its model"):
        await graph.ainvoke(_base_state(), config=config)


@pytest.mark.asyncio
async def test_second_questionnaire_does_not_erase_the_first_answers() -> None:
    """Answers accumulate per request id across a multi-question run."""
    first, second = _request("clarify-a"), _request("clarify-b")

    class _TwoShotProducer:
        def __init__(self) -> None:
            self.remaining = [first, second]

        async def __call__(self, state: TeamState) -> ClarificationRequest | None:
            return self.remaining.pop(0) if self.remaining else None

    builder: StateGraph = StateGraph(cast("Any", TeamState))
    producer = _TwoShotProducer()

    builder.add_node(
        "clarify_request",
        create_clarification_request_node(
            producer, gate_target="clarify_gate", proceed_target="second_request"
        ),
    )
    builder.add_node(
        "clarify_gate", create_clarification_gate_node(proceed_target="second_request")
    )
    builder.add_node(
        "second_request",
        create_clarification_request_node(
            producer, gate_target="second_gate", proceed_target="proceed"
        ),
    )
    builder.add_node(
        "second_gate", create_clarification_gate_node(proceed_target="proceed")
    )

    async def proceed(state: TeamState) -> dict[str, Any]:
        return {}

    builder.add_node("proceed", proceed)
    builder.add_edge(START, "clarify_request")
    builder.add_edge("proceed", END)
    graph = builder.compile(checkpointer=InMemorySaver())

    config: Any = {"configurable": {"thread_id": "clarify-twice"}}
    await graph.ainvoke(_base_state(), config=config)
    await graph.ainvoke(
        Command(
            resume={
                "type": "clarification_response",
                "request_id": "clarify-a",
                "answers": {"scope": "right"},
            }
        ),
        config=config,
    )
    final = await graph.ainvoke(
        Command(
            resume={
                "type": "clarification_response",
                "request_id": "clarify-b",
                "answers": {"scope": "left"},
            }
        ),
        config=config,
    )

    assert final["clarification_answers"] == {
        "clarify-a": {"scope": "right"},
        "clarify-b": {"scope": "left"},
    }

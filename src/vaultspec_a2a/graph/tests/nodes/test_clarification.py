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

from typing import TYPE_CHECKING, Any

import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START
from langgraph.types import Command

from ....graph.nodes.clarification import (
    ClarificationQuestionProducer,
    create_clarification_gate_node,
    create_clarification_request_node,
)
from ....testing import (
    add_test_node,
    compile_test_graph,
    new_state_graph,
)
from ....thread import project_checkpoint_tuple
from ....thread.clarification import (
    CLARIFICATION_DECLINE_MARKER,
    ClarificationAnswers,
    ClarificationContinuation,
    ClarificationDecline,
    ClarificationKind,
    ClarificationQuestion,
    ClarificationRequest,
    clarification_resolution_fingerprint,
    pending_clarification,
)

if TYPE_CHECKING:
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
    builder = new_state_graph()

    async def proceed(state: TeamState) -> dict[str, Any]:
        return {}

    add_test_node(
        builder,
        "clarify_request",
        create_clarification_request_node(
            producer, gate_target="clarify_gate", proceed_target="proceed"
        ),
    )
    add_test_node(
        builder,
        "clarify_gate",
        create_clarification_gate_node(proceed_target="proceed"),
    )
    add_test_node(builder, "proceed", proceed)
    builder.add_edge(START, "clarify_request")
    builder.add_edge("proceed", END)
    return compile_test_graph(builder, checkpointer=InMemorySaver())


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
async def test_answers_resume_the_run_and_render_one_transcript_turn() -> None:
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
    expected = clarification_resolution_fingerprint(
        ClarificationAnswers(
            request_id="clarify-1",
            answers={"scope": "right", "constraints": "must survive a reload"},
        )
    )
    assert resumed["clarification_resolution_receipts"] == {"clarify-1": expected}
    # The questionnaire is answered, so a later status read must not re-offer it.
    assert resumed.get("clarification_request") is None
    assert resumed.get("clarification_request_id") is None
    # The transcript is the only state a model turn reads, so it alone carries
    # the answers, as one rendered human turn.
    assert resumed["messages"][-1].content == (
        "Answers to the clarification questionnaire:\n"
        "- Which surface should the monitor panel dock to?: right\n"
        "- Any constraints the panel must respect?: must survive a reload"
    )


@pytest.mark.asyncio
async def test_an_empty_effective_answer_map_appends_no_transcript_turn() -> None:
    """An all-optional questionnaire resolved empty leaves the transcript alone.

    The resolution is still recorded (its receipt), but no contentless human turn
    is put in front of downstream roles.
    """
    request = ClarificationRequest(
        request_id="clarify-1",
        questions=[
            ClarificationQuestion(
                id="notes",
                prompt="Anything else?",
                kind=ClarificationKind.TEXT,
                required=False,
            )
        ],
    )
    graph = _clarify_graph(_CountingProducer(request))
    config = {"configurable": {"thread_id": "clarify-empty-answers"}}

    initial = _base_state()
    await graph.ainvoke(initial, config=config)
    resolution = ClarificationAnswers(request_id="clarify-1", answers={})
    resumed = await graph.ainvoke(
        Command(resume=resolution.as_resume_value()),
        config=config,
    )

    assert resumed["clarification_resolution_receipts"] == {
        "clarify-1": clarification_resolution_fingerprint(resolution)
    }
    assert len(resumed["messages"]) == len(initial["messages"])


@pytest.mark.asyncio
async def test_continuation_records_a_receipt_without_copying_prompt_state() -> None:
    """The prompt lives in messages; its receipt persists only the fingerprint."""
    graph = _clarify_graph(_CountingProducer(_request()))
    config = {"configurable": {"thread_id": "clarify-continuation-receipt"}}
    initial = _base_state()

    await graph.ainvoke(initial, config=config)
    resolution = ClarificationContinuation(
        request_id="clarify-1", prompt="Compare both surfaces before choosing."
    )
    resumed = await graph.ainvoke(
        Command(resume=resolution.as_resume_value()),
        config=config,
    )

    assert resumed["clarification_resolution_receipts"] == {
        "clarify-1": clarification_resolution_fingerprint(resolution)
    }
    assert resumed["messages"][-1].content == resolution.prompt
    assert [message.content for message in resumed["messages"]].count(
        resolution.prompt
    ) == 1
    assert (
        resolution.prompt not in resumed["clarification_resolution_receipts"].values()
    )


@pytest.mark.asyncio
async def test_decline_leaves_one_marker_and_no_answer_turn() -> None:
    """Refusal resumes the run with the fixed marker as its only trace.

    The run advances through the same proceed target as an answered
    questionnaire, the pending request is cleared so a status read stops
    re-offering it, the receipt carries the decline's own fingerprint, and no
    answer turn is fabricated - a declined question was not answered.
    """
    graph = _clarify_graph(_CountingProducer(_request()))
    config = {"configurable": {"thread_id": "clarify-decline"}}

    initial = _base_state()
    await graph.ainvoke(initial, config=config)
    resolution = ClarificationDecline(request_id="clarify-1")
    resumed = await graph.ainvoke(
        Command(resume=resolution.as_resume_value()),
        config=config,
    )

    assert resumed["next"] == "proceed"
    assert resumed["messages"][-1].content == CLARIFICATION_DECLINE_MARKER
    assert [message.content for message in resumed["messages"]].count(
        CLARIFICATION_DECLINE_MARKER
    ) == 1
    assert len(resumed["messages"]) == len(initial["messages"]) + 1
    assert resumed["clarification_resolution_receipts"] == {
        "clarify-1": clarification_resolution_fingerprint(resolution)
    }
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
    builder = new_state_graph()

    async def proceed(state: TeamState) -> dict[str, Any]:
        return {}

    add_test_node(
        builder,
        "clarify_request",
        create_clarification_request_node(
            _CountingProducer(_request("clarify-recover")),
            gate_target="clarify_gate",
            proceed_target="proceed",
        ),
    )
    add_test_node(
        builder,
        "clarify_gate",
        create_clarification_gate_node(proceed_target="proceed"),
    )
    add_test_node(builder, "proceed", proceed)
    builder.add_edge(START, "clarify_request")
    builder.add_edge("proceed", END)
    graph = compile_test_graph(builder, checkpointer=saver)

    config: Any = {"configurable": {"thread_id": "clarify-checkpoint"}}
    await graph.ainvoke(_base_state(), config=config)

    tuple_ = await saver.aget_tuple(config)
    assert tuple_ is not None
    recovered = pending_clarification(
        project_checkpoint_tuple(tuple_, thread_id="clarify-checkpoint")
    )

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
    assert settled is not None
    assert (
        pending_clarification(
            project_checkpoint_tuple(settled, thread_id="clarify-checkpoint")
        )
        is None
    )


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
    nowhere to be routed, so it is dropped rather than rendered.
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

    assert resumed["messages"][-1].content == (
        "Answers to the clarification questionnaire:\n"
        "- Which surface should the monitor panel dock to?: right"
    )


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
async def test_second_questionnaire_appends_its_own_turn_after_the_first() -> None:
    """Each answered questionnaire leaves its own turn across a multi-question run."""
    first, second = _request("clarify-a"), _request("clarify-b")

    class _TwoShotProducer:
        def __init__(self) -> None:
            self.remaining = [first, second]

        async def __call__(self, state: TeamState) -> ClarificationRequest | None:
            return self.remaining.pop(0) if self.remaining else None

    builder = new_state_graph()
    producer = _TwoShotProducer()

    add_test_node(
        builder,
        "clarify_request",
        create_clarification_request_node(
            producer, gate_target="clarify_gate", proceed_target="second_request"
        ),
    )
    add_test_node(
        builder,
        "clarify_gate",
        create_clarification_gate_node(proceed_target="second_request"),
    )
    add_test_node(
        builder,
        "second_request",
        create_clarification_request_node(
            producer, gate_target="second_gate", proceed_target="proceed"
        ),
    )
    add_test_node(
        builder, "second_gate", create_clarification_gate_node(proceed_target="proceed")
    )

    async def proceed(state: TeamState) -> dict[str, Any]:
        return {}

    add_test_node(builder, "proceed", proceed)
    builder.add_edge(START, "clarify_request")
    builder.add_edge("proceed", END)
    graph = compile_test_graph(builder, checkpointer=InMemorySaver())

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

    assert [message.content for message in final["messages"][-2:]] == [
        "Answers to the clarification questionnaire:\n"
        "- Which surface should the monitor panel dock to?: right",
        "Answers to the clarification questionnaire:\n"
        "- Which surface should the monitor panel dock to?: left",
    ]
    assert final["clarification_resolution_receipts"] == {
        "clarify-a": clarification_resolution_fingerprint(
            ClarificationAnswers(request_id="clarify-a", answers={"scope": "right"})
        ),
        "clarify-b": clarification_resolution_fingerprint(
            ClarificationAnswers(request_id="clarify-b", answers={"scope": "left"})
        ),
    }


@pytest.mark.asyncio
async def test_a_refused_answer_re_parks_and_the_next_one_still_resolves() -> None:
    """A bad answer must not end the run's ability to be answered.

    ``interrupt()`` records its resume value against the running task before
    the gate can judge it. A gate that raised on a bad answer left that value
    recorded, so every later answer replayed the bad one and failed the same
    way - the questionnaire became unanswerable for the life of the run.
    """
    graph = _clarify_graph(_CountingProducer(_request()))
    config = {"configurable": {"thread_id": "clarify-refused"}}

    initial = _base_state()
    await graph.ainvoke(initial, config=config)

    # An answer to a request this run never asked.
    reparked = await graph.ainvoke(
        Command(
            resume={
                "type": "clarification_response",
                "request_id": "clarify-from-another-turn",
                "answers": {"scope": "right"},
            }
        ),
        config=config,
    )
    assert "__interrupt__" in reparked
    assert reparked["__interrupt__"][0].value["request_id"] == "clarify-1"

    state = await graph.aget_state(config)
    assert state.values["clarification_request_id"] == "clarify-1"
    assert len(state.values["messages"]) == len(initial["messages"])

    resolved = await graph.ainvoke(
        Command(
            resume={
                "type": "clarification_response",
                "request_id": "clarify-1",
                "answers": {"scope": "right"},
            }
        ),
        config=config,
    )
    assert "__interrupt__" not in resolved
    assert resolved["messages"][-1].content == (
        "Answers to the clarification questionnaire:\n"
        "- Which surface should the monitor panel dock to?: right"
    )
    assert resolved["clarification_request_id"] is None

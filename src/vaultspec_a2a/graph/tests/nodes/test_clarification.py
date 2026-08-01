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

The bounding tests cover the other half of the contract: what a model TURN
proposes is untrusted, so the producer-side coercion degrades a bad proposal
instead of failing the run. Those tests assert against the canonical bounds by
name, never against a literal 4, so a change to the contract moves the test with
it rather than leaving it asserting a stale number.
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
    bound_clarification_questions,
    create_clarification_gate_node,
    create_clarification_request_node,
)
from ....thread.clarification import (
    MAX_IDENTIFIER_CHARS,
    MAX_OPTION_CHARS,
    MAX_OPTIONS_PER_QUESTION,
    MAX_PROMPT_CHARS,
    MAX_QUESTIONS_PER_REQUEST,
    ClarificationAnswers,
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


class TestBoundClarificationQuestions:
    """Producer-side coercion of an untrusted proposed question list."""

    def test_caps_the_question_count(self) -> None:
        proposed = [
            {"id": f"q{i}", "prompt": f"Question {i}?"}
            for i in range(MAX_QUESTIONS_PER_REQUEST * 2 + 2)
        ]
        assert len(bound_clarification_questions(proposed)) == (
            MAX_QUESTIONS_PER_REQUEST
        )

    def test_malformed_leading_entries_do_not_shrink_the_cap_window(self) -> None:
        """Filter THEN cap - the regression this lane has already shipped once.

        The cap bounds the VALID result, not the raw input window. Capping first
        would let the two unusable leaders consume two of the four slots and
        yield ``["q0", "q1"]``; filtering first yields all four valid questions.
        The assertion is on the full id list rather than the length so that a
        cap-then-filter implementation cannot satisfy it by coincidence.
        """
        proposed: list[Any] = [
            {"id": "", "prompt": "unusable: no id"},
            {"id": "blank_prompt", "prompt": ""},
            *(
                {"id": f"q{i}", "prompt": f"Question {i}?"}
                for i in range(MAX_QUESTIONS_PER_REQUEST)
            ),
        ]
        bounded = bound_clarification_questions(proposed)
        assert [question["id"] for question in bounded] == [
            f"q{i}" for i in range(MAX_QUESTIONS_PER_REQUEST)
        ]

    def test_valid_entries_after_the_cap_are_the_only_ones_dropped(self) -> None:
        """The cap keeps the EARLIEST valid questions, in proposal order."""
        proposed = [
            {"id": f"q{i}", "prompt": f"Question {i}?"}
            for i in range(MAX_QUESTIONS_PER_REQUEST + 3)
        ]
        bounded = bound_clarification_questions(proposed)
        assert [question["id"] for question in bounded] == [
            f"q{i}" for i in range(MAX_QUESTIONS_PER_REQUEST)
        ]

    def test_caps_the_option_count_of_a_choice(self) -> None:
        bounded = bound_clarification_questions(
            [
                {
                    "id": "provider",
                    "prompt": "Which provider?",
                    "kind": "choice",
                    "options": [f"opt{i}" for i in range(MAX_OPTIONS_PER_QUESTION * 3)],
                }
            ]
        )
        assert bounded[0]["options"] == [
            f"opt{i}" for i in range(MAX_OPTIONS_PER_QUESTION)
        ]

    def test_drops_entries_missing_an_id_or_a_prompt(self) -> None:
        assert (
            bound_clarification_questions(
                [{"id": "", "prompt": "no id"}, {"id": "q1", "prompt": ""}]
            )
            == []
        )

    def test_drops_ids_outside_the_answer_key_grammar(self) -> None:
        """An id the answer path could never key is dropped, not advertised.

        Answers travel as JSON object keys and in a URL path, so the identifier
        alphabet is the contract's, not the model's imagination. A question with
        an unroutable id would park a run on something no client can answer.
        """
        proposed = [
            {"id": "has space", "prompt": "unroutable"},
            {"id": "emoji😀id", "prompt": "unroutable"},
            {"id": "slash/id", "prompt": "unroutable"},
            {"id": "colon:id", "prompt": "unroutable"},
            {"id": "good_id-1.2", "prompt": "routable"},
        ]
        bounded = bound_clarification_questions(proposed)
        assert [question["id"] for question in bounded] == ["good_id-1.2"]

    def test_drops_an_id_with_a_leading_hyphen_but_not_a_mid_string_one(self) -> None:
        """A leading hyphen is a distinct rejection from a mid-string one."""
        proposed = [
            {"id": "-leading", "prompt": "unroutable"},
            {"id": "good-id", "prompt": "routable"},
        ]
        bounded = bound_clarification_questions(proposed)
        assert [question["id"] for question in bounded] == ["good-id"]

    def test_drops_a_duplicate_id_keeping_the_first(self) -> None:
        bounded = bound_clarification_questions(
            [
                {"id": "q1", "prompt": "First"},
                {"id": "q1", "prompt": "Second, same id"},
            ]
        )
        assert [(q["id"], q["prompt"]) for q in bounded] == [("q1", "First")]

    def test_an_unknown_kind_reads_as_text(self) -> None:
        bounded = bound_clarification_questions(
            [{"id": "q1", "prompt": "How?", "kind": "essay"}]
        )
        assert bounded[0]["kind"] == "text"
        assert "options" not in bounded[0]

    def test_a_text_question_carries_no_options_key(self) -> None:
        bounded = bound_clarification_questions(
            [{"id": "q1", "prompt": "How?", "kind": "text", "options": ["a", "b"]}]
        )
        assert bounded == [
            {"id": "q1", "prompt": "How?", "kind": "text", "required": False}
        ]

    def test_strips_control_characters_from_a_prompt(self) -> None:
        bounded = bound_clarification_questions(
            [{"id": "q1", "prompt": "line one\nline two\ttabbed"}]
        )
        assert bounded[0]["prompt"] == "line oneline twotabbed"

    def test_strips_tab_from_an_option_label_so_the_option_stays_answerable(
        self,
    ) -> None:
        """A tab kept here would make the option it labels unanswerable.

        An option is offered verbatim and an answer must match it verbatim, but
        a tab is a control character on the answer path - so a label carrying
        one could only be matched by a string the answer path refuses, parking
        the run on a question with no admissible answer. Stripping it here is
        what keeps the offered label and the acceptable answer the same string.
        """
        bounded = bound_clarification_questions(
            [
                {
                    "id": "q1",
                    "prompt": "Which lane?",
                    "kind": "choice",
                    "options": ["web\tlane", "local lane"],
                }
            ]
        )
        offered = bounded[0]["options"][0]
        assert offered == "weblane"
        # The proof that matters is not the spelling but that the offered label
        # is admissible as an answer to its own question.
        assert ClarificationAnswers(request_id="r1", answers={"q1": offered})

    def test_strips_del_and_c1_controls_the_edge_would_also_refuse(self) -> None:
        """Control characters above the C0 block are stripped too.

        DEL and the C1 range are Unicode ``Cc`` exactly as C0 is, and the
        browser edge ahead of this one tests that same category. A narrower
        rule here would emit text that edge refuses.
        """
        bounded = bound_clarification_questions(
            [{"id": "q1", "prompt": "del\x7fhere\x85and-c1"}]
        )
        assert bounded[0]["prompt"] == "delhereand-c1"

    def test_truncates_overlong_strings_to_the_canonical_bounds(self) -> None:
        bounded = bound_clarification_questions(
            [
                {
                    "id": "i" * (MAX_IDENTIFIER_CHARS + 20),
                    "prompt": "p" * (MAX_PROMPT_CHARS + 20),
                    "kind": "choice",
                    "options": ["o" * (MAX_OPTION_CHARS + 20)],
                }
            ]
        )
        assert len(bounded[0]["id"]) == MAX_IDENTIFIER_CHARS
        assert len(bounded[0]["prompt"]) == MAX_PROMPT_CHARS
        assert len(bounded[0]["options"][0]) == MAX_OPTION_CHARS

    def test_non_dict_entries_are_dropped(self) -> None:
        assert bound_clarification_questions(["not-a-dict", 42, None, []]) == []

    def test_choice_options_are_deduplicated_and_blanks_dropped(self) -> None:
        bounded = bound_clarification_questions(
            [
                {
                    "id": "q1",
                    "prompt": "Pick",
                    "kind": "choice",
                    "options": ["a", "a", "", "b"],
                }
            ]
        )
        assert bounded[0]["options"] == ["a", "b"]

    def test_a_choice_left_with_no_usable_option_is_dropped(self) -> None:
        """A choice offering nothing to choose is not a renderable question."""
        proposed = [
            {"id": "empty", "prompt": "Pick", "kind": "choice", "options": []},
            {"id": "blanks", "prompt": "Pick", "kind": "choice", "options": ["", ""]},
            {"id": "wrong_type", "prompt": "Pick", "kind": "choice", "options": "a,b"},
            {"id": "absent", "prompt": "Pick", "kind": "choice"},
        ]
        assert bound_clarification_questions(proposed) == []

    def test_an_unstated_requirement_reads_as_optional(self) -> None:
        bounded = bound_clarification_questions([{"id": "q1", "prompt": "How?"}])
        assert bounded[0]["required"] is False

    def test_bounded_output_is_admissible_to_the_wire_contract(self) -> None:
        """The whole point of the coercion: what survives it always constructs.

        The two layers are only complementary if the producer's output never
        trips the wire's refusal. This drives a deliberately hostile proposal
        through the coercion and then builds the real request from the result -
        a bound the coercion failed to honour would raise here.
        """
        proposed: list[Any] = [
            "not-a-dict",
            {"id": "bad id", "prompt": "unroutable"},
            {"id": "q1", "prompt": "p" * (MAX_PROMPT_CHARS + 50)},
            {
                "id": "q2",
                "prompt": "Pick one",
                "kind": "choice",
                "options": [f"opt{i}" for i in range(MAX_OPTIONS_PER_QUESTION + 5)],
                "required": True,
            },
            *(
                {"id": f"extra{i}", "prompt": f"Extra {i}?"}
                for i in range(MAX_QUESTIONS_PER_REQUEST)
            ),
        ]
        bounded = bound_clarification_questions(proposed)

        request = ClarificationRequest(
            request_id="clarify-bounded",
            questions=[ClarificationQuestion(**question) for question in bounded],
        )

        assert [question.id for question in request.questions] == [
            "q1",
            "q2",
            "extra0",
            "extra1",
        ]
        choice = request.question("q2")
        assert choice is not None
        assert choice.kind is ClarificationKind.CHOICE
        assert len(choice.options or []) == MAX_OPTIONS_PER_QUESTION

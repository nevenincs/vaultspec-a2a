"""Tests for the mid-run clarification interrupt node (agent-flow ADR D5).

The node is exercised over a real ``StateGraph`` with an ``InMemorySaver``
checkpointer, mirroring ``test_phase_gate.py``: the interrupt/resume and the
replay-on-resume are real, not simulated.
"""

from __future__ import annotations

from typing import Any, cast

import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from ....thread.state import TeamState
from ...nodes.clarification import (
    MAX_ANSWER_CHARS,
    MAX_CLARIFICATION_QUESTIONS,
    MAX_QUESTION_OPTIONS,
    bound_clarification_questions,
    create_clarification_node,
)


def _base_state(questions: list[dict[str, Any]]) -> TeamState:
    return {
        "active_agent": "clarification",
        "artifacts": [],
        "current_plan": [],
        "messages": [HumanMessage(content="Ground the feature.")],
        "next": "",
        "thread_id": "clarify-thread",
        "active_feature": "agent-panel",
        "token_usage": {},
        "clarification_questions": questions,
    }


def _graph() -> Any:
    """Build START -> clarification -> END for isolated node testing."""
    builder: StateGraph = StateGraph(cast("Any", TeamState))
    builder.add_node("clarification", create_clarification_node())
    builder.add_edge(START, "clarification")
    builder.add_edge("clarification", END)
    return builder.compile(checkpointer=InMemorySaver())


_ONE_QUESTION = [
    {"id": "scope", "prompt": "Which module should this target?", "kind": "text"}
]
_CHOICE_QUESTION = [
    {
        "id": "provider",
        "prompt": "Which provider should author the plan?",
        "kind": "choice",
        "options": ["codex", "zai"],
        "required": True,
    }
]


class TestBoundClarificationQuestions:
    """Pure-logic bounding: truncate, never raise."""

    def test_caps_question_count(self) -> None:
        questions = [
            {"id": f"q{i}", "prompt": f"Question {i}?"} for i in range(10)
        ]
        bounded = bound_clarification_questions(questions)
        assert len(bounded) == MAX_CLARIFICATION_QUESTIONS

    def test_caps_option_count_for_choice_questions(self) -> None:
        questions = [
            {
                "id": "q1",
                "prompt": "Pick one",
                "kind": "choice",
                "options": [f"opt{i}" for i in range(10)],
            }
        ]
        bounded = bound_clarification_questions(questions)
        assert len(bounded[0]["options"]) == MAX_QUESTION_OPTIONS

    def test_drops_entries_missing_id_or_prompt(self) -> None:
        questions = [{"id": "", "prompt": "no id"}, {"id": "q1", "prompt": ""}]
        assert bound_clarification_questions(questions) == []

    def test_drops_duplicate_ids(self) -> None:
        questions = [
            {"id": "q1", "prompt": "First"},
            {"id": "q1", "prompt": "Second, same id"},
        ]
        bounded = bound_clarification_questions(questions)
        assert len(bounded) == 1
        assert bounded[0]["prompt"] == "First"

    def test_unknown_kind_falls_back_to_text(self) -> None:
        bounded = bound_clarification_questions(
            [{"id": "q1", "prompt": "?", "kind": "essay"}]
        )
        assert bounded[0]["kind"] == "text"

    def test_strips_control_characters_from_prompt(self) -> None:
        bounded = bound_clarification_questions(
            [{"id": "q1", "prompt": "line one\nline two\ttabbed"}]
        )
        assert "\n" not in bounded[0]["prompt"]
        assert bounded[0]["prompt"] == "line oneline two\ttabbed"

    def test_non_dict_entries_are_skipped(self) -> None:
        assert bound_clarification_questions(["not-a-dict", 42, None]) == []

    def test_choice_options_deduplicated_and_empty_dropped(self) -> None:
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


class TestClarificationNode:
    @pytest.mark.asyncio
    async def test_empty_question_list_is_a_no_op_passthrough(self) -> None:
        graph = _graph()
        config = {"configurable": {"thread_id": "clarify-empty"}}
        result = await graph.ainvoke(_base_state([]), config=config)
        assert "__interrupt__" not in result
        assert result.get("clarification_answers") is None

    @pytest.mark.asyncio
    async def test_interrupts_with_bounded_question_payload(self) -> None:
        graph = _graph()
        config = {"configurable": {"thread_id": "clarify-interrupt"}}
        result = await graph.ainvoke(_base_state(_CHOICE_QUESTION), config=config)

        assert "__interrupt__" in result
        payload = result["__interrupt__"][0].value
        assert payload["type"] == "clarification_request"
        assert isinstance(payload["request_id"], str) and payload["request_id"]
        assert payload["questions"] == [
            {
                "id": "provider",
                "prompt": "Which provider should author the plan?",
                "kind": "choice",
                "required": True,
                "options": ["codex", "zai"],
            }
        ]

    @pytest.mark.asyncio
    async def test_resume_records_bounded_answers(self) -> None:
        graph = _graph()
        config = {"configurable": {"thread_id": "clarify-resume"}}
        await graph.ainvoke(_base_state(_ONE_QUESTION), config=config)

        resumed = await graph.ainvoke(
            Command(resume={"scope": "authoring/submitter.py"}), config=config
        )
        assert "__interrupt__" not in resumed
        assert resumed["clarification_answers"] == {
            "scope": "authoring/submitter.py"
        }

    @pytest.mark.asyncio
    async def test_resume_answer_is_capped_and_single_line(self) -> None:
        graph = _graph()
        config = {"configurable": {"thread_id": "clarify-cap"}}
        await graph.ainvoke(_base_state(_ONE_QUESTION), config=config)

        overlong = "x" * (MAX_ANSWER_CHARS + 500) + "\nmore after a newline"
        resumed = await graph.ainvoke(
            Command(resume={"scope": overlong}), config=config
        )
        answer = resumed["clarification_answers"]["scope"]
        assert len(answer) <= MAX_ANSWER_CHARS
        assert "\n" not in answer

    @pytest.mark.asyncio
    async def test_resume_ignores_answers_for_unknown_non_string_keys(self) -> None:
        graph = _graph()
        config = {"configurable": {"thread_id": "clarify-nonstring"}}
        await graph.ainvoke(_base_state(_ONE_QUESTION), config=config)

        # A malformed resume (non-dict) must not crash the node.
        resumed = await graph.ainvoke(Command(resume="not-a-dict"), config=config)
        assert resumed["clarification_answers"] == {}

    @pytest.mark.asyncio
    async def test_replay_on_resume_recomputes_the_same_bounded_payload(self) -> None:
        """A resumed run re-executes the node from its start (interrupt semantics).

        Bounding runs again on replay; it must be deterministic, matching the
        parked interrupt's payload exactly (no drift between park and resume).
        """
        graph = _graph()
        config = {"configurable": {"thread_id": "clarify-replay"}}
        first = await graph.ainvoke(_base_state(_CHOICE_QUESTION), config=config)
        parked_questions = first["__interrupt__"][0].value["questions"]

        resumed = await graph.ainvoke(
            Command(resume={"provider": "codex"}), config=config
        )
        # The answer is recorded, and the checkpoint's own bounded question set
        # (re-derived on replay) is unchanged from what parked originally.
        assert resumed["clarification_answers"] == {"provider": "codex"}
        replayed_state = await graph.aget_state(config)
        assert (
            bound_clarification_questions(
                replayed_state.values.get("clarification_questions", [])
            )
            == parked_questions
        )

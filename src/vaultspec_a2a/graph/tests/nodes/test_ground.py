"""Tests for the pre-diverge ground decision node (agent-flow ADR D5 wiring)."""

from __future__ import annotations

import json
from typing import Any, cast

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from ....thread.state import TeamState
from ...nodes.ground import (
    GROUND_CLARIFICATION_SENTINEL,
    GROUND_READY_SENTINEL,
    GROUND_SYSTEM_PROMPT,
    _parse_ground_clarification,
    create_ground_node,
)

_ONE_QUESTION_JSON = json.dumps(
    [{"id": "scope", "prompt": "Which module?", "kind": "text"}]
)


class TestParseGroundClarification:
    """Pure-logic sentinel parsing: fail-open on anything malformed."""

    def test_no_sentinel_returns_empty(self) -> None:
        assert _parse_ground_clarification(GROUND_READY_SENTINEL) == []

    def test_plain_prose_without_sentinel_returns_empty(self) -> None:
        assert _parse_ground_clarification("Sure, I'll get started.") == []

    def test_sentinel_with_valid_json_parses_and_bounds(self) -> None:
        content = f"{GROUND_CLARIFICATION_SENTINEL}\n{_ONE_QUESTION_JSON}"
        questions = _parse_ground_clarification(content)
        assert questions == [
            {
                "id": "scope",
                "prompt": "Which module?",
                "kind": "text",
                "required": False,
            }
        ]

    def test_sentinel_with_malformed_json_fails_open(self) -> None:
        content = f"{GROUND_CLARIFICATION_SENTINEL}\nnot valid json"
        assert _parse_ground_clarification(content) == []

    def test_sentinel_with_no_body_fails_open(self) -> None:
        assert _parse_ground_clarification(GROUND_CLARIFICATION_SENTINEL) == []

    def test_sentinel_with_non_list_json_fails_open(self) -> None:
        content = f'{GROUND_CLARIFICATION_SENTINEL}\n{{"id": "scope"}}'
        assert _parse_ground_clarification(content) == []

    def test_sentinel_line_must_match_exactly_not_mid_prose(self) -> None:
        content = f"I think {GROUND_CLARIFICATION_SENTINEL} here.\n{_ONE_QUESTION_JSON}"
        assert _parse_ground_clarification(content) == []

    def test_sentinel_respects_the_question_count_cap(self) -> None:
        many = json.dumps(
            [{"id": f"q{i}", "prompt": f"Q{i}?"} for i in range(10)]
        )
        content = f"{GROUND_CLARIFICATION_SENTINEL}\n{many}"
        assert len(_parse_ground_clarification(content)) == 4


def _graph(model: Any) -> Any:
    """Build START -> ground -> {clarify_end | proceed_end} for isolated testing.

    Each terminal node stamps ``active_agent`` with its own name so a test can
    tell which branch the ground node actually routed to.
    """
    builder: StateGraph = StateGraph(cast("Any", TeamState))

    async def clarify_end(state: TeamState) -> dict[str, Any]:
        return {"active_agent": "clarify_end"}

    async def proceed_end(state: TeamState) -> dict[str, Any]:
        return {"active_agent": "proceed_end"}

    builder.add_node(
        "ground",
        create_ground_node(
            model,
            GROUND_SYSTEM_PROMPT,
            clarify_target="clarify_end",
            proceed_target="proceed_end",
        ),
    )
    builder.add_node("clarify_end", clarify_end)
    builder.add_node("proceed_end", proceed_end)
    builder.add_edge(START, "ground")
    builder.add_edge("clarify_end", END)
    builder.add_edge("proceed_end", END)
    return builder.compile(checkpointer=InMemorySaver())


def _state() -> TeamState:
    return cast(
        "TeamState",
        {
            "messages": [HumanMessage(content="Research the phase machine.")],
            "thread_id": "ground-node-thread",
        },
    )


@pytest.mark.asyncio
async def test_ground_ready_routes_to_proceed_target() -> None:
    model = FakeListChatModel(responses=[GROUND_READY_SENTINEL])
    graph = _graph(model)
    result = await graph.ainvoke(
        _state(), config={"configurable": {"thread_id": "ready"}}
    )
    assert result["active_agent"] == "proceed_end"
    assert result.get("clarification_questions") is None


@pytest.mark.asyncio
async def test_clarification_sentinel_routes_to_clarify_target_with_questions() -> None:
    content = f"{GROUND_CLARIFICATION_SENTINEL}\n{_ONE_QUESTION_JSON}"
    model = FakeListChatModel(responses=[content])
    graph = _graph(model)
    result = await graph.ainvoke(
        _state(), config={"configurable": {"thread_id": "clarify"}}
    )
    assert result["active_agent"] == "clarify_end"
    assert result["clarification_questions"] == [
        {
            "id": "scope",
            "prompt": "Which module?",
            "kind": "text",
            "required": False,
        }
    ]


@pytest.mark.asyncio
async def test_malformed_clarification_fails_open_to_proceed() -> None:
    """A garbled ground turn must never wedge the pipeline."""
    content = f"{GROUND_CLARIFICATION_SENTINEL}\nnot json"
    model = FakeListChatModel(responses=[content])
    graph = _graph(model)
    result = await graph.ainvoke(
        _state(), config={"configurable": {"thread_id": "malformed"}}
    )
    assert result["active_agent"] == "proceed_end"
    assert result.get("clarification_questions") is None

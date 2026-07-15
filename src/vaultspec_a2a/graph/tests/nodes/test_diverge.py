"""Tests for the Send-based diverge stage (adr-authoring-orchestration S04).

The fan-out/join structure is exercised over a real ``StateGraph`` with an
``InMemorySaver`` checkpointer -- no mocks. The researcher work is a small
deterministic producer so the test isolates the diverge structure (dispatch
fan-out, per-branch findings, reducer accumulation, synthesis join) from any
model.
"""

from __future__ import annotations

from typing import Any, cast

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from vaultspec_a2a.graph.compiler import _wire_diverge_stage
from vaultspec_a2a.graph.nodes.diverge import (
    create_research_dispatch_node,
    create_researcher_node,
    researcher_node_name,
)
from vaultspec_a2a.thread.state import TeamState

_SPECS: list[dict[str, Any]] = [
    {"thread_id": "codebase", "locators": ["compiler.py:402"]},
    {"thread_id": "prior-art", "locators": ["Send docs"]},
    {"thread_id": "engine", "locators": ["events endpoint"]},
]


def _base_state() -> TeamState:
    return {
        "active_agent": "dispatch",
        "artifacts": [],
        "current_plan": [],
        "messages": [HumanMessage(content="Research the phase machine.")],
        "next": "",
        "thread_id": "diverge-thread",
        "token_usage": {},
    }


async def _fake_producer(state: TeamState, spec: dict[str, Any]) -> dict[str, Any]:
    """Deterministic finding producer derived solely from the thread spec."""
    return {
        "claim": f"finding from {spec['thread_id']}",
        "locators": spec["locators"],
        "source_thread": spec["thread_id"],
    }


@pytest.mark.asyncio
async def test_dispatch_emits_one_send_per_researcher() -> None:
    node = create_research_dispatch_node(["r00", "r01", "r02"])
    command = await node(_base_state())
    assert isinstance(command, Command)
    assert command.goto is not None
    assert [send.node for send in command.goto] == ["r00", "r01", "r02"]


@pytest.mark.asyncio
async def test_researcher_node_appends_single_finding() -> None:
    node = create_researcher_node(_SPECS[0], _fake_producer)
    result = await node(_base_state())
    assert result == {
        "research_findings": [
            {
                "claim": "finding from codebase",
                "locators": ["compiler.py:402"],
                "source_thread": "codebase",
            }
        ]
    }


@pytest.mark.asyncio
async def test_researcher_node_rejects_finding_missing_contract_key() -> None:
    """A producer output missing a contract key fails fast at the branch."""

    async def bad_producer(state: TeamState, spec: dict[str, Any]) -> dict[str, Any]:
        return {"claim": "no locators or source_thread"}

    node = create_researcher_node(_SPECS[0], bad_producer)
    with pytest.raises(ValueError, match="missing required key"):
        await node(_base_state())


@pytest.mark.asyncio
async def test_researcher_node_rejects_finding_wrong_type() -> None:
    """A producer output with a wrong-typed field fails fast at the branch."""

    async def bad_producer(state: TeamState, spec: dict[str, Any]) -> dict[str, Any]:
        return {"claim": "c", "locators": "not-a-list", "source_thread": "t"}

    node = create_researcher_node(_SPECS[0], bad_producer)
    with pytest.raises(TypeError, match="locators"):
        await node(_base_state())


@pytest.mark.asyncio
async def test_diverge_stage_accumulates_findings_and_joins() -> None:
    """All parallel branches accumulate into research_findings before synthesis.

    The synthesis node runs once (the join), and by the time it runs every
    researcher branch's finding is visible through the reducer.
    """
    builder: StateGraph = StateGraph(cast("Any", TeamState))

    seen_at_synthesis: dict[str, list[dict[str, Any]]] = {}

    async def synthesis_node(state: TeamState) -> dict[str, Any]:
        seen_at_synthesis["findings"] = list(state.get("research_findings") or [])
        return {"messages": [AIMessage(content="synthesised", name="synthesist")]}

    dispatch = _wire_diverge_stage(
        builder,
        dispatch_name="research_dispatch",
        synthesis_name="synthesis",
        specs=_SPECS,
        make_researcher=lambda spec: create_researcher_node(spec, _fake_producer),
    )
    builder.add_node("synthesis", synthesis_node)
    builder.add_edge(START, dispatch)
    builder.add_edge("synthesis", END)
    graph = builder.compile(checkpointer=InMemorySaver())

    result = await graph.ainvoke(
        _base_state(), config={"configurable": {"thread_id": "diverge-run"}}
    )

    threads = sorted(f["source_thread"] for f in result["research_findings"])
    assert threads == ["codebase", "engine", "prior-art"]
    # Synthesis observed the full accumulated set at the join, not a partial one.
    assert len(seen_at_synthesis["findings"]) == len(_SPECS)


@pytest.mark.asyncio
async def test_wire_diverge_stage_rejects_empty_specs() -> None:
    from vaultspec_a2a.thread.errors import ConfigError

    builder: StateGraph = StateGraph(cast("Any", TeamState))
    with pytest.raises(ConfigError, match="at least one research thread spec"):
        _wire_diverge_stage(
            builder,
            dispatch_name="research_dispatch",
            synthesis_name="synthesis",
            specs=[],
            make_researcher=lambda spec: create_researcher_node(spec, _fake_producer),
        )


def test_researcher_node_name_is_deterministic() -> None:
    assert (
        researcher_node_name("research_dispatch", 0)
        == "research_dispatch_researcher_00"
    )
    assert researcher_node_name("research_dispatch", 12) == (
        "research_dispatch_researcher_12"
    )

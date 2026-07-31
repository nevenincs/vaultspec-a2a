"""Interrupt-to-frame projection of ACP permission options.

Real objects throughout: a real ``StateGraph`` compiled with LangGraph's
``InMemorySaver``, suspended by a real ``interrupt()`` call, inspected through
the real ``aget_state`` checkpointer read, and projected by the real
``emit_interrupt_events`` into a real ``EventAggregator``. Nothing here stands in
for production code, so the assertions describe what a dashboard client actually
receives.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import pytest
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from typing_extensions import TypedDict

from ..aggregator import EventAggregator
from ..transformer import emit_interrupt_events

if TYPE_CHECKING:
    from ..types import StreamableGraph


class _GateState(TypedDict):
    """Minimal graph state: the offered options carried into the gate node."""

    acp_options: list[dict[str, Any]]


async def _suspend_on_permission(thread_id: str, acp_options: list[dict[str, Any]]):
    """Run a real graph to a real permission interrupt and return graph + config."""

    def gate(state: _GateState) -> _GateState:
        interrupt(
            {
                "type": "permission_request",
                "tool_name": "Edit",
                "tool_input": {"path": "src/a.py"},
                "options": state["acp_options"],
            }
        )
        return state

    builder = StateGraph(cast("Any", _GateState))
    builder.add_node("gate", gate)
    builder.add_edge(START, "gate")
    builder.add_edge("gate", END)
    graph = builder.compile(checkpointer=InMemorySaver())

    config = RunnableConfig(configurable={"thread_id": thread_id})
    result = await graph.ainvoke({"acp_options": acp_options}, config)
    assert "__interrupt__" in result  # the graph really did suspend

    return cast("StreamableGraph", graph), cast("dict[str, Any]", config)


async def _project(thread_id: str, acp_options: list[dict[str, Any]]) -> list[dict]:
    """Return the option list a client receives for the given ACP options."""
    aggregator = EventAggregator()
    graph, config = await _suspend_on_permission(thread_id, acp_options)

    emitted = await emit_interrupt_events(
        thread_id, "coder", graph, config, aggregator._emitters
    )
    assert emitted

    pending = aggregator.get_pending_permissions(thread_id)
    assert len(pending) == 1
    return pending[0].options


@pytest.mark.asyncio
async def test_both_option_id_spellings_reach_the_client_intact() -> None:
    """The projection normalises either wire spelling onto ``option_id``."""
    options = await _project(
        "thread-mixed",
        [
            {"option_id": "allow_always", "label": "Always allow"},
            {"optionId": "reject_once", "label": "Deny"},
        ],
    )

    assert [opt["option_id"] for opt in options] == ["allow_always", "reject_once"]
    assert [opt["name"] for opt in options] == ["Always allow", "Deny"]
    assert [str(opt["kind"]) for opt in options] == ["allow_always", "reject_once"]


@pytest.mark.asyncio
async def test_an_option_id_present_but_null_does_not_reach_the_client() -> None:
    """A present-but-null key defeated the old ``dict.get`` fallback chain.

    ``opt.get("optionId", ...)`` returns ``None`` when the key exists with a null
    value — the default never fires — so a null id was projected into the frame
    and offered to the dashboard as something a human could answer with.
    """
    options = await _project("thread-null", [{"optionId": None, "label": "Broken"}])

    assert options[0]["option_id"] == "allow_once"
    assert options[0]["option_id"] is not None


@pytest.mark.asyncio
async def test_an_options_list_the_agent_omits_falls_back_to_allow_and_deny() -> None:
    """An agent offering nothing still yields an answerable pair."""
    options = await _project("thread-empty", [])

    assert [opt["option_id"] for opt in options] == ["allow_once", "deny_once"]

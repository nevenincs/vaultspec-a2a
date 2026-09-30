"""A permission answer applies only to the tool call it was given for.

A resumed LangGraph node replays its whole turn, and a provider's regenerated
turn may ask about a different call than the one the human saw. A real graph
over a real checkpointer drives the worker's permission callback through that
replay: an answer naming one request must never be handed to another call,
the run must park again on the call actually being made, and the same call
asked again must receive its answer.
"""

from __future__ import annotations

from typing import Any, TypedDict, cast

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from ...nodes.worker import _interrupt_permission_callback

_OPTIONS = [
    {"optionId": "allow_once", "name": "Allow once", "kind": "allow_once"},
    {"optionId": "reject_once", "name": "Reject once", "kind": "reject_once"},
]


class _Turn(TypedDict):
    granted: list[str]


def _graph(calls: list[tuple[str, dict[str, Any]]], granted: list[str]) -> Any:
    """One node that asks permission for the next scripted call on every run."""

    async def ask(state: _Turn) -> dict[str, list[str]]:
        del state
        tool_name, tool_input = calls.pop(0)
        option = await _interrupt_permission_callback(tool_name, tool_input, _OPTIONS)
        granted.append(f"{tool_name}:{option}")
        return {"granted": [option]}

    builder: StateGraph[Any, None, Any, Any] = StateGraph(cast("Any", _Turn))
    builder.add_node("ask", ask)
    builder.add_edge(START, "ask")
    builder.add_edge("ask", END)
    return builder.compile(checkpointer=InMemorySaver())


def _parked(result: dict[str, Any]) -> dict[str, Any]:
    interrupts = result["__interrupt__"]
    assert len(interrupts) == 1
    return cast("dict[str, Any]", interrupts[0].value)


_CONFIG = {"configurable": {"thread_id": "permission-binding"}}


@pytest.mark.asyncio
async def test_an_answer_is_not_applied_to_a_different_replayed_call() -> None:
    read_secrets = ("Bash", {"command": "cat ~/.ssh/id_rsa"})
    list_files = ("Bash", {"command": "ls"})
    granted: list[str] = []
    graph = _graph([list_files, read_secrets, read_secrets], granted)

    first = _parked(await graph.ainvoke({"granted": []}, _CONFIG))
    assert first["tool_input"] == {"command": "ls"}

    # The human allows `ls`, but the replayed turn now asks to read a key.
    second = _parked(
        await graph.ainvoke(
            Command(
                resume={"option_id": "allow_once", "request_id": first["request_id"]}
            ),
            _CONFIG,
        )
    )
    assert granted == []
    assert second["tool_input"] == {"command": "cat ~/.ssh/id_rsa"}
    assert second["request_id"] != first["request_id"]

    # Answering the call actually being made is what lets the turn proceed.
    final = await graph.ainvoke(
        Command(
            resume={"option_id": "reject_once", "request_id": second["request_id"]}
        ),
        _CONFIG,
    )
    assert "__interrupt__" not in final
    assert granted == ["Bash:reject_once"]


@pytest.mark.asyncio
async def test_the_same_call_asked_again_receives_its_answer() -> None:
    list_files = ("Bash", {"command": "ls"})
    granted: list[str] = []
    graph = _graph([list_files, list_files], granted)

    parked = _parked(await graph.ainvoke({"granted": []}, _CONFIG))
    final = await graph.ainvoke(
        Command(resume={"option_id": "allow_once", "request_id": parked["request_id"]}),
        _CONFIG,
    )

    assert "__interrupt__" not in final
    assert granted == ["Bash:allow_once"]


@pytest.mark.asyncio
async def test_an_answer_naming_no_request_is_taken_as_before() -> None:
    list_files = ("Bash", {"command": "ls"})
    granted: list[str] = []
    graph = _graph([list_files, list_files], granted)

    await graph.ainvoke({"granted": []}, _CONFIG)
    final = await graph.ainvoke(Command(resume="allow_once"), _CONFIG)

    assert "__interrupt__" not in final
    assert granted == ["Bash:allow_once"]

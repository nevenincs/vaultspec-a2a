"""A permission answer applies only to the tool call it was given for.

A resumed LangGraph node replays its whole turn, and a provider's regenerated
turn may ask about a different call than the one the human saw. A real graph
over a real checkpointer drives the worker's permission callback through that
replay: an answer naming one request must never be handed to another call,
the run must park again on the call actually being made, and the same call
asked again must receive its answer.

The answers a turn has already obtained reach the callback through graph
state, keyed by the request they answered, exactly as the worker node binds
them. Position is deliberately not the binding: LangGraph matches a task's
stored resume values to its ``interrupt()`` calls by position, and the order a
replayed provider turn reaches its tool calls in is not fixed. The node
executions below therefore each reach ``interrupt()`` at most once, which the
call counter asserts directly.
"""

from __future__ import annotations

from typing import Annotated, Any, NotRequired, TypedDict, cast

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from ....thread.state import merge_permission_answers
from ...nodes.worker import _permission_callback_for, _recorded_permission_answers

_OPTIONS = [
    {"optionId": "allow_once", "name": "Allow once", "kind": "allow_once"},
    {"optionId": "reject_once", "name": "Reject once", "kind": "reject_once"},
]


class _Turn(TypedDict):
    granted: list[str]
    # The production channel with the production reducer, so the accumulation
    # these tests depend on is the one the real state performs.
    permission_answers: NotRequired[Annotated[dict[str, str], merge_permission_answers]]


def _bound_callback(state: _Turn) -> Any:
    """The callback the worker node binds, over this state's recorded answers."""
    return _permission_callback_for(_recorded_permission_answers(cast("Any", state)))


def _graph(calls: list[tuple[str, dict[str, Any]]], granted: list[str]) -> Any:
    """One node that asks permission for the next scripted call on every run."""

    async def ask(state: _Turn) -> dict[str, Any]:
        tool_name, tool_input = calls.pop(0)
        option = await _bound_callback(state)(tool_name, tool_input, _OPTIONS)
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


def _answer(parked: dict[str, Any], option_id: str) -> Command[Any]:
    """The resume a real dispatch sends: the answer, and its record in state."""
    return Command(
        resume={"option_id": option_id, "request_id": parked["request_id"]},
        update={"permission_answers": {parked["request_id"]: option_id}},
    )


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
    second = _parked(await graph.ainvoke(_answer(first, "allow_once"), _CONFIG))
    assert granted == []
    assert second["tool_input"] == {"command": "cat ~/.ssh/id_rsa"}
    assert second["request_id"] != first["request_id"]

    # Answering the call actually being made is what lets the turn proceed.
    final = await graph.ainvoke(_answer(second, "reject_once"), _CONFIG)
    assert "__interrupt__" not in final
    assert granted == ["Bash:reject_once"]


@pytest.mark.asyncio
async def test_the_same_call_asked_again_receives_its_answer() -> None:
    list_files = ("Bash", {"command": "ls"})
    granted: list[str] = []
    graph = _graph([list_files, list_files], granted)

    parked = _parked(await graph.ainvoke({"granted": []}, _CONFIG))
    final = await graph.ainvoke(_answer(parked, "allow_once"), _CONFIG)

    assert "__interrupt__" not in final
    assert granted == ["Bash:allow_once"]


@pytest.mark.asyncio
async def test_an_answer_naming_no_request_is_refused() -> None:
    """A bare option id approves nothing: it cannot be shown to belong here.

    It was previously applied to whatever call was asking, which is how an
    approval given for one call could settle another.
    """
    list_files = ("Bash", {"command": "ls"})
    granted: list[str] = []
    graph = _graph([list_files, list_files, list_files], granted)

    parked = _parked(await graph.ainvoke({"granted": []}, _CONFIG))
    reparked = _parked(await graph.ainvoke(Command(resume="allow_once"), _CONFIG))

    assert granted == []
    assert reparked["request_id"] == parked["request_id"]

    # Refusing it must not cost the call its ability to be approved.
    final = await graph.ainvoke(_answer(parked, "allow_once"), _CONFIG)
    assert "__interrupt__" not in final
    assert granted == ["Bash:allow_once"]


@pytest.mark.asyncio
async def test_a_turn_reordering_its_calls_still_gets_each_answer() -> None:
    """Two approvals survive a replay that reaches the calls in another order.

    Position was the binding before: a task's stored resume values are matched
    to its ``interrupt()`` calls in order, so a turn whose regenerated replay
    settled on a different order left a stored answer lined up against the
    wrong call. Each approval was still refused for the call it did not
    belong to, but the turn then re-asked a call the human had already
    approved and never finished. Keying the answers by request removes the
    dependence on order entirely.
    """
    edit = ("Edit", {"path": "a.py"})
    bash = ("Bash", {"command": "pytest"})
    # The order each successive node execution reaches the two calls in: the
    # regenerated turn settles on the other order and keeps it, which is what
    # a provider is free to do and what leaves stored answers misaligned.
    orders = [[edit, bash], [bash, edit], [bash, edit]]
    executions: list[str] = []

    async def two_calls(state: _Turn) -> dict[str, Any]:
        order = orders[min(len(executions), len(orders) - 1)]
        executions.append("started")
        callback = _bound_callback(state)
        granted = [
            f"{tool_name}:{await callback(tool_name, tool_input, _OPTIONS)}"
            for tool_name, tool_input in order
        ]
        return {"granted": granted}

    builder: StateGraph[Any, None, Any, Any] = StateGraph(cast("Any", _Turn))
    builder.add_node("ask", two_calls)
    builder.add_edge(START, "ask")
    builder.add_edge("ask", END)
    graph: Any = builder.compile(checkpointer=InMemorySaver())

    first = _parked(await graph.ainvoke({"granted": []}, _CONFIG))
    assert first["tool_name"] == "Edit"

    # The replay asks Bash first; Edit is answered from state, not re-asked.
    second = _parked(await graph.ainvoke(_answer(first, "allow_once"), _CONFIG))
    assert second["tool_name"] == "Bash"

    # Both calls are answered, so the turn finishes rather than re-asking the
    # one whose stored answer no longer lines up with where it now falls.
    final = await graph.ainvoke(_answer(second, "reject_once"), _CONFIG)
    assert "__interrupt__" not in final
    assert final["granted"] == ["Bash:reject_once", "Edit:allow_once"]
    # One execution per delivery: no re-park was needed to place an answer.
    assert len(executions) == 3


@pytest.mark.asyncio
async def test_a_remembered_approval_is_never_offered_or_accepted() -> None:
    options: list[dict[str, Any]] = [
        {"optionId": "allow_always", "name": "Always allow", "kind": "allow_always"},
        *_OPTIONS,
    ]
    granted: list[str] = []

    async def ask(state: _Turn) -> dict[str, Any]:
        option = await _bound_callback(state)("Bash", {"command": "ls"}, options)
        granted.append(option)
        return {"granted": [option]}

    builder: StateGraph[Any, None, Any, Any] = StateGraph(cast("Any", _Turn))
    builder.add_node("ask", ask)
    builder.add_edge(START, "ask")
    builder.add_edge("ask", END)
    graph: Any = builder.compile(checkpointer=InMemorySaver())

    parked = _parked(await graph.ainvoke({"granted": []}, _CONFIG))
    assert [o["optionId"] for o in parked["options"]] == ["allow_once", "reject_once"]

    # The withheld choice is refused wherever it arrives from - including the
    # recorded answers, which is what stops it being smuggled past the offer.
    reparked = _parked(await graph.ainvoke(_answer(parked, "allow_always"), _CONFIG))
    assert granted == []
    assert reparked["request_id"] == parked["request_id"]

    final = await graph.ainvoke(_answer(parked, "allow_once"), _CONFIG)
    assert "__interrupt__" not in final
    assert granted == ["allow_once"]


def test_recorded_answers_drop_entries_that_name_nothing() -> None:
    """Durable state is untrusted: only a real request-to-option pair counts."""
    state = cast(
        "Any",
        {
            "permission_answers": {
                "perm-good": "allow_once",
                "": "allow_once",
                "perm-empty": "",
                "perm-not-a-string": 7,
            }
        },
    )
    assert _recorded_permission_answers(state) == {"perm-good": "allow_once"}


def test_recorded_answers_merge_under_their_request_ids() -> None:
    """The reducer accumulates a turn's approvals instead of replacing them."""
    merged = merge_permission_answers(
        {"perm-edit": "allow_once"}, {"perm-bash": "reject_once"}
    )
    assert merged == {"perm-edit": "allow_once", "perm-bash": "reject_once"}
    assert (
        merge_permission_answers(merged, {"perm-edit": "reject_once"})["perm-edit"]
        == "reject_once"
    )

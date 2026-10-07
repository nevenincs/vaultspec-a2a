"""A model call tagged not-to-stream never reaches a client as message text.

A real compiled graph runs two deterministic-lane models, built through the real
provider factory, in one node through the real producer ingest: the supervisor
invoked the way the supervisor invokes its routing decision, tagged
``TAG_NOSTREAM``, and a researcher as an ordinary call. The v2 event API emits
stream events for both; only the untagged call's text may be relayed.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, TypedDict, cast

import pytest
from langchain_core.messages import HumanMessage
from langgraph.constants import TAG_NOSTREAM
from langgraph.graph import END, START

from ...graph.enums import Provider
from ...graph.events import MessageChunk
from ...providers import ProviderFactory
from ...team.team_config import load_agent_config
from ...testing import add_test_node, compile_test_graph, new_state_graph
from ..aggregator import RunEventProducer
from ._relay_capture import relayed_events

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Coroutine

    from langchain_core.language_models import BaseChatModel

    from ..types import StreamableGraph


class _State(TypedDict):
    note: str


def _lane_model(agent_id: str) -> BaseChatModel:
    """The deterministic lane's model for *agent_id*, built as a run builds it."""
    return ProviderFactory().create(
        Provider.DETERMINISTIC,
        model="deterministic",
        agent_config=load_agent_config(agent_id),
    )


def _route_then_answer(
    replies: dict[str, str],
) -> Callable[[_State], Awaitable[dict[str, str]]]:
    """A node that routes, then answers, keeping what each call replied."""

    async def node(state: _State) -> dict[str, str]:
        del state
        routing = _lane_model("vaultspec-supervisor").with_config(
            {"tags": [TAG_NOSTREAM]}
        )
        answering = _lane_model("vaultspec-researcher")
        route = await routing.ainvoke([HumanMessage(content="who next?")])
        answer = await answering.ainvoke([HumanMessage(content="answer")])
        replies["route"] = str(route.content)
        replies["answer"] = str(answer.content)
        return {"note": "done"}

    return node


@pytest.mark.asyncio
async def test_a_nostream_model_call_is_not_relayed_to_clients() -> None:
    replies: dict[str, str] = {}
    builder = new_state_graph(_State)
    add_test_node(builder, "supervisor", _route_then_answer(replies))
    builder.add_edge(START, "supervisor")
    builder.add_edge("supervisor", END)
    graph = cast("StreamableGraph", compile_test_graph(builder))

    producer = RunEventProducer()
    events = relayed_events(producer)
    ingest = cast("Callable[..., Coroutine[Any, Any, str]]", producer.ingest)
    outcome = await asyncio.wait_for(
        ingest(
            thread_id="thread-nostream",
            agent_id="supervisor",
            graph=graph,
            graph_input={"note": ""},
            config={"configurable": {"thread_id": "thread-nostream"}},
        ),
        timeout=10.0,
    )

    assert outcome == "completed"
    relayed = "".join(
        s.event.content for s in events if isinstance(s.event, MessageChunk)
    )
    assert replies["answer"] in relayed
    assert replies["route"] not in relayed

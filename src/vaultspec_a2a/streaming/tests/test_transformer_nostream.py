"""A model call tagged not-to-stream never reaches a client as message text.

A real compiled graph runs two streaming chat models in one node through the
real aggregator ingest: one invoked the way the supervisor invokes its routing
decision, tagged ``TAG_NOSTREAM``, and one ordinary call. The v2 event API emits
stream events for both; only the untagged call's text may be relayed.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, TypedDict, cast

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.constants import TAG_NOSTREAM
from langgraph.graph import END, START, StateGraph

from ...graph.compiler import _add_node
from ...graph.events import MessageChunk
from ..aggregator import EventAggregator

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from ..types import SequencedEvent, StreamableGraph


class _State(TypedDict):
    note: str


async def _route_then_answer(state: _State) -> dict[str, str]:
    del state
    routing = GenericFakeChatModel(
        messages=iter([AIMessage(content="ROUTE-TOKEN-coder")])
    ).with_config({"tags": [TAG_NOSTREAM]})
    answering = GenericFakeChatModel(
        messages=iter([AIMessage(content="visible answer text")])
    )
    await routing.ainvoke([HumanMessage(content="who next?")])
    await answering.ainvoke([HumanMessage(content="answer")])
    return {"note": "done"}


@pytest.mark.asyncio
async def test_a_nostream_model_call_is_not_relayed_to_clients() -> None:
    builder: StateGraph[Any, None, Any, Any] = StateGraph(cast("Any", _State))
    _add_node(builder, "supervisor", _route_then_answer)
    builder.add_edge(START, "supervisor")
    builder.add_edge("supervisor", END)
    graph = cast("StreamableGraph", builder.compile())

    aggregator = EventAggregator()
    queue = aggregator.add_subscriber("client-nostream")
    aggregator.subscribe("client-nostream", ["thread-nostream"])
    ingest = cast("Callable[..., Coroutine[Any, Any, str]]", aggregator.ingest)
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
    events: list[SequencedEvent] = []
    while not queue.empty():
        events.append(queue.get_nowait())
    relayed = "".join(
        s.event.content for s in events if isinstance(s.event, MessageChunk)
    )
    assert "visible" in relayed
    assert "ROUTE-TOKEN" not in relayed

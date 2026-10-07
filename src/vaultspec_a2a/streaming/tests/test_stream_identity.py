"""Who a run's frames are attributed to, against a graph that can tell.

A run reports nodes, tool calls and model text. Each is keyed
on an identity, and each identity was once taken from whatever was nearest
rather than from what LangGraph documents:

- a node boundary was any chain event carrying a node's name in its metadata,
  which a nested runnable inside that node and a subgraph's inner node both
  do, so a helper chain reported a second turn of its node and published a
  plan the node never wrote, and a subgraph's node joined the team roster;
- a tool call was keyed by the id its LangChain run was given, while the
  chunks that announced it were keyed by the id the model gave it, leaving one
  call described twice and one of the two stuck pending;
- a model call the supervisor asked not to stream was filtered after the
  library had already produced it.

The graph here has all of those shapes - a node with a nested runnable, a
subgraph, a model that streams a tool call the node then executes, and a model
tagged not to stream - and it is a real
compiled graph over a real checkpointer driven through the real event producer.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, TypedDict, cast, override

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.runnables import RunnableLambda
from langchain_core.tools import tool
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.constants import TAG_NOSTREAM
from langgraph.graph import END, START

from ...graph.enums import ToolCallStatus
from ...graph.events import (
    AgentStatus,
    MessageChunk,
    PlanUpdate,
    ToolCallStart,
    ToolCallUpdate,
)
from ...testing import add_test_node, compile_test_graph, new_state_graph
from ..aggregator import RunEventProducer
from ._relay_capture import relayed_events

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Coroutine, Mapping

    from ...graph.events import DomainEvent
    from ..types import StreamableGraph

_MODEL_TOOL_CALL_ID = "call_FROM_THE_MODEL"


class _State(TypedDict, total=False):
    note: str
    current_plan: list[dict[str, str]]


class _ToolStreamingModel(BaseChatModel):
    """A model that streams text and then a tool call with its own id."""

    @property
    @override
    def _llm_type(self) -> str:
        return "identity-probe"

    @override
    def _generate(
        self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any
    ) -> ChatResult:
        del messages, stop, run_manager, kwargs
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content="not streamed"))]
        )

    @override
    async def _astream(
        self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any
    ) -> AsyncIterator[ChatGenerationChunk]:
        del messages, stop, kwargs
        text = ChatGenerationChunk(message=AIMessageChunk(content="visible answer"))
        if run_manager:
            await run_manager.on_llm_new_token("visible answer", chunk=text)
        yield text
        call = ChatGenerationChunk(
            message=AIMessageChunk(
                content="",
                tool_call_chunks=[
                    {
                        "name": "mark_done",
                        "args": '{"task_id": "t1"}',
                        "id": _MODEL_TOOL_CALL_ID,
                        "index": 0,
                    }
                ],
            )
        )
        if run_manager:
            await run_manager.on_llm_new_token("", chunk=call)
        yield call


@tool
def mark_done(task_id: str) -> str:
    """Mark a task done."""
    return f"done {task_id}"


async def _worker(state: _State) -> dict[str, Any]:
    del state

    def _format(_: Mapping[str, object]) -> dict[str, list[dict[str, str]]]:
        return {"current_plan": [{"content": "PLAN FROM A NESTED CHAIN"}]}

    # A nested runnable inside the node. It carries the node's name in its
    # metadata and returns a plan-shaped value, which is exactly the pair
    # that would produce a phantom turn and a plan nobody wrote.
    nested = RunnableLambda(_format).with_config(run_name="formatter")
    await nested.ainvoke({"x": 1})

    routing = _ToolStreamingModel().with_config(tags=[TAG_NOSTREAM])
    async for _ in routing.astream([HumanMessage(content="who next?")]):
        pass

    answering = _ToolStreamingModel()
    async for _ in answering.astream([HumanMessage(content="answer")]):
        pass
    await mark_done.ainvoke(
        {
            "name": "mark_done",
            "args": {"task_id": "t1"},
            "id": _MODEL_TOOL_CALL_ID,
            "type": "tool_call",
        }
    )
    return {
        "note": "worked",
        "current_plan": [{"content": "THE PLAN THE NODE WROTE", "status": "pending"}],
    }


def _subgraph() -> Any:
    async def inner(state: _State) -> dict[str, Any]:
        del state
        return {"note": "inner"}

    builder = new_state_graph(_State)
    add_test_node(builder, "inner", inner)
    builder.add_edge(START, "inner")
    builder.add_edge("inner", END)
    return compile_test_graph(builder)


def _identity_graph(saver: AsyncSqliteSaver) -> StreamableGraph:
    builder = new_state_graph(_State)
    add_test_node(builder, "worker", _worker)
    add_test_node(builder, "team", _subgraph())
    builder.add_edge(START, "worker")
    builder.add_edge("worker", "team")
    builder.add_edge("team", END)
    return cast("StreamableGraph", compile_test_graph(builder, checkpointer=saver))


async def _run_identity_graph() -> list[DomainEvent]:
    async with AsyncSqliteSaver.from_conn_string(":memory:") as saver:
        await saver.setup()
        producer = RunEventProducer()
        relayed = relayed_events(producer)
        ingest = cast("Callable[..., Coroutine[Any, Any, str]]", producer.ingest)
        outcome = await asyncio.wait_for(
            ingest(
                thread_id="thread-identity",
                agent_id="supervisor",
                graph=_identity_graph(saver),
                graph_input={"note": ""},
                config={"configurable": {"thread_id": "thread-identity"}},
            ),
            timeout=30.0,
        )
    assert outcome == "completed"
    return [sequenced.event for sequenced in relayed]


@pytest.fixture(scope="module")
def identity_events() -> list[DomainEvent]:
    """One run of the identity graph, shared by every property it proves."""
    return asyncio.run(_run_identity_graph())


def test_a_nested_runnable_is_not_a_second_turn_of_its_node(
    identity_events: list[DomainEvent],
) -> None:
    statuses = [
        (event.node_name, event.state.value)
        for event in identity_events
        if isinstance(event, AgentStatus)
    ]
    assert statuses.count(("worker", "working")) == 1, statuses
    assert statuses.count(("worker", "idle")) == 1, statuses


def test_a_nested_runnables_return_value_is_not_published_as_the_nodes_plan(
    identity_events: list[DomainEvent],
) -> None:
    published = [
        entry["content"]
        for event in identity_events
        if isinstance(event, PlanUpdate)
        for entry in event.entries
    ]
    assert published == ["THE PLAN THE NODE WROTE"]


def test_a_subgraphs_inner_node_is_not_reported_as_an_agent(
    identity_events: list[DomainEvent],
) -> None:
    named = {
        event.node_name for event in identity_events if isinstance(event, AgentStatus)
    }
    assert "inner" not in named, named
    assert {"worker", "team"} <= named, named


def test_one_tool_call_is_reported_under_one_identity_and_one_agent(
    identity_events: list[DomainEvent],
) -> None:
    """The id the model gave the call is the id the whole call is reported on."""
    starts = [event for event in identity_events if isinstance(event, ToolCallStart)]
    updates = [event for event in identity_events if isinstance(event, ToolCallUpdate)]
    assert [event.tool_call_id for event in starts] == [_MODEL_TOOL_CALL_ID]
    assert {event.tool_call_id for event in updates} == {_MODEL_TOOL_CALL_ID}
    # Announced by the model, run by the tool, then resolved - one call
    # moving through its own states, not three calls.
    assert [event.status for event in updates] == [
        ToolCallStatus.IN_PROGRESS,
        ToolCallStatus.COMPLETED,
    ]
    assert {event.agent_id for event in starts + updates} == {"worker"}


def test_a_nostream_model_call_reaches_the_client_in_no_form(
    identity_events: list[DomainEvent],
) -> None:
    """Neither its text nor the frame that would close its turn."""
    chunks = [event for event in identity_events if isinstance(event, MessageChunk)]
    relayed = "".join(event.content for event in chunks)
    assert relayed.count("visible answer") == 1, relayed
    # The routing model produced the same text, so a second copy would be it.
    assert len([event for event in chunks if event.finish_reason]) <= 1

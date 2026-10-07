"""A produced message carries the time it was produced, through the checkpoint.

The transcript's timestamps used to be the time a snapshot read the messages,
so every message of a run reported the same instant, later than the
checkpoint that held it. A worker turn is driven through a real graph over a
real checkpointer, and the snapshot projection reads its time back.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, TypedDict, cast

import pytest
from langchain_core.messages import AIMessage, AnyMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from ....control.snapshot import _checkpoint_messages
from ...nodes.worker import _finalize_worker_response
from .._state_graph_helpers import add_test_node, compile_test_graph


class _Transcript(TypedDict):
    messages: list[AnyMessage]


@pytest.mark.asyncio
async def test_a_worker_turn_keeps_its_production_time_through_the_checkpoint() -> None:
    async def turn(state: _Transcript) -> dict[str, Any]:
        del state
        return _finalize_worker_response(
            response=AIMessage(content="done"),
            worker_name="vaultspec-coder",
        )

    builder: StateGraph[Any, None, Any, Any] = StateGraph(cast("Any", _Transcript))
    add_test_node(builder, "turn", turn)
    builder.add_edge(START, "turn")
    builder.add_edge("turn", END)
    graph: Any = compile_test_graph(builder, checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "message-time"}}

    before = datetime.now(UTC)
    await graph.ainvoke({"messages": []}, config)
    after = datetime.now(UTC)

    snapshot = await graph.aget_state(config)
    projected = _checkpoint_messages(snapshot.values)
    assert [m.content for m in projected] == ["done"]
    produced = projected[0].timestamp
    assert produced is not None
    assert before <= produced <= after
    # Read again later, the time does not move: it is the turn's, not the read's.
    assert _checkpoint_messages(snapshot.values)[0].timestamp == produced

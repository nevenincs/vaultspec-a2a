"""Completion is a committed graph output, scoped to the accepted action."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import pytest
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from ....thread.action_receipts import (
    GraphActionReceipt,
    control_action_payload_fingerprint,
)
from ....thread.enums import ControlActionType
from ....thread.state import TeamState
from ...nodes.action_completion import GRAPH_COMPLETION_NODE, record_graph_completion

if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig


def _receipt(dispatch_id: str) -> dict[str, object]:
    return GraphActionReceipt(
        schema_version="graph-action-v1",
        thread_id="run",
        action_id=dispatch_id,
        action_type=ControlActionType.RESUME
        if dispatch_id == "resume"
        else ControlActionType.INGEST,
        payload_fingerprint=control_action_payload_fingerprint(
            {"dispatch": dispatch_id}
        ),
        dispatch_id=dispatch_id,
        run_revision=1,
        writer_generation=1,
    ).model_dump(mode="json")


def _input(dispatch_id: str) -> dict[str, object]:
    receipt = _receipt(dispatch_id)
    return {
        "active_graph_action_receipt": receipt,
        "graph_action_receipts": {dispatch_id: receipt},
    }


def _gate(state: TeamState) -> dict[str, object]:
    if state["active_graph_action_receipt"]["dispatch_id"] != "first":
        interrupt("approve")
    return {}


@pytest.mark.asyncio
async def test_completion_survives_restart_and_does_not_complete_next_action(tmp_path):
    builder = StateGraph(cast("Any", TeamState))
    builder.add_node("gate", _gate)
    builder.add_node(GRAPH_COMPLETION_NODE, record_graph_completion)
    builder.add_edge(START, "gate")
    builder.add_edge("gate", GRAPH_COMPLETION_NODE)
    builder.add_edge(GRAPH_COMPLETION_NODE, END)
    path = str(tmp_path / "completion.db")
    config: RunnableConfig = {"configurable": {"thread_id": "run"}}
    async with AsyncSqliteSaver.from_conn_string(path) as saver:
        graph = builder.compile(checkpointer=saver)
        await graph.ainvoke(_input("first"), config)
        await graph.ainvoke(_input("second"), config)
        pending = await saver.aget_tuple(config)
        assert pending is not None
        evidence = pending.checkpoint["channel_values"]["graph_completion_receipts"]
        assert set(evidence) == {"first"}
        assert evidence["first"]["action"] == _receipt("first")
    async with AsyncSqliteSaver.from_conn_string(path) as reopened:
        graph = builder.compile(checkpointer=reopened)
        await graph.ainvoke(Command(resume="approved", update=_input("resume")), config)
        completed = await reopened.aget_tuple(config)
        assert completed is not None
        evidence = completed.checkpoint["channel_values"]["graph_completion_receipts"]
        assert set(evidence) == {"first", "resume"}
        assert evidence["resume"]["action"] == _receipt("resume")
        assert evidence["resume"]["outcome"] == "completed"


def test_completion_refuses_missing_active_incorporation():
    with pytest.raises(ValueError):
        record_graph_completion(
            cast(
                "TeamState",
                {
                    "active_graph_action_receipt": _receipt("missing"),
                    "graph_action_receipts": {"other": _receipt("other")},
                },
            )
        )

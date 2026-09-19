"""Action incorporation evidence survives real graph checkpoint boundaries."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START
from pydantic import ValidationError

from ..action_receipts import GraphActionReceipt, control_action_payload_fingerprint
from ..enums import ControlActionType
from ._graph_helpers import add_node, compile_graph, new_builder

if TYPE_CHECKING:
    from pathlib import Path

    from langchain_core.runnables import RunnableConfig

    from ..state import TeamState


def _receipt(dispatch_id: str, *, content: str) -> GraphActionReceipt:
    return GraphActionReceipt(
        schema_version="graph-action-v1",
        thread_id="receipt-run",
        action_id=f"action-{dispatch_id}",
        action_type=ControlActionType.INGEST,
        payload_fingerprint=control_action_payload_fingerprint({"content": content}),
        dispatch_id=dispatch_id,
        run_revision=1,
        writer_generation=1,
    )


def _finish(state: TeamState) -> dict[str, str]:
    return {"active_agent": state["active_agent"]}


@pytest.mark.asyncio
async def test_checkpoint_preserves_receipts_and_refuses_conflicting_replay(
    tmp_path: Path,
) -> None:
    path = str(tmp_path / "receipts.sqlite")
    first = _receipt("first", content="initial accepted input")
    second = _receipt("second", content="accepted follow-up")
    config: RunnableConfig = {"configurable": {"thread_id": "receipt-run"}}
    builder = new_builder()
    add_node(builder, "finish", _finish)
    builder.add_edge(START, "finish")
    builder.add_edge("finish", END)
    async with AsyncSqliteSaver.from_conn_string(path) as saver:
        graph = compile_graph(builder, checkpointer=saver)
        await graph.ainvoke(
            {
                "active_agent": "worker",
                "graph_action_receipts": {
                    first.dispatch_id: first.model_dump(mode="json"),
                },
            },
            config,
        )
        await graph.ainvoke(
            {
                "graph_action_receipts": {
                    second.dispatch_id: second.model_dump(mode="json"),
                }
            },
            config,
        )
    async with AsyncSqliteSaver.from_conn_string(path) as reopened:
        graph = compile_graph(builder, checkpointer=reopened)
        restored = await graph.aget_state(config)
        assert restored.values["graph_action_receipts"] == {
            first.dispatch_id: first.model_dump(mode="json"),
            second.dispatch_id: second.model_dump(mode="json"),
        }
        conflicting = _receipt("first", content="different unaccepted input")
        with pytest.raises(ValueError, match="conflicts with durable identity"):
            await graph.ainvoke(
                {
                    "graph_action_receipts": {
                        conflicting.dispatch_id: conflicting.model_dump(mode="json"),
                    }
                },
                config,
            )


def test_receipt_refuses_retired_schema_and_cancellation_incorporation() -> None:
    receipt = _receipt("dispatch", content="accepted").model_dump(mode="json")
    with pytest.raises(ValidationError):
        GraphActionReceipt.model_validate({**receipt, "schema_version": 0})
    with pytest.raises(ValidationError):
        GraphActionReceipt.model_validate({**receipt, "action_type": "cancel"})
    with pytest.raises(ValidationError):
        GraphActionReceipt.model_validate({**receipt, "payload_fingerprint": ""})

"""Mounted vault text reaches the worker's prompt and never the checkpoint.

A real preset is compiled over a real ``AsyncSqliteSaver`` file and run to
completion against a workspace holding one ADR. The prompt the worker sends is
captured with a LangChain callback handler, and the saver's own tables are read
back afterwards, so both halves of the contract are observed on the real path:
the document is in front of the model, and no checkpoint or pending write
carries it.
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, Any

import pytest
from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from ...team.team_config import load_agent_config, load_team_config
from ...thread.action_receipts import (
    GraphActionReceipt,
    control_action_payload_fingerprint,
)
from ...thread.enums import ControlActionType
from ..compiler import compile_team_graph
from .conftest import deterministic_model_assignment

if TYPE_CHECKING:
    from pathlib import Path
    from uuid import UUID

    from langchain_core.messages import BaseMessage

    from ..protocols import ProviderFactoryProtocol

_MARKER = "MOUNTED-ONLY-8c41e2"
_FEATURE = "mount-persistence"


class _PromptCapture(AsyncCallbackHandler):
    """Records every prompt a chat model is started with."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[BaseMessage]],
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        del serialized, run_id, kwargs
        for batch in messages:
            self.prompts.append("\n".join(str(m.content) for m in batch))


def _run_input(thread_id: str) -> dict[str, Any]:
    receipt = GraphActionReceipt(
        schema_version="graph-action-v1",
        thread_id=thread_id,
        action_id="ingest",
        action_type=ControlActionType.INGEST,
        payload_fingerprint=control_action_payload_fingerprint({"run": thread_id}),
        dispatch_id="ingest",
        run_revision=1,
        writer_generation=1,
    ).model_dump(mode="json")
    return {
        "messages": [HumanMessage(content="Implement the decision.")],
        "thread_id": thread_id,
        "active_feature": _FEATURE,
        "artifacts": [],
        "current_plan": [],
        "token_usage": {},
        "active_graph_action_receipt": receipt,
        "graph_action_receipts": {"ingest": receipt},
    }


@pytest.mark.asyncio
async def test_mounted_documents_reach_the_prompt_but_not_the_checkpoint(
    tmp_path: Path,
    pf: ProviderFactoryProtocol,
) -> None:
    workspace = tmp_path / "workspace"
    adr_dir = workspace / ".vault" / "adr"
    adr_dir.mkdir(parents=True)
    (adr_dir / f"2026-09-24-{_FEATURE}-adr.md").write_text(
        f"# Decision\n\nBinding text {_MARKER}.\n", encoding="utf-8"
    )
    team = load_team_config("vaultspec-solo-coder")
    agent_configs = {w.agent_id: load_agent_config(w.agent_id) for w in team.workers}
    database = tmp_path / "checkpoints.db"
    capture = _PromptCapture()

    async with AsyncSqliteSaver.from_conn_string(str(database)) as saver:
        await saver.setup()
        graph = compile_team_graph(
            team_config=team,
            agent_configs=agent_configs,
            checkpointer=saver,
            provider_factory=pf,
            workspace_root=workspace,
            model_assignment=deterministic_model_assignment(team),
        )
        await graph.ainvoke(
            _run_input("mount-run"),
            {"configurable": {"thread_id": "mount-run"}, "callbacks": [capture]},
        )

    assert any(_MARKER in prompt for prompt in capture.prompts), capture.prompts

    marker = _MARKER.encode()
    with sqlite3.connect(database) as connection:
        checkpoints = connection.execute(
            "SELECT checkpoint FROM checkpoints"
        ).fetchall()
        writes = connection.execute("SELECT value FROM writes").fetchall()
    assert checkpoints, "the run must have written checkpoints"
    assert not [row for row in checkpoints if marker in bytes(row[0])]
    assert not [row for row in writes if row[0] is not None and marker in row[0]]

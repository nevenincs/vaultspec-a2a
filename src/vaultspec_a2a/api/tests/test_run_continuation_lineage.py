"""Live gateway coverage for a successor run's durable parent link."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING
from uuid import uuid4

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage

from ...control.thread_service import successor_seed_transcript
from ...database.checkpoints import open_checkpointer
from ...ipc.schemas import DispatchRequest
from ...testing import (
    DEFAULT_TEAM_PRESET,
    async_catalog_run_fields,
    serve_on_loopback,
    settings_override,
)
from ...tests._checkpoint_seeding import real_checkpoint
from ...worker.graph_lifecycle import GraphLifecycleManager
from .conftest import make_app
from .test_gateway_drain import _relay_terminal, _RelayContext

if TYPE_CHECKING:
    from pathlib import Path

    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.mark.asyncio(loop_scope="function")
async def test_successor_requires_settled_parent_and_discloses_durable_link(
    session_factory: async_sessionmaker[AsyncSession],
    checkpointer: AsyncSqliteSaver,
    tmp_path: Path,
) -> None:
    app, _aggregator, worker, _cp = make_app(session_factory, checkpointer)
    async with (
        serve_on_loopback(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
    ):
        fields = await async_catalog_run_fields(client)
        parent = await client.post(
            "/v1/runs",
            json={
                "run_id": "lineage-parent",
                "team_preset": DEFAULT_TEAM_PRESET,
                "message": "first turn",
                **fields,
            },
        )
        assert parent.status_code == 201, parent.text
        successor = {
            "run_id": "lineage-successor",
            "continues_run_id": "lineage-parent",
            "team_preset": DEFAULT_TEAM_PRESET,
            "message": "second turn",
            **fields,
        }
        premature = await client.post("/v1/runs", json=successor)
        assert premature.status_code == 409, premature.text
        await _relay_terminal(
            client,
            "lineage-parent",
            _RelayContext(checkpointer, worker, session_factory),
        )
        checkpoint = await real_checkpoint()
        checkpoint["id"] = "cp-lineage-final"
        checkpoint["channel_values"] = {
            "messages": [
                HumanMessage(content=f"history-{index}")
                if index % 2 == 0
                else AIMessage(content=f"history-{index}")
                for index in range(23)
            ]
        }
        checkpoint["channel_versions"] = {
            "messages": checkpointer.get_next_version(None, None)
        }
        await checkpointer.aput(
            {"configurable": {"thread_id": "lineage-parent", "checkpoint_ns": ""}},
            checkpoint,
            {"source": "loop", "step": 2, "parents": {}},
            checkpoint["channel_versions"],
        )
        admitted = await client.post("/v1/runs", json=successor)
        assert admitted.status_code == 201, admitted.text
        successor_dispatch = DispatchRequest.model_validate(worker.dispatches[-1])
        assert len(successor_dispatch.seed_transcript) == 20
        assert successor_dispatch.seed_transcript[0].content == "history-3"
        graph_input = GraphLifecycleManager.build_graph_input(
            successor_dispatch, is_first_ingest=True
        )
        assert [message.content for message in graph_input["messages"]][-3:] == [
            "history-21",
            "history-22",
            "second turn",
        ]
        status = await client.get("/v1/runs/lineage-successor")
        assert status.status_code == 200, status.text
        assert status.json()["continues_run_id"] == "lineage-parent"
        parent_status = await client.get("/v1/runs/lineage-parent")
        assert parent_status.json()["continues_run_id"] is None

        await checkpointer.adelete_thread("lineage-parent")
        lost = await client.post(
            "/v1/runs",
            json={**successor, "run_id": "lineage-no-checkpoint"},
        )
        assert lost.status_code == 409, lost.text
        absent = await client.get("/v1/runs/lineage-no-checkpoint")
        assert absent.status_code == 404

        other = await client.post(
            "/v1/runs",
            json={
                "run_id": "lineage-other-workspace",
                "team_preset": DEFAULT_TEAM_PRESET,
                "message": "another project",
                **await async_catalog_run_fields(client, workspace_root=str(tmp_path)),
            },
        )
        assert other.status_code == 201, other.text
        await _relay_terminal(
            client,
            "lineage-other-workspace",
            _RelayContext(checkpointer, worker, session_factory),
        )
        wrong_workspace = await client.post(
            "/v1/runs",
            json={
                **successor,
                "run_id": "lineage-wrong-workspace",
                "continues_run_id": "lineage-other-workspace",
            },
        )
        assert wrong_workspace.status_code == 409, wrong_workspace.text


@pytest.mark.asyncio(loop_scope="function")
@pytest.mark.requires_prerequisites("postgres")
async def test_postgres_final_checkpoint_seeds_successor_transcript() -> None:
    with settings_override(
        checkpoint_backend="postgres",
        checkpoint_database_url=os.environ["VAULTSPEC_A2A_TEST_POSTGRES_URL"],
    ):
        async with open_checkpointer() as checkpointer:
            predecessor_id = f"lineage-postgres-{uuid4().hex}"
            checkpoint = await real_checkpoint()
            checkpoint["id"] = f"cp-{uuid4().hex}"
            checkpoint["channel_values"] = {
                "messages": [
                    HumanMessage(content="question"),
                    AIMessage(content="answer"),
                ]
            }
            checkpoint["channel_versions"] = {
                "messages": checkpointer.get_next_version(None, None)
            }
            await checkpointer.aput(
                {"configurable": {"thread_id": predecessor_id, "checkpoint_ns": ""}},
                checkpoint,
                {"source": "loop", "step": 1, "parents": {}},
                checkpoint["channel_versions"],
            )
            transcript = await successor_seed_transcript(
                checkpointer, predecessor_id, 1
            )
            assert transcript is not None
            assert [(turn.role, turn.content) for turn in transcript] == [
                ("assistant", "answer")
            ]

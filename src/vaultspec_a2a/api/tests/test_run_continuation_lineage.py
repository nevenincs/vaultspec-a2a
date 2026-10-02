"""Live gateway coverage for a successor run's durable parent link."""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import pytest

from .conftest import async_catalog_run_fields, make_app
from .test_gateway_drain import _relay_terminal, _RelayContext
from .test_gateway_live import _live_server

if TYPE_CHECKING:
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.mark.asyncio(loop_scope="function")
async def test_successor_requires_settled_parent_and_discloses_durable_link(
    session_factory: async_sessionmaker[AsyncSession],
    checkpointer: AsyncSqliteSaver,
) -> None:
    app, _aggregator, worker, _cp = make_app(session_factory, checkpointer)
    async with (
        _live_server(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
    ):
        fields = await async_catalog_run_fields(client)
        parent = await client.post(
            "/v1/runs",
            json={
                "run_id": "lineage-parent",
                "team_preset": "mock-success-single",
                "message": "first turn",
                **fields,
            },
        )
        assert parent.status_code == 201, parent.text
        successor = {
            "run_id": "lineage-successor",
            "continues_run_id": "lineage-parent",
            "team_preset": "mock-success-single",
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
        admitted = await client.post("/v1/runs", json=successor)
        assert admitted.status_code == 201, admitted.text
        status = await client.get("/v1/runs/lineage-successor")
        assert status.status_code == 200, status.text
        assert status.json()["continues_run_id"] == "lineage-parent"
        parent_status = await client.get("/v1/runs/lineage-parent")
        assert parent_status.json()["continues_run_id"] is None

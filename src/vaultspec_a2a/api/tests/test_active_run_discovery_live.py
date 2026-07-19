"""Live contract proof for bounded active-run discovery and viewer recovery."""

from __future__ import annotations

import asyncio
import contextlib
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import httpx
import pytest
import uvicorn

from ...database.thread_repository import create_thread
from ...streaming.aggregator import EventAggregator
from ...thread.enums import ThreadStatus
from ..app import create_app

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from fastapi import FastAPI


@asynccontextmanager
async def _app_lifespan(_app: FastAPI) -> AsyncIterator[None]:
    yield


@asynccontextmanager
async def _live_server(app: FastAPI) -> AsyncIterator[str]:
    config = uvicorn.Config(
        app, host="127.0.0.1", port=0, log_level="warning", lifespan="on"
    )
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    try:
        for _ in range(500):
            if server.started and server.servers:
                break
            await asyncio.sleep(0.01)
        assert server.started and server.servers, "uvicorn did not start"
        port = server.servers[0].sockets[0].getsockname()[1]
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(task, timeout=5.0)


@pytest.mark.asyncio(loop_scope="function")
async def test_active_run_discovery_rebinds_to_authoritative_status(
    session_factory, checkpointer, tmp_path
) -> None:
    """A reload discovers the scoped live run, then reads its recovery snapshot."""
    workspace = (tmp_path / "workspace").resolve()
    foreign_workspace = (tmp_path / "foreign").resolve()
    workspace.mkdir()
    foreign_workspace.mkdir()
    now = datetime(2026, 7, 19, 12, tzinfo=UTC)

    async with session_factory() as session:
        rows = [
            await create_thread(
                session,
                thread_id="active-old",
                status=ThreadStatus.INPUT_REQUIRED,
                metadata=json.dumps(
                    {"workspace_root": str(workspace), "feature_tag": "feature-a"}
                ),
            ),
            await create_thread(
                session,
                thread_id="active-new",
                status=ThreadStatus.RUNNING,
                metadata=json.dumps(
                    {"workspace_root": str(workspace), "feature_tag": "feature-a"}
                ),
            ),
            await create_thread(
                session,
                thread_id="other-feature",
                status=ThreadStatus.RUNNING,
                metadata=json.dumps(
                    {"workspace_root": str(workspace), "feature_tag": "feature-b"}
                ),
            ),
            await create_thread(
                session,
                thread_id="foreign-workspace",
                status=ThreadStatus.RUNNING,
                metadata=json.dumps(
                    {
                        "workspace_root": str(foreign_workspace),
                        "feature_tag": "feature-a",
                    }
                ),
            ),
            await create_thread(
                session,
                thread_id="terminal",
                status=ThreadStatus.COMPLETED,
                metadata=json.dumps(
                    {"workspace_root": str(workspace), "feature_tag": "feature-a"}
                ),
            ),
            await create_thread(
                session,
                thread_id="malformed-metadata",
                status=ThreadStatus.RUNNING,
                metadata="{not-json",
            ),
            await create_thread(
                session,
                thread_id="invalid-status",
                status=ThreadStatus.RUNNING,
                metadata=json.dumps(
                    {"workspace_root": str(workspace), "feature_tag": "feature-a"}
                ),
            ),
            await create_thread(
                session,
                thread_id="r" * 129,
                status=ThreadStatus.RUNNING,
                metadata=json.dumps(
                    {"workspace_root": str(workspace), "feature_tag": "feature-a"}
                ),
            ),
        ]
        rows[-2].status = "unknown"
        for index, row in enumerate(rows):
            row.created_at = now + timedelta(seconds=index)
        await session.commit()

    app = create_app(lifespan=_app_lifespan)
    app.state.db_session_factory = session_factory
    app.state.aggregator = EventAggregator()
    app.state.checkpointer = checkpointer

    async with (
        _live_server(app) as base_url,
        httpx.AsyncClient(base_url=base_url, timeout=10.0) as client,
    ):
        first = await client.get(
            "/v1/runs",
            params={
                "state": "active",
                "workspace_root": str(workspace),
                "feature_tag": "feature-a",
                "limit": 1,
            },
        )
        assert first.status_code == 200, first.text
        assert first.json() == {
            "api_version": "v1",
            "state": "active",
            "runs": [
                {
                    "run_id": "active-new",
                    "status": "running",
                    "feature_tag": "feature-a",
                }
            ],
            "truncated": True,
        }

        complete = await client.get(
            "/v1/runs",
            params={
                "workspace_root": str(workspace),
                "feature_tag": "feature-a",
                "limit": 10,
            },
        )
        assert complete.status_code == 200, complete.text
        assert [run["run_id"] for run in complete.json()["runs"]] == [
            "active-new",
            "active-old",
        ]
        assert complete.json()["truncated"] is False
        assert "token" not in complete.text.lower()

        status = await client.get("/v1/runs/active-new")
        assert status.status_code == 200, status.text
        assert status.json()["run_id"] == "active-new"
        assert status.json()["status"] == "running"


@pytest.mark.asyncio(loop_scope="function")
async def test_active_run_discovery_rejects_unbounded_selectors(
    session_factory, tmp_path
) -> None:
    """Only the active state, absolute workspaces, and bounded limits are valid."""
    app = create_app(lifespan=_app_lifespan)
    app.state.db_session_factory = session_factory

    async with (
        _live_server(app) as base_url,
        httpx.AsyncClient(base_url=base_url, timeout=10.0) as client,
    ):
        wrong_state = await client.get("/v1/runs", params={"state": "completed"})
        assert wrong_state.status_code == 422

        relative_workspace = await client.get(
            "/v1/runs", params={"workspace_root": "relative/workspace"}
        )
        assert relative_workspace.status_code == 422
        assert relative_workspace.json()["detail"] == "workspace_root must be absolute"

        oversized_limit = await client.get("/v1/runs", params={"limit": 101})
        assert oversized_limit.status_code == 422

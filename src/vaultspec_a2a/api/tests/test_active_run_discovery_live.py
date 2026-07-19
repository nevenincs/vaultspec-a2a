"""Live contract proof for bounded active-run discovery and viewer recovery."""

from __future__ import annotations

import asyncio
import json
import os
import socket
import sys
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ...database.models import ThreadModel
from ...database.thread_repository import create_thread
from ...thread.enums import ThreadStatus

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

_SERVICE_TOKEN = "active-discovery-service-token"


def _unused_loopback_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


@asynccontextmanager
async def _production_gateway(
    tmp_path: Path,
) -> AsyncIterator[tuple[str, async_sessionmaker[AsyncSession]]]:
    """Boot the installed gateway with its production lifespan and real storage."""
    port = _unused_loopback_port()
    database_path = tmp_path / "gateway.db"
    database_url = f"sqlite+aiosqlite:///{database_path.as_posix()}"
    checkpoint_path = tmp_path / "checkpoints.db"
    runtime_home = tmp_path / "a2a-home"
    environment = os.environ.copy()
    environment.update(
        {
            "VAULTSPEC_HOST": "127.0.0.1",
            "VAULTSPEC_PORT": str(port),
            "VAULTSPEC_DATABASE_BACKEND": "sqlite",
            "VAULTSPEC_DATABASE_URL": database_url,
            "VAULTSPEC_CHECKPOINT_BACKEND": "sqlite",
            "VAULTSPEC_CHECKPOINT_DATABASE_URL": (
                f"sqlite+aiosqlite:///{checkpoint_path}"
            ),
            "VAULTSPEC_A2A_HOME": str(runtime_home),
            "VAULTSPEC_WORKSPACE_ROOT": str(tmp_path / "managed-workspaces"),
            "VAULTSPEC_AUTO_SPAWN_WORKER": "false",
            "VAULTSPEC_REPAIR_ON_STARTUP": "false",
            "VAULTSPEC_WORKER_URL": f"http://127.0.0.1:{_unused_loopback_port()}",
            "VAULTSPEC_INTERNAL_TOKEN": _SERVICE_TOKEN,
        }
    )
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "vaultspec_a2a.cli.main",
        "serve",
        env=environment,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    base_url = f"http://127.0.0.1:{port}"
    try:
        async with httpx.AsyncClient(
            base_url=base_url,
            timeout=2.0,
            headers={"Authorization": f"Bearer {_SERVICE_TOKEN}"},
        ) as client:
            for _ in range(500):
                if process.returncode is not None:
                    output = await process.stdout.read() if process.stdout else b""
                    pytest.fail(
                        "production gateway exited during startup:\n"
                        + output.decode(errors="replace")
                    )
                try:
                    response = await client.get("/v1/runs", params={"limit": 1})
                    if response.status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                await asyncio.sleep(0.02)
            else:
                pytest.fail("production gateway did not become ready")
        fixture_engine = create_async_engine(database_url)
        try:
            session_factory = async_sessionmaker(
                fixture_engine,
                class_=AsyncSession,
                expire_on_commit=False,
            )
            yield base_url, session_factory
        finally:
            await fixture_engine.dispose()
    finally:
        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=10.0)
            except TimeoutError:
                process.kill()
                await process.wait()


@pytest.mark.asyncio(loop_scope="function")
async def test_active_run_discovery_rebinds_to_authoritative_status(
    tmp_path,
) -> None:
    """A reload discovers the scoped live run, then reads its recovery snapshot."""
    workspace = (tmp_path / "workspace").resolve()
    foreign_workspace = (tmp_path / "foreign").resolve()
    workspace.mkdir()
    foreign_workspace.mkdir()
    now = datetime(2026, 7, 19, 12, tzinfo=UTC)

    async with (
        _production_gateway(tmp_path) as (base_url, session_factory),
        httpx.AsyncClient(
            base_url=base_url,
            timeout=10.0,
            headers={"Authorization": f"Bearer {_SERVICE_TOKEN}"},
        ) as client,
    ):
        async with httpx.AsyncClient(base_url=base_url, timeout=10.0) as anonymous:
            missing = await anonymous.get("/v1/runs")
            wrong = await anonymous.get(
                "/v1/runs",
                headers={"Authorization": "Bearer wrong-service-token"},
            )
        assert missing.status_code == 401, missing.text
        assert wrong.status_code == 401, wrong.text

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
                    thread_id="recursive-metadata",
                    status=ThreadStatus.RUNNING,
                    metadata="[" * 1200 + "]" * 1200,
                ),
                await create_thread(
                    session,
                    thread_id="oversized-metadata",
                    status=ThreadStatus.RUNNING,
                    metadata=json.dumps({"padding": "x" * 250_000}),
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

        service_state = await client.get("/v1/service")
        assert service_state.status_code == 200, service_state.text
        assert "GET /v1/runs" in service_state.json()["routes"]

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

        async with session_factory() as session:
            session.add_all(
                [
                    ThreadModel(
                        id=f"newer-foreign-{index:04d}",
                        status=ThreadStatus.RUNNING.value,
                        is_active=True,
                        workspace_root=os.path.normcase(
                            os.path.realpath(foreign_workspace)
                        ),
                        feature_tag="feature-a",
                        thread_metadata=json.dumps(
                            {
                                "workspace_root": str(foreign_workspace),
                                "feature_tag": "feature-a",
                            }
                        ),
                        created_at=now + timedelta(hours=1, seconds=index),
                    )
                    for index in range(1001)
                ]
            )
            await session.commit()

        scan_bound = await client.get(
            "/v1/runs",
            params={
                "workspace_root": str(workspace),
                "feature_tag": "feature-a",
                "limit": 10,
            },
        )
        assert scan_bound.status_code == 200, scan_bound.text
        assert [run["run_id"] for run in scan_bound.json()["runs"]] == [
            "active-new",
            "active-old",
        ]
        assert scan_bound.json()["truncated"] is False


@pytest.mark.asyncio(loop_scope="function")
async def test_active_run_discovery_rejects_unbounded_selectors(
    tmp_path,
) -> None:
    """Only the active state, absolute workspaces, and bounded limits are valid."""
    async with (
        _production_gateway(tmp_path) as (base_url, _session_factory),
        httpx.AsyncClient(
            base_url=base_url,
            timeout=10.0,
            headers={"Authorization": f"Bearer {_SERVICE_TOKEN}"},
        ) as client,
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

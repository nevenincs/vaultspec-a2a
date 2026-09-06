"""Gateway-side actor-token threading and non-persistence.

Proves the run-start intake path does two things with the engine-provisioned
token bundle: it threads the real tokens onto the dispatch payload the worker
receives, and it writes none of them to any durable gateway store (the control
journal payload or the thread metadata). The worker is a real in-process ASGI
app that captures the posted ``DispatchRequest`` body — real HTTP serialization,
no mock transport — and the database is a real file-backed SQLite engine.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ...conftest import materialize_schema
from ...control.circuit_breaker import WorkerCircuitBreaker
from ...control.thread_service import (
    ThreadCreationRequest,
    create_and_dispatch_thread,
    generate_thread_id,
)
from ...control.worker_management import LazyWorkerSpawner
from ...database import (
    ThreadStatusElectionOutcome,
    delete_thread,
    elect_thread_status,
    get_thread,
    successor_thread_write_authority,
    thread_write_expectation,
)
from ...database.models import ControlActionModel, ThreadModel
from ...domain_config import domain_config
from ...thread.actor_tokens import ActorTokenBundle
from ...thread.dispatch_policy import FailureType
from ...thread.enums import ThreadStatus

_CODER_TOKEN = "secret-coder-xyz"
_REVIEWER_TOKEN = "secret-reviewer-xyz"
_BEARER = "secret-bearer-xyz"
_PRESET = "mock-success-single"


@pytest_asyncio.fixture
async def session_factory(tmp_path_factory: pytest.TempPathFactory):
    case_dir = tmp_path_factory.mktemp("token-thread-db")
    materialize_schema(Path(case_dir / "test.db"))
    engine = create_async_engine(f"sqlite+aiosqlite:///{case_dir / 'test.db'}")
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


def _capturing_worker(captured: dict[str, Any]) -> FastAPI:
    """A real ASGI worker that records the dispatch body and acknowledges it."""
    app = FastAPI()

    @app.post("/dispatch")
    async def _dispatch(request: Request) -> JSONResponse:
        captured["body"] = await request.json()
        return JSONResponse({"status": "dispatched", "thread_id": "x"})

    return app


def _early_terminal_worker(
    captured: dict[str, Any],
    session_factory: async_sessionmaker[AsyncSession],
    *,
    response_status: int = 200,
) -> FastAPI:
    """Settle the run before acknowledging its initial dispatch."""
    app = FastAPI()

    @app.post("/dispatch")
    async def _dispatch(request: Request) -> JSONResponse:
        body = await request.json()
        captured["body"] = body
        async with session_factory() as session:
            thread = await get_thread(session, body["thread_id"])
            assert thread is not None
            expectation = thread_write_expectation(thread)
            result = await elect_thread_status(
                session,
                thread.id,
                expectation=expectation,
                status=ThreadStatus.COMPLETED,
                successor=successor_thread_write_authority(
                    expectation,
                    action_type=expectation.authority.action_type,
                    action_receipt_id=body["dispatch_id"],
                ),
            )
            assert result.outcome is ThreadStatusElectionOutcome.WON
            await session.commit()
        return JSONResponse(
            {"status": "dispatched", "thread_id": body["thread_id"]},
            status_code=response_status,
        )

    return app


def _deleting_worker(
    session_factory: async_sessionmaker[AsyncSession],
) -> FastAPI:
    """Delete the durable reservation before acknowledging dispatch."""
    app = FastAPI()

    @app.post("/dispatch")
    async def _dispatch(request: Request) -> JSONResponse:
        body = await request.json()
        async with session_factory() as session:
            assert await delete_thread(session, body["thread_id"])
            await session.commit()
        return JSONResponse({"status": "dispatched", "thread_id": body["thread_id"]})

    return app


@pytest.mark.asyncio
async def test_run_start_threads_tokens_to_worker_but_never_persists_them(
    session_factory,
    tmp_path: Path,
) -> None:
    captured: dict[str, Any] = {}
    spawner = LazyWorkerSpawner(
        worker_url="http://127.0.0.1:9", worker_port=9, auto_spawn=False
    )
    spawner.replace_process(None)
    circuit_breaker = WorkerCircuitBreaker(failure_threshold=1, recovery_timeout=1.0)
    bundle = ActorTokenBundle(
        tokens={"coder": _CODER_TOKEN, "reviewer": _REVIEWER_TOKEN},
        engine_bearer=_BEARER,
    )
    thread_id = generate_thread_id()

    async with (
        httpx.AsyncClient(
            transport=ASGITransport(app=_capturing_worker(captured)),
            base_url="http://worker",
        ) as worker_client,
        session_factory() as session,
    ):
        result = await create_and_dispatch_thread(
            session,
            ThreadCreationRequest(
                thread_id=thread_id,
                title="token run",
                initial_message="build it",
                team_preset=_PRESET,
                autonomous=True,
                nickname=None,
                metadata=None,
                metadata_json=None,
                workspace_root=tmp_path,
                actor_tokens=bundle,
            ),
            circuit_breaker=circuit_breaker,
            worker_spawner=spawner,
            worker_client=worker_client,
            recursion_limit=domain_config.graph_recursion_limit,
            trace_headers=None,
        )

    assert result.dispatched is True

    # The worker received the real tokens on the dispatch payload (transport).
    body = captured["body"]
    assert body["actor_tokens"]["tokens"]["coder"] == _CODER_TOKEN
    assert body["actor_tokens"]["tokens"]["reviewer"] == _REVIEWER_TOKEN
    assert body["actor_tokens"]["engine_bearer"] == _BEARER

    # No token was written to the durable control journal or thread metadata.
    async with session_factory() as session:
        rows = (
            (
                await session.execute(
                    select(ControlActionModel).where(
                        ControlActionModel.thread_id == thread_id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert rows, "run-start must have journaled at least the ingest action"
        thread = await session.get(ThreadModel, thread_id)
        assert thread is not None
        assert thread.run_revision == 1
        assert thread.writer_generation == 1
        assert thread.writer_action_type == "ingest"
        assert thread.writer_action_receipt_id == rows[0].dispatch_id
        assert thread.writer_action_receipt_id == body["dispatch_id"]
        journal_blob = json.dumps([row.payload_json for row in rows])
        for secret in (_CODER_TOKEN, _REVIEWER_TOKEN, _BEARER):
            assert secret not in journal_blob, "token leaked into control journal"


@pytest.mark.asyncio
async def test_early_terminal_initial_dispatch_cannot_be_reopened(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    captured: dict[str, Any] = {}
    spawner = LazyWorkerSpawner(
        worker_url="http://127.0.0.1:9", worker_port=9, auto_spawn=False
    )
    spawner.replace_process(None)
    thread_id = generate_thread_id()
    async with (
        httpx.AsyncClient(
            transport=ASGITransport(
                app=_early_terminal_worker(captured, session_factory)
            ),
            base_url="http://worker",
        ) as worker_client,
        session_factory() as session,
    ):
        result = await create_and_dispatch_thread(
            session,
            ThreadCreationRequest(
                thread_id=thread_id,
                title="early terminal",
                initial_message="finish immediately",
                team_preset=_PRESET,
                autonomous=True,
                nickname=None,
                metadata=None,
                metadata_json=None,
                workspace_root=tmp_path,
            ),
            circuit_breaker=WorkerCircuitBreaker(
                failure_threshold=1, recovery_timeout=1.0
            ),
            worker_spawner=spawner,
            worker_client=worker_client,
            recursion_limit=domain_config.graph_recursion_limit,
            trace_headers=None,
        )
    assert result.dispatched is True
    assert result.status == ThreadStatus.COMPLETED.value
    async with session_factory() as session:
        thread = await get_thread(session, thread_id)
    assert thread is not None
    assert thread.status == ThreadStatus.COMPLETED.value
    assert thread.run_revision == 1
    assert thread.writer_action_receipt_id == captured["body"]["dispatch_id"]
    assert thread.last_applied_action is None


@pytest.mark.asyncio
async def test_initial_dispatch_reports_missing_row_without_refresh_failure(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    spawner = LazyWorkerSpawner(
        worker_url="http://127.0.0.1:9", worker_port=9, auto_spawn=False
    )
    spawner.replace_process(None)
    thread_id = generate_thread_id()
    async with (
        httpx.AsyncClient(
            transport=ASGITransport(app=_deleting_worker(session_factory)),
            base_url="http://worker",
        ) as worker_client,
        session_factory() as session,
    ):
        result = await create_and_dispatch_thread(
            session,
            ThreadCreationRequest(
                thread_id=thread_id,
                title="deleted before ack",
                initial_message="start",
                team_preset=_PRESET,
                autonomous=True,
                nickname=None,
                metadata=None,
                metadata_json=None,
                workspace_root=tmp_path,
            ),
            circuit_breaker=WorkerCircuitBreaker(
                failure_threshold=1, recovery_timeout=1.0
            ),
            worker_spawner=spawner,
            worker_client=worker_client,
            recursion_limit=domain_config.graph_recursion_limit,
            trace_headers=None,
        )
    assert result.dispatched is True
    assert result.status == ""
    assert result.failure_type is FailureType.NOT_FOUND


@pytest.mark.asyncio
async def test_lost_initial_ack_yields_to_early_terminal_authority(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    captured: dict[str, Any] = {}
    spawner = LazyWorkerSpawner(
        worker_url="http://127.0.0.1:9", worker_port=9, auto_spawn=False
    )
    spawner.replace_process(None)
    thread_id = generate_thread_id()
    async with (
        httpx.AsyncClient(
            transport=ASGITransport(
                app=_early_terminal_worker(
                    captured,
                    session_factory,
                    response_status=503,
                )
            ),
            base_url="http://worker",
        ) as worker_client,
        session_factory() as session,
    ):
        result = await create_and_dispatch_thread(
            session,
            ThreadCreationRequest(
                thread_id=thread_id,
                title="terminal before lost ack",
                initial_message="finish",
                team_preset=_PRESET,
                autonomous=True,
                nickname=None,
                metadata=None,
                metadata_json=None,
                workspace_root=tmp_path,
            ),
            circuit_breaker=WorkerCircuitBreaker(
                failure_threshold=1, recovery_timeout=1.0
            ),
            worker_spawner=spawner,
            worker_client=worker_client,
            recursion_limit=domain_config.graph_recursion_limit,
            trace_headers=None,
        )
    assert result.status == ThreadStatus.COMPLETED.value
    assert result.dispatched is True
    assert result.error_detail is None
    assert result.failure_type is None

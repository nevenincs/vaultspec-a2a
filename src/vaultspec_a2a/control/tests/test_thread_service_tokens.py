"""Gateway-side actor-token threading and non-persistence (ADR R7).

Proves the run-start intake path does two things with the engine-provisioned
token bundle: it threads the real tokens onto the dispatch payload the worker
receives, and it writes none of them to any durable gateway store (the control
journal payload or the thread metadata). The worker is a real in-process ASGI
app that captures the posted ``DispatchRequest`` body — real HTTP serialization,
no mock transport — and the database is a real file-backed SQLite engine.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from vaultspec_a2a.control.circuit_breaker import WorkerCircuitBreaker
from vaultspec_a2a.control.thread_service import (
    ThreadCreationRequest,
    create_and_dispatch_thread,
    generate_thread_id,
)
from vaultspec_a2a.control.worker_management import LazyWorkerSpawner
from vaultspec_a2a.database.models import Base, ControlActionModel
from vaultspec_a2a.domain_config import domain_config
from vaultspec_a2a.thread.actor_tokens import ActorTokenBundle

_CODER_TOKEN = "secret-coder-xyz"
_REVIEWER_TOKEN = "secret-reviewer-xyz"
_BEARER = "secret-bearer-xyz"
_PRESET = "mock-success-single"


@pytest_asyncio.fixture
async def session_factory(tmp_path_factory: pytest.TempPathFactory):
    case_dir = tmp_path_factory.mktemp("token-thread-db")
    engine = create_async_engine(f"sqlite+aiosqlite:///{case_dir / 'test.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
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


@pytest.mark.asyncio
async def test_run_start_threads_tokens_to_worker_but_never_persists_them(
    session_factory,
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
                workspace_root=None,
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
        journal_blob = json.dumps([row.payload_json for row in rows])
        for secret in (_CODER_TOKEN, _REVIEWER_TOKEN, _BEARER):
            assert secret not in journal_blob, "token leaked into control journal"

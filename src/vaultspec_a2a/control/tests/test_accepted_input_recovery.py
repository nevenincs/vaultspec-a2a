"""Recovery delivers the accepted input without reconstructing mutable controls."""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ...database import create_control_action, create_thread
from ...database.models import Base, RunWriteAuthority
from ...database.session import configure_sqlite_transactions
from ...ipc.schemas import DispatchRequest
from ...thread.enums import ControlActionType, ThreadStatus
from ..accepted_input import freeze_accepted_input
from ..circuit_breaker import WorkerCircuitBreaker
from ..direct_control_recovery import redrive_direct_control_actions
from ..dispatch_receipts import prepare_graph_action_receipt
from ..execution_authority import resolve_execution_authority
from ..worker_management import LazyWorkerSpawner
from ._catalog_authority import current_execution_metadata


@pytest.mark.asyncio
@pytest.mark.parametrize("complete", [True, False])
async def test_redrive_uses_complete_accepted_input_and_refuses_retired_shape(
    tmp_path, complete
):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'run.db'}")
    configure_sqlite_transactions(engine)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    accepted_dispatch = DispatchRequest(
        dispatch_id="accepted",
        action="resume",
        thread_id="run",
        workspace_root=str(tmp_path),
        option_id={"decision": "approved"},
        team_preset="accepted-preset",
        recursion_limit=37,
        model_assignment=resolve_execution_authority(
            current_execution_metadata(tmp_path)
        ).model_assignment,
    )
    payload: dict[str, object] = freeze_accepted_input(
        accepted_dispatch, intent={"decision": "approved"}
    )
    if not complete:
        payload = {"decision": "approved"}
    async with sessions() as db:
        await create_thread(
            db,
            thread_id="run",
            status=ThreadStatus.RECONCILING,
            team_preset="different-unavailable-current-preset",
            metadata="{}",
            write_authority=RunWriteAuthority(
                0, 1, ControlActionType.RESUME, "accepted"
            ),
        )
        await create_control_action(
            db,
            thread_id="run",
            action_type=ControlActionType.RESUME,
            idempotency_key="accepted",
            dispatch_id="accepted",
            payload=payload,
        )
        receipt = await prepare_graph_action_receipt(
            db, thread_id="run", dispatch_id="accepted"
        )
        assert (receipt is not None) is complete
        await db.commit()
    received: list[dict[str, object]] = []
    app = FastAPI()

    @app.post("/dispatch")
    async def receive(request: Request):
        received.append(await request.json())
        return JSONResponse({"status": "dispatched", "thread_id": "run"})

    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://worker",
        ) as client:
            summary = await redrive_direct_control_actions(
                sessions,
                worker_client=client,
                circuit_breaker=WorkerCircuitBreaker(
                    failure_threshold=3, recovery_timeout=30
                ),
                worker_spawner=LazyWorkerSpawner(
                    worker_url="http://worker", worker_port=8001, auto_spawn=False
                ),
                trace_headers=None,
            )
        if complete:
            assert summary.dispatched == 1
            assert len(received) == 1
            delivered = DispatchRequest.model_validate(received[0])
            assert delivered.dispatch_id == "accepted"
            assert delivered.recursion_limit == 37
            assert delivered.team_preset == "accepted-preset"
            assert delivered.option_id == {"decision": "approved"}
            assert delivered.model_assignment == accepted_dispatch.model_assignment
            assert delivered.require_graph_action_receipt() == receipt
        else:
            assert summary.dispatched == 0
            assert summary.conflicted == 1
            assert received == []
    finally:
        await engine.dispose()

"""Current-schema recovery proofs for direct control actions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ...database import (
    create_control_action,
    create_thread,
    elect_thread_status,
    get_thread,
    thread_write_expectation,
)
from ...database.models import Base, RunWriteAuthority
from ...database.session import configure_sqlite_transactions
from ...database.thread_repository import ThreadStatusElectionOutcome
from ...ipc.schemas import DispatchRequest
from ...team.team_config import load_team_config
from ...thread.enums import ControlActionType, ThreadStatus
from ...thread.executable_graph import FrozenGraphDefinition, freeze_graph_definition
from ..accepted_input import freeze_accepted_input
from ..circuit_breaker import WorkerCircuitBreaker
from ..direct_control_recovery import (
    DirectControlRecoverySummary,
    redrive_direct_control_actions,
)
from ..dispatch_receipts import prepare_graph_action_receipt
from ..execution_authority import resolve_execution_authority
from ..worker_management import LazyWorkerSpawner
from ._catalog_authority import current_execution_metadata

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@pytest_asyncio.fixture
async def sessions(
    tmp_path: Path,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'recovery.db'}")
    configure_sqlite_transactions(engine)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await engine.dispose()


@dataclass(frozen=True, slots=True)
class _AcceptedCase:
    thread_id: str
    action_type: ControlActionType
    status: ThreadStatus
    dispatch: DispatchRequest
    intent: dict[str, object]


def _graph_authority(
    workspace: Path,
) -> tuple[FrozenGraphDefinition, dict[str, dict[str, object]]]:
    definition = freeze_graph_definition(
        load_team_config("mock-success-single", workspace_root=workspace),
        workspace_root=workspace,
    )
    assignment = resolve_execution_authority(
        current_execution_metadata(workspace)
    ).model_assignment
    return definition, assignment


def _accepted_cases(workspace: Path) -> tuple[_AcceptedCase, ...]:
    definition, assignment = _graph_authority(workspace)
    return (
        _AcceptedCase(
            "message-run",
            ControlActionType.MESSAGE_FOLLOWUP_REQUESTED,
            ThreadStatus.RUNNING,
            DispatchRequest(
                dispatch_id="message-stable",
                action="ingest",
                thread_id="message-run",
                agent_id="vaultspec-supervisor",
                content="continue",
                workspace_root=str(workspace),
                team_preset="mock-success-single",
                graph_definition=definition,
                recursion_limit=37,
                model_assignment=assignment,
            ),
            {"content": "continue", "agent_id": "vaultspec-supervisor"},
        ),
        _AcceptedCase(
            "permission-run",
            ControlActionType.PERMISSION_RESPONSE_SUBMITTED,
            ThreadStatus.INPUT_REQUIRED,
            DispatchRequest(
                dispatch_id="permission-stable",
                action="resume",
                thread_id="permission-run",
                option_id={"option_id": "allow_once", "notes": None},
                workspace_root=str(workspace),
                team_preset="mock-success-single",
                graph_definition=definition,
                recursion_limit=37,
                model_assignment=assignment,
            ),
            {"option_id": "allow_once", "notes": None},
        ),
        _AcceptedCase(
            "cancel-run",
            ControlActionType.CANCEL,
            ThreadStatus.CANCELLING,
            DispatchRequest(
                dispatch_id="cancel-stable",
                action="cancel",
                thread_id="cancel-run",
                workspace_root=str(workspace),
                recursion_limit=37,
                model_assignment=assignment,
            ),
            {"reason": "user_requested"},
        ),
    )


async def _persist_case(db: AsyncSession, case: _AcceptedCase) -> None:
    authority = RunWriteAuthority(0, 1, case.action_type, case.dispatch.dispatch_id)
    await create_thread(
        db,
        thread_id=case.thread_id,
        status=case.status,
        team_preset=case.dispatch.team_preset,
        metadata=current_execution_metadata(Path(case.dispatch.workspace_root or ".")),
        write_authority=authority,
    )
    await create_control_action(
        db,
        thread_id=case.thread_id,
        action_type=case.action_type,
        idempotency_key=f"accepted:{case.thread_id}",
        dispatch_id=case.dispatch.dispatch_id,
        payload=freeze_accepted_input(case.dispatch, intent=case.intent),
    )
    if case.action_type is not ControlActionType.CANCEL:
        receipt = await prepare_graph_action_receipt(
            db,
            thread_id=case.thread_id,
            dispatch_id=case.dispatch.dispatch_id,
        )
        assert receipt is not None


async def _run_recovery(
    sessions: async_sessionmaker[AsyncSession],
) -> tuple[DirectControlRecoverySummary, list[dict[str, object]]]:
    received: list[dict[str, object]] = []
    app = FastAPI()

    @app.post("/dispatch")
    async def receive(request: Request) -> JSONResponse:
        received.append(await request.json())
        return JSONResponse({"status": "dispatched"})

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://worker"
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
    return summary, received


@pytest.mark.asyncio
async def test_current_message_permission_and_cancel_redrive_stable_ids(
    tmp_path: Path,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    cases = _accepted_cases(tmp_path)
    async with sessions() as db:
        for case in cases:
            await _persist_case(db, case)
        await db.commit()

    summary, received = await _run_recovery(sessions)

    assert summary.examined == 3
    assert summary.dispatched == 3
    assert summary.refused == 0
    assert summary.conflicted == 0
    assert {item["dispatch_id"] for item in received} == {
        "message-stable",
        "permission-stable",
        "cancel-stable",
    }
    delivered = {str(item["dispatch_id"]): item for item in received}
    assert delivered["message-stable"]["action"] == "ingest"
    assert delivered["message-stable"]["content"] == "continue"
    assert delivered["message-stable"]["agent_id"] == "vaultspec-supervisor"
    assert delivered["message-stable"]["recursion_limit"] == 37
    assert delivered["message-stable"]["team_preset"] == "mock-success-single"
    assert delivered["message-stable"]["graph_action_receipt"] is not None
    assert delivered["permission-stable"]["action"] == "resume"
    assert delivered["permission-stable"]["option_id"] == {
        "option_id": "allow_once",
        "notes": None,
    }
    assert delivered["permission-stable"]["graph_action_receipt"] is not None
    assert delivered["cancel-stable"]["action"] == "cancel"
    assert delivered["cancel-stable"]["graph_action_receipt"] is None


@pytest.mark.asyncio
async def test_unavailable_project_refuses_graph_action_but_allows_cancel(
    tmp_path: Path,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    missing = tmp_path / "deleted-project"
    cases = list(_accepted_cases(tmp_path))
    graph_case = cases[1]
    graph_case = _AcceptedCase(
        graph_case.thread_id,
        graph_case.action_type,
        graph_case.status,
        graph_case.dispatch.model_copy(update={"workspace_root": str(missing)}),
        graph_case.intent,
    )
    cancel_case = cases[2]
    cancel_case = _AcceptedCase(
        cancel_case.thread_id,
        cancel_case.action_type,
        cancel_case.status,
        cancel_case.dispatch.model_copy(update={"workspace_root": str(missing)}),
        cancel_case.intent,
    )
    async with sessions() as db:
        await _persist_case(db, graph_case)
        await _persist_case(db, cancel_case)
        await db.commit()

    summary, received = await _run_recovery(sessions)

    assert summary.examined == 2
    assert summary.dispatched == 1
    assert summary.refused == 1
    assert [item["dispatch_id"] for item in received] == ["cancel-stable"]


@pytest.mark.asyncio
async def test_older_accepted_action_loses_to_newer_exact_authority(
    tmp_path: Path,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    old = _accepted_cases(tmp_path)[1]
    async with sessions() as db:
        await _persist_case(db, old)
        thread = await get_thread(db, old.thread_id)
        assert thread is not None
        expectation = thread_write_expectation(thread)
        newer = _accepted_cases(tmp_path)[2]
        newer_dispatch = newer.dispatch.model_copy(
            update={"thread_id": old.thread_id, "dispatch_id": "newer-cancel"}
        )
        await create_control_action(
            db,
            thread_id=old.thread_id,
            action_type=ControlActionType.CANCEL,
            idempotency_key="accepted:newer-cancel",
            dispatch_id="newer-cancel",
            payload=freeze_accepted_input(
                newer_dispatch, intent={"reason": "user_requested"}
            ),
        )
        elected = await elect_thread_status(
            db,
            old.thread_id,
            expectation=expectation,
            status=ThreadStatus.CANCELLING,
            successor=RunWriteAuthority(
                1, 2, ControlActionType.CANCEL, "newer-cancel"
            ),
        )
        assert elected.outcome is ThreadStatusElectionOutcome.WON
        await db.commit()

    summary, received = await _run_recovery(sessions)

    assert summary.examined == 2
    assert summary.dispatched == 1
    assert summary.conflicted == 1
    assert [item["dispatch_id"] for item in received] == ["newer-cancel"]

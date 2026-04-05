"""Dispatch-failure state transitions stay aligned with readiness semantics."""

from __future__ import annotations

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from vaultspec_a2a.control.circuit_breaker import WorkerCircuitBreaker
from vaultspec_a2a.control.diagnostics import mark_thread_failed
from vaultspec_a2a.control.message_service import send_followup_message
from vaultspec_a2a.control.worker_management import LazyWorkerSpawner
from vaultspec_a2a.database import (
    create_thread,
    get_pending_permission_requests,
    get_thread,
    record_permission_request,
)
from vaultspec_a2a.database.models import Base
from vaultspec_a2a.graph.events import PermissionRequest
from vaultspec_a2a.streaming.aggregator import EventAggregator


@pytest_asyncio.fixture
async def engine(tmp_path_factory: pytest.TempPathFactory):
    """Create a file-backed engine for dispatch-failure tests."""
    case_dir = tmp_path_factory.mktemp("dispatch-failure-db")
    db_file = case_dir / "test.db"
    eng = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session_factory(engine):
    """Provide an async session factory bound to the test engine."""
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest.mark.asyncio
async def test_send_followup_message_dispatch_failure_degrades_readiness(
    session_factory,
) -> None:
    """A dispatch-marked failure must also degrade repair/readiness metadata."""
    async with session_factory() as session:
        thread = await create_thread(
            session,
            title="Dispatch failure",
            repair_status="healthy",
            execution_readiness="healthy",
        )
        await session.commit()

    spawner = LazyWorkerSpawner(
        worker_url="http://127.0.0.1:9",
        worker_port=9,
        auto_spawn=False,
    )
    spawner.replace_process(None)
    circuit_breaker = WorkerCircuitBreaker(
        failure_threshold=1,
        recovery_timeout=1.0,
    )

    async with httpx.AsyncClient(base_url="http://127.0.0.1:9", timeout=0.2) as client:
        async with session_factory() as session:
            result = await send_followup_message(
                session,
                thread_id=thread.id,
                content="hello",
                agent_id="vaultspec-supervisor",
                idempotency_key=None,
                circuit_breaker=circuit_breaker,
                worker_spawner=spawner,
                worker_client=client,
                recursion_limit=1,
                trace_headers=None,
            )

        assert result.dispatched is False
        assert result.thread_status == "failed"

    async with session_factory() as session:
        updated = await get_thread(session, thread.id)
        assert updated is not None
        assert updated.status == "failed"
        assert updated.repair_status == "operator_intervention_required"
        assert updated.execution_readiness == "operator_intervention_required"
        assert updated.repair_reason == "Worker dispatch failed"


@pytest.mark.asyncio
async def test_mark_thread_failed_degrades_repair_state(session_factory) -> None:
    """Websocket failure marking must also degrade repair/readiness metadata."""
    async with session_factory() as session:
        thread = await create_thread(
            session,
            thread_id="thread-ws-fail",
            repair_status="healthy",
            execution_readiness="healthy",
        )
        await session.commit()

    await mark_thread_failed("thread-ws-fail", session_factory)

    async with session_factory() as session:
        updated = await get_thread(session, thread.id)
        assert updated is not None
        assert updated.status == "failed"
        assert updated.repair_status == "operator_intervention_required"
        assert updated.execution_readiness == "operator_intervention_required"
        assert (
            updated.repair_reason
            == "Worker dispatch failed during websocket command handling"
        )


@pytest.mark.asyncio
async def test_mark_thread_failed_expires_pending_permissions_and_prunes_aggregator(
    session_factory,
) -> None:
    """WS failure cleanup must mirror the canonical terminal-event path."""
    async with session_factory() as session:
        await create_thread(
            session,
            thread_id="thread-ws-fail-permissions",
            status="input_required",
            repair_status="healthy",
            execution_readiness="healthy",
        )
        await record_permission_request(
            session,
            request_id="thread-ws-fail-permissions:perm-1",
            thread_id="thread-ws-fail-permissions",
            pause_reason_type="permission_request",
            description="Approve write?",
            allowed_options=[{"option_id": "allow_once", "name": "Allow once"}],
            tool_call="bash",
        )
        await session.commit()

    aggregator = EventAggregator()
    aggregator._emitters._pending_permissions["thread-ws-fail-permissions:perm-1"] = (
        PermissionRequest(
            thread_id="thread-ws-fail-permissions",
            agent_id="vaultspec-coder",
            timestamp=0.0,
            request_id="thread-ws-fail-permissions:perm-1",
            description="Approve write?",
            options=[],
        ),
        0.0,
    )

    await mark_thread_failed(
        "thread-ws-fail-permissions",
        session_factory,
        aggregator=aggregator,
    )

    async with session_factory() as session:
        updated = await get_thread(session, "thread-ws-fail-permissions")
        pending = await get_pending_permission_requests(
            session,
            thread_id="thread-ws-fail-permissions",
        )

    assert updated is not None
    assert updated.status == "failed"
    assert updated.repair_status == "operator_intervention_required"
    assert pending == []
    assert aggregator.get_pending_permissions() == []

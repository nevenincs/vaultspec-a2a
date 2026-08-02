"""Dispatch-failure state transitions stay aligned with readiness semantics."""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import pytest
import pytest_asyncio
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ...api.tests.clarification_harness import park_clarification
from ...control.circuit_breaker import WorkerCircuitBreaker
from ...control.clarification_service import respond_to_clarification
from ...control.message_service import send_followup_message
from ...control.repair_transitions import apply_dispatch_failure
from ...control.worker_management import LazyWorkerSpawner
from ...database import (
    create_thread,
    get_thread,
)
from ...database.models import Base
from ...providers.conditions import ProviderCondition
from ...thread.clarification import ClarificationAnswers
from ...thread.dispatch_policy import FailureType
from ...thread.enums import ThreadStatus

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path


@pytest_asyncio.fixture
async def engine(
    tmp_path_factory: pytest.TempPathFactory,
) -> AsyncIterator[AsyncEngine]:
    """Create a file-backed engine for dispatch-failure tests."""
    case_dir = tmp_path_factory.mktemp("dispatch-failure-db")
    db_file = case_dir / "test.db"
    eng = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session_factory(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    """Provide an async session factory bound to the test engine."""
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest.mark.asyncio
async def test_ambiguous_followup_failure_preserves_redrive_eligibility(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Unreachable delivery retains ownership without terminalizing the run."""
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
        assert result.thread_status == "submitted"

    async with session_factory() as session:
        updated = await get_thread(session, thread.id)
        assert updated is not None
        assert updated.status == "submitted"
        assert updated.last_requested_action == "message_followup_requested"
        # Delivery is undecided here - the lease is retained precisely because
        # the worker may have scheduled the task before the acknowledgement was
        # lost - so no arm may record that the message did not arrive.
        assert updated.repair_reason is None
        assert updated.failure_reason is None
        assert updated.provider_condition is None


@pytest.mark.asyncio
async def test_a_definitely_undelivered_followup_records_why_it_did_not_arrive(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A released follow-up claim leaves a durable account, not silence.

    An open circuit is a definite non-delivery: the dispatch never left the
    gateway, so the claim is released and the message certainly did not arrive.
    That is a fact worth persisting, and the run is alive throughout, so it
    persists where a live run can honestly carry it.
    """
    async with session_factory() as session:
        thread = await create_thread(
            session,
            title="Definite non-delivery",
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
        recovery_timeout=30.0,
    )
    circuit_breaker.force_open()

    async with (
        httpx.AsyncClient(base_url="http://127.0.0.1:9", timeout=0.2) as client,
        session_factory() as session,
    ):
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
    assert result.failure_type is FailureType.CIRCUIT_OPEN

    async with session_factory() as session:
        updated = await get_thread(session, thread.id)
        assert updated is not None
        # The run never changed state: a message that did not arrive did not
        # fail the run, and neither failure column may claim otherwise.
        assert updated.status == "submitted"
        assert updated.failure_reason is None
        assert updated.provider_condition is None
        assert updated.repair_reason is not None
        assert updated.repair_reason.startswith("Follow-up message not delivered:")
        assert result.error_detail is not None
        assert result.error_detail in updated.repair_reason
        # The released claim stays redrivable, so the repair state must not have
        # escalated to the terminal operator-intervention state.
        assert updated.repair_status == "healthy"
        assert updated.execution_readiness == "healthy"


@pytest.mark.asyncio
async def test_a_failed_dispatch_records_its_reason_and_condition(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A dispatch that fails the run persists why, on both durable channels."""
    async with session_factory() as session:
        thread = await create_thread(
            session,
            title="Failed dispatch",
            repair_status="healthy",
            execution_readiness="healthy",
        )
        await session.commit()

    async with session_factory() as session:
        await apply_dispatch_failure(
            session,
            thread.id,
            failed_status=ThreadStatus.FAILED,
            reason="the gateway worker is not reachable",
        )
        await session.commit()

    async with session_factory() as session:
        updated = await get_thread(session, thread.id)
        assert updated is not None
        assert updated.status == ThreadStatus.FAILED.value
        assert updated.failure_reason == "the gateway worker is not reachable"
        # The floor, not a provider member: nothing here reached a provider.
        assert updated.provider_condition == ProviderCondition.UNKNOWN.value
        assert updated.repair_reason == "the gateway worker is not reachable"


@pytest.mark.asyncio
async def test_an_undelivered_resume_does_not_stamp_a_failure_on_a_live_run(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A run left parked keeps its question, and reports no failure.

    The permission-resume caller passes INPUT_REQUIRED: the resume did not
    arrive, but the run is still alive and still waiting on its answer. Writing
    a failure reason or condition here would make a reloading client report a
    failure that never happened, because both columns are defined as describing
    a run that FAILED. The account survives on the repair reason instead.
    """
    async with session_factory() as session:
        thread = await create_thread(
            session,
            title="Undelivered resume",
            repair_status="healthy",
            execution_readiness="healthy",
        )
        await session.commit()

    async with session_factory() as session:
        await apply_dispatch_failure(
            session,
            thread.id,
            failed_status=ThreadStatus.INPUT_REQUIRED,
            reason="the gateway worker is not reachable",
        )
        await session.commit()

    async with session_factory() as session:
        updated = await get_thread(session, thread.id)
        assert updated is not None
        assert updated.status == ThreadStatus.INPUT_REQUIRED.value
        assert updated.failure_reason is None
        assert updated.provider_condition is None
        # Not lost, just carried where a still-live run can honestly carry it.
        assert updated.repair_reason == "the gateway worker is not reachable"


@pytest.mark.asyncio
async def test_a_definitely_undelivered_resume_records_why_the_answer_did_not_land(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """An answer that never reached the parked node says so durably.

    The clarification is parked in a real checkpoint by the real graph, and an
    open circuit is a definite non-delivery: the resume never left the gateway,
    so the claim is released and the answer certainly did not reach the node.
    The run is untouched - still parked, still answerable - so the account is
    recorded where a live run can carry it and nowhere that claims a failure.
    """
    thread_id = "undelivered-clarification-resume"
    async with AsyncSqliteSaver.from_conn_string(
        str(tmp_path / "clarification-checkpoints.db")
    ) as checkpointer:
        await checkpointer.setup()
        parked = await park_clarification(checkpointer, thread_id=thread_id)

        async with session_factory() as session:
            await create_thread(
                session,
                thread_id=thread_id,
                status=ThreadStatus.INPUT_REQUIRED,
                title="Undelivered clarification resume",
                repair_status="paused_resumable",
                execution_readiness="paused_resumable",
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
            recovery_timeout=30.0,
        )
        circuit_breaker.force_open()

        async with (
            httpx.AsyncClient(base_url="http://127.0.0.1:9", timeout=0.2) as client,
            session_factory() as session,
        ):
            result = await respond_to_clarification(
                session,
                thread_id=thread_id,
                request_id=parked.request.request_id,
                resolution=ClarificationAnswers(
                    request_id=parked.request.request_id,
                    answers={"provider": "codex"},
                ),
                checkpointer=checkpointer,
                worker_client=client,
                circuit_breaker=circuit_breaker,
                worker_spawner=spawner,
                recursion_limit=1,
                trace_headers=None,
            )

    assert result.dispatched is False
    assert result.failure_type is FailureType.CIRCUIT_OPEN

    async with session_factory() as session:
        updated = await get_thread(session, thread_id)
        assert updated is not None
        # Still parked on the same question, so no failure may be stamped.
        assert updated.status == ThreadStatus.INPUT_REQUIRED.value
        assert updated.failure_reason is None
        assert updated.provider_condition is None
        assert updated.repair_reason is not None
        assert updated.repair_reason.startswith("Clarification resume not delivered:")
        assert result.error_detail is not None
        assert result.error_detail in updated.repair_reason
        # The resume stays resumable: a released claim is redrivable, and the
        # pause it is parked on is unchanged.
        assert updated.repair_status == "paused_resumable"
        assert updated.execution_readiness == "paused_resumable"

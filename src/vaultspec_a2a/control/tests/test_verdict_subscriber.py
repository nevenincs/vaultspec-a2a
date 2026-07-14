"""Integration tests for the verdict subscriber's correlation and cursor paths.

Real aiosqlite database and a real LangGraph ``AsyncSqliteSaver`` checkpointer,
no mocks. These cover the two internals that do not require the engine or the
worker: correlating an inbound verdict's ids to a parked run through its
checkpointed ``TeamState`` references, and the durable cursor that survives a
gateway restart. The engine-facing SSE consumption is proved live in
``test_verdict_subscriber_live``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import pytest
import pytest_asyncio
from langgraph.checkpoint.base import empty_checkpoint
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

from vaultspec_a2a.control.circuit_breaker import WorkerCircuitBreaker
from vaultspec_a2a.control.verdict_subscriber import VerdictSubscriber
from vaultspec_a2a.control.worker_management import LazyWorkerSpawner
from vaultspec_a2a.database import (
    create_thread,
    get_authoring_cursor,
    update_thread_status,
)
from vaultspec_a2a.database.models import Base
from vaultspec_a2a.thread.enums import ThreadStatus


@pytest_asyncio.fixture
async def session_factory(
    tmp_path,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """A real file-backed aiosqlite session factory with the schema created."""
    db_file = tmp_path / "subscriber.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


def _make_subscriber(
    session_factory: async_sessionmaker[AsyncSession],
    checkpointer: AsyncSqliteSaver,
    worker_client: httpx.AsyncClient,
) -> VerdictSubscriber:
    """Construct a subscriber with real (unused-in-correlation) dispatch deps."""
    return VerdictSubscriber(
        session_factory=session_factory,
        checkpointer=checkpointer,
        worker_client=worker_client,
        circuit_breaker=WorkerCircuitBreaker(
            failure_threshold=3, recovery_timeout=30.0
        ),
        worker_spawner=LazyWorkerSpawner(
            worker_url="http://127.0.0.1:1", worker_port=1, auto_spawn=False
        ),
        endpoint_provider=lambda: None,
        recursion_limit=25,
    )


async def _seed_parked_thread(
    session_factory: async_sessionmaker[AsyncSession],
    checkpointer: AsyncSqliteSaver,
    *,
    thread_id: str,
    proposal_ids: list[str],
    changeset_ids: list[str],
) -> None:
    """Create an INPUT_REQUIRED thread with a checkpoint carrying authoring ids."""
    await checkpointer.setup()
    checkpoint = empty_checkpoint()
    checkpoint["id"] = f"cp-{thread_id}"
    checkpoint["channel_values"]["authoring_proposal_ids"] = proposal_ids
    checkpoint["channel_values"]["authoring_changeset_ids"] = changeset_ids
    await checkpointer.aput(
        {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}},
        checkpoint,
        {"source": "loop", "step": 1, "parents": {}},
        {},
    )
    async with session_factory() as session:
        await create_thread(session, thread_id=thread_id)
        await update_thread_status(session, thread_id, ThreadStatus.INPUT_REQUIRED)
        await session.commit()


@pytest.mark.asyncio
async def test_correlates_parked_thread_by_proposal_id(
    tmp_path, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    checkpoints = tmp_path / "cp-proposal.db"
    async with (
        AsyncSqliteSaver.from_conn_string(str(checkpoints)) as checkpointer,
        httpx.AsyncClient(base_url="http://127.0.0.1:1") as worker_client,
    ):
        await _seed_parked_thread(
            session_factory,
            checkpointer,
            thread_id="thread-parked-1",
            proposal_ids=["prop_abc"],
            changeset_ids=["cs_abc"],
        )
        subscriber = _make_subscriber(session_factory, checkpointer, worker_client)
        matched = await subscriber._find_parked_thread({"prop_abc"})
        assert matched == "thread-parked-1"


@pytest.mark.asyncio
async def test_correlates_parked_thread_by_changeset_id(
    tmp_path, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    checkpoints = tmp_path / "cp-changeset.db"
    async with (
        AsyncSqliteSaver.from_conn_string(str(checkpoints)) as checkpointer,
        httpx.AsyncClient(base_url="http://127.0.0.1:1") as worker_client,
    ):
        await _seed_parked_thread(
            session_factory,
            checkpointer,
            thread_id="thread-parked-2",
            proposal_ids=[],
            changeset_ids=["cs_xyz"],
        )
        subscriber = _make_subscriber(session_factory, checkpointer, worker_client)
        matched = await subscriber._find_parked_thread({"cs_xyz", "unrelated"})
        assert matched == "thread-parked-2"


@pytest.mark.asyncio
async def test_unknown_ids_correlate_to_nothing(
    tmp_path, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    checkpoints = tmp_path / "cp-none.db"
    async with (
        AsyncSqliteSaver.from_conn_string(str(checkpoints)) as checkpointer,
        httpx.AsyncClient(base_url="http://127.0.0.1:1") as worker_client,
    ):
        await _seed_parked_thread(
            session_factory,
            checkpointer,
            thread_id="thread-parked-3",
            proposal_ids=["prop_known"],
            changeset_ids=["cs_known"],
        )
        subscriber = _make_subscriber(session_factory, checkpointer, worker_client)
        assert await subscriber._find_parked_thread({"prop_missing"}) is None


@pytest.mark.asyncio
async def test_non_parked_thread_is_not_correlated(
    tmp_path, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """A RUNNING thread is not a gate-parked candidate even with matching ids."""
    checkpoints = tmp_path / "cp-running.db"
    async with (
        AsyncSqliteSaver.from_conn_string(str(checkpoints)) as checkpointer,
        httpx.AsyncClient(base_url="http://127.0.0.1:1") as worker_client,
    ):
        await _seed_parked_thread(
            session_factory,
            checkpointer,
            thread_id="thread-running",
            proposal_ids=["prop_running"],
            changeset_ids=[],
        )
        async with session_factory() as session:
            await update_thread_status(session, "thread-running", ThreadStatus.RUNNING)
            await session.commit()
        subscriber = _make_subscriber(session_factory, checkpointer, worker_client)
        assert await subscriber._find_parked_thread({"prop_running"}) is None


@pytest.mark.asyncio
async def test_cursor_advances_and_survives_restart(
    tmp_path, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """The durable cursor a restarted subscriber reads is the last it advanced."""
    checkpoints = tmp_path / "cp-cursor.db"
    async with (
        AsyncSqliteSaver.from_conn_string(str(checkpoints)) as checkpointer,
        httpx.AsyncClient(base_url="http://127.0.0.1:1") as worker_client,
    ):
        first = _make_subscriber(session_factory, checkpointer, worker_client)
        assert await first._read_cursor() == 0
        await first._advance_cursor(17)

        # A fresh subscriber instance models the post-restart gateway process.
        second = _make_subscriber(session_factory, checkpointer, worker_client)
        assert await second._read_cursor() == 17

    async with session_factory() as session:
        assert await get_authoring_cursor(session) == 17

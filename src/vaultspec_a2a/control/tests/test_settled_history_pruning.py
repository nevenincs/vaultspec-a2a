"""The gateway prunes a run's checkpoint history once its terminal is proven.

Drives the real relay seam (``_handle_terminal_event``) against a real SQLite
application database and a real checkpoint store holding a superseded
checkpoint beneath the run's proven completion. Pruning follows acceptance and
never precedes it: a completion the checkpoint cannot prove keeps every
checkpoint recovery may still need.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pytest
import pytest_asyncio
from langgraph.checkpoint.base import empty_checkpoint
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ...conftest import materialize_schema
from ...database.models import ThreadModel
from ...thread.enums import ThreadStatus
from ..event_handlers import _handle_terminal_event, settle_pending_checkpoint_prunes
from .test_terminal_sequence_capture import _seed_completed_authority

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@pytest_asyncio.fixture
async def engine(
    tmp_path_factory: pytest.TempPathFactory,
) -> AsyncIterator[AsyncEngine]:
    db_file = tmp_path_factory.mktemp("settled-history-db") / "test.db"
    materialize_schema(Path(db_file))
    eng = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def checkpointer(
    tmp_path_factory: pytest.TempPathFactory,
) -> AsyncIterator[AsyncSqliteSaver]:
    db_file = tmp_path_factory.mktemp("settled-history-checkpoints") / "cp.db"
    async with AsyncSqliteSaver.from_conn_string(str(db_file)) as cp:
        yield cp


async def _put_bare_checkpoint(
    checkpointer: AsyncSqliteSaver, thread_id: str, checkpoint_id: str
) -> None:
    checkpoint = empty_checkpoint()
    checkpoint["id"] = checkpoint_id
    await checkpointer.aput(
        {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}},
        checkpoint,
        {"source": "loop", "step": 0, "parents": {}},
        {},
    )


async def _checkpoint_ids(checkpointer: AsyncSqliteSaver, thread_id: str) -> list[str]:
    config = cast("Any", {"configurable": {"thread_id": thread_id}})
    return sorted(
        [
            item.config["configurable"]["checkpoint_id"]
            async for item in checkpointer.alist(config)
        ]
    )


async def _status(
    session_factory: async_sessionmaker[AsyncSession], thread_id: str
) -> str:
    async with session_factory() as session:
        row = await session.get(ThreadModel, thread_id)
    assert row is not None
    return row.status


@pytest.mark.asyncio
async def test_a_proven_completion_prunes_the_superseded_checkpoints(
    session_factory: async_sessionmaker[AsyncSession], checkpointer: AsyncSqliteSaver
) -> None:
    async with session_factory() as session:
        thread_id, _receipt = await _seed_completed_authority(
            session, checkpointer, title="settled history"
        )
    # Sorts beneath the seeded completion, as an earlier superstep's id would.
    await _put_bare_checkpoint(checkpointer, thread_id, f"a-{thread_id}")
    assert await _checkpoint_ids(checkpointer, thread_id) == [
        f"a-{thread_id}",
        f"cp-{thread_id}",
    ]

    await _handle_terminal_event(
        thread_id,
        {"event_type": "thread_terminal", "status": "completed"},
        session_factory=session_factory,
        checkpointer=checkpointer,
    )
    # The prune runs behind the relay rather than inside it; shutdown waits for
    # it the same way before closing the store.
    await settle_pending_checkpoint_prunes()

    assert await _status(session_factory, thread_id) == ThreadStatus.COMPLETED
    assert await _checkpoint_ids(checkpointer, thread_id) == [f"cp-{thread_id}"]


@pytest.mark.asyncio
async def test_an_unproven_completion_keeps_the_whole_history(
    session_factory: async_sessionmaker[AsyncSession], checkpointer: AsyncSqliteSaver
) -> None:
    async with session_factory() as session:
        thread_id, _receipt = await _seed_completed_authority(
            session, checkpointer, title="unproven history"
        )
    # A newer checkpoint carrying no completion receipt is what the proof reads,
    # so the completion is refused and the run is not settled.
    await _put_bare_checkpoint(checkpointer, thread_id, f"a-{thread_id}")
    await _put_bare_checkpoint(checkpointer, thread_id, f"zz-{thread_id}")
    history = await _checkpoint_ids(checkpointer, thread_id)
    assert len(history) == 3

    await _handle_terminal_event(
        thread_id,
        {"event_type": "thread_terminal", "status": "completed"},
        session_factory=session_factory,
        checkpointer=checkpointer,
    )
    await settle_pending_checkpoint_prunes()

    assert await _status(session_factory, thread_id) != ThreadStatus.COMPLETED
    assert await _checkpoint_ids(checkpointer, thread_id) == history

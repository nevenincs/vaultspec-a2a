"""The gateway prunes a run's checkpoint history once its terminal is proven.

Drives the real relay seam (``_handle_terminal_event``) against a real SQLite
application database and a real checkpoint store holding a superseded
checkpoint beneath the run's proven completion. Pruning follows acceptance and
never precedes it: a completion the checkpoint cannot prove keeps every
checkpoint recovery may still need.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import pytest

from ...database.models import ThreadModel
from ...tests._checkpoint_seeding import real_checkpoint
from ...thread.enums import ThreadStatus
from ..event_handlers import CheckpointPruneRegistry, _handle_terminal_event
from .test_terminal_sequence_capture import _seed_completed_authority

if TYPE_CHECKING:
    from collections.abc import Mapping

    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
    )


async def _put_bare_checkpoint(
    checkpointer: AsyncSqliteSaver, thread_id: str, checkpoint_id: str
) -> None:
    checkpoint = await real_checkpoint()
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
            cast("Mapping[str, Mapping[str, str]]", item.config)["configurable"][
                "checkpoint_id"
            ]
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

    prunes = CheckpointPruneRegistry()
    await _handle_terminal_event(
        thread_id,
        {"event_type": "thread_terminal", "status": "completed"},
        session_factory=session_factory,
        checkpointer=checkpointer,
        prune_registry=prunes,
    )
    # The prune runs behind the relay rather than inside it; shutdown waits for
    # it the same way before closing the store.
    await prunes.settle()

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

    prunes = CheckpointPruneRegistry()
    await _handle_terminal_event(
        thread_id,
        {"event_type": "thread_terminal", "status": "completed"},
        session_factory=session_factory,
        checkpointer=checkpointer,
        prune_registry=prunes,
    )
    await prunes.settle()

    assert await _status(session_factory, thread_id) != ThreadStatus.COMPLETED
    assert await _checkpoint_ids(checkpointer, thread_id) == history

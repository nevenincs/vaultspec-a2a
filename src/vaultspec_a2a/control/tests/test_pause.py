"""The pause recorder trusts the checkpoint over a merely-submitted response.

The checkpoint owns whether a run is parked; the permission journal only
records that a request exists and, once answered, that an option was chosen.
A submitted response is not an applied one: the answer is durable before the
graph has resumed and cleared the checkpoint's interrupt, so a reconcile pass
that ran in that exact window must still read the run as parked. Reading the
DB-level "answered" status instead would un-park a run whose question the
worker has not actually taken off the table yet.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ...control.pause import reconcile_run_pause
from ...database import (
    get_thread,
    record_permission_response_submission,
)
from ...testing import park_journaled_permission, seed_journaled_thread
from ...thread.enums import ThreadStatus

if TYPE_CHECKING:
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.mark.asyncio
async def test_a_submitted_response_does_not_release_a_still_parked_checkpoint(
    session_factory: async_sessionmaker[AsyncSession],
    checkpointer: AsyncSqliteSaver,
) -> None:
    """The run stays parked while its checkpoint still holds the interrupt.

    The permission response is submitted (``answered_pending_apply``) at the
    journal level, but nothing has resumed the graph, so the checkpoint this
    reconcile pass reads still shows the same unanswered interrupt it parked
    on. The run must stay ``input_required``.
    """
    thread_id = "pause-submitted-not-applied"
    async with session_factory() as session:
        await seed_journaled_thread(
            session, status=ThreadStatus.INPUT_REQUIRED, thread_id=thread_id
        )
        await session.commit()

    request_id = await park_journaled_permission(
        checkpointer, session_factory, thread_id=thread_id
    )

    async with session_factory() as session:
        await record_permission_response_submission(
            session,
            request_id=request_id,
            option_id="allow_once",
            idempotency_key="submitted-not-applied",
        )
        await session.commit()

    async with session_factory() as session:
        await reconcile_run_pause(
            session, thread_id=thread_id, checkpointer=checkpointer
        )

    async with session_factory() as session:
        thread = await get_thread(session, thread_id)
    assert thread is not None
    assert thread.status == ThreadStatus.INPUT_REQUIRED.value
    assert thread.repair_status == "paused_resumable"


@pytest.mark.asyncio
async def test_a_run_with_no_checkpoint_at_all_is_left_untouched(
    session_factory: async_sessionmaker[AsyncSession],
    checkpointer: AsyncSqliteSaver,
) -> None:
    """A recordable run with nothing in the checkpoint store yet is a no-op.

    Nothing is readable, so the pass projects nothing to compare and writes
    nothing - the counterpart case to the submitted-but-unapplied response:
    just as a stale DB answer must not release a parked run, a wholly absent
    checkpoint must not move a running one either.
    """
    thread_id = "pause-nothing-to-reconcile"
    async with session_factory() as session:
        await seed_journaled_thread(
            session, status=ThreadStatus.RUNNING, thread_id=thread_id
        )
        await session.commit()

    async with session_factory() as session:
        await reconcile_run_pause(
            session, thread_id=thread_id, checkpointer=checkpointer
        )

    async with session_factory() as session:
        thread = await get_thread(session, thread_id)
    assert thread is not None
    assert thread.status == ThreadStatus.RUNNING.value

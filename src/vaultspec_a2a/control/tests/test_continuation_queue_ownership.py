"""A run with a turn waiting on it is owned, not abandoned - for a while.

Between a turn ending and its continuation being promoted, a run is RUNNING
with no live worker. The abandoned-transition reconciler cannot tell that from
a writer that died: both leave a live run whose checkpoint proves nothing is
happening. Moving it into repair there is not harmless - it takes the run away
from the promoter underneath them and leaves the accepted turn waiting behind
a run nobody is promoting.

The lease on the waiting reservation is what separates the two, and it is also
what bounds the exemption. While a promoter holds it, the reconciler leaves
the run alone and the startup pass reports it as owned rather than as backlog.
Once it lapses, nobody is answerable and ordinary reconciliation resumes.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from ...database import get_thread
from ...database.models import ControlActionModel
from ...database.reconciliation import reconcile_threads_on_startup
from ...thread.enums import ControlActionResultStatus, RepairStatus, ThreadStatus
from ..recovery_authority import (
    HOLDS_QUEUED_CONTINUATION,
    RecoveryRequest,
    RecoveryTrigger,
    reconcile_run_checkpoint,
)
from ..repositories import count_queued_continuations
from ._continuation import RUN, BusyRun, queue_continuation


async def _lapse_the_lease(run: BusyRun) -> None:
    """Let the promoter's ownership of the waiting turn expire."""
    async with run.sessions() as db:
        waiting = await db.scalar(
            select(ControlActionModel).where(
                ControlActionModel.thread_id == RUN,
                ControlActionModel.result_status
                == ControlActionResultStatus.QUEUED.value,
            )
        )
        assert waiting is not None
        waiting.claim_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await db.commit()


@pytest.mark.asyncio
async def test_a_run_with_a_turn_waiting_on_it_is_left_alone(
    busy_run: BusyRun,
) -> None:
    """The first turn proved nothing yet, and the run is still someone's."""
    await queue_continuation(busy_run.sessions, busy_run.workspace)

    async with busy_run.sessions() as db:
        observed = await reconcile_run_checkpoint(
            db,
            busy_run.saver,
            RecoveryRequest(
                thread_id=RUN,
                trigger=RecoveryTrigger.STARTUP,
                checkpoint_timeout_seconds=5,
            ),
        )

    assert observed.condition == HOLDS_QUEUED_CONTINUATION
    assert observed.status is ThreadStatus.RUNNING
    assert not observed.changed

    async with busy_run.sessions() as reader:
        thread = await get_thread(reader, RUN)
        assert thread is not None
        assert thread.status == ThreadStatus.RUNNING.value
        assert thread.repair_status != RepairStatus.NEEDS_RECONCILIATION.value
        # The waiting turn is still waiting, at the place it was given.
        assert await count_queued_continuations(reader, thread_id=RUN) == 1


@pytest.mark.asyncio
async def test_the_startup_pass_counts_an_owned_run_apart_from_its_backlog(
    busy_run: BusyRun,
) -> None:
    """A run somebody is answerable for is not damage a boot has to report."""
    await queue_continuation(busy_run.sessions, busy_run.workspace)

    async with busy_run.sessions() as db:
        summary = await reconcile_threads_on_startup(db, busy_run.saver)
        await db.commit()

    assert summary["owned_by_promotion"] == 1
    assert summary["repair_backlog"] == 0

    async with busy_run.sessions() as reader:
        thread = await get_thread(reader, RUN)
        assert thread is not None
        assert thread.status == ThreadStatus.RUNNING.value


@pytest.mark.asyncio
async def test_ownership_ends_with_the_lease_and_reconciliation_resumes(
    busy_run: BusyRun,
) -> None:
    """The exemption is bounded: a lapsed lease makes the run damage again.

    This is the half that keeps the rule honest. A run exempted forever
    because something is queued on it would be the abandoned transition the
    reconciler exists to catch, wearing a queue as a disguise.
    """
    await queue_continuation(busy_run.sessions, busy_run.workspace)
    await _lapse_the_lease(busy_run)

    async with busy_run.sessions() as db:
        summary = await reconcile_threads_on_startup(db, busy_run.saver)
        await db.commit()

    assert summary["owned_by_promotion"] == 0
    assert summary["repair_backlog"] == 1

    async with busy_run.sessions() as reader:
        thread = await get_thread(reader, RUN)
        assert thread is not None
        assert thread.status == ThreadStatus.RECONCILING.value
        # Even then the turn is not thrown away: it waits for whatever
        # repair does with the run.
        assert await count_queued_continuations(reader, thread_id=RUN) == 1

"""A queue cannot make a run immortal.

Deferring a terminal is the whole point of the continuation model, so the
thing that has to be proven is where the deferral stops. A run carries one
total lifetime from its creation, spanning every turn a continuation adds.
Past it, the run ends with the terminal its last turn actually reached, and
what was still waiting is refused rather than left on a settled run waiting
for a promotion that can never come.

Short of it, the last turn a run is allowed gets the time that is left rather
than a fresh full budget, which is the other half of the same bound.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from ...database import get_thread
from ...domain_config import domain_config
from ...thread.enums import ControlActionResultStatus, ThreadStatus
from ..recovery_authority import (
    CONTINUATION_PROMOTED,
    RecoveryObservation,
    RecoveryRequest,
    RecoveryTrigger,
    reconcile_run_checkpoint,
)
from ..repositories import count_queued_continuations, run_lifetime_deadline
from ._continuation import (
    RUN,
    BusyRun,
    busy_run_state,
    definition,
    finish_turn,
    journal_action,
    queue_continuation,
)

if TYPE_CHECKING:
    from pathlib import Path


def _age(seconds: int) -> datetime:
    """Return a creation instant *seconds* in the past."""
    return datetime.now(UTC) - timedelta(seconds=seconds)


async def _reconcile(run: BusyRun) -> RecoveryObservation:
    async with run.sessions() as db:
        return await reconcile_run_checkpoint(
            db,
            run.saver,
            RecoveryRequest(
                thread_id=RUN,
                trigger=RecoveryTrigger.WORKER_EVENT,
                checkpoint_timeout_seconds=5,
            ),
        )


@pytest.mark.asyncio
async def test_a_run_past_its_lifetime_settles_rather_than_promoting(
    tmp_path: Path,
) -> None:
    """The run ends where it is, and the waiting turn is refused, not lost.

    The reservation is admitted while the run still had time, as a real one
    would be; the bound is read at promotion from the run's own age, which is
    the only moment that can know whether another turn still fits.
    """
    spent = _age(domain_config.max_run_lifetime_seconds + 60)
    async with busy_run_state(tmp_path, created_at=spent) as run:
        continuation = await queue_continuation(run.sessions, run.workspace)
        await finish_turn(run.saver, run.receipt)

        observed = await _reconcile(run)

        assert observed.status is ThreadStatus.COMPLETED
        assert observed.condition != CONTINUATION_PROMOTED
        assert observed.changed

        async with run.sessions() as reader:
            thread = await get_thread(reader, RUN)
            assert thread is not None
            assert thread.status == ThreadStatus.COMPLETED.value

            refused = await journal_action(reader, continuation)
            assert refused.result_status == (
                ControlActionResultStatus.REJECTED_INVALID_STATE.value
            )
            assert refused.applied_at is not None
            assert refused.claim_token is None
            # The record still says what was refused and where it sat.
            assert refused.queue_position == 1
            # Nothing is left waiting on a run that can never promote it.
            assert await count_queued_continuations(reader, thread_id=RUN) == 0


@pytest.mark.asyncio
async def test_the_last_turn_gets_the_time_that_is_left(tmp_path: Path) -> None:
    """A promotion near the bound is capped by it, not given a fresh budget."""
    remaining = 120
    started = _age(domain_config.max_run_lifetime_seconds - remaining)
    async with busy_run_state(tmp_path, created_at=started) as run:
        continuation = await queue_continuation(run.sessions, run.workspace)
        await finish_turn(run.saver, run.receipt)
        lifetime_deadline = run_lifetime_deadline(started)
        budget = definition(run.workspace).run_timeout_seconds
        assert budget > remaining, "the turn's own budget must exceed what is left"

        observed = await _reconcile(run)

        assert observed.condition == CONTINUATION_PROMOTED
        async with run.sessions() as reader:
            promoted = await journal_action(reader, continuation)
            assert promoted.recovery_deadline_at is not None
            assert promoted.recovery_deadline_at == lifetime_deadline
            assert promoted.recovery_deadline_at < datetime.now(UTC) + timedelta(
                seconds=budget
            )


@pytest.mark.asyncio
async def test_a_young_run_keeps_its_turn_s_own_budget(tmp_path: Path) -> None:
    """The cap only binds near the end; an ordinary promotion is unaffected."""
    async with busy_run_state(tmp_path, created_at=_age(60)) as run:
        continuation = await queue_continuation(run.sessions, run.workspace)
        await finish_turn(run.saver, run.receipt)
        budget = definition(run.workspace).run_timeout_seconds
        before = datetime.now(UTC)

        observed = await _reconcile(run)

        assert observed.condition == CONTINUATION_PROMOTED
        async with run.sessions() as reader:
            promoted = await journal_action(reader, continuation)
            assert promoted.recovery_deadline_at is not None
            assert promoted.recovery_deadline_at >= before + timedelta(
                seconds=budget - 5
            )
            assert promoted.recovery_deadline_at < run_lifetime_deadline(_age(60))

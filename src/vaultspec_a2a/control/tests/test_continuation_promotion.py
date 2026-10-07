"""A proven turn hands the run to the continuation waiting behind it.

Driven end to end against the real pieces: a real LangGraph run over a real
``AsyncSqliteSaver`` produces the completion receipt, a real journal row
reserved through the production queue repository is the continuation, and the
real reconciliation authority reads one and promotes the other. Nothing here
stands in for anything.

The run must come out of this still RUNNING, owned by the next turn, with the
turn that just ended recorded as applied - and with none of the things a
settlement does: no terminal election, no settled-history prune, no release of
the run's admission slot.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from ...database import get_thread
from ...thread.enums import (
    ControlActionResultStatus,
    ControlActionType,
    ThreadStatus,
)
from ..drain import DrainGate
from ..event_handlers import CheckpointPruneRegistry, relay_event
from ..recovery_authority import (
    CONTINUATION_PROMOTED,
    RecoveryObservation,
    RecoveryRequest,
    RecoveryTrigger,
    reconcile_run_checkpoint,
)
from ..repositories import count_queued_continuations
from ._continuation import (
    FIRST_RECEIPT,
    RUN,
    BusyRun,
    checkpoint_count,
    definition,
    finish_turn,
    journal_action,
    queue_continuation,
)


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
async def test_a_proven_turn_promotes_instead_of_settling(busy_run: BusyRun) -> None:
    """The next turn takes the run's write authority; the run stays RUNNING."""
    continuation = await queue_continuation(busy_run.sessions, busy_run.workspace)
    await finish_turn(busy_run.saver, busy_run.receipt)

    observed = await _reconcile(busy_run)

    assert observed.status is ThreadStatus.RUNNING
    assert observed.condition == CONTINUATION_PROMOTED
    assert observed.changed

    async with busy_run.sessions() as reader:
        thread = await get_thread(reader, RUN)
        assert thread is not None
        assert thread.status == ThreadStatus.RUNNING.value
        assert thread.is_active
        # The continuation now holds the run's write authority, under a
        # generation of its own so the first turn's receipt cannot speak again.
        assert thread.writer_action_type == (
            ControlActionType.MESSAGE_FOLLOWUP_REQUESTED.value
        )
        assert thread.writer_action_receipt_id == continuation
        assert thread.writer_generation == 2
        assert thread.run_revision == 1

        promoted = await journal_action(reader, continuation)
        assert promoted.applied_at is None
        assert promoted.result_status == (
            ControlActionResultStatus.ACCEPTED_NOT_APPLIED.value
        )
        assert promoted.graph_receipt_json is not None
        # Promotion is not the dispatcher, so it gives the lease back for the
        # durable owner that will deliver this turn.
        assert promoted.claim_token is None
        assert promoted.claim_expires_at is None
        # Where this turn came from survives promotion.
        assert promoted.queue_position == 1
        assert await count_queued_continuations(reader, thread_id=RUN) == 0


@pytest.mark.asyncio
async def test_the_turn_that_ended_is_recorded_applied_and_its_budget_renewed(
    busy_run: BusyRun,
) -> None:
    """The proven turn settles as applied; the next one gets its own deadline."""
    continuation = await queue_continuation(busy_run.sessions, busy_run.workspace)
    await finish_turn(busy_run.saver, busy_run.receipt)
    before = datetime.now(UTC)

    await _reconcile(busy_run)

    async with busy_run.sessions() as reader:
        first = await journal_action(reader, FIRST_RECEIPT)
        assert first.applied_at is not None
        assert first.result_status == ControlActionResultStatus.APPLIED.value

        promoted = await journal_action(reader, continuation)
        assert promoted.recovery_deadline_at is not None
        budget = definition(busy_run.workspace).run_timeout_seconds
        # Re-derived at promotion from the promoted turn's OWN envelope, not
        # inherited from the reservation's run-lifetime bound.
        assert promoted.recovery_deadline_at >= before + timedelta(seconds=budget - 5)
        assert promoted.recovery_deadline_at <= datetime.now(UTC) + timedelta(
            seconds=budget
        )


@pytest.mark.asyncio
async def test_an_empty_queue_settles_the_run_exactly_as_before(
    busy_run: BusyRun,
) -> None:
    """Nothing waiting, nothing changed: the run completes as it always has."""
    await finish_turn(busy_run.saver, busy_run.receipt)

    observed = await _reconcile(busy_run)

    assert observed.status is ThreadStatus.COMPLETED
    assert observed.changed
    async with busy_run.sessions() as reader:
        thread = await get_thread(reader, RUN)
        assert thread is not None
        assert thread.status == ThreadStatus.COMPLETED.value


@pytest.mark.asyncio
async def test_a_promoted_run_keeps_its_history_and_its_admission_slot(
    busy_run: BusyRun,
) -> None:
    """Relaying the turn's terminal frame settles nothing on a promoted run.

    The three effects a settlement has are each observable, and each must be
    absent: the run must not reach a terminal status, its superseded
    checkpoints must survive the prune a settled run triggers, and the drain
    gate must still hold the run, because the run has not finished.
    """
    await queue_continuation(busy_run.sessions, busy_run.workspace)
    await finish_turn(busy_run.saver, busy_run.receipt)
    history_before = await checkpoint_count(busy_run.saver)
    assert history_before > 1, "the probe graph must leave superseded checkpoints"

    gate = DrainGate()
    admitted = await gate.admit(RUN)
    assert admitted.admitted
    prunes = CheckpointPruneRegistry()

    await relay_event(
        RUN,
        {"type": "thread_terminal", "status": ThreadStatus.COMPLETED.value},
        session_factory=busy_run.sessions,
        checkpointer=busy_run.saver,
        drain_gate=gate,
        prune_registry=prunes,
    )
    await prunes.settle()

    assert gate.is_active(RUN), "a run with a further turn still holds its slot"
    assert await checkpoint_count(busy_run.saver) == history_before
    async with busy_run.sessions() as reader:
        thread = await get_thread(reader, RUN)
        assert thread is not None
        assert thread.status == ThreadStatus.RUNNING.value


@pytest.mark.asyncio
async def test_relaying_a_terminal_with_no_continuation_still_settles(
    busy_run: BusyRun,
) -> None:
    """The same relay path settles and releases when nothing is waiting."""
    await finish_turn(busy_run.saver, busy_run.receipt)

    gate = DrainGate()
    await gate.admit(RUN)
    prunes = CheckpointPruneRegistry()

    await relay_event(
        RUN,
        {"type": "thread_terminal", "status": ThreadStatus.COMPLETED.value},
        session_factory=busy_run.sessions,
        checkpointer=busy_run.saver,
        drain_gate=gate,
        prune_registry=prunes,
    )
    await prunes.settle()

    assert not gate.is_active(RUN)
    async with busy_run.sessions() as reader:
        thread = await get_thread(reader, RUN)
        assert thread is not None
        assert thread.status == ThreadStatus.COMPLETED.value

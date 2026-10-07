"""Admitting a continuation and settling the run resolve to exactly one outcome.

Two transactions decide opposite things about one run: an admission asks
whether the run can take another turn, and a settlement declares it over.
Run concurrently with nothing ordering them, both can win - the settlement
reads an empty queue while the admission reads a live run - and the run ends
with a turn waiting on it that nothing will ever promote. That third outcome
is the one the queue rules forbid, and it is invisible on SQLite, whose write
transaction already excludes a second writer for its whole length.

So these proofs run on a real PostgreSQL server with real concurrent
transactions on separate connections, racing in both orders, and assert the
two admissible outcomes and nothing else: either the turn queued and the
settlement promoted it, or the turn met a settled run and was refused.

The replay proofs share the lane because they rest on the same ordering: a
key already accepted is answered by its own journal row whatever the run has
done since.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from ...database import get_thread
from ...database.models import ControlActionModel
from ...domain_config import domain_config
from ...testing.catalog_authority import current_execution_metadata
from ...thread.dispatch_policy import FailureType
from ...thread.enums import ControlActionResultStatus, ThreadStatus
from ...thread.executable_graph import FrozenGraphDefinition
from ..accepted_input import AcceptedActionInput
from ..message_service import MessageResult, send_followup_message
from ..recovery_authority import (
    RecoveryObservation,
    RecoveryRequest,
    RecoveryTrigger,
    reconcile_run_checkpoint,
)
from ..repositories import count_queued_continuations
from ._continuation import RUN, BusyRun, busy_run_state, finish_turn, journal_action

if TYPE_CHECKING:
    from pathlib import Path

#: The run the continuation suites seed runs this team, so its roles are the
#: ones a current stored authority has to freeze.
_ROLES = ("mock-coder-success",)

_QUEUED = ControlActionResultStatus.QUEUED.value
_ACCEPTED = ControlActionResultStatus.ACCEPTED_NOT_APPLIED.value


async def _site_the_run(run: BusyRun) -> None:
    """Give the seeded run the stored project and authority a follow-up needs.

    Both are read, never re-derived, by the admission path: a run with no
    workspace root cannot site a turn, and one with no current execution
    authority cannot name the models it would run under.
    """
    async with run.sessions() as db:
        thread = await get_thread(db, RUN)
        assert thread is not None
        thread.thread_metadata = current_execution_metadata(
            run.workspace, required_roles=_ROLES
        )
        await db.commit()


async def _offer(
    run: BusyRun, *, key: str, content: str = "second turn"
) -> MessageResult:
    """Offer one follow-up turn through the production verb, on its own session."""
    async with run.sessions() as db:
        return await send_followup_message(
            db,
            thread_id=RUN,
            content=content,
            agent_id="vaultspec-supervisor",
            idempotency_key=key,
        )


async def _settle(run: BusyRun) -> RecoveryObservation:
    """Drive the terminal settlement of the run's proven turn, on its own session."""
    async with run.sessions() as db:
        return await reconcile_run_checkpoint(
            db,
            run.saver,
            RecoveryRequest(
                thread_id=RUN,
                trigger=RecoveryTrigger.WORKER_EVENT,
                checkpoint_timeout_seconds=10,
            ),
        )


@pytest.mark.requires_prerequisites("postgres")
@pytest.mark.parametrize("admission_first", [True, False])
@pytest.mark.asyncio
async def test_a_continuation_racing_settlement_queues_or_meets_a_settled_run(
    tmp_path: Path, admission_first: bool
) -> None:
    """Exactly one of the two admissible outcomes, in either arrival order."""
    async with busy_run_state(tmp_path, backend="postgres") as run:
        await _site_the_run(run)
        await finish_turn(run.saver, run.receipt)

        offered = _offer(run, key="race-key")
        settled = _settle(run)
        racers = (offered, settled) if admission_first else (settled, offered)
        await asyncio.gather(*racers)

        async with run.sessions() as reader:
            thread = await get_thread(reader, RUN)
            assert thread is not None
            waiting = await count_queued_continuations(reader, thread_id=RUN)
            status = thread.status
            writer = thread.writer_action_receipt_id
            if status == ThreadStatus.RUNNING.value:
                # The turn queued first and the settlement promoted it instead
                # of settling: the run goes on, owned by a turn that no longer
                # waits. Nothing is left queued behind it.
                promoted = await journal_action(reader, writer)
                assert promoted.queue_position == 1
                assert promoted.result_status == _ACCEPTED
                assert waiting == 0
                return

        # Or the settlement won and the run is over, with nothing left waiting
        # on it - the offer met a settled run and was refused.
        assert status == ThreadStatus.COMPLETED.value
        assert waiting == 0


@pytest.mark.requires_prerequisites("postgres")
@pytest.mark.asyncio
async def test_a_continuation_offered_after_settlement_is_refused(
    tmp_path: Path,
) -> None:
    """The losing order on its own, so the refusal is asserted and not inferred."""
    async with busy_run_state(tmp_path, backend="postgres") as run:
        await _site_the_run(run)
        await finish_turn(run.saver, run.receipt)

        await _settle(run)
        refused = await _offer(run, key="after-settlement")

        assert refused.queued is False
        assert refused.failure_type is FailureType.TERMINAL
        async with run.sessions() as reader:
            assert await count_queued_continuations(reader, thread_id=RUN) == 0


@pytest.mark.requires_prerequisites("postgres")
@pytest.mark.asyncio
async def test_two_continuations_racing_for_one_place_admit_exactly_one(
    tmp_path: Path,
) -> None:
    """The per-run depth holds under concurrency, not only in sequence.

    Both offers read the queue to decide whether there is room, so without
    the run lock each reads the other's empty queue and both find the same
    free place. The configured depth is one, so one of them has to lose.
    """
    async with busy_run_state(tmp_path, backend="postgres") as run:
        await _site_the_run(run)

        first, second = await asyncio.gather(
            _offer(run, key="race-a", content="turn a"),
            _offer(run, key="race-b", content="turn b"),
        )

        assert sorted([first.queued, second.queued], reverse=True) == [True, False]
        refusals = [
            result.failure_type for result in (first, second) if not result.queued
        ]
        assert refusals == [FailureType.QUEUE_FULL]
        async with run.sessions() as reader:
            assert await count_queued_continuations(reader, thread_id=RUN) == 1


@pytest.mark.requires_prerequisites("postgres")
@pytest.mark.asyncio
async def test_a_repeat_key_replays_its_place_and_a_changed_body_conflicts(
    tmp_path: Path,
) -> None:
    """One key, one turn: the same body replays, a different body refuses.

    The replay runs while the queue is full of its own first attempt, which
    is the case a depth check applied before the key lookup would get wrong.
    """
    async with busy_run_state(tmp_path, backend="postgres") as run:
        await _site_the_run(run)

        first = await _offer(run, key="replay-key", content="second turn")
        again = await _offer(run, key="replay-key", content="second turn")
        changed = await _offer(run, key="replay-key", content="a different turn")

        assert first.queued is True
        assert again.queued is True
        assert again.action_id == first.action_id
        assert again.queue_position == first.queue_position == 1
        assert again.action_status == _QUEUED

        assert changed.queued is False
        assert changed.failure_type is FailureType.CONFLICT

        async with run.sessions() as reader:
            assert await count_queued_continuations(reader, thread_id=RUN) == 1


@pytest.mark.requires_prerequisites("postgres")
@pytest.mark.asyncio
async def test_a_repeat_key_still_replays_once_its_turn_was_promoted(
    tmp_path: Path,
) -> None:
    """A lost response is answered by what became of the turn, not by the run.

    A caller that retried after losing the first answer must not be told the
    run cannot take a turn, because that reads as "your turn never ran" and
    invites it to send the work again. The run's state answers new offers; a
    key already accepted is answered by its own journal row.
    """
    async with busy_run_state(tmp_path, backend="postgres") as run:
        await _site_the_run(run)
        accepted = await _offer(run, key="survives-settlement")
        await finish_turn(run.saver, run.receipt)
        await _settle(run)

        async with run.sessions() as reader:
            thread = await get_thread(reader, RUN)
            assert thread is not None
            assert thread.status == ThreadStatus.RUNNING.value

        replayed = await _offer(run, key="survives-settlement")

        assert replayed.queued is True
        assert replayed.action_id == accepted.action_id
        assert replayed.queue_position == 1
        # The row says what became of it: promoted, no longer waiting.
        assert replayed.action_status == _ACCEPTED


@pytest.mark.requires_prerequisites("postgres")
@pytest.mark.asyncio
async def test_a_queued_turn_carries_its_runs_own_recursion_budget(
    tmp_path: Path,
) -> None:
    """The envelope is frozen complete at admission, budget included.

    The budget is the operator ceiling lowered to the run's own accepted preset
    budget, decided when the turn is offered rather than when it is promoted,
    so a ceiling that moves in between cannot change the turn, and a preset
    that declares more than the ceiling cannot escape it.
    """
    async with busy_run_state(tmp_path, backend="postgres") as run:
        await _site_the_run(run)
        offered = await _offer(run, key="budget-key", content="second turn")

        async with run.sessions() as reader:
            stored = await reader.get(ControlActionModel, offered.action_id)
            assert stored is not None and stored.payload_json is not None
            accepted = AcceptedActionInput.model_validate_json(stored.payload_json)

    definition = FrozenGraphDefinition.model_validate(
        accepted.dispatch["graph_definition"]
    )
    assert accepted.dispatch["recursion_limit"] == min(
        domain_config.graph_recursion_limit, definition.recursion_limit
    )
    assert accepted.dispatch["action"] == "ingest"
    assert accepted.intent == {
        "content": "second turn",
        "agent_id": "vaultspec-supervisor",
    }

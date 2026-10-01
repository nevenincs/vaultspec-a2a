"""A continuation admitted behind a busy turn waits, and owns nothing.

Driven against a real migrated SQLite file and a real migrated PostgreSQL
database, because both are first-class homes for this journal and the queue's
invariants are the schema's as much as the repository's.

What the reservation must NOT do is as load-bearing as what it does: no graph
receipt, no application, no change to the run's writer. Those three absences
are what let the turn already in flight keep the run's write authority and
settle its own terminal.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select

from ....control.repositories import (
    ContinuationQueueLimits,
    QueuedContinuationDisposition,
    QueuedContinuationRequest,
    count_queued_continuations,
    count_service_queued_continuations,
    next_queue_position,
    read_next_queued_continuation,
    reserve_queued_continuation,
    run_lifetime_deadline,
    served_continuation_queue_limits,
)
from ....database import create_thread, get_thread
from ....database.models import ControlActionModel
from ....database.tests._backends import BACKENDS, migrated_session_factory
from ....domain_config import domain_config
from ....ipc.schemas import DispatchRequest
from ....team.team_config import load_team_config
from ....tests._write_authority import make_test_write_authority
from ....thread.enums import (
    ControlActionResultStatus,
    ControlActionType,
    ThreadStatus,
)
from ....thread.executable_graph import freeze_graph_definition
from ...accepted_input import freeze_accepted_input

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncSession

_RUN = "continuation-queue-run"
_PRESET = "mock-success-single"
_ONE_EACH = ContinuationQueueLimits(per_run_depth=1, service_cap=1)
_ROOMY = ContinuationQueueLimits(per_run_depth=3, service_cap=9)


def _envelope(
    content: str, *, workspace: Path, thread_id: str = _RUN
) -> dict[str, object]:
    """Freeze the accepted dispatch a promoted turn would be rebuilt from.

    Complete on purpose, graph definition and recursion budget included: a
    promoted turn reads this envelope and never reloads a preset, so a
    reservation holding half of one would promote into a run with no program.
    """
    return freeze_accepted_input(
        DispatchRequest(
            action="ingest",
            thread_id=thread_id,
            agent_id="vaultspec-supervisor",
            content=content,
            workspace_root=str(workspace),
            team_preset=_PRESET,
            graph_definition=freeze_graph_definition(
                load_team_config(_PRESET, workspace_root=workspace),
                workspace_root=workspace,
            ),
            recursion_limit=37,
        ),
        intent={"content": content, "agent_id": "vaultspec-supervisor"},
    )


def _request(
    *,
    key: str,
    content: str,
    workspace: Path,
    thread_id: str = _RUN,
    limits: ContinuationQueueLimits = _ONE_EACH,
) -> QueuedContinuationRequest:
    return QueuedContinuationRequest(
        thread_id=thread_id,
        idempotency_key=key,
        payload=_envelope(content, workspace=workspace, thread_id=thread_id),
        dispatch_id=f"dispatch-{key}",
        lifetime_deadline_at=datetime.now(UTC) + timedelta(hours=6),
        limits=limits,
    )


async def _seed_busy_run(session: AsyncSession, thread_id: str = _RUN) -> None:
    await create_thread(
        session,
        write_authority=make_test_write_authority(),
        thread_id=thread_id,
        status=ThreadStatus.RUNNING,
    )
    await session.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("backend_name", BACKENDS)
async def test_a_reserved_continuation_waits_and_owns_nothing(
    backend_name: str, tmp_path: Path
) -> None:
    """It takes a place and a lease, and leaves the run's writer alone."""
    async with migrated_session_factory(backend_name, tmp_path) as (_target, factory):
        async with factory() as session:
            await _seed_busy_run(session)
            before = await get_thread(session, _RUN)
            assert before is not None
            writer_before = before.writer_action_receipt_id
            generation_before = before.writer_generation

        async with factory() as session:
            outcome = await reserve_queued_continuation(
                session,
                _request(key="first", content="second turn", workspace=tmp_path),
            )
            await session.commit()

        assert outcome.disposition is QueuedContinuationDisposition.QUEUED
        assert outcome.position == 1
        assert outcome.claim_token is not None

        async with factory() as session:
            action = await session.get(ControlActionModel, outcome.action_id)
            assert action is not None
            assert action.result_status == ControlActionResultStatus.QUEUED.value
            assert action.action_type == (
                ControlActionType.MESSAGE_FOLLOWUP_REQUESTED.value
            )
            assert action.queue_position == 1
            # The three absences that keep the in-flight turn in charge.
            assert action.graph_receipt_json is None
            assert action.applied_at is None
            assert action.payload_json is not None
            # A waiting reservation is owned, so a second identical admission
            # meets a live lease rather than a free row.
            assert action.claim_token is not None
            assert action.claim_expires_at is not None
            # Its budget is the run's whole remaining lifetime, not one turn's:
            # the predecessor may run longer than a turn's own deadline.
            assert action.recovery_deadline_at is not None

            after = await get_thread(session, _RUN)
            assert after is not None
            assert after.status == ThreadStatus.RUNNING.value
            assert after.writer_action_receipt_id == writer_before
            assert after.writer_generation == generation_before


@pytest.mark.asyncio
@pytest.mark.parametrize("backend_name", BACKENDS)
async def test_a_repeat_key_replays_its_place_and_a_changed_body_conflicts(
    backend_name: str, tmp_path: Path
) -> None:
    """One key is one turn: the same body replays, a different body refuses."""
    async with migrated_session_factory(backend_name, tmp_path) as (_target, factory):
        async with factory() as session:
            await _seed_busy_run(session)

        async with factory() as session:
            first = await reserve_queued_continuation(
                session, _request(key="same", content="second turn", workspace=tmp_path)
            )
            await session.commit()

        async with factory() as session:
            replay = await reserve_queued_continuation(
                session, _request(key="same", content="second turn", workspace=tmp_path)
            )
            await session.commit()

        async with factory() as session:
            changed = await reserve_queued_continuation(
                session,
                _request(
                    key="same", content="a different second turn", workspace=tmp_path
                ),
            )
            await session.rollback()

        assert replay.disposition is QueuedContinuationDisposition.REPLAYED
        assert replay.action_id == first.action_id
        assert replay.position == first.position
        assert changed.disposition is QueuedContinuationDisposition.CONFLICT
        assert changed.action_id == first.action_id

        async with factory() as session:
            assert await count_queued_continuations(session, thread_id=_RUN) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("backend_name", BACKENDS)
async def test_the_per_run_depth_refuses_the_second_waiting_turn(
    backend_name: str, tmp_path: Path
) -> None:
    """A full queue is a typed refusal, and it writes nothing."""
    async with migrated_session_factory(backend_name, tmp_path) as (_target, factory):
        async with factory() as session:
            await _seed_busy_run(session)

        async with factory() as session:
            await reserve_queued_continuation(
                session,
                _request(key="first", content="second turn", workspace=tmp_path),
            )
            await session.commit()

        async with factory() as session:
            refused = await reserve_queued_continuation(
                session,
                _request(key="second", content="third turn", workspace=tmp_path),
            )
            await session.commit()

        assert refused.disposition is QueuedContinuationDisposition.QUEUE_FULL
        assert refused.position is None
        async with factory() as session:
            keys = (
                await session.execute(select(ControlActionModel.idempotency_key))
            ).scalars()
            assert list(keys) == ["first"]


@pytest.mark.asyncio
@pytest.mark.parametrize("backend_name", BACKENDS)
async def test_the_service_cap_refuses_a_second_run_with_room_of_its_own(
    backend_name: str, tmp_path: Path
) -> None:
    """The cap is service-wide, so a run under its own depth still refuses."""
    other = f"{_RUN}-other"
    limits = ContinuationQueueLimits(per_run_depth=3, service_cap=1)
    async with migrated_session_factory(backend_name, tmp_path) as (_target, factory):
        async with factory() as session:
            await _seed_busy_run(session)
            await _seed_busy_run(session, other)

        async with factory() as session:
            await reserve_queued_continuation(
                session,
                _request(
                    key="first",
                    content="second turn",
                    workspace=tmp_path,
                    limits=limits,
                ),
            )
            await session.commit()

        async with factory() as session:
            refused = await reserve_queued_continuation(
                session,
                _request(
                    key="elsewhere",
                    content="second turn",
                    workspace=tmp_path,
                    thread_id=other,
                    limits=limits,
                ),
            )
            await session.commit()

        assert refused.disposition is QueuedContinuationDisposition.QUEUE_FULL
        async with factory() as session:
            assert await count_queued_continuations(session, thread_id=other) == 0
            assert await count_service_queued_continuations(session) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("backend_name", BACKENDS)
async def test_the_next_continuation_to_promote_is_the_lowest_place(
    backend_name: str, tmp_path: Path
) -> None:
    """Order is the place each caller was told, not insertion order read back."""
    async with migrated_session_factory(backend_name, tmp_path) as (_target, factory):
        async with factory() as session:
            await _seed_busy_run(session)

        async with factory() as session:
            assert await next_queue_position(session, thread_id=_RUN) == 1
            first = await reserve_queued_continuation(
                session,
                _request(
                    key="first",
                    content="second turn",
                    workspace=tmp_path,
                    limits=_ROOMY,
                ),
            )
            await session.commit()

        async with factory() as session:
            assert await next_queue_position(session, thread_id=_RUN) == 2
            second = await reserve_queued_continuation(
                session,
                _request(
                    key="second",
                    content="third turn",
                    workspace=tmp_path,
                    limits=_ROOMY,
                ),
            )
            await session.commit()

        assert (first.position, second.position) == (1, 2)
        async with factory() as session:
            waiting = await read_next_queued_continuation(session, thread_id=_RUN)
            assert waiting is not None
            assert waiting.id == first.action_id
            await session.rollback()

        async with factory() as session:
            promoted = await session.get(ControlActionModel, first.action_id)
            assert promoted is not None
            promoted.result_status = (
                ControlActionResultStatus.ACCEPTED_NOT_APPLIED.value
            )
            await session.commit()

        async with factory() as session:
            waiting = await read_next_queued_continuation(session, thread_id=_RUN)
            assert waiting is not None
            assert waiting.id == second.action_id
            await session.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize("backend_name", BACKENDS)
async def test_a_run_whose_lifetime_is_spent_admits_nothing(
    backend_name: str, tmp_path: Path
) -> None:
    """A reservation past the run's own lifetime is refused, not clamped."""
    async with migrated_session_factory(backend_name, tmp_path) as (_target, factory):
        async with factory() as session:
            await _seed_busy_run(session)

        async with factory() as session:
            spent = QueuedContinuationRequest(
                thread_id=_RUN,
                idempotency_key="too-late",
                payload=_envelope("second turn", workspace=tmp_path),
                dispatch_id="dispatch-too-late",
                lifetime_deadline_at=datetime.now(UTC) - timedelta(seconds=1),
                limits=_ONE_EACH,
            )
            with pytest.raises(ValueError, match="lifetime"):
                await reserve_queued_continuation(session, spent)
            await session.rollback()

        async with factory() as session:
            assert await count_service_queued_continuations(session) == 0


def test_the_served_limits_and_lifetime_come_from_configuration() -> None:
    """The served depth is one, and both other bounds are read, not hardcoded."""
    limits = served_continuation_queue_limits()

    assert limits.per_run_depth == 1
    assert limits.per_run_depth == domain_config.run_continuation_queue_depth
    assert limits.service_cap == domain_config.run_continuation_service_queue_cap
    assert limits.service_cap >= limits.per_run_depth

    started = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
    assert run_lifetime_deadline(started) - started == timedelta(
        seconds=domain_config.max_run_lifetime_seconds
    )
    assert run_lifetime_deadline(started) > started

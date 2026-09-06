"""F20: a run stuck in ``reconciling`` past its own derived bound must reach a
defined terminal outcome, not persist indefinitely.

Live incident: a run sat in ``reconciling`` across a gateway AND a worker
restart, permanently heading the default ``GET /v1/runs`` active-run listing
(``state=active``) with no path out - the writer obliged to advance it
(``control.dispatch.redispatch_reconciling_threads``, a background sweep run
once at gateway startup) never ran again for it.

These drive ``discover_active_runs`` and ``build_thread_state`` against a
real aiosqlite database - no mocks - through the actual read seams a client
hits. The only manual state is backdating ``updated_at`` to simulate elapsed
time without a real wait; the thread's ``status`` is never set directly to
manufacture the reconciled outcome under test.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from vaultspec_a2a.tests._write_authority import make_test_write_authority

from ...conftest import materialize_schema
from ...control.run_discovery_service import (
    discover_active_runs,
    reconcile_abandoned_reconciling_thread,
)
from ...control.thread_state_service import build_thread_state
from ...database import (
    ThreadStatusElectionOutcome,
    create_control_action,
    create_thread,
    elect_thread_status,
    get_thread,
    successor_thread_write_authority,
    thread_write_expectation,
)
from ...database.models import ThreadModel
from ...streaming.aggregator import EventAggregator
from ...thread.enums import ThreadStatus


@pytest_asyncio.fixture
async def session_factory(tmp_path_factory: pytest.TempPathFactory):
    case_dir = tmp_path_factory.mktemp("reconciling-abandonment-db")
    materialize_schema(Path(case_dir / "test.db"))
    engine = create_async_engine(f"sqlite+aiosqlite:///{case_dir / 'test.db'}")
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


async def _seed_reconciling_thread(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    thread_id: str,
    team_preset: str | None,
    updated_at: datetime,
) -> None:
    """Create a thread already in ``reconciling``, then backdate its last touch.

    Backdating ``updated_at`` is the only way to exercise elapsed-time logic
    without a real wait; ``status`` itself always goes through the normal
    ``create_thread`` write, never a direct field assignment.
    """
    async with session_factory() as session:
        authority = make_test_write_authority()
        await create_thread(
            session,
            write_authority=authority,
            thread_id=thread_id,
            status=ThreadStatus.RECONCILING,
            team_preset=team_preset,
        )
        await create_control_action(
            session,
            thread_id=thread_id,
            action_type=authority.action_type,
            idempotency_key=f"{thread_id}-ingest",
            dispatch_id=authority.action_receipt_id,
        )
        await session.commit()
    async with session_factory() as session:
        thread = await session.get(ThreadModel, thread_id)
        assert thread is not None
        thread.updated_at = updated_at
        await session.commit()


@pytest.mark.asyncio
async def test_an_abandoned_reconciling_thread_is_moved_to_failed_by_discovery(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """FIX: discovery is now the reconciler a stuck run's next read passes through.

    Before this Step, nothing on the discovery read path checked how long a
    thread had sat in ``reconciling``; the same dead run would head this list
    forever. ``mock-success-single`` declares ``step_timeout_seconds=60``,
    which the floor (300s) still governs, so 400s of silence is unambiguously
    past the derived bound.
    """
    stale = datetime.now(UTC) - timedelta(seconds=400)
    await _seed_reconciling_thread(
        session_factory,
        thread_id="stuck-discovery",
        team_preset="mock-success-single",
        updated_at=stale,
    )

    async with session_factory() as session:
        result = await discover_active_runs(session, limit=10)

    assert result.runs == []

    async with session_factory() as session:
        thread = await get_thread(session, "stuck-discovery")
    assert thread is not None
    assert thread.status == ThreadStatus.FAILED.value
    assert thread.failure_reason is not None
    assert "abandoned" in thread.failure_reason.lower()
    assert "reconciling" in thread.failure_reason.lower()


@pytest.mark.asyncio
async def test_a_freshly_reconciling_thread_is_not_reconciled_away(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Companion negative: reconciliation must not fire before the bound elapses.

    Without this, a reconciler that fired unconditionally on every
    ``reconciling`` thread would also satisfy the test above - this pins the
    condition to actual elapsed time exceeding the derived bound, not mere
    membership in ``reconciling``.
    """
    recent = datetime.now(UTC)
    await _seed_reconciling_thread(
        session_factory,
        thread_id="fresh-reconciling",
        team_preset="mock-success-single",
        updated_at=recent,
    )

    async with session_factory() as session:
        result = await discover_active_runs(session, limit=10)

    assert [run.run_id for run in result.runs] == ["fresh-reconciling"]
    assert result.runs[0].status == ThreadStatus.RECONCILING

    async with session_factory() as session:
        thread = await get_thread(session, "fresh-reconciling")
    assert thread is not None
    assert thread.status == ThreadStatus.RECONCILING.value


@pytest.mark.asyncio
async def test_a_larger_preset_budget_is_not_preempted_by_the_flat_floor(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """T3: a run's own declared budget must widen the bound, never be narrowed
    by a flat floor.

    ``vaultspec-doc-editor`` declares ``step_timeout_seconds=600``, giving a
    derived bound of 630s (600 + margin) - wider than the 300s flat floor
    that governs a preset declaring none. A thread 400s into ``reconciling``
    has exceeded that flat floor but not its own preset's derived bound, so
    it must survive: this is the exact generalization of the F25 defect the
    state-truthfulness ADR's T3 clause exists to prevent - a flat bound
    narrower than a run's own declared budget wrongly killing work that
    budget sanctioned.
    """
    within_own_budget_but_past_the_floor = datetime.now(UTC) - timedelta(seconds=400)
    await _seed_reconciling_thread(
        session_factory,
        thread_id="wide-budget-preset",
        team_preset="vaultspec-doc-editor",
        updated_at=within_own_budget_but_past_the_floor,
    )

    async with session_factory() as session:
        result = await discover_active_runs(session, limit=10)

    assert [run.run_id for run in result.runs] == ["wide-budget-preset"]

    async with session_factory() as session:
        thread = await get_thread(session, "wide-budget-preset")
    assert thread is not None
    assert thread.status == ThreadStatus.RECONCILING.value


@pytest.mark.asyncio
async def test_a_direct_run_status_read_also_reconciles_an_abandoned_thread(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """FIX: the single-run status read is a second reconciler seam, not only the list.

    A client polling one specific stuck run's status (rather than the active
    list) must also see it resolved - before this Step, ``capture_thread_state``
    never checked ``reconciling`` staleness at all.
    """
    stale = datetime.now(UTC) - timedelta(seconds=400)
    await _seed_reconciling_thread(
        session_factory,
        thread_id="stuck-single-read",
        team_preset="mock-success-single",
        updated_at=stale,
    )

    async with session_factory() as session:
        snapshot = await build_thread_state(
            session,
            thread_id="stuck-single-read",
            aggregator=EventAggregator(),
            checkpointer=InMemorySaver(),
        )

    assert snapshot is not None
    assert snapshot.status == ThreadStatus.FAILED.value
    assert snapshot.failure_reason is not None
    assert "abandoned" in snapshot.failure_reason.lower()


@pytest.mark.asyncio
async def test_abandonment_loses_to_a_newer_terminal_writer(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A stale discovery session cannot overwrite a newer terminal outcome."""
    stale = datetime.now(UTC) - timedelta(seconds=400)
    await _seed_reconciling_thread(
        session_factory,
        thread_id="stale-abandonment-reader",
        team_preset="mock-success-single",
        updated_at=stale,
    )

    async with session_factory() as stale_session:
        stale_thread = await get_thread(stale_session, "stale-abandonment-reader")
        assert stale_thread is not None
        await stale_session.commit()

        async with session_factory() as winning_session:
            current = await get_thread(winning_session, "stale-abandonment-reader")
            assert current is not None
            expectation = thread_write_expectation(current)
            election = await elect_thread_status(
                winning_session,
                current.id,
                expectation=expectation,
                status=ThreadStatus.COMPLETED,
                successor=successor_thread_write_authority(
                    expectation,
                    action_type=expectation.authority.action_type,
                    action_receipt_id=expectation.authority.action_receipt_id,
                ),
            )
            assert election.outcome is ThreadStatusElectionOutcome.WON
            await winning_session.commit()

        reconciled = await reconcile_abandoned_reconciling_thread(
            stale_session, "stale-abandonment-reader"
        )
        assert reconciled is False

    async with session_factory() as verification_session:
        final = await get_thread(verification_session, "stale-abandonment-reader")
    assert final is not None
    assert final.status == ThreadStatus.COMPLETED.value
    assert final.failure_reason is None

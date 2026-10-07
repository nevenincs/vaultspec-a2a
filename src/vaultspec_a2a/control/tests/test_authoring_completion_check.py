"""A document-authoring run cannot report clean success while producing nothing.

A ``vaultspec-doc-editor`` run was observed reaching ``status: "completed"``,
``failure_reason: null``, ``repair_status: "healthy"`` while its checkpoint
carried empty ``authoring_proposal_ids`` / ``authoring_changeset_ids`` - the
authoring tool call never landed, and nothing on the completion path checked
for it. ``repair_status: "healthy"`` was never lying: that column classifies
checkpoint-lineage integrity, not whether the run did its job, and the
checkpoint really was readable and consistent.

These drive ``capture_thread_state`` against a real aiosqlite database and a
real LangGraph ``AsyncSqliteSaver`` checkpointer - no mocks - through the
actual read seam a reconnecting client uses, so the wiring under test is the
production path rather than a hand-set snapshot field.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from ...control.thread_state_service import capture_thread_state
from ...streaming import RelayHub
from ...testing import elect_status, seed_accepted_thread
from ...tests._checkpoint_seeding import real_checkpoint
from ...thread.enums import ThreadStatus

if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from ...thread.snapshots import ThreadStateData


async def _snapshot(
    session: AsyncSession,
    *,
    thread_id: str,
    aggregator: RelayHub,
    checkpointer: AsyncSqliteSaver,
) -> ThreadStateData | None:
    """Project the live capture service to the snapshot these tests inspect."""
    capture = await capture_thread_state(
        session,
        thread_id=thread_id,
        aggregator=aggregator,
        checkpointer=checkpointer,
    )
    return capture.snapshot if capture is not None else None


@dataclass(frozen=True, slots=True)
class _ThreadSeed:
    thread_id: str
    team_preset: str
    proposal_ids: list[str]
    changeset_ids: list[str]
    status: ThreadStatus = ThreadStatus.COMPLETED


async def _seed_completed_thread(
    session_factory: async_sessionmaker[AsyncSession],
    checkpointer: AsyncSqliteSaver,
    seed: _ThreadSeed,
) -> None:
    """Seed a thread whose checkpoint carries the given authoring id lists.

    The run is accepted as a real one is - its initial action journaled with the
    frozen definition and its receipt - while it is still active, because a
    receipt is only prepared for an active run; it then moves to the seeded status.
    """
    await checkpointer.setup()
    config: RunnableConfig = {
        "configurable": {"thread_id": seed.thread_id, "checkpoint_ns": ""}
    }
    checkpoint = await real_checkpoint()
    checkpoint["id"] = f"cp-{seed.thread_id}"
    checkpoint["channel_values"]["authoring_proposal_ids"] = seed.proposal_ids
    checkpoint["channel_values"]["authoring_changeset_ids"] = seed.changeset_ids
    await checkpointer.aput(
        config,
        checkpoint,
        {"source": "loop", "step": 1, "parents": {}},
        {},
    )
    async with session_factory() as session:
        await seed_accepted_thread(
            session,
            thread_id=seed.thread_id,
            team_preset=seed.team_preset,
            workspace=Path(__file__).resolve().parent,
        )
        if seed.status is not ThreadStatus.RUNNING:
            await elect_status(session, seed.thread_id, seed.status)
        await session.commit()


@pytest.mark.asyncio
async def test_a_completed_doc_editor_run_with_no_artifact_is_flagged(
    session_factory: async_sessionmaker[AsyncSession],
    checkpointer: AsyncSqliteSaver,
) -> None:
    """The reported gap: completed, healthy, and produced nothing - now caught.

    This is a FIX, not a preservation: before ``apply_authoring_completion_check``
    was wired into ``capture_thread_state``, nothing on the completion path read
    ``authoring_proposal_ids`` / ``authoring_changeset_ids`` at all, so this
    snapshot reported ``degraded_reasons: []`` for a run that produced nothing.
    """
    await _seed_completed_thread(
        session_factory,
        checkpointer,
        _ThreadSeed(
            thread_id="doc-editor-empty",
            team_preset="vaultspec-doc-editor",
            proposal_ids=[],
            changeset_ids=[],
        ),
    )

    async with session_factory() as session:
        snapshot = await _snapshot(
            session,
            thread_id="doc-editor-empty",
            aggregator=RelayHub(),
            checkpointer=checkpointer,
        )

    assert snapshot is not None
    assert snapshot.status == ThreadStatus.COMPLETED.value
    assert snapshot.failure_reason is None
    assert snapshot.repair_status == "healthy"
    assert "authoring_run_produced_no_proposal" in snapshot.degraded_reasons
    assert snapshot.snapshot_complete is False


@pytest.mark.asyncio
async def test_a_completed_doc_editor_run_that_did_propose_is_not_flagged(
    session_factory: async_sessionmaker[AsyncSession],
    checkpointer: AsyncSqliteSaver,
) -> None:
    """Companion negative: a real proposal id must clear the new gate.

    Without this, a hardcoded degraded reason on every completed doc-editor
    run would also pass the test above - this pins the condition to actual
    emptiness of the checkpointed id lists.
    """
    await _seed_completed_thread(
        session_factory,
        checkpointer,
        _ThreadSeed(
            thread_id="doc-editor-proposed",
            team_preset="vaultspec-doc-editor",
            proposal_ids=["prop-1"],
            changeset_ids=[],
        ),
    )

    async with session_factory() as session:
        snapshot = await _snapshot(
            session,
            thread_id="doc-editor-proposed",
            aggregator=RelayHub(),
            checkpointer=checkpointer,
        )

    assert snapshot is not None
    assert snapshot.status == ThreadStatus.COMPLETED.value
    assert "authoring_run_produced_no_proposal" not in snapshot.degraded_reasons


@pytest.mark.asyncio
async def test_a_completed_coder_run_with_no_authoring_ids_is_not_flagged(
    session_factory: async_sessionmaker[AsyncSession],
    checkpointer: AsyncSqliteSaver,
) -> None:
    """A coding preset never produces a document proposal; it must not be flagged.

    ``vaultspec-solo-coder`` also arms ``[team.harness] authoring_bridge`` (the
    engine bridge is armed on coder presets too, for a different purpose), so
    this pins the predicate to the worker's persona ROLE rather than the
    harness flag - a topology- or harness-only predicate would misclassify
    this preset as well.
    """
    await _seed_completed_thread(
        session_factory,
        checkpointer,
        _ThreadSeed(
            thread_id="coder-empty",
            team_preset="vaultspec-solo-coder",
            proposal_ids=[],
            changeset_ids=[],
        ),
    )

    async with session_factory() as session:
        snapshot = await _snapshot(
            session,
            thread_id="coder-empty",
            aggregator=RelayHub(),
            checkpointer=checkpointer,
        )

    assert snapshot is not None
    assert "authoring_run_produced_no_proposal" not in snapshot.degraded_reasons


@pytest.mark.asyncio
async def test_a_still_running_doc_editor_thread_is_not_flagged(
    session_factory: async_sessionmaker[AsyncSession],
    checkpointer: AsyncSqliteSaver,
) -> None:
    """A run still in flight has not failed to produce anything - it just hasn't yet."""
    await _seed_completed_thread(
        session_factory,
        checkpointer,
        _ThreadSeed(
            thread_id="doc-editor-running",
            team_preset="vaultspec-doc-editor",
            proposal_ids=[],
            changeset_ids=[],
            status=ThreadStatus.RUNNING,
        ),
    )

    async with session_factory() as session:
        snapshot = await _snapshot(
            session,
            thread_id="doc-editor-running",
            aggregator=RelayHub(),
            checkpointer=checkpointer,
        )

    assert snapshot is not None
    assert "authoring_run_produced_no_proposal" not in snapshot.degraded_reasons

"""A document-authoring run cannot report clean success while producing nothing.

A ``vaultspec-doc-editor`` run was observed reaching ``status: "completed"``,
``failure_reason: null``, ``repair_status: "healthy"`` while its checkpoint
carried empty ``authoring_proposal_ids`` / ``authoring_changeset_ids`` - the
authoring tool call never landed, and nothing on the completion path checked
for it. ``repair_status: "healthy"`` was never lying: that column classifies
checkpoint-lineage integrity, not whether the run did its job, and the
checkpoint really was readable and consistent.

These drive ``build_thread_state`` against a real aiosqlite database and a
real LangGraph ``AsyncSqliteSaver`` checkpointer - no mocks - through the
actual read seam a reconnecting client uses, so the wiring under test is the
production path rather than a hand-set snapshot field.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from langgraph.checkpoint.base import empty_checkpoint
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ...conftest import materialize_schema
from ...control.thread_state_service import build_thread_state
from ...database import create_thread
from ...streaming.aggregator import EventAggregator
from ...thread.enums import ThreadStatus


@pytest.fixture
def _case_dirs(tmp_path: Path) -> tuple[Path, Path]:
    case_dir = tmp_path / "authoring-completion-check"
    case_dir.mkdir(parents=True, exist_ok=True)
    return case_dir / "test.db", case_dir / "checkpoints.db"


async def _seed_completed_thread(
    session_factory: async_sessionmaker[AsyncSession],
    checkpointer: AsyncSqliteSaver,
    *,
    thread_id: str,
    team_preset: str,
    proposal_ids: list[str],
    changeset_ids: list[str],
    status: ThreadStatus = ThreadStatus.COMPLETED,
) -> None:
    """Seed a thread whose checkpoint carries the given authoring id lists."""
    await checkpointer.setup()
    checkpoint = empty_checkpoint()
    checkpoint["id"] = f"cp-{thread_id}"
    checkpoint["channel_values"]["authoring_proposal_ids"] = proposal_ids
    checkpoint["channel_values"]["authoring_changeset_ids"] = changeset_ids
    await checkpointer.aput(
        {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}},
        checkpoint,
        {"source": "loop", "step": 1, "parents": {}},
        {},
    )
    async with session_factory() as session:
        await create_thread(
            session,
            thread_id=thread_id,
            team_preset=team_preset,
            status=status,
            repair_status="healthy",
            execution_readiness="healthy",
        )
        await session.commit()


@pytest.mark.asyncio
async def test_a_completed_doc_editor_run_with_no_artifact_is_flagged(
    _case_dirs: tuple[Path, Path],
) -> None:
    """The reported gap: completed, healthy, and produced nothing - now caught.

    This is a FIX, not a preservation: before ``apply_authoring_completion_check``
    was wired into ``capture_thread_state``, nothing on the completion path read
    ``authoring_proposal_ids`` / ``authoring_changeset_ids`` at all, so this
    snapshot reported ``degraded_reasons: []`` for a run that produced nothing.
    """
    db_file, checkpoints_file = _case_dirs
    materialize_schema(Path(db_file))
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with AsyncSqliteSaver.from_conn_string(str(checkpoints_file)) as checkpointer:
        await _seed_completed_thread(
            session_factory,
            checkpointer,
            thread_id="doc-editor-empty",
            team_preset="vaultspec-doc-editor",
            proposal_ids=[],
            changeset_ids=[],
        )

        async with session_factory() as session:
            snapshot = await build_thread_state(
                session,
                thread_id="doc-editor-empty",
                aggregator=EventAggregator(),
                checkpointer=checkpointer,
            )

    assert snapshot is not None
    assert snapshot.status == ThreadStatus.COMPLETED.value
    assert snapshot.failure_reason is None
    assert snapshot.repair_status == "healthy"
    assert "authoring_run_produced_no_proposal" in snapshot.degraded_reasons
    assert snapshot.snapshot_complete is False

    await engine.dispose()


@pytest.mark.asyncio
async def test_a_completed_doc_editor_run_that_did_propose_is_not_flagged(
    _case_dirs: tuple[Path, Path],
) -> None:
    """Companion negative: a real proposal id must clear the new gate.

    Without this, a hardcoded degraded reason on every completed doc-editor
    run would also pass the test above - this pins the condition to actual
    emptiness of the checkpointed id lists.
    """
    db_file, checkpoints_file = _case_dirs
    materialize_schema(Path(db_file))
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with AsyncSqliteSaver.from_conn_string(str(checkpoints_file)) as checkpointer:
        await _seed_completed_thread(
            session_factory,
            checkpointer,
            thread_id="doc-editor-proposed",
            team_preset="vaultspec-doc-editor",
            proposal_ids=["prop-1"],
            changeset_ids=[],
        )

        async with session_factory() as session:
            snapshot = await build_thread_state(
                session,
                thread_id="doc-editor-proposed",
                aggregator=EventAggregator(),
                checkpointer=checkpointer,
            )

    assert snapshot is not None
    assert snapshot.status == ThreadStatus.COMPLETED.value
    assert "authoring_run_produced_no_proposal" not in snapshot.degraded_reasons


@pytest.mark.asyncio
async def test_a_completed_coder_run_with_no_authoring_ids_is_not_flagged(
    _case_dirs: tuple[Path, Path],
) -> None:
    """A coding preset never produces a document proposal; it must not be flagged.

    ``vaultspec-solo-coder`` also arms ``[team.harness] authoring_bridge`` (the
    engine bridge is armed on coder presets too, for a different purpose), so
    this pins the predicate to the worker's persona ROLE rather than the
    harness flag - a topology- or harness-only predicate would misclassify
    this preset as well.
    """
    db_file, checkpoints_file = _case_dirs
    materialize_schema(Path(db_file))
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with AsyncSqliteSaver.from_conn_string(str(checkpoints_file)) as checkpointer:
        await _seed_completed_thread(
            session_factory,
            checkpointer,
            thread_id="coder-empty",
            team_preset="vaultspec-solo-coder",
            proposal_ids=[],
            changeset_ids=[],
        )

        async with session_factory() as session:
            snapshot = await build_thread_state(
                session,
                thread_id="coder-empty",
                aggregator=EventAggregator(),
                checkpointer=checkpointer,
            )

    assert snapshot is not None
    assert "authoring_run_produced_no_proposal" not in snapshot.degraded_reasons

    await engine.dispose()


@pytest.mark.asyncio
async def test_a_still_running_doc_editor_thread_is_not_flagged(
    _case_dirs: tuple[Path, Path],
) -> None:
    """A run still in flight has not failed to produce anything - it just hasn't yet."""
    db_file, checkpoints_file = _case_dirs
    materialize_schema(Path(db_file))
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with AsyncSqliteSaver.from_conn_string(str(checkpoints_file)) as checkpointer:
        await _seed_completed_thread(
            session_factory,
            checkpointer,
            thread_id="doc-editor-running",
            team_preset="vaultspec-doc-editor",
            proposal_ids=[],
            changeset_ids=[],
            status=ThreadStatus.RUNNING,
        )

        async with session_factory() as session:
            snapshot = await build_thread_state(
                session,
                thread_id="doc-editor-running",
                aggregator=EventAggregator(),
                checkpointer=checkpointer,
            )

    assert snapshot is not None
    assert "authoring_run_produced_no_proposal" not in snapshot.degraded_reasons

    await engine.dispose()

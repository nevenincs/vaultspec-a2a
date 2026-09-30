"""Tests for graph.nodes.vault_reader -- the mount node and the context mounter."""

from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ....database import create_thread, seed_task_queue
from ....database.models import Base
from ....domain_config import domain_config
from ....tests._write_authority import make_test_write_authority
from ....thread.state import TeamState, merge_vault_index
from ....worker.task_queue_port import SqlTaskQueuePort
from ...nodes.vault_reader import (
    build_initial_vault_index,
    create_context_mounter,
    create_mount_node,
)
from ...protocols import TaskQueuePort


async def _mount_pass(
    workspace_root: Path | None,
    state: TeamState,
    task_queue_port: TaskQueuePort | None = None,
) -> tuple[dict[str, Any], str | None]:
    """Run one mount pass the way the compiled graph does.

    The mount node's index update is folded into state through the production
    reducer before the worker-side mounter expands the documents it names.
    """
    update = await create_mount_node(workspace_root)(state)
    merged: TeamState = {
        **state,
        "vault_index": merge_vault_index(
            state.get("vault_index") or {}, update.get("vault_index", {})
        ),
    }
    mounter = create_context_mounter(workspace_root, task_queue_port)
    return update, await mounter(merged)


def _make_state(
    active_feature: str | None = "my-feature",
    vault_index: dict[str, list[str]] | None = None,
    pipeline_phase: str | None = None,
    thread_id: str = "t1",
    current_task_id: str | None = None,
) -> TeamState:
    base: TeamState = {
        "messages": [],
        "thread_id": thread_id,
        "active_agent": "worker",
        "artifacts": [],
        "current_plan": [],
        "token_usage": {},
    }
    if active_feature is not None:
        base["active_feature"] = active_feature
    if vault_index is not None:
        base["vault_index"] = vault_index
    if pipeline_phase is not None:
        base["pipeline_phase"] = pipeline_phase
    if current_task_id is not None:
        base["current_task_id"] = current_task_id
    return base


@pytest.mark.asyncio
async def test_mount_is_empty_when_workspace_root_is_none() -> None:
    update, mounted = await _mount_pass(None, _make_state())
    assert update == {}
    assert mounted is None


@pytest.mark.asyncio
async def test_mount_is_empty_when_no_active_feature() -> None:
    update, mounted = await _mount_pass(
        Path("/tmp/ws"), _make_state(active_feature=None)
    )
    assert update == {}
    assert mounted is None


@pytest.mark.asyncio
async def test_mount_node_never_writes_document_text_to_state(tmp_path: Path) -> None:
    """The node's update is the index handle list only; text stays out of state."""
    adr_dir = tmp_path / ".vault" / "adr"
    adr_dir.mkdir(parents=True)
    (adr_dir / "my-feature-adr.md").write_text(
        "# ADR\n\nSecret text.", encoding="utf-8"
    )

    update = await create_mount_node(tmp_path)(_make_state())

    assert set(update) == {"vault_index"}
    assert "Secret text." not in repr(update)


@pytest.mark.asyncio
async def test_mount_node_returns_content_for_adr_files(tmp_path: Path) -> None:
    adr_dir = tmp_path / ".vault" / "adr"
    adr_dir.mkdir(parents=True)
    adr_file = adr_dir / "my-feature-adr.md"
    adr_file.write_text("# ADR\n\nDecision text.", encoding="utf-8")

    state = _make_state(
        vault_index={"adr": [".vault/adr/my-feature-adr.md"]},
    )
    _update, mounted = await _mount_pass(tmp_path, state)
    assert mounted is not None
    assert "Decision text." in mounted


@pytest.mark.asyncio
async def test_mount_refreshes_vault_index_for_documents_written_mid_run(
    tmp_path: Path,
) -> None:
    """A document produced after compile time is discovered on the next pass.

    The index is seeded empty; the mount node re-scans .vault/ each pass, so a
    research document written during the run must appear in both the mounted
    context and the returned vault_index update.
    """
    research_dir = tmp_path / ".vault" / "research"
    research_dir.mkdir(parents=True)
    (research_dir / "my-feature-research.md").write_text(
        "# Research\n\nProduced mid-run.", encoding="utf-8"
    )

    state = _make_state(pipeline_phase="research", vault_index={})
    update, mounted = await _mount_pass(tmp_path, state)

    expected_rel = str(Path(".vault/research/my-feature-research.md"))
    assert update["vault_index"] == {"research": [expected_rel]}
    assert mounted is not None
    assert "Produced mid-run." in mounted


@pytest.mark.asyncio
async def test_mount_refresh_preserves_prior_index_entries(tmp_path: Path) -> None:
    """The refresh is add-only: pre-existing state entries are not dropped."""
    adr_dir = tmp_path / ".vault" / "adr"
    adr_dir.mkdir(parents=True)
    (adr_dir / "my-feature-adr.md").write_text("# ADR\n\nBinding.", encoding="utf-8")

    # A plan path lives only in state (no matching file on disk to re-glob).
    state = _make_state(
        pipeline_phase="adr",
        vault_index={"plan": [".vault/plan/my-feature-plan.md"]},
    )
    update, mounted = await _mount_pass(tmp_path, state)

    # The returned update carries only the freshly discovered ADR; the reducer
    # merges it with the surviving plan entry already in state.
    expected_rel = str(Path(".vault/adr/my-feature-adr.md"))
    assert update["vault_index"] == {"adr": [expected_rel]}
    assert mounted is not None
    assert "Binding." in mounted


# ---------------------------------------------------------------------------
# Database-backed queue injection — real SQLite via SqlTaskQueuePort
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def engine() -> AsyncGenerator[AsyncEngine]:
    """Fresh in-memory async engine with all tables created."""
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session_factory(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    """Async session factory bound to the in-memory engine."""
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def queue_thread(session_factory: async_sessionmaker[AsyncSession]) -> str:
    """Create a thread with a seeded exec queue; return the thread id."""
    async with session_factory() as session:
        thread = await create_thread(
            session, write_authority=make_test_write_authority(), title="queue"
        )
        await seed_task_queue(
            session,
            thread_id=thread.id,
            feature_tag="my-feature",
            entries=[
                {"task_key": "Q-1", "description": "Do first", "status": "in_progress"},
                {"task_key": "Q-2", "description": "Do next", "status": "pending"},
                {"task_key": "Q-3", "description": "Then this", "status": "pending"},
                {"task_key": "Q-4", "description": "Later", "status": "pending"},
            ],
        )
        await session.commit()
        return thread.id


@pytest.mark.asyncio
async def test_mount_injects_db_queue_view_during_exec(
    tmp_path: Path,
    session_factory: async_sessionmaker[AsyncSession],
    queue_thread: str,
) -> None:
    port = SqlTaskQueuePort(session_factory)
    state = _make_state(
        pipeline_phase="exec",
        thread_id=queue_thread,
        current_task_id="Q-1",
    )
    _update, context = await _mount_pass(tmp_path, state, port)
    assert context is not None
    assert "## Task Queue -- my-feature" in context
    assert "| Q-1 | in_progress | Do first |" in context
    assert "| Q-2 | pending | Do next |" in context
    assert "| Q-3 | pending | Then this |" in context
    # horizon is 2 pending rows -> Q-4 must not appear
    assert "Q-4" not in context


@pytest.mark.asyncio
async def test_mount_skips_queue_outside_queue_phases(
    tmp_path: Path,
    session_factory: async_sessionmaker[AsyncSession],
    queue_thread: str,
) -> None:
    port = SqlTaskQueuePort(session_factory)
    state = _make_state(
        pipeline_phase="research",
        thread_id=queue_thread,
        current_task_id="Q-1",
    )
    _update, mounted = await _mount_pass(tmp_path, state, port)
    assert mounted is None


@pytest.mark.asyncio
async def test_mount_no_queue_block_when_empty(
    tmp_path: Path,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        thread = await create_thread(
            session, write_authority=make_test_write_authority(), title="empty-queue"
        )
        await session.commit()
        thread_id = thread.id

    port = SqlTaskQueuePort(session_factory)
    state = _make_state(
        pipeline_phase="exec",
        thread_id=thread_id,
        current_task_id=None,
    )
    _update, mounted = await _mount_pass(tmp_path, state, port)
    assert mounted is None


def test_the_index_keeps_the_most_recent_records_when_a_stage_exceeds_its_cap(
    tmp_path: Path,
) -> None:
    """A capped stage must surrender its OLDEST records, never its newest.

    The cap binds on real features - this repository's own vault holds 130 and 97
    execution records for two of them - so which end is discarded decides what a
    resuming run can see. Truncating from the front is silent and inverts the
    answer: the run grounds on the first steps ever written and learns nothing
    about the work it is resuming.

    Written against the real glob and the real configured cap rather than a
    stubbed one, so it fails if either the discard order or the pattern regresses.
    """
    cap = domain_config.vault_index_cap
    feature = "capped-feature"
    exec_dir = tmp_path / ".vault" / "exec" / f"2026-01-01-{feature}"
    exec_dir.mkdir(parents=True)
    # Zero-padded so ascending filename order is ascending step order, which is
    # the convention the vault's own naming rules mandate.
    total = cap + 5
    for step in range(1, total + 1):
        (exec_dir / f"2026-01-01-{feature}-P01-S{step:03d}.md").write_text(
            "x", encoding="utf-8"
        )

    index = build_initial_vault_index(tmp_path, feature)
    kept = index["exec"]

    assert len(kept) == cap, f"expected the stage capped at {cap}, got {len(kept)}"
    assert kept[-1].endswith(f"S{total:03d}.md"), (
        "the newest execution record was discarded: the index ends at "
        f"{kept[-1]!r}. Truncating from the head keeps a feature's oldest "
        "records, which is the opposite of what a resuming run needs."
    )
    assert not any(entry.endswith("S001.md") for entry in kept), (
        "the oldest record survived a full cap, so nothing was discarded from "
        "the correct end"
    )

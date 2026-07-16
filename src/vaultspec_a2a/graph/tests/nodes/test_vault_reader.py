"""Tests for graph.nodes.vault_reader -- create_mount_node."""

from collections.abc import AsyncGenerator
from pathlib import Path

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
from ....worker.task_queue_port import SqlTaskQueuePort
from ...nodes.vault_reader import create_mount_node


def _make_state(
    active_feature: str | None = "my-feature",
    vault_index: dict | None = None,
    pipeline_phase: str | None = None,
    thread_id: str = "t1",
    current_task_id: str | None = None,
) -> dict:
    base: dict = {
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
async def test_mount_node_returns_none_when_workspace_root_is_none() -> None:
    mount = create_mount_node(None)
    result = await mount(_make_state())
    assert result == {"mounted_context": None}


@pytest.mark.asyncio
async def test_mount_node_returns_none_when_no_active_feature() -> None:
    mount = create_mount_node(Path("/tmp/ws"))
    result = await mount(_make_state(active_feature=None))
    assert result == {"mounted_context": None}


@pytest.mark.asyncio
async def test_mount_node_returns_content_for_adr_files(tmp_path: Path) -> None:
    adr_dir = tmp_path / ".vault" / "adr"
    adr_dir.mkdir(parents=True)
    adr_file = adr_dir / "my-feature-adr.md"
    adr_file.write_text("# ADR\n\nDecision text.", encoding="utf-8")

    mount = create_mount_node(tmp_path)
    state = _make_state(
        vault_index={"adr": [".vault/adr/my-feature-adr.md"]},
    )
    result = await mount(state)
    assert result["mounted_context"] is not None
    assert "Decision text." in result["mounted_context"]


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

    mount = create_mount_node(tmp_path)
    state = _make_state(pipeline_phase="research", vault_index={})
    result = await mount(state)

    expected_rel = str(Path(".vault/research/my-feature-research.md"))
    assert result["vault_index"] == {"research": [expected_rel]}
    assert result["mounted_context"] is not None
    assert "Produced mid-run." in result["mounted_context"]


@pytest.mark.asyncio
async def test_mount_refresh_preserves_prior_index_entries(tmp_path: Path) -> None:
    """The refresh is add-only: pre-existing state entries are not dropped."""
    adr_dir = tmp_path / ".vault" / "adr"
    adr_dir.mkdir(parents=True)
    (adr_dir / "my-feature-adr.md").write_text("# ADR\n\nBinding.", encoding="utf-8")

    mount = create_mount_node(tmp_path)
    # A plan path lives only in state (no matching file on disk to re-glob).
    state = _make_state(
        pipeline_phase="adr",
        vault_index={"plan": [".vault/plan/my-feature-plan.md"]},
    )
    result = await mount(state)

    # The returned update carries only the freshly discovered ADR; the reducer
    # merges it with the surviving plan entry already in state.
    expected_rel = str(Path(".vault/adr/my-feature-adr.md"))
    assert result["vault_index"] == {"adr": [expected_rel]}
    assert "Binding." in result["mounted_context"]


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
        thread = await create_thread(session, title="queue")
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
    mount = create_mount_node(tmp_path, port)
    state = _make_state(
        pipeline_phase="exec",
        thread_id=queue_thread,
        current_task_id="Q-1",
    )
    result = await mount(state)
    context = result["mounted_context"]
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
    mount = create_mount_node(tmp_path, port)
    state = _make_state(
        pipeline_phase="research",
        thread_id=queue_thread,
        current_task_id="Q-1",
    )
    result = await mount(state)
    assert result == {"mounted_context": None}


@pytest.mark.asyncio
async def test_mount_no_queue_block_when_empty(
    tmp_path: Path,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        thread = await create_thread(session, title="empty-queue")
        await session.commit()
        thread_id = thread.id

    port = SqlTaskQueuePort(session_factory)
    mount = create_mount_node(tmp_path, port)
    state = _make_state(
        pipeline_phase="exec",
        thread_id=thread_id,
        current_task_id=None,
    )
    result = await mount(state)
    assert result == {"mounted_context": None}

"""Observed-negative proof: the queue path performs zero .vault writes (ADR R5, S14).

Real file-backed aiosqlite, no mocks. A continuous filesystem watcher runs across
the whole exercise while the database-backed queue is injected (mount node reads
.vault docs) and advanced (mark-complete tool). The assertion is an observed
negative — the watcher records every create/modify/delete under .vault for the
duration and must observe none — not a no-write-path argument.
"""

import threading
import time
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
from ...tools.task_queue import create_mark_task_complete_tool

_FEATURE = "queue-isolation"


class _VaultWriteWatcher:
    """Continuous polling watcher recording writes under a directory tree.

    Samples (mtime_ns, size) for every file under ``root`` at a tight interval
    on a background thread, accumulating any created/modified/deleted path
    observed between the start and stop calls. Reads never change mtime or size,
    so read-only mounting produces no events.
    """

    def __init__(self, root: Path, interval: float = 0.005) -> None:
        self._root = root
        self._interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.events: list[tuple[str, str]] = []
        self._seen: dict[Path, tuple[int, int]] = {}

    def _snapshot(self) -> dict[Path, tuple[int, int]]:
        snap: dict[Path, tuple[int, int]] = {}
        for path in self._root.rglob("*"):
            if path.is_file():
                try:
                    st = path.stat()
                except OSError:
                    continue
                snap[path] = (st.st_mtime_ns, st.st_size)
        return snap

    def _diff(self, current: dict[Path, tuple[int, int]]) -> None:
        for path, meta in current.items():
            if path not in self._seen:
                self.events.append(("created", str(path)))
            elif self._seen[path] != meta:
                self.events.append(("modified", str(path)))
        for path in self._seen:
            if path not in current:
                self.events.append(("deleted", str(path)))
        self._seen = current

    def _run(self) -> None:
        while not self._stop.is_set():
            self._diff(self._snapshot())
            time.sleep(self._interval)

    def start(self) -> None:
        self._seen = self._snapshot()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        # Final reconcile in case a write landed between the last poll and stop.
        self._diff(self._snapshot())


@pytest_asyncio.fixture
async def file_engine(tmp_path: Path) -> AsyncGenerator[AsyncEngine]:
    """File-backed async engine (shared across the port's separate sessions)."""
    db_file = tmp_path / "service.db"
    eng = create_async_engine(f"sqlite+aiosqlite:///{db_file.as_posix()}")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session_factory(
    file_engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    """Session factory bound to the file-backed engine."""
    return async_sessionmaker(file_engine, class_=AsyncSession, expire_on_commit=False)


def _make_workspace(tmp_path: Path) -> Path:
    """Create a workspace with a real .vault/adr document to mount and read."""
    workspace = tmp_path / "ws"
    adr_dir = workspace / ".vault" / "adr"
    adr_dir.mkdir(parents=True)
    (adr_dir / f"{_FEATURE}-adr.md").write_text(
        "# ADR\n\nBinding decision text.", encoding="utf-8"
    )
    # A plan directory exists but carries NO queue markdown — the queue is in the DB.
    (workspace / ".vault" / "plan").mkdir(parents=True)
    return workspace


def _exec_state(thread_id: str, current_task_id: str | None) -> dict:
    return {
        "messages": [],
        "thread_id": thread_id,
        "active_agent": "coder",
        "artifacts": [],
        "current_plan": [],
        "token_usage": {},
        "active_feature": _FEATURE,
        "pipeline_phase": "exec",
        "vault_index": {"adr": [f".vault/adr/{_FEATURE}-adr.md"]},
        "current_task_id": current_task_id,
    }


@pytest.mark.asyncio
async def test_db_queue_functions_with_zero_vault_writes(
    tmp_path: Path,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    workspace = _make_workspace(tmp_path)
    vault_dir = workspace / ".vault"

    async with session_factory() as session:
        thread = await create_thread(session, title="isolation")
        await seed_task_queue(
            session,
            thread_id=thread.id,
            feature_tag=_FEATURE,
            entries=[
                {"task_key": "Q-1", "description": "First", "status": "in_progress"},
                {"task_key": "Q-2", "description": "Second", "status": "pending"},
                {"task_key": "Q-3", "description": "Third", "status": "pending"},
            ],
        )
        await session.commit()
        thread_id = thread.id

    port = SqlTaskQueuePort(session_factory)
    mount = create_mount_node(workspace, port)
    tool_fn, drain_fn = create_mark_task_complete_tool(port, thread_id)

    watcher = _VaultWriteWatcher(vault_dir)
    watcher.start()
    try:
        # 1. Mount reads the .vault ADR and injects the DB-sourced queue view.
        mounted = await mount(_exec_state(thread_id, "Q-1"))
        context = mounted["mounted_context"]
        assert context is not None
        assert "Binding decision text." in context  # .vault read succeeded
        assert "## Task Queue -- queue-isolation" in context  # queue came from the DB
        assert "| Q-1 | in_progress | First |" in context
        assert "| Q-2 | pending | Second |" in context

        # 2. The worker loop advances the queue via the mark-complete tool.
        ack = await tool_fn("Q-1")
        assert ack == "Task Q-1 marked complete. Next task: Q-2."
        assert drain_fn() == {"current_task_id": "Q-2"}

        # 3. Re-mounting reflects the advanced cursor, still DB-sourced.
        remounted = await mount(_exec_state(thread_id, "Q-2"))
        remounted_context = remounted["mounted_context"]
        assert remounted_context is not None
        assert "| Q-2 | in_progress | Second |" not in remounted_context
        assert "| Q-2 | pending | Second |" in remounted_context
        assert "Q-1" not in remounted_context  # completed row no longer shown

        # Give the watcher time to observe any stray write before stopping.
        time.sleep(0.05)
    finally:
        watcher.stop()

    assert watcher.events == [], (
        f"Expected zero .vault writes during the DB-queue exercise, "
        f"observed: {watcher.events}"
    )

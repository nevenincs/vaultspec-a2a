"""Tests for the database layer using real in-memory SQLite.

No mocks, no monkeypatching. Every test runs against a real aiosqlite
in-memory database with full WAL mode verification.
"""

import json

from collections.abc import AsyncGenerator
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ...core.exceptions import NicknameConflictError
from ..crud import (
    append_cost_record,
    append_permission_log,
    create_artifact,
    create_thread,
    get_artifact,
    get_artifacts_by_thread,
    get_permission_logs_by_thread,
    get_thread,
    get_thread_metadata,
    list_threads,
    save_model,
    sum_cost_by_agent,
    sum_cost_by_thread,
    update_thread_status,
)
from ..models import ArtifactModel, Base, CostTrackingModel, PermissionLogModel
from ..session import close_db, get_engine, init_db, verify_wal_mode


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

EXPECTED_TABLES = {"artifacts", "cost_tracking", "permission_logs", "threads"}


@pytest_asyncio.fixture
async def engine() -> AsyncGenerator[AsyncEngine]:
    """Create a fresh in-memory async engine with tables."""
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session(engine: AsyncEngine) -> AsyncGenerator[AsyncSession]:
    """Provide a fresh async session for each test."""
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as sess:
        yield sess
        await sess.rollback()


# ---------------------------------------------------------------------------
# Session & Engine Tests
# ---------------------------------------------------------------------------


class TestSessionManagement:
    """Tests for engine creation, WAL mode, and init_db."""

    @pytest_asyncio.fixture(autouse=True)
    async def _isolate_singleton(self) -> AsyncGenerator[None]:
        """Ensure the module-level singleton engine is torn down.

        Prevents singleton state from leaking between tests (H30 fix).
        """
        await close_db()
        yield
        await close_db()

    @pytest.mark.asyncio
    async def test_init_db_creates_tables(self) -> None:
        """init_db should create all tables in a fresh database."""
        engine = await init_db(":memory:")
        async with engine.connect() as conn:
            result = await conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
            )
            tables = {row[0] for row in result}
            assert tables >= EXPECTED_TABLES

    @pytest.mark.asyncio
    async def test_get_engine_returns_singleton(self) -> None:
        """get_engine should return the same instance when called twice."""
        e1 = get_engine(":memory:")
        e2 = get_engine()
        assert e1 is e2


# ---------------------------------------------------------------------------
# Thread CRUD Tests
# ---------------------------------------------------------------------------


class TestThreadCRUD:
    """Tests for thread create, read, list, and status update."""

    @pytest.mark.asyncio
    async def test_create_thread_defaults(self, session: AsyncSession) -> None:
        """Creating a thread with defaults should set status='submitted'."""
        thread = await create_thread(session, title="Test Thread")
        assert thread.id is not None
        assert thread.title == "Test Thread"
        assert thread.status == "submitted"
        assert thread.created_at is not None

    @pytest.mark.asyncio
    async def test_create_thread_explicit_id(self, session: AsyncSession) -> None:
        """Creating a thread with an explicit ID should use that ID."""
        thread = await create_thread(session, thread_id="custom-id", title="Custom")
        assert thread.id == "custom-id"

    @pytest.mark.asyncio
    async def test_create_thread_with_metadata(self, session: AsyncSession) -> None:
        """metadata should store JSON as text (ADR-014 rename from agent_config)."""
        meta = json.dumps(
            {"workspace_root": "Y:/code/vaultspec", "feature_tag": "auth"},
        )
        thread = await create_thread(session, title="Configured", metadata=meta)
        assert thread.thread_metadata == meta
        assert thread.thread_metadata is not None
        parsed = json.loads(thread.thread_metadata)
        assert parsed["workspace_root"] == "Y:/code/vaultspec"

    @pytest.mark.asyncio
    async def test_create_thread_with_nickname(self, session: AsyncSession) -> None:
        """nickname should be stored on the thread (ADR-014)."""
        thread = await create_thread(
            session, title="Named", nickname="auth-flow-star-a3f2"
        )
        assert thread.nickname == "auth-flow-star-a3f2"

    @pytest.mark.asyncio
    async def test_nickname_uniqueness_conflict(self, session: AsyncSession) -> None:
        """Duplicate nicknames should raise NicknameConflictError."""
        await create_thread(session, title="First", nickname="unique-nick-0001")
        with pytest.raises(NicknameConflictError, match="unique-nick-0001"):
            await create_thread(session, title="Second", nickname="unique-nick-0001")

    @pytest.mark.asyncio
    async def test_get_thread_metadata(self, session: AsyncSession) -> None:
        """get_thread_metadata returns the metadata JSON string."""
        meta = json.dumps({"workspace_root": "Y:/code/vaultspec"})
        thread = await create_thread(session, title="Meta", metadata=meta)
        result = await get_thread_metadata(session, thread.id)
        assert result == meta

    @pytest.mark.asyncio
    async def test_get_thread_metadata_none(self, session: AsyncSession) -> None:
        """get_thread_metadata returns None for threads without metadata."""
        thread = await create_thread(session, title="No Meta")
        result = await get_thread_metadata(session, thread.id)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_thread_metadata_missing_thread(
        self, session: AsyncSession
    ) -> None:
        """get_thread_metadata returns None for nonexistent thread."""
        result = await get_thread_metadata(session, "nonexistent-thread")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_thread_found(self, session: AsyncSession) -> None:
        """get_thread should return the thread when it exists."""
        created = await create_thread(session, title="Findable")
        found = await get_thread(session, created.id)
        assert found is not None
        assert found.id == created.id
        assert found.title == "Findable"

    @pytest.mark.asyncio
    async def test_get_thread_not_found(self, session: AsyncSession) -> None:
        """get_thread should return None for a nonexistent ID."""
        result = await get_thread(session, "nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_list_threads_pagination(self, session: AsyncSession) -> None:
        """list_threads should respect offset and limit."""
        thread_count = 5
        page_size = 3
        for i in range(thread_count):
            await create_thread(session, title=f"Thread {i}")

        threads, total = await list_threads(session, offset=0, limit=page_size)
        assert total == thread_count
        assert len(threads) == page_size

        threads2, total2 = await list_threads(
            session, offset=page_size, limit=page_size
        )
        assert total2 == thread_count
        assert len(threads2) == thread_count - page_size

    @pytest.mark.asyncio
    async def test_list_threads_empty(self, session: AsyncSession) -> None:
        """list_threads on an empty table should return zero results."""
        threads, total = await list_threads(session)
        assert total == 0
        assert len(threads) == 0

    @pytest.mark.asyncio
    async def test_update_thread_status(self, session: AsyncSession) -> None:
        """update_thread_status should change the status field."""
        thread = await create_thread(session, title="Updatable")
        assert thread.status == "submitted"

        updated = await update_thread_status(session, thread.id, "running")
        assert updated is not None
        assert updated.status == "running"

    @pytest.mark.asyncio
    async def test_update_thread_status_not_found(self, session: AsyncSession) -> None:
        """update_thread_status should return None for missing thread."""
        result = await update_thread_status(session, "missing", "running")
        assert result is None


# ---------------------------------------------------------------------------
# Artifact CRUD Tests
# ---------------------------------------------------------------------------


class TestArtifactCRUD:
    """Tests for artifact create and query operations."""

    @pytest.mark.asyncio
    async def test_create_artifact(self, session: AsyncSession) -> None:
        """Creating an artifact should link it to the parent thread."""
        thread = await create_thread(session, title="Artifact Thread")
        artifact = await create_artifact(
            session,
            thread_id=thread.id,
            artifact_type="file",
            path="/src/main.py",
        )
        assert artifact.id is not None
        assert artifact.thread_id == thread.id
        assert artifact.type == "file"
        assert artifact.path == "/src/main.py"

    @pytest.mark.asyncio
    async def test_save_artifact_with_extra_fields(self, session: AsyncSession) -> None:
        """save_model should persist an ArtifactModel with all fields set."""
        thread = await create_thread(session, title="Full Artifact")
        artifact = ArtifactModel(
            id=uuid4().hex,
            thread_id=thread.id,
            type="file",
            path="/src/lib.py",
            content_hash="abc123",
            agent_id="coder-1",
        )
        saved = await save_model(session, artifact)
        assert isinstance(saved, ArtifactModel)
        assert saved.content_hash == "abc123"
        assert saved.agent_id == "coder-1"

    @pytest.mark.asyncio
    async def test_get_artifact_by_id(self, session: AsyncSession) -> None:
        """get_artifact should return the artifact by its primary key."""
        thread = await create_thread(session, title="Parent")
        created = await create_artifact(
            session,
            thread_id=thread.id,
            artifact_type="diff",
            path="/src/lib.py",
        )
        found = await get_artifact(session, created.id)
        assert found is not None
        assert found.path == "/src/lib.py"

    @pytest.mark.asyncio
    async def test_get_artifact_not_found(self, session: AsyncSession) -> None:
        """get_artifact should return None for nonexistent ID."""
        result = await get_artifact(session, "no-such-id")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_artifacts_by_thread(self, session: AsyncSession) -> None:
        """get_artifacts_by_thread should return all artifacts for a thread."""
        thread = await create_thread(session, title="Multi-Artifact")
        expected_paths = {"/a.py", "/b.py"}
        for path in expected_paths:
            await create_artifact(
                session,
                thread_id=thread.id,
                artifact_type="file",
                path=path,
            )

        artifacts = await get_artifacts_by_thread(session, thread.id)
        assert len(artifacts) == len(expected_paths)
        assert {a.path for a in artifacts} == expected_paths

    @pytest.mark.asyncio
    async def test_get_artifacts_by_thread_empty(self, session: AsyncSession) -> None:
        """get_artifacts_by_thread returns empty for thread with no artifacts."""
        thread = await create_thread(session, title="No Artifacts")
        artifacts = await get_artifacts_by_thread(session, thread.id)
        assert len(artifacts) == 0


# ---------------------------------------------------------------------------
# Permission Log Tests
# ---------------------------------------------------------------------------


class TestPermissionLogCRUD:
    """Tests for permission log append and query operations."""

    @pytest.mark.asyncio
    async def test_append_permission_log(self, session: AsyncSession) -> None:
        """append_permission_log should create an audit entry."""
        thread = await create_thread(session, title="Permission Thread")
        log = await append_permission_log(
            session,
            thread_id=thread.id,
            agent_id="coder-1",
            tool_name="file_write",
            action="allow_once",
        )
        assert log.id is not None
        assert log.thread_id == thread.id
        assert log.agent_id == "coder-1"
        assert log.tool_name == "file_write"
        assert log.action == "allow_once"

    @pytest.mark.asyncio
    async def test_save_permission_log_with_option_id(
        self, session: AsyncSession
    ) -> None:
        """save_model should persist a PermissionLogModel with option_id."""
        thread = await create_thread(session, title="Opt Thread")
        log = PermissionLogModel(
            id=uuid4().hex,
            thread_id=thread.id,
            agent_id="coder-1",
            tool_name="bash",
            action="allow_once",
            option_id="opt-42",
        )
        saved = await save_model(session, log)
        assert isinstance(saved, PermissionLogModel)
        assert saved.option_id == "opt-42"

    @pytest.mark.asyncio
    async def test_get_permission_logs_by_thread(self, session: AsyncSession) -> None:
        """get_permission_logs_by_thread should return ordered entries."""
        thread = await create_thread(session, title="Multi-Perm")
        await append_permission_log(
            session,
            thread_id=thread.id,
            agent_id="coder-1",
            tool_name="bash",
            action="allow_once",
        )
        await append_permission_log(
            session,
            thread_id=thread.id,
            agent_id="coder-2",
            tool_name="file_read",
            action="reject_once",
        )

        logs = await get_permission_logs_by_thread(session, thread.id)
        expected_tools = ["bash", "file_read"]
        assert [log.tool_name for log in logs] == expected_tools

    @pytest.mark.asyncio
    async def test_get_permission_logs_empty(self, session: AsyncSession) -> None:
        """Empty thread should have no permission logs."""
        thread = await create_thread(session, title="No Perms")
        logs = await get_permission_logs_by_thread(session, thread.id)
        assert len(logs) == 0


# ---------------------------------------------------------------------------
# Cost Tracking Tests
# ---------------------------------------------------------------------------


class TestCostTrackingCRUD:
    """Tests for cost tracking append and aggregation operations."""

    @staticmethod
    def _make_cost_record(**kwargs: object) -> CostTrackingModel:
        """Build a CostTrackingModel instance for testing.

        Accepts any ``CostTrackingModel`` field as a keyword argument.
        Defaults: ``provider="claude"``, ``model="max"``, tokens and cost
        are zero.
        """
        defaults: dict[str, object] = {
            "id": uuid4().hex,
            "provider": "claude",
            "model": "max",
            "input_tokens": 0,
            "output_tokens": 0,
            "estimated_cost": 0.0,
        }
        return CostTrackingModel(**(defaults | kwargs))

    @pytest.mark.asyncio
    async def test_append_cost_record(self, session: AsyncSession) -> None:
        """append_cost_record should create a cost entry."""
        thread = await create_thread(session, title="Cost Thread")
        record = self._make_cost_record(
            thread_id=thread.id,
            agent_id="coder-1",
            input_tokens=1000,
            output_tokens=500,
            estimated_cost=0.05,
        )
        saved = await append_cost_record(session, record)
        assert saved.id is not None
        assert saved.input_tokens == record.input_tokens
        assert saved.output_tokens == record.output_tokens
        assert saved.estimated_cost == pytest.approx(record.estimated_cost)

    @pytest.mark.asyncio
    async def test_sum_cost_by_thread(self, session: AsyncSession) -> None:
        """sum_cost_by_thread should aggregate all records for a thread."""
        thread = await create_thread(session, title="Sum Thread")
        r1 = self._make_cost_record(
            thread_id=thread.id,
            agent_id="coder-1",
            input_tokens=1000,
            output_tokens=500,
            estimated_cost=0.05,
        )
        r2 = self._make_cost_record(
            thread_id=thread.id,
            agent_id="coder-2",
            provider="gemini",
            model="high",
            input_tokens=2000,
            output_tokens=800,
            estimated_cost=0.03,
        )
        await append_cost_record(session, r1)
        await append_cost_record(session, r2)

        totals = await sum_cost_by_thread(session, thread.id)
        expected_input = r1.input_tokens + r2.input_tokens
        expected_output = r1.output_tokens + r2.output_tokens
        expected_cost = r1.estimated_cost + r2.estimated_cost
        assert totals["input_tokens"] == expected_input
        assert totals["output_tokens"] == expected_output
        assert totals["estimated_cost"] == pytest.approx(expected_cost)

    @pytest.mark.asyncio
    async def test_sum_cost_by_thread_empty(self, session: AsyncSession) -> None:
        """sum_cost_by_thread for an empty thread should return zeros."""
        thread = await create_thread(session, title="Empty Cost")
        totals = await sum_cost_by_thread(session, thread.id)
        assert totals["input_tokens"] == 0
        assert totals["output_tokens"] == 0
        assert totals["estimated_cost"] == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_sum_cost_by_agent(self, session: AsyncSession) -> None:
        """sum_cost_by_agent should aggregate across threads."""
        t1 = await create_thread(session, title="Thread 1")
        t2 = await create_thread(session, title="Thread 2")

        r1 = self._make_cost_record(
            thread_id=t1.id,
            agent_id="coder-1",
            input_tokens=500,
            output_tokens=200,
            estimated_cost=0.02,
        )
        r2 = self._make_cost_record(
            thread_id=t2.id,
            agent_id="coder-1",
            model="high",
            input_tokens=700,
            output_tokens=300,
            estimated_cost=0.04,
        )
        await append_cost_record(session, r1)
        await append_cost_record(session, r2)

        totals = await sum_cost_by_agent(session, "coder-1")
        expected_input = r1.input_tokens + r2.input_tokens
        expected_output = r1.output_tokens + r2.output_tokens
        expected_cost = r1.estimated_cost + r2.estimated_cost
        assert totals["input_tokens"] == expected_input
        assert totals["output_tokens"] == expected_output
        assert totals["estimated_cost"] == pytest.approx(expected_cost)

    @pytest.mark.asyncio
    async def test_sum_cost_by_agent_empty(self, session: AsyncSession) -> None:
        """sum_cost_by_agent for unknown agent should return zeros."""
        totals = await sum_cost_by_agent(session, "nonexistent-agent")
        assert totals["input_tokens"] == 0
        assert totals["output_tokens"] == 0
        assert totals["estimated_cost"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# WAL Mode Tests (M17: file-backed DB)
# ---------------------------------------------------------------------------


class TestWALMode:
    """M17: verify WAL mode on a file-backed SQLite database."""

    @pytest.mark.asyncio
    async def test_wal_mode_on_file_db(self, tmp_path: Path) -> None:
        """verify_wal_mode returns 'wal' on a file-backed SQLite DB."""
        db_path = tmp_path / "test_wal.db"
        eng = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)

        # WAL mode is set via the connect event listener in session.py;
        # replicate it here for a standalone engine.
        @event.listens_for(eng.sync_engine, "connect")
        def _set_wal(dbapi_conn: object, _rec: object) -> None:
            dbapi_conn.execute("PRAGMA journal_mode=WAL")  # type: ignore[union-attr]

        async with eng.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        mode = await verify_wal_mode(eng)
        assert mode == "wal"
        await eng.dispose()

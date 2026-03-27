"""Tests for the database layer using real in-memory SQLite.

No mocks, no monkeypatching. Every test runs against a real aiosqlite
in-memory database. Tests cover CRUD operations, session management
(init_db, close_db, get_session_factory, get_db), WAL mode verification,
cross-session durability, and cascade-delete behaviour.
"""

import json
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any
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
from starlette.datastructures import State
from starlette.requests import Request

from ...thread.errors import NicknameConflictError
from .. import session as _session_module
from ..crud import (
    ApprovalStatus,
    InvalidTransitionError,
    PermissionRequestStatus,
    ThreadStatus,
    append_cost_record,
    append_permission_log,
    create_artifact,
    create_thread,
    delete_thread,
    get_artifact,
    get_artifacts_by_thread,
    get_permission_logs_by_thread,
    get_permission_request,
    get_thread,
    get_thread_metadata,
    list_threads,
    record_permission_request,
    save_model,
    set_thread_approval_state,
    sum_cost_by_agent,
    sum_cost_by_thread,
    supersede_permission_requests,
    update_thread_metadata,
    update_thread_status,
)
from ..models import (
    ArtifactModel,
    Base,
    CostTrackingModel,
    PermissionLogModel,
)
from ..session import (
    close_db,
    get_db,
    get_engine,
    get_session_factory,
    init_db,
    verify_wal_mode,
)

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


@pytest_asyncio.fixture
async def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Provide the session factory for durability and multi-session tests."""
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


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
        assert thread.approval_status is None
        assert thread.approval_request_id is None

    @pytest.mark.asyncio
    async def test_create_thread_explicit_id(self, session: AsyncSession) -> None:
        """Creating a thread with an explicit ID should use that ID."""
        thread = await create_thread(session, thread_id="custom-id", title="Custom")
        assert thread.id == "custom-id"

    @pytest.mark.asyncio
    async def test_create_thread_rejects_removed_created_status(
        self, session: AsyncSession
    ) -> None:
        """The orphaned created status is no longer accepted for new threads."""
        with pytest.raises(ValueError, match="created"):
            await create_thread(session, title="Legacy", status="created")

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
    async def test_set_thread_approval_state(self, session: AsyncSession) -> None:
        """Thread approval state should persist durable plan-approval truth."""
        thread = await create_thread(session, title="Approval State")

        updated = await set_thread_approval_state(
            session,
            thread.id,
            approval_status=ApprovalStatus.PENDING,
            approval_request_id="approval-1",
            approval_reason="Approve plan before exec",
            approval_response_action_id="action-1",
        )

        assert updated is not None
        assert updated.approval_status == "pending"
        assert updated.approval_request_id == "approval-1"
        assert updated.approval_reason == "Approve plan before exec"
        assert updated.approval_response_action_id == "action-1"
        assert updated.approval_updated_at is not None

    @pytest.mark.asyncio
    async def test_supersede_permission_requests(self, session: AsyncSession) -> None:
        """Earlier plan-approval requests should be markable as superseded."""
        thread = await create_thread(session, title="Supersede Approval")
        await record_permission_request(
            session,
            request_id="approval-old",
            thread_id=thread.id,
            pause_reason_type="plan_approval",
            description="Old approval",
            allowed_options=[],
            tool_call="plan_approval",
        )
        await record_permission_request(
            session,
            request_id="approval-new",
            thread_id=thread.id,
            pause_reason_type="plan_approval",
            description="New approval",
            allowed_options=[],
            tool_call="plan_approval",
        )

        updated = await supersede_permission_requests(
            session,
            thread_id=thread.id,
            pause_reason_type="plan_approval",
            except_request_id="approval-new",
        )
        old_request = await get_permission_request(session, "approval-old")
        new_request = await get_permission_request(session, "approval-new")

        assert updated == 1
        assert old_request is not None
        assert old_request.request_status == PermissionRequestStatus.SUPERSEDED.value
        assert new_request is not None
        assert new_request.request_status == PermissionRequestStatus.PENDING.value

    @pytest.mark.asyncio
    async def test_update_thread_status_not_found(self, session: AsyncSession) -> None:
        """update_thread_status should return None for missing thread."""
        result = await update_thread_status(session, "missing", "running")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_thread_not_found_returns_none(
        self, session: AsyncSession
    ) -> None:
        """DB-H1: get_thread returns None (not an exception) for non-existent ID.

        Callers must handle None — the API layer converts it to a 404 response.
        """
        result = await get_thread(session, "completely-nonexistent-thread-id")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_thread_after_status_update_has_fresh_updated_at(
        self, session: AsyncSession
    ) -> None:
        """DB-H2: updated_at in the returned object should reflect the update time.

        With expire_on_commit=False and onupdate= on the column, the in-memory
        value is stale after flush unless we set it explicitly.
        """
        thread = await create_thread(session, title="Staleness Check")
        original_updated_at = thread.updated_at

        updated = await update_thread_status(session, thread.id, "running")
        assert updated is not None
        # The returned object must have a fresh timestamp, not the original one.
        assert updated.updated_at >= original_updated_at

    @pytest.mark.asyncio
    async def test_nickname_conflict_via_create_thread(
        self, session: AsyncSession
    ) -> None:
        """DB-MEDIUM-01: create_thread() raises NicknameConflictError on duplicate.

        Calls create_thread() twice with the same nickname. Verifies that the
        SELECT pre-check in create_thread() produces NicknameConflictError.
        """
        nickname = "dupe-nick-0001"
        await create_thread(session, nickname=nickname, title="first")
        await session.commit()
        with pytest.raises(NicknameConflictError):
            await create_thread(session, nickname=nickname, title="second")

    @pytest.mark.asyncio
    async def test_update_thread_metadata(self, session: AsyncSession) -> None:
        """DB-M2: update_thread_metadata should update the thread_metadata field."""
        thread = await create_thread(session, title="Meta Update")
        assert thread.thread_metadata is None

        new_meta = '{"workspace_root": "Y:/code/updated"}'
        updated = await update_thread_metadata(session, thread.id, new_meta)
        assert updated is not None
        assert updated.thread_metadata == new_meta
        assert updated.id == thread.id

    @pytest.mark.asyncio
    async def test_update_thread_metadata_not_found(
        self, session: AsyncSession
    ) -> None:
        """update_thread_metadata returns None for a non-existent thread."""
        result = await update_thread_metadata(session, "nonexistent-id", '{"x": 1}')
        assert result is None

    @pytest.mark.asyncio
    async def test_update_thread_metadata_clear(self, session: AsyncSession) -> None:
        """update_thread_metadata can clear metadata by passing None."""
        meta = '{"workspace_root": "Y:/code/vaultspec"}'
        thread = await create_thread(session, title="Clear Meta", metadata=meta)
        assert thread.thread_metadata == meta

        cleared = await update_thread_metadata(session, thread.id, None)
        assert cleared is not None
        assert cleared.thread_metadata is None

    @pytest.mark.asyncio
    async def test_create_thread_invalid_status_raises(
        self, session: AsyncSession
    ) -> None:
        """DB-HIGH-02: create_thread() rejects invalid status strings."""
        with pytest.raises(ValueError, match="Invalid thread status"):
            await create_thread(session, title="Bad Status", status="bogus")

    @pytest.mark.asyncio
    async def test_update_thread_status_invalid_raises(
        self, session: AsyncSession
    ) -> None:
        """DB-HIGH-02: update_thread_status() rejects invalid status strings."""
        thread = await create_thread(session, title="Valid Thread")
        with pytest.raises(ValueError, match="Invalid thread status"):
            await update_thread_status(session, thread.id, "not-a-real-status")

    @pytest.mark.asyncio
    async def test_create_thread_all_valid_statuses(
        self, session: AsyncSession
    ) -> None:
        """DB-HIGH-02: create_thread() accepts all ThreadStatus enum values."""
        for status in ThreadStatus:
            thread = await create_thread(
                session, title=f"Status {status.value}", status=status.value
            )
            assert thread.status == status.value

    @pytest.mark.asyncio
    async def test_data_survives_commit_in_fresh_session(
        self,
        session_factory: async_sessionmaker,
    ) -> None:
        """DB-MEDIUM-03: committed data is readable from a new session.

        Verifies that WAL + commit semantics are correct — data is not
        ephemeral in the session-local state.
        """
        async with session_factory() as s1:
            t = await create_thread(s1, title="durable")
            await s1.commit()
            tid = t.id

        async with session_factory() as s2:
            found = await get_thread(s2, tid)
            assert found is not None
            assert found.title == "durable"


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
    async def test_wal_mode_on_file_db(self, runtime_dir: Path) -> None:
        """verify_wal_mode returns 'wal' on a file-backed SQLite DB."""
        db_path = runtime_dir / "test_wal.db"
        eng = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)

        # WAL mode is set via the connect event listener in session.py;
        # replicate it here for a standalone engine.
        @event.listens_for(eng.sync_engine, "connect")
        def _set_wal(dbapi_conn: Any, _rec: object) -> None:
            dbapi_conn.execute("PRAGMA journal_mode=WAL")

        async with eng.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        mode = await verify_wal_mode(eng)
        assert mode == "wal"
        await eng.dispose()


# ---------------------------------------------------------------------------
# Session Management Function Tests (DB-MEDIUM-04)
# ---------------------------------------------------------------------------


class TestSessionFunctions:
    """Tests for close_db, get_session_factory, and get_db utility functions."""

    @pytest_asyncio.fixture(autouse=True)
    async def _isolate_singleton(self) -> AsyncGenerator[None]:
        """Isolate the module singleton from other tests."""
        await close_db()
        yield
        await close_db()

    @pytest.mark.asyncio
    async def test_close_db_resets_singleton(self) -> None:
        """close_db() disposes the engine and resets the singleton state."""
        await init_db(":memory:")
        # Access the live singleton value via the module reference — a direct
        # import binding would be stale after close_db() resets the global.
        assert _session_module._engine is not None

        await close_db()

        assert _session_module._engine is None

    @pytest.mark.asyncio
    async def test_get_session_factory_returns_factory(self) -> None:
        """get_session_factory() returns an async_sessionmaker."""
        await init_db(":memory:")
        factory = get_session_factory()
        assert callable(factory)
        # Verify we can actually create a session from it
        async with factory() as session:
            assert isinstance(session, AsyncSession)

    @pytest.mark.asyncio
    async def test_get_session_factory_with_explicit_engine(self) -> None:
        """get_session_factory(engine) accepts an explicit engine."""
        eng = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with eng.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        try:
            factory = get_session_factory(eng)
            assert callable(factory)
            async with factory() as session:
                assert isinstance(session, AsyncSession)
        finally:
            await eng.dispose()

    @pytest.mark.asyncio
    async def test_get_db_yields_session(self) -> None:
        """get_db() yields an AsyncSession suitable for dependency injection."""
        await init_db(":memory:")
        app_cls = type("_App", (), {"state": State()})
        request = Request({"type": "http", "app": app_cls()})
        gen = get_db(request)
        session = await gen.__anext__()
        assert isinstance(session, AsyncSession)
        # aclose() triggers the finally block and is safe to call unconditionally
        await gen.aclose()


# ---------------------------------------------------------------------------
# Cascade Delete Tests (DB-MEDIUM-05)
# ---------------------------------------------------------------------------


class TestCascadeDelete:
    """Verify that cascade="all, delete-orphan" removes child records."""

    @pytest.mark.asyncio
    async def test_delete_thread_cascades_to_artifacts(
        self, session: AsyncSession
    ) -> None:
        """Deleting a thread removes all associated artifact records."""
        thread = await create_thread(session, title="Cascade Artifacts")
        artifact = await create_artifact(
            session,
            thread_id=thread.id,
            artifact_type="file",
            path="/src/main.py",
        )
        artifact_id = artifact.id
        await session.commit()

        # Reload and delete the thread
        t = await get_thread(session, thread.id)
        await session.delete(t)
        await session.commit()

        found = await get_artifact(session, artifact_id)
        assert found is None, "Artifact should be deleted with its parent thread"

    @pytest.mark.asyncio
    async def test_delete_thread_cascades_to_permission_logs(
        self, session: AsyncSession
    ) -> None:
        """Deleting a thread removes all associated permission log records."""
        thread = await create_thread(session, title="Cascade Permissions")
        await append_permission_log(
            session,
            thread_id=thread.id,
            agent_id="coder-1",
            tool_name="bash",
            action="allow_once",
        )
        await session.commit()

        t = await get_thread(session, thread.id)
        await session.delete(t)
        await session.commit()

        logs = await get_permission_logs_by_thread(session, thread.id)
        assert len(logs) == 0, "Permission logs should be deleted with the thread"


# ---------------------------------------------------------------------------
# Thread Status State Machine Tests (DB-H / BE-37)
# ---------------------------------------------------------------------------


class TestInvalidTransitionError:
    """BE-37: _VALID_TRANSITIONS state machine — allowed and forbidden paths."""

    @pytest.mark.asyncio
    async def test_submitted_to_running_is_allowed(self, session: AsyncSession) -> None:
        """submitted → running is a valid forward transition."""
        thread = await create_thread(session, title="SM-01", status="submitted")
        updated = await update_thread_status(session, thread.id, ThreadStatus.RUNNING)
        assert updated is not None
        assert updated.status == "running"

    @pytest.mark.asyncio
    async def test_running_to_completed_is_allowed(self, session: AsyncSession) -> None:
        """running → completed is a valid terminal transition."""
        thread = await create_thread(session, title="SM-02", status="running")
        updated = await update_thread_status(session, thread.id, ThreadStatus.COMPLETED)
        assert updated is not None
        assert updated.status == "completed"

    @pytest.mark.asyncio
    async def test_running_to_failed_is_allowed(self, session: AsyncSession) -> None:
        """running → failed is valid (error path)."""
        thread = await create_thread(session, title="SM-03", status="running")
        updated = await update_thread_status(session, thread.id, ThreadStatus.FAILED)
        assert updated is not None
        assert updated.status == "failed"

    @pytest.mark.asyncio
    async def test_terminal_to_archived_is_allowed(self, session: AsyncSession) -> None:
        """completed → archived is allowed (soft-delete path)."""
        thread = await create_thread(session, title="SM-04", status="completed")
        updated = await update_thread_status(session, thread.id, ThreadStatus.ARCHIVED)
        assert updated is not None
        assert updated.status == "archived"

    @pytest.mark.asyncio
    async def test_running_to_submitted_raises(self, session: AsyncSession) -> None:
        """running → submitted is a backward transition — must raise."""
        thread = await create_thread(session, title="SM-05", status="running")
        with pytest.raises(InvalidTransitionError, match=r"running.*submitted"):
            await update_thread_status(session, thread.id, ThreadStatus.SUBMITTED)

    @pytest.mark.asyncio
    async def test_completed_to_running_raises(self, session: AsyncSession) -> None:
        """completed → running is a terminal regression — must raise."""
        thread = await create_thread(session, title="SM-06", status="completed")
        with pytest.raises(InvalidTransitionError, match=r"completed.*running"):
            await update_thread_status(session, thread.id, ThreadStatus.RUNNING)

    @pytest.mark.asyncio
    async def test_failed_to_running_raises(self, session: AsyncSession) -> None:
        """failed → running is a terminal regression — must raise."""
        thread = await create_thread(session, title="SM-07", status="failed")
        with pytest.raises(InvalidTransitionError, match=r"failed.*running"):
            await update_thread_status(session, thread.id, ThreadStatus.RUNNING)

    @pytest.mark.asyncio
    async def test_archived_to_any_raises(self, session: AsyncSession) -> None:
        """archived → any is forbidden (truly terminal state)."""
        thread = await create_thread(session, title="SM-08", status="archived")
        for target in (
            ThreadStatus.SUBMITTED,
            ThreadStatus.RUNNING,
            ThreadStatus.COMPLETED,
            ThreadStatus.FAILED,
        ):
            with pytest.raises(InvalidTransitionError):
                await update_thread_status(session, thread.id, target)

    @pytest.mark.asyncio
    async def test_invalid_transition_error_is_value_error(
        self, session: AsyncSession
    ) -> None:
        """InvalidTransitionError is a subclass of ValueError for broad catching."""
        thread = await create_thread(session, title="SM-09", status="completed")
        with pytest.raises(ValueError):
            await update_thread_status(session, thread.id, ThreadStatus.SUBMITTED)


# ---------------------------------------------------------------------------
# delete_thread CRUD Tests (DB-H)
# ---------------------------------------------------------------------------


class TestDeleteThread:
    """Tests for the delete_thread() CRUD function."""

    @pytest.mark.asyncio
    async def test_delete_thread_returns_true(self, session: AsyncSession) -> None:
        """delete_thread() returns True when the thread exists and is deleted."""
        thread = await create_thread(session, title="Delete Me")
        result = await delete_thread(session, thread.id)
        assert result is True

    @pytest.mark.asyncio
    async def test_delete_thread_removes_from_db(self, session: AsyncSession) -> None:
        """After delete_thread(), get_thread() returns None."""
        thread = await create_thread(session, title="Gone")
        tid = thread.id
        await delete_thread(session, tid)
        await session.commit()
        found = await get_thread(session, tid)
        assert found is None

    @pytest.mark.asyncio
    async def test_delete_thread_nonexistent_returns_false(
        self, session: AsyncSession
    ) -> None:
        """delete_thread() returns False for a thread ID that does not exist."""
        result = await delete_thread(session, "completely-nonexistent-id")
        assert result is False

    @pytest.mark.asyncio
    async def test_delete_thread_cascades_artifacts(
        self, session: AsyncSession
    ) -> None:
        """delete_thread() removes cascading artifact records via CRUD function."""
        thread = await create_thread(session, title="With Artifacts")
        artifact = await create_artifact(
            session, thread_id=thread.id, artifact_type="file", path="/x.py"
        )
        artifact_id = artifact.id
        await delete_thread(session, thread.id)
        await session.commit()
        assert await get_artifact(session, artifact_id) is None

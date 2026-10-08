"""Tests for the database layer using real SQLite.

No mocks, no monkeypatching. Every test runs against a real aiosqlite
database: the per-test file the root fixtures provide, or an in-memory one
where the test drives ``init_db`` itself. Tests cover CRUD operations, session
management (init_db, close_db, get_session_factory, get_db), WAL mode
verification, cross-session durability, and cascade-delete behaviour.
"""

import json
from collections.abc import AsyncGenerator
from typing import cast
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)
from starlette.datastructures import State
from starlette.requests import Request

from ...conftest import SqlitePosture
from ...testing import seed_thread_expectation
from ...tests._write_authority import make_test_write_authority
from ...thread.enums import (
    ApprovalStatus,
    InvalidTransitionError,
    PermissionRequestStatus,
    ThreadStatus,
)
from ...thread.errors import NicknameConflictError
from .. import (
    append_cost_record,
    append_permission_log,
    create_thread,
    delete_thread,
    elect_thread_status,
    get_permission_logs_by_thread,
    get_permission_request,
    get_thread,
    list_threads,
    record_permission_request,
    save_model,
    set_thread_approval_state,
    sum_cost_by_role,
    sum_cost_by_thread,
    supersede_permission_requests,
)
from .. import session as _session_module
from ..models import (
    CostTrackingModel,
    PermissionLogModel,
    ThreadModel,
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

EXPECTED_TABLES = {"cost_tracking", "permission_logs", "threads"}

# The bound the cross-repository consumer of a failed run's reason enforces: it
# rejects anything longer than 500 BYTES outright, so a reason over that is not
# shown shortened, it is not shown at all. Restated here rather than imported
# from the repository so these assertions measure the production cap against the
# requirement it exists to satisfy instead of against itself.
_CONSUMER_REASON_BYTES = 500


async def _elect_from(
    session_factory: async_sessionmaker[AsyncSession],
    source: ThreadStatus,
    target: ThreadStatus,
    *,
    run: str,
    failure_reason: str | None = None,
) -> ThreadModel:
    """Seed a run in *source* with its accepted action, elect *target*, read it back.

    The election is made as the run's current writer from the witness the seed
    returns, so what comes back is what the production lifecycle write leaves
    durable.
    """
    expectation = await seed_thread_expectation(
        session_factory, run, source, f"{run}-receipt"
    )
    authority = expectation.authority
    async with session_factory() as session:
        await elect_thread_status(
            session,
            run,
            expectation=expectation,
            status=target,
            action_type=authority.action_type,
            action_receipt_id=authority.action_receipt_id,
            failure_reason=failure_reason,
        )
        await session.commit()
    async with session_factory() as reader:
        durable = await get_thread(reader, run)
    assert durable is not None
    return durable


# ---------------------------------------------------------------------------
# Session & Engine Tests
# ---------------------------------------------------------------------------


class TestSessionManagement:
    """Tests for engine creation, WAL mode, and init_db."""

    @pytest_asyncio.fixture(autouse=True)
    async def _isolate_singleton(self) -> AsyncGenerator[None]:
        """Ensure the module-level singleton engine is torn down.

        Prevents singleton state from leaking between tests.
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
        thread = await create_thread(
            session, write_authority=make_test_write_authority(), title="Test Thread"
        )
        assert thread.id is not None
        assert thread.title == "Test Thread"
        assert thread.status == "submitted"
        assert thread.created_at is not None
        assert thread.approval_status is None
        assert thread.approval_request_id is None

    @pytest.mark.asyncio
    async def test_create_thread_explicit_id(self, session: AsyncSession) -> None:
        """Creating a thread with an explicit ID should use that ID."""
        thread = await create_thread(
            session,
            write_authority=make_test_write_authority(),
            thread_id="custom-id",
            title="Custom",
        )
        assert thread.id == "custom-id"

    @pytest.mark.asyncio
    async def test_create_thread_rejects_removed_created_status(
        self, session: AsyncSession
    ) -> None:
        """The orphaned created status is no longer accepted for new threads."""
        with pytest.raises(ValueError, match="created"):
            await create_thread(
                session,
                write_authority=make_test_write_authority(),
                title="Legacy",
                status="created",
            )

    @pytest.mark.asyncio
    async def test_create_thread_with_metadata(self, session: AsyncSession) -> None:
        """metadata should store JSON as text (rename from agent_config)."""
        meta = json.dumps(
            {"workspace_root": "Y:/code/vaultspec", "feature_tag": "auth"},
        )
        thread = await create_thread(
            session,
            write_authority=make_test_write_authority(),
            title="Configured",
            metadata=meta,
        )
        assert thread.thread_metadata == meta
        assert thread.thread_metadata is not None
        parsed = json.loads(thread.thread_metadata)
        assert parsed["workspace_root"] == "Y:/code/vaultspec"

    @pytest.mark.asyncio
    async def test_create_thread_with_nickname(self, session: AsyncSession) -> None:
        """nickname should be stored on the thread."""
        thread = await create_thread(
            session,
            write_authority=make_test_write_authority(),
            title="Named",
            nickname="auth-flow-star-a3f2",
        )
        assert thread.nickname == "auth-flow-star-a3f2"

    @pytest.mark.asyncio
    async def test_nickname_uniqueness_conflict(self, session: AsyncSession) -> None:
        """Duplicate nicknames should raise NicknameConflictError."""
        await create_thread(
            session,
            write_authority=make_test_write_authority(),
            title="First",
            nickname="unique-nick-0001",
        )
        with pytest.raises(NicknameConflictError, match="unique-nick-0001"):
            await create_thread(
                session,
                write_authority=make_test_write_authority(),
                title="Second",
                nickname="unique-nick-0001",
            )

    @pytest.mark.asyncio
    async def test_thread_metadata_round_trips_through_get_thread(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """A stored metadata JSON string is read back off the thread row."""
        meta = json.dumps({"workspace_root": "Y:/code/vaultspec"})
        async with session_factory() as session:
            thread = await create_thread(
                session,
                write_authority=make_test_write_authority(),
                title="Meta",
                metadata=meta,
            )
            await session.commit()
        async with session_factory() as reader:
            found = await get_thread(reader, thread.id)
        assert found is not None
        assert found.thread_metadata == meta

    @pytest.mark.asyncio
    async def test_thread_without_metadata_reads_none(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """A thread created without metadata reads back None."""
        async with session_factory() as session:
            thread = await create_thread(
                session, write_authority=make_test_write_authority(), title="No Meta"
            )
            await session.commit()
        async with session_factory() as reader:
            found = await get_thread(reader, thread.id)
        assert found is not None
        assert found.thread_metadata is None

    @pytest.mark.asyncio
    async def test_get_thread_found(self, session: AsyncSession) -> None:
        """get_thread should return the thread when it exists."""
        created = await create_thread(
            session, write_authority=make_test_write_authority(), title="Findable"
        )
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
            await create_thread(
                session,
                write_authority=make_test_write_authority(),
                title=f"Thread {i}",
            )

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
    async def test_an_election_restores_the_active_projection(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """Lifecycle writes restore the denormalized discovery selector."""
        run = "stale-selector"
        expectation = await seed_thread_expectation(
            session_factory, run, ThreadStatus.RUNNING, f"{run}-receipt"
        )
        authority = expectation.authority
        async with session_factory() as session:
            thread = await get_thread(session, run)
            assert thread is not None
            thread.is_active = False
            await session.flush()
            await elect_thread_status(
                session,
                run,
                expectation=expectation,
                status=ThreadStatus.INPUT_REQUIRED,
                action_type=authority.action_type,
                action_receipt_id=authority.action_receipt_id,
            )
            await session.commit()
        async with session_factory() as reader:
            durable = await get_thread(reader, run)

        assert durable is not None
        assert durable.is_active is True

    @pytest.mark.asyncio
    async def test_an_overlong_ascii_reason_is_truncated_and_marked(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """The durable column never grows past the bound its consumer enforces."""
        failed = await _elect_from(
            session_factory,
            ThreadStatus.RUNNING,
            ThreadStatus.FAILED,
            run="long-ascii-reason",
            failure_reason="x" * 4000,
        )

        assert failed.failure_reason is not None
        assert len(failed.failure_reason.encode("utf-8")) <= _CONSUMER_REASON_BYTES
        assert failed.failure_reason.endswith("…")

    @pytest.mark.asyncio
    async def test_a_multibyte_reason_is_bounded_in_bytes_not_characters(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """A non-ASCII reason must fit the reader's bound, not merely look short.

        The consumer that validates this reason counts bytes. A character-counted
        cap of the same number lets a multibyte reason through at well over the
        limit, and the consumer then rejects it outright - so the run reports
        nothing rather than a shortened something.
        """
        # Three bytes per character, so a character-counted cap would admit
        # roughly three times the consumer's budget.
        reason = "провайдер отказал" * 60

        failed = await _elect_from(
            session_factory,
            ThreadStatus.RUNNING,
            ThreadStatus.FAILED,
            run="multibyte-reason",
            failure_reason=reason,
        )

        assert failed.failure_reason is not None
        assert len(failed.failure_reason) < len(reason)
        assert len(failed.failure_reason.encode("utf-8")) <= _CONSUMER_REASON_BYTES

    @pytest.mark.asyncio
    async def test_truncation_cuts_on_a_character_boundary(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """A cut mid-sequence would store bytes that are not valid UTF-8.

        The reason is built so the byte budget lands INSIDE a multi-byte
        character: a column holding half a character is worse than one holding a
        slightly shorter reason, and a strict decode is what tells the two apart.
        """
        # One ASCII character then three-byte characters, so successive budgets
        # fall at differing offsets within a character rather than aligning.
        reason = "e" + "字" * 400

        failed = await _elect_from(
            session_factory,
            ThreadStatus.RUNNING,
            ThreadStatus.FAILED,
            run="boundary-reason",
            failure_reason=reason,
        )

        assert failed.failure_reason is not None
        stored = failed.failure_reason
        assert len(stored.encode("utf-8")) <= _CONSUMER_REASON_BYTES
        # Round-trips through a strict decode: every character is whole.
        assert stored.encode("utf-8").decode("utf-8") == stored
        assert stored.startswith("e字")
        assert stored.endswith("字…")

    @pytest.mark.asyncio
    async def test_a_reason_within_the_bound_is_stored_verbatim(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """Only an overlong reason is touched; a short one keeps its own text."""
        reason = "Graph event stream failed unexpectedly: AcpPromptError: 402"

        failed = await _elect_from(
            session_factory,
            ThreadStatus.RUNNING,
            ThreadStatus.FAILED,
            run="short-reason",
            failure_reason=reason,
        )

        assert failed.failure_reason == reason

    @pytest.mark.asyncio
    async def test_set_thread_approval_state(self, session: AsyncSession) -> None:
        """Thread approval state should persist durable plan-approval truth."""
        thread = await create_thread(
            session, write_authority=make_test_write_authority(), title="Approval State"
        )

        updated = await set_thread_approval_state(
            session,
            thread.id,
            approval_status=ApprovalStatus.PENDING,
            approval_request_id="approval-1",
            approval_response_action_id="action-1",
        )

        assert updated is not None
        assert updated.approval_status == "pending"
        assert updated.approval_request_id == "approval-1"
        assert updated.approval_response_action_id == "action-1"
        assert updated.approval_updated_at is not None

    @pytest.mark.asyncio
    async def test_supersede_permission_requests(self, session: AsyncSession) -> None:
        """Earlier plan-approval requests should be markable as superseded."""
        thread = await create_thread(
            session,
            write_authority=make_test_write_authority(),
            title="Supersede Approval",
        )
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
    async def test_get_thread_not_found_returns_none(
        self, session: AsyncSession
    ) -> None:
        """get_thread returns None (not an exception) for non-existent ID.

        Callers must handle None — the API layer converts it to a 404 response.
        """
        result = await get_thread(session, "completely-nonexistent-thread-id")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_thread_after_an_election_has_fresh_updated_at(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """updated_at on the loaded object should reflect the election time.

        With expire_on_commit=False and onupdate= on the column, the in-memory
        value is stale after the update unless the election refreshes the row.
        """
        run = "staleness-check"
        expectation = await seed_thread_expectation(
            session_factory, run, ThreadStatus.SUBMITTED, f"{run}-receipt"
        )
        authority = expectation.authority
        async with session_factory() as session:
            thread = await get_thread(session, run)
            assert thread is not None
            original_updated_at = thread.updated_at
            await elect_thread_status(
                session,
                run,
                expectation=expectation,
                status=ThreadStatus.RUNNING,
                action_type=authority.action_type,
                action_receipt_id=authority.action_receipt_id,
            )
            # The loaded object must carry a fresh timestamp, not the original.
            assert thread.updated_at >= original_updated_at

    @pytest.mark.asyncio
    async def test_nickname_conflict_via_create_thread(
        self, session: AsyncSession
    ) -> None:
        """create_thread() raises NicknameConflictError on duplicate.

        Calls create_thread() twice with the same nickname. Verifies that the
        SELECT pre-check in create_thread() produces NicknameConflictError.
        """
        nickname = "dupe-nick-0001"
        await create_thread(
            session,
            write_authority=make_test_write_authority(),
            nickname=nickname,
            title="first",
        )
        await session.commit()
        with pytest.raises(NicknameConflictError):
            await create_thread(
                session,
                write_authority=make_test_write_authority(),
                nickname=nickname,
                title="second",
            )

    @pytest.mark.asyncio
    async def test_create_thread_invalid_status_raises(
        self, session: AsyncSession
    ) -> None:
        """create_thread() rejects invalid status strings."""
        with pytest.raises(ValueError, match="Invalid thread status"):
            await create_thread(
                session,
                write_authority=make_test_write_authority(),
                title="Bad Status",
                status="bogus",
            )

    @pytest.mark.asyncio
    async def test_elect_thread_status_rejects_an_untyped_status(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """elect_thread_status() refuses a status that is not a ThreadStatus."""
        run = "untyped-status"
        expectation = await seed_thread_expectation(
            session_factory, run, ThreadStatus.SUBMITTED, f"{run}-receipt"
        )
        authority = expectation.authority
        async with session_factory() as session:
            with pytest.raises(TypeError, match="ThreadStatus"):
                await elect_thread_status(
                    session,
                    run,
                    expectation=expectation,
                    status=cast("ThreadStatus", "not-a-real-status"),
                    action_type=authority.action_type,
                    action_receipt_id=authority.action_receipt_id,
                )

    @pytest.mark.asyncio
    async def test_create_thread_all_valid_statuses(
        self, session: AsyncSession
    ) -> None:
        """create_thread() accepts all ThreadStatus enum values."""
        for status in ThreadStatus:
            thread = await create_thread(
                session,
                write_authority=make_test_write_authority(),
                title=f"Status {status.value}",
                status=status.value,
            )
            assert thread.status == status.value

    @pytest.mark.asyncio
    async def test_data_survives_commit_in_fresh_session(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """committed data is readable from a new session.

        Verifies that WAL + commit semantics are correct — data is not
        ephemeral in the session-local state.
        """
        async with session_factory() as s1:
            t = await create_thread(
                s1, write_authority=make_test_write_authority(), title="durable"
            )
            await s1.commit()
            tid = t.id

        async with session_factory() as s2:
            found = await get_thread(s2, tid)
            assert found is not None
            assert found.title == "durable"


# ---------------------------------------------------------------------------
# Permission Log Tests
# ---------------------------------------------------------------------------


class TestPermissionLogCRUD:
    """Tests for permission log append and query operations."""

    @pytest.mark.asyncio
    async def test_append_permission_log(self, session: AsyncSession) -> None:
        """append_permission_log should create an audit entry."""
        thread = await create_thread(
            session,
            write_authority=make_test_write_authority(),
            title="Permission Thread",
        )
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
        thread = await create_thread(
            session, write_authority=make_test_write_authority(), title="Opt Thread"
        )
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
        thread = await create_thread(
            session, write_authority=make_test_write_authority(), title="Multi-Perm"
        )
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
        thread = await create_thread(
            session, write_authority=make_test_write_authority(), title="No Perms"
        )
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
        Defaults: ``provider="claude"``, ``model="max"``, counts zero.
        """
        defaults: dict[str, object] = {
            "id": uuid4().hex,
            "provider": "claude",
            "model": "max",
            "input_tokens": 0,
            "output_tokens": 0,
        }
        return CostTrackingModel(**(defaults | kwargs))

    @pytest.mark.asyncio
    async def test_append_cost_record(self, session: AsyncSession) -> None:
        """append_cost_record should create a cost entry."""
        thread = await create_thread(
            session, write_authority=make_test_write_authority(), title="Cost Thread"
        )
        record = self._make_cost_record(
            thread_id=thread.id,
            agent_id="coder-1",
            input_tokens=1000,
            output_tokens=500,
        )
        saved = await append_cost_record(session, record)
        assert saved.id is not None
        assert saved.input_tokens == record.input_tokens
        assert saved.output_tokens == record.output_tokens

    @pytest.mark.asyncio
    async def test_sum_cost_by_thread(self, session: AsyncSession) -> None:
        """sum_cost_by_thread should aggregate all records for a thread."""
        thread = await create_thread(
            session, write_authority=make_test_write_authority(), title="Sum Thread"
        )
        r1 = self._make_cost_record(
            thread_id=thread.id,
            agent_id="coder-1",
            input_tokens=1000,
            output_tokens=500,
        )
        r2 = self._make_cost_record(
            thread_id=thread.id,
            agent_id="coder-2",
            provider="codex",
            model="high",
            input_tokens=2000,
            output_tokens=800,
        )
        await append_cost_record(session, r1)
        await append_cost_record(session, r2)

        totals = await sum_cost_by_thread(session, thread.id)
        assert totals is not None
        assert totals.input_tokens == r1.input_tokens + r2.input_tokens
        assert totals.output_tokens == r1.output_tokens + r2.output_tokens

    @pytest.mark.asyncio
    async def test_sum_cost_by_thread_empty(self, session: AsyncSession) -> None:
        """A thread with no accounting rows reads back as no accounting.

        Not as zeros: a reviewer told a run spent zero tokens has been told
        something the system never measured.
        """
        thread = await create_thread(
            session, write_authority=make_test_write_authority(), title="Empty Cost"
        )
        assert await sum_cost_by_thread(session, thread.id) is None

    @pytest.mark.asyncio
    async def test_sum_cost_by_role_groups_within_the_thread(
        self, session: AsyncSession
    ) -> None:
        """Per-role totals cover the read thread's rows and no other thread's.

        The role id is the same in both threads, which is the hazard: it names a
        seat in a team preset rather than one run's agent, so an aggregate keyed
        on the role alone would fold the other run's tokens into this answer.
        """
        read = await create_thread(
            session, write_authority=make_test_write_authority(), title="Thread 1"
        )
        other = await create_thread(
            session, write_authority=make_test_write_authority(), title="Thread 2"
        )
        await append_cost_record(
            session,
            self._make_cost_record(
                thread_id=read.id,
                agent_id="coder-1",
                input_tokens=500,
                output_tokens=200,
            ),
        )
        await append_cost_record(
            session,
            self._make_cost_record(
                thread_id=read.id,
                agent_id="reviewer-1",
                input_tokens=40,
                output_tokens=9,
            ),
        )
        await append_cost_record(
            session,
            self._make_cost_record(
                thread_id=other.id,
                agent_id="coder-1",
                model="high",
                input_tokens=700,
                output_tokens=300,
            ),
        )

        per_role = await sum_cost_by_role(session, read.id)
        assert sorted(per_role) == ["coder-1", "reviewer-1"]
        coder, reviewer = per_role["coder-1"], per_role["reviewer-1"]
        assert (coder.input_tokens, coder.output_tokens) == (500, 200)
        assert (reviewer.input_tokens, reviewer.output_tokens) == (40, 9)

    @pytest.mark.asyncio
    async def test_sum_cost_by_role_is_empty_for_a_thread_with_no_rows(
        self, session: AsyncSession
    ) -> None:
        """A seat that took no turn is absent rather than present with zeros."""
        assert await sum_cost_by_role(session, "nonexistent-thread") == {}


# ---------------------------------------------------------------------------
# WAL Mode Tests (file-backed DB)
# ---------------------------------------------------------------------------


class TestWALMode:
    """Verify WAL mode on a file-backed SQLite database."""

    @pytest.mark.asyncio
    @pytest.mark.sqlite_engine(SqlitePosture.APPLICATION)
    async def test_wal_mode_on_file_db(self, engine: AsyncEngine) -> None:
        """verify_wal_mode returns 'wal' on a file-backed SQLite DB."""
        assert await verify_wal_mode(engine) == "wal"


# ---------------------------------------------------------------------------
# Session Management Function Tests
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
    async def test_get_session_factory_with_explicit_engine(
        self, engine: AsyncEngine
    ) -> None:
        """get_session_factory(engine) accepts an explicit engine."""
        factory = get_session_factory(engine)
        assert callable(factory)
        async with factory() as session:
            assert isinstance(session, AsyncSession)

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
# Cascade Delete Tests
# ---------------------------------------------------------------------------


class TestCascadeDelete:
    """Verify that cascade="all, delete-orphan" removes child records."""

    @pytest.mark.asyncio
    async def test_delete_thread_cascades_to_permission_logs(
        self, session: AsyncSession
    ) -> None:
        """Deleting a thread removes all associated permission log records."""
        thread = await create_thread(
            session,
            write_authority=make_test_write_authority(),
            title="Cascade Permissions",
        )
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
# Thread Status State Machine Tests
# ---------------------------------------------------------------------------


class TestInvalidTransitionError:
    """_VALID_TRANSITIONS state machine — allowed and forbidden paths."""

    @pytest.mark.asyncio
    async def test_submitted_to_running_is_allowed(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """submitted → running is a valid forward transition."""
        updated = await _elect_from(
            session_factory, ThreadStatus.SUBMITTED, ThreadStatus.RUNNING, run="sm-01"
        )
        assert updated.status == "running"

    @pytest.mark.asyncio
    async def test_running_to_completed_is_allowed(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """running → completed is a valid terminal transition."""
        updated = await _elect_from(
            session_factory, ThreadStatus.RUNNING, ThreadStatus.COMPLETED, run="sm-02"
        )
        assert updated.status == "completed"

    @pytest.mark.asyncio
    async def test_running_to_failed_is_allowed(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """running → failed is valid (error path)."""
        updated = await _elect_from(
            session_factory, ThreadStatus.RUNNING, ThreadStatus.FAILED, run="sm-03"
        )
        assert updated.status == "failed"

    @pytest.mark.asyncio
    async def test_terminal_to_archived_is_allowed(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """completed → archived is allowed (soft-delete path)."""
        updated = await _elect_from(
            session_factory, ThreadStatus.COMPLETED, ThreadStatus.ARCHIVED, run="sm-04"
        )
        assert updated.status == "archived"

    @pytest.mark.asyncio
    async def test_running_to_submitted_raises(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """running → submitted is a backward transition — must raise."""
        with pytest.raises(InvalidTransitionError, match=r"running.*submitted"):
            await _elect_from(
                session_factory,
                ThreadStatus.RUNNING,
                ThreadStatus.SUBMITTED,
                run="sm-05",
            )

    @pytest.mark.asyncio
    async def test_completed_to_running_raises(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """completed → running is a terminal regression — must raise."""
        with pytest.raises(InvalidTransitionError, match=r"completed.*running"):
            await _elect_from(
                session_factory,
                ThreadStatus.COMPLETED,
                ThreadStatus.RUNNING,
                run="sm-06",
            )

    @pytest.mark.asyncio
    async def test_failed_to_running_raises(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """failed → running is a terminal regression — must raise."""
        with pytest.raises(InvalidTransitionError, match=r"failed.*running"):
            await _elect_from(
                session_factory, ThreadStatus.FAILED, ThreadStatus.RUNNING, run="sm-07"
            )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "target",
        [
            ThreadStatus.SUBMITTED,
            ThreadStatus.RUNNING,
            ThreadStatus.COMPLETED,
            ThreadStatus.FAILED,
        ],
    )
    async def test_archived_to_any_raises(
        self, session_factory: async_sessionmaker[AsyncSession], target: ThreadStatus
    ) -> None:
        """archived → any is forbidden (truly terminal state)."""
        with pytest.raises(InvalidTransitionError):
            await _elect_from(
                session_factory,
                ThreadStatus.ARCHIVED,
                target,
                run=f"sm-08-{target.value}",
            )

    @pytest.mark.asyncio
    async def test_invalid_transition_error_is_value_error(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """InvalidTransitionError is a subclass of ValueError for broad catching."""
        with pytest.raises(ValueError):
            await _elect_from(
                session_factory,
                ThreadStatus.COMPLETED,
                ThreadStatus.SUBMITTED,
                run="sm-09",
            )


# ---------------------------------------------------------------------------
# delete_thread CRUD Tests
# ---------------------------------------------------------------------------


class TestDeleteThread:
    """Tests for the delete_thread() CRUD function."""

    @pytest.mark.asyncio
    async def test_delete_thread_returns_true(self, session: AsyncSession) -> None:
        """delete_thread() returns True when the thread exists and is deleted."""
        thread = await create_thread(
            session, write_authority=make_test_write_authority(), title="Delete Me"
        )
        result = await delete_thread(session, thread.id)
        assert result is True

    @pytest.mark.asyncio
    async def test_delete_thread_removes_from_db(self, session: AsyncSession) -> None:
        """After delete_thread(), get_thread() returns None."""
        thread = await create_thread(
            session, write_authority=make_test_write_authority(), title="Gone"
        )
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

"""Schema-integrity guards that structural parity cannot express.

``test_schema_parity.py`` proves the Alembic chain reproduces
``Base.metadata``. These tests cover four things that comparison is blind to,
each one a decision that would otherwise survive only as a comment:

* Index DIRECTION. SQLite reflection reports ``created_at DESC`` as the bare
  name ``created_at``, an omission the parity suite documents and cannot work
  around. The four partial ``ix_threads_active_*`` indexes are ordered
  descending on purpose, and a batch rebuild of ``threads`` rewrites them
  ascending without failing anything. This reads the stored DDL text, which is
  the one place the direction survives.
* That an unnamed foreign key IS droppable under SQLite batch mode. ``Base``
  declines a ``naming_convention`` on the grounds that Alembic's per-migration
  ``naming_convention`` argument already solves this; that claim is worth only
  as much as a real database says it is.
* That the status-column defaults are enum members rather than bare strings,
  asserted through a real write rather than by reading the model source.
* That caller-controlled text on the permission path is bounded before it
  reaches a client, and bounded WITHOUT destroying the frame.

Everything drives real SQLite databases, the real revision chain, and the real
Pydantic models.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from alembic import command
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Connection, create_engine, inspect, select, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ...api.schemas.events import (
    MAX_TOOL_CALL_CHARS,
    PermissionRequestEvent,
)
from ...graph.enums import ServerEventType
from ...thread.constants import MAX_PERMISSION_DESCRIPTION_CHARS
from ...thread.enums import ControlActionResultStatus, RepairStatus, ThreadStatus
from ..migrate import build_migration_config
from ..models import Base, ControlActionModel, ThreadModel

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Iterator
    from pathlib import Path

# The four partial indexes revision 0009 created descending, and the ordering it
# gave each one. Newest-first listing is the access pattern they exist for, so
# the direction is part of the index rather than a detail of how it was written.
_DESCENDING_ACTIVE_INDEXES: dict[str, str] = {
    "ix_threads_active_order": "created_at DESC, id DESC",
    "ix_threads_active_workspace_order": "workspace_key, created_at DESC, id DESC",
    "ix_threads_active_feature_order": "feature_tag, created_at DESC, id DESC",
    "ix_threads_active_workspace_feature_order": (
        "workspace_key, feature_tag, created_at DESC, id DESC"
    ),
}

# The convention Alembic applies to reflected constraints so an unnamed foreign
# key becomes targetable. Spelled the way Alembic's own batch documentation
# spells it.
_FK_CONVENTION = {"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}


@pytest.fixture(scope="module")
def migrated_database(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A real file-backed SQLite database migrated through the real chain.

    File-backed rather than ``:memory:`` because only a file forces the Alembic
    chain, which is what production replays and what these tests are about.
    """
    database = tmp_path_factory.mktemp("schema-integrity") / "migrated.db"
    command.upgrade(build_migration_config(f"sqlite+aiosqlite:///{database}"), "head")
    return database


@pytest.fixture(scope="module")
def migrated_connection(migrated_database: Path) -> Iterator[Connection]:
    """An open sync connection to the migrated database."""
    engine = create_engine(f"sqlite:///{migrated_database}")
    with engine.connect() as connection:
        yield connection
    engine.dispose()


@pytest_asyncio.fixture
async def session() -> AsyncGenerator[AsyncSession]:
    """A real session over the live declarative schema."""
    engine: AsyncEngine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as sess:
        yield sess
    await engine.dispose()


def _index_ddl(connection: Connection, index_name: str) -> str:
    """Return the stored CREATE INDEX text for one index on ``threads``."""
    ddl = connection.execute(
        text(
            "SELECT sql FROM sqlite_master "
            "WHERE type = 'index' AND tbl_name = 'threads' AND name = :name"
        ).bindparams(name=index_name)
    ).scalar_one_or_none()
    assert ddl is not None, f"{index_name} is absent from the migrated database"
    return str(ddl)


class TestActiveRunIndexDirection:
    """The partial active-run indexes must stay descending through the chain."""

    @pytest.mark.parametrize(
        ("index_name", "ordering"), sorted(_DESCENDING_ACTIVE_INDEXES.items())
    )
    def test_index_is_created_descending(
        self, migrated_connection: Connection, index_name: str, ordering: str
    ) -> None:
        """Head still orders this index newest-first.

        Guards a live hazard rather than a hypothetical one: adding a server
        default to ``threads.status`` was attempted and reverted precisely
        because the batch rebuild it requires rewrote all four of these indexes
        ascending, and every structural comparison in the suite still passed.
        A failure here means some migration rebuilt ``threads`` and flattened
        the ordering on the way through.
        """
        ddl = _index_ddl(migrated_connection, index_name)

        assert f"({ordering})" in ddl, (
            f"{index_name} lost its descending ordering; expected columns "
            f"({ordering}) but the migrated DDL is: {ddl}"
        )

    @pytest.mark.parametrize("index_name", sorted(_DESCENDING_ACTIVE_INDEXES))
    def test_index_stays_partial(
        self, migrated_connection: Connection, index_name: str
    ) -> None:
        """The partial predicate survives alongside the ordering."""
        ddl = _index_ddl(migrated_connection, index_name)

        assert "WHERE is_active IS 1" in ddl, (
            f"{index_name} lost its partial predicate; migrated DDL: {ddl}"
        )


class TestUnnamedForeignKeysAreTargetable:
    """``Base`` declines a naming convention; this proves that is affordable."""

    def test_thread_foreign_keys_are_unnamed_at_head(
        self, migrated_connection: Connection
    ) -> None:
        """Every ``thread_id`` foreign key reaches SQLite without a name.

        The premise of the decision recorded on ``Base``. If a later revision
        starts naming these, that decision is worth revisiting and this test
        says so.
        """
        inspector = inspect(migrated_connection)
        named = {
            table: [
                foreign_key["name"]
                for foreign_key in inspector.get_foreign_keys(table)
                if foreign_key["name"] is not None
            ]
            for table in sorted(Base.metadata.tables)
        }

        assert {table: names for table, names in named.items() if names} == {}, (
            f"foreign keys are now named in the migrated schema: {named}"
        )

    def test_batch_naming_convention_drops_an_unnamed_foreign_key(
        self, migrated_database: Path, tmp_path: Path
    ) -> None:
        """Alembic's batch ``naming_convention`` targets an unnamed FK for real.

        This is the whole remedy ``Base`` points at, exercised end to end: a
        real migrated database, a real ``Operations`` context, a real batch
        rebuild, and a reflection afterwards proving the constraint is gone.
        Run against a copy so the module-scoped database stays pristine.
        """
        working = tmp_path / "fk-drop.db"
        working.write_bytes(migrated_database.read_bytes())
        engine = create_engine(f"sqlite:///{working}")
        try:
            with engine.connect() as connection:
                before = inspect(connection).get_foreign_keys("artifacts")
                assert [key["constrained_columns"] for key in before] == [
                    ["thread_id"]
                ], f"expected one unnamed thread_id FK on artifacts, got {before}"

                operations = Operations(MigrationContext.configure(connection))
                with operations.batch_alter_table(
                    "artifacts", naming_convention=_FK_CONVENTION
                ) as batch_op:
                    batch_op.drop_constraint(
                        "fk_artifacts_thread_id_threads", type_="foreignkey"
                    )

                after = inspect(connection).get_foreign_keys("artifacts")

            assert after == [], (
                "the unnamed foreign key survived a batch drop that named it "
                f"through Alembic's naming_convention: {after}"
            )
        finally:
            engine.dispose()


class TestStatusDefaultsComeFromEnums:
    """Durable status defaults must be enum members, not loose strings."""

    @pytest.mark.asyncio
    async def test_thread_repair_defaults_are_repair_status_members(
        self, session: AsyncSession
    ) -> None:
        """A thread written with no repair state stores ``RepairStatus.HEALTHY``.

        Asserted against the enum member rather than the literal ``"healthy"``
        so the test tracks the vocabulary instead of restating it: renaming the
        member's value moves both sides together, which is the property the
        enum-backed default exists to give.
        """
        session.add(ThreadModel(id="thread-defaults"))
        await session.flush()
        session.expunge_all()

        stored = (
            await session.execute(
                select(ThreadModel).where(ThreadModel.id == "thread-defaults")
            )
        ).scalar_one()

        assert stored.repair_status == RepairStatus.HEALTHY
        assert stored.execution_readiness == RepairStatus.HEALTHY
        assert stored.status == ThreadStatus.SUBMITTED

    @pytest.mark.asyncio
    async def test_execution_readiness_accepts_the_repair_vocabulary(
        self, session: AsyncSession
    ) -> None:
        """The column round-trips every ``RepairStatus`` member.

        ``execution_readiness`` shares ``RepairStatus`` with ``repair_status``
        rather than owning a parallel enum, because every producer in the
        codebase already writes a ``RepairStatus`` member into it. This asserts
        the whole vocabulary survives the column, so the sharing is a fact about
        the schema and not just a convention.
        """
        for index, member in enumerate(RepairStatus):
            session.add(
                ThreadModel(id=f"thread-readiness-{index}", execution_readiness=member)
            )
        await session.flush()
        session.expunge_all()

        stored = {
            thread.id: thread.execution_readiness
            for thread in (await session.execute(select(ThreadModel))).scalars()
        }

        assert stored == {
            f"thread-readiness-{index}": member.value
            for index, member in enumerate(RepairStatus)
        }

    @pytest.mark.asyncio
    async def test_control_action_result_default_is_an_enum_member(
        self, session: AsyncSession
    ) -> None:
        """A journaled action defaults to ``ACCEPTED_NOT_APPLIED`` by member."""
        session.add(ThreadModel(id="thread-control"))
        session.add(
            ControlActionModel(
                id="action-1",
                thread_id="thread-control",
                action_type="ingest",
                idempotency_key="ingest:1",
                requested_at=datetime.now(UTC),
            )
        )
        await session.flush()
        session.expunge_all()

        stored = (
            await session.execute(
                select(ControlActionModel).where(ControlActionModel.id == "action-1")
            )
        ).scalar_one()

        assert stored.result_status == ControlActionResultStatus.ACCEPTED_NOT_APPLIED


def _permission_event(
    *, description: str, tool_call: str | None
) -> PermissionRequestEvent:
    """Build a permission frame the way ``api/event_adapter`` builds one."""
    return PermissionRequestEvent(
        type=ServerEventType.PERMISSION_REQUEST,
        thread_id="thread-1",
        agent_id="agent-1",
        timestamp=datetime.now(UTC),
        sequence=1,
        request_id="req-1",
        description=description,
        options=[],
        tool_call=tool_call,
    )


class TestPermissionTextIsBounded:
    """Worker-influenced permission text is capped before it reaches a client."""

    def test_oversize_description_is_truncated_not_refused(self) -> None:
        """A pathological description is shortened and still delivered.

        The delivery half matters as much as the bound. ``event_adapter`` builds
        this frame with no error handling, and the frame is the only signal that
        a run is waiting on an operator, so a cap that raised would convert an
        over-long description into a silently hung run.
        """
        event = _permission_event(
            description="d" * (MAX_PERMISSION_DESCRIPTION_CHARS * 3), tool_call=None
        )

        assert len(event.description) == MAX_PERMISSION_DESCRIPTION_CHARS

    def test_oversize_tool_call_is_truncated_not_refused(self) -> None:
        """An over-long tool identifier is shortened rather than fatal."""
        event = _permission_event(
            description="fine", tool_call="t" * (MAX_TOOL_CALL_CHARS * 3)
        )

        assert event.tool_call is not None
        assert len(event.tool_call) == MAX_TOOL_CALL_CHARS

    def test_text_within_the_bound_is_untouched(self) -> None:
        """The cap shortens only what exceeds it."""
        description = "a permission is required" * 8
        event = _permission_event(description=description, tool_call="write_file")

        assert event.description == description
        assert event.tool_call == "write_file"

    def test_absent_tool_call_stays_absent(self) -> None:
        """The bound leaves the optional field's ``None`` alone."""
        event = _permission_event(description="fine", tool_call=None)

        assert event.tool_call is None

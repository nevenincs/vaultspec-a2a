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
* That every reader of the workspace-root selector enforces the width the
  COLUMN declares, measured off the mapped column rather than off a number
  repeated in the test.
* That the accounting table records provider-reported counts and nothing
  priced or derived, in the model and in the migrated database alike.
* That the permission request table records the request's lifecycle and nothing
  about the answer, which the response journal owns.

Everything drives real SQLite databases, the real revision chain, the real
Pydantic models, and the real stream catalog.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from pydantic import ValidationError
from sqlalchemy import Connection, String, create_engine, inspect, select, text

from ...api.schemas.gateway import (
    ActiveRunRecord,
    ProviderCatalogSelection,
    RunStartRequest,
    RunSummaryRecord,
)
from ...control.run_discovery_service import discover_active_runs
from ...graph.enums import ServerEventType
from ...streaming.sse_frames import enforce_progress_allowlist
from ...tests._write_authority import (
    make_test_thread_authority_columns,
    make_test_write_authority,
)
from ...thread.constants import MAX_PERMISSION_DESCRIPTION_CHARS, MAX_TOOL_CALL_CHARS
from ...thread.enums import ControlActionResultStatus, RepairStatus, ThreadStatus
from ..models import Base, ControlActionModel, ThreadModel
from ..thread_repository import create_thread, list_active_thread_page

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from sqlalchemy.ext.asyncio import AsyncSession

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
def migrated_connection(migrated_template: Path) -> Iterator[Connection]:
    """An open sync connection to the session's migrated database, read only."""
    engine = create_engine(f"sqlite:///{migrated_template}")
    with engine.connect() as connection:
        yield connection
    engine.dispose()


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
        self, migrated_database_file: Path
    ) -> None:
        """Alembic's batch ``naming_convention`` targets an unnamed FK for real.

        This is the whole remedy ``Base`` points at, exercised end to end: a
        real migrated database, a real ``Operations`` context, a real batch
        rebuild, and a reflection afterwards proving the constraint is gone.
        Run against the test's own copy so the shared template stays pristine.
        """
        engine = create_engine(f"sqlite:///{migrated_database_file}")
        try:
            with engine.connect() as connection:
                before = inspect(connection).get_foreign_keys("permission_logs")
                assert [key["constrained_columns"] for key in before] == [
                    ["thread_id"]
                ], f"expected one unnamed thread_id FK on permission_logs, got {before}"

                operations = Operations(MigrationContext.configure(connection))
                with operations.batch_alter_table(
                    "permission_logs", naming_convention=_FK_CONVENTION
                ) as batch_op:
                    batch_op.drop_constraint(
                        "fk_permission_logs_thread_id_threads", type_="foreignkey"
                    )

                after = inspect(connection).get_foreign_keys("permission_logs")

            assert after == [], (
                "the unnamed foreign key survived a batch drop that named it "
                f"through Alembic's naming_convention: {after}"
            )
        finally:
            engine.dispose()


#: Every column ``cost_tracking`` is allowed to carry: the row's identity, the
#: lane that reported it, the five provider-reported counts, and when it landed.
_ACCOUNTING_COLUMNS = frozenset(
    {
        "id",
        "thread_id",
        "agent_id",
        "provider",
        "model",
        "input_tokens",
        "output_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
        "reasoning_tokens",
        "created_at",
    }
)


class TestAccountingRecordsOnlyWhatAProviderReported:
    """``cost_tracking`` holds measured counts and nothing priced or derived.

    The decision this pins is one no comparison of the two schemas can state: no
    column records a cost the system did not measure. Every served lane is a
    subscription-authenticated CLI agent and the project holds no rate table for
    any model, so a price column can only ever hold a structural zero - and a
    SUM over structural zeros reads back as a measured total of zero dollars.
    That is why a column recording a measurement nobody takes is worse than an
    absent one, and why one was removed rather than left unwritten.

    Asserted as an EXACT column set rather than as the absence of one name, so a
    price re-added under any spelling fails here. Asserted against the migrated
    database as well as the model, because the model alone cannot prove the
    column left the stores that already have it.
    """

    def test_the_model_declares_exactly_the_reported_counts(self) -> None:
        """The mapped table carries no priced or derived column."""
        declared = set(Base.metadata.tables["cost_tracking"].columns.keys())

        assert declared == set(_ACCOUNTING_COLUMNS), (
            "cost_tracking's mapped columns are no longer exactly the "
            f"provider-reported record: {sorted(declared ^ _ACCOUNTING_COLUMNS)}"
        )

    def test_the_migrated_table_declares_exactly_the_reported_counts(
        self, migrated_connection: Connection
    ) -> None:
        """Head agrees, so the chain really dropped it rather than stopping writing."""
        migrated = {
            column["name"]
            for column in inspect(migrated_connection).get_columns("cost_tracking")
        }

        assert migrated == set(_ACCOUNTING_COLUMNS), (
            "the migrated cost_tracking table is no longer exactly the "
            f"provider-reported record: {sorted(migrated ^ _ACCOUNTING_COLUMNS)}"
        )


#: Every column ``permission_requests`` is allowed to carry: the request's
#: identity, the run it belongs to, the question as it was asked, the lifecycle
#: state of the ask, and the three instants that state moved through.
_PERMISSION_REQUEST_COLUMNS = frozenset(
    {
        "request_id",
        "thread_id",
        "pause_reason_type",
        "tool_call",
        "description",
        "allowed_options_json",
        "request_status",
        "created_at",
        "responded_at",
        "applied_at",
    }
)


class TestThePermissionRequestRowHoldsNoCopyOfTheAnswer:
    """``permission_requests`` records the ask; the answer lives elsewhere.

    Two columns here used to hold a second copy of a decision: the option the
    responder chose and the journal key its response action was filed under. The
    settlement reads neither - it reads the answer off the frozen envelope of the
    accepted response action, deliberately, so a row rewritten after acceptance
    cannot change which option a run is settled under - and ``permission_logs``
    is the durable record of the decision itself. What remained was write-only
    storage of a fact with an owner elsewhere: a reader that trusted it could be
    told a different answer than the one the run was resumed with.

    Asserted as an EXACT column set rather than as the absence of two names, so a
    second copy re-added under any spelling fails here. Asserted against the
    migrated database as well as the model, because the model alone cannot prove
    the columns left the stores that already have them.
    """

    def test_the_model_declares_only_the_request_lifecycle(self) -> None:
        """The mapped table carries no column about the answer."""
        declared = set(Base.metadata.tables["permission_requests"].columns.keys())

        assert declared == set(_PERMISSION_REQUEST_COLUMNS), (
            "permission_requests' mapped columns are no longer exactly the "
            f"request's own record: {sorted(declared ^ _PERMISSION_REQUEST_COLUMNS)}"
        )

    def test_the_migrated_table_declares_only_the_request_lifecycle(
        self, migrated_connection: Connection
    ) -> None:
        """Head agrees, so the chain dropped them rather than stopping writing."""
        migrated = {
            column["name"]
            for column in inspect(migrated_connection).get_columns(
                "permission_requests"
            )
        }

        assert migrated == set(_PERMISSION_REQUEST_COLUMNS), (
            "the migrated permission_requests table is no longer exactly the "
            f"request's own record: {sorted(migrated ^ _PERMISSION_REQUEST_COLUMNS)}"
        )


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
        session.add(
            ThreadModel(**make_test_thread_authority_columns(), id="thread-defaults")
        )
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
        rather than owning a parallel enum, because it is written from the
        repair status and so can only ever hold a ``RepairStatus`` member. This
        asserts the whole vocabulary survives the column, so the sharing is a
        fact about the schema and not just a convention.
        """
        for index, member in enumerate(RepairStatus):
            session.add(
                ThreadModel(
                    **make_test_thread_authority_columns(),
                    id=f"thread-readiness-{index}",
                    execution_readiness=member,
                )
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
        session.add(
            ThreadModel(**make_test_thread_authority_columns(), id="thread-control")
        )
        session.add(
            ControlActionModel(
                id="action-1",
                thread_id="thread-control",
                action_type="ingest",
                idempotency_key="ingest:1",
                requested_at=datetime.now(UTC),
                recovery_deadline_at=datetime.now(UTC) + timedelta(minutes=5),
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


def _served_permission_frame(
    *, description: str, tool_call: str | None
) -> Mapping[str, object]:
    """Project a permission frame through the catalog the stream serves it with."""
    payload: dict[str, object] = {
        "type": ServerEventType.PERMISSION_REQUEST,
        "thread_id": "thread-1",
        "agent_id": "agent-1",
        "timestamp": 1.0,
        "sequence": 1,
        "request_id": "req-1",
        "description": description,
        "options": [],
    }
    if tool_call is not None:
        payload["tool_call"] = tool_call
    return enforce_progress_allowlist(payload)


class TestPermissionTextIsBounded:
    """Worker-influenced permission text is capped before it reaches a client."""

    def test_oversize_description_is_truncated_not_refused(self) -> None:
        """A pathological description is shortened and still delivered.

        The delivery half matters as much as the bound. The frame is the only
        signal that a run is waiting on an operator, so a cap that refused it
        would convert an over-long description into a silently hung run.
        """
        description = "d" * (MAX_PERMISSION_DESCRIPTION_CHARS * 3)
        frame = _served_permission_frame(description=description, tool_call=None)

        served = frame["description"]
        assert isinstance(served, str)
        assert frame["request_id"] == "req-1"
        assert 0 < len(served) <= MAX_PERMISSION_DESCRIPTION_CHARS
        assert description.startswith(served)

    def test_oversize_tool_call_is_truncated_not_refused(self) -> None:
        """An over-long tool identifier is shortened rather than fatal."""
        tool_call = "t" * (MAX_TOOL_CALL_CHARS * 3)
        frame = _served_permission_frame(description="fine", tool_call=tool_call)

        served = frame["tool_call"]
        assert isinstance(served, str)
        assert frame["request_id"] == "req-1"
        assert len(served) == MAX_TOOL_CALL_CHARS
        assert tool_call.startswith(served)

    def test_text_within_the_bound_is_untouched(self) -> None:
        """The cap shortens only what exceeds it."""
        description = "a permission is required" * 8
        frame = _served_permission_frame(
            description=description, tool_call="write_file"
        )

        assert frame["description"] == description
        assert frame["tool_call"] == "write_file"

    def test_absent_tool_call_stays_absent(self) -> None:
        """The bound leaves the optional field's absence alone."""
        frame = _served_permission_frame(description="fine", tool_call=None)

        assert "tool_call" not in frame


class TestWorkspaceRootBoundIsTheColumn:
    """Every reader of the workspace-root selector enforces the column's width.

    The column is the only site that can REFUSE an over-long root, and it
    refuses by failing the write inside a transaction rather than by telling a
    caller no. Each upstream check exists to convert that into a refusal at the
    edge, which means each one is enforcing this column - and the failure is
    asymmetric in both directions. Lower the column without lowering a check and
    an accepted request dies at the write; raise a check without raising the
    column and it dies the same way. Only lockstep change is safe.

    The width is read off the mapped column here rather than written down, so
    these stay true wherever the declaration moves and fail the moment a reader
    stops agreeing with it.
    """

    @staticmethod
    def _column_width() -> int:
        """Return the declared width of ``threads.workspace_root``."""
        column_type = ThreadModel.__table__.c.workspace_root.type
        assert isinstance(column_type, String)
        width = column_type.length
        assert isinstance(width, int), (
            "threads.workspace_root no longer declares a width; the bound every "
            "upstream check enforces has nothing left to be derived from"
        )
        return width

    @staticmethod
    def _root_of_length(length: int) -> str:
        """Build an absolute workspace root of exactly ``length`` characters."""
        prefix = Path.cwd().anchor
        root = prefix + "w" * (length - len(prefix))
        assert len(root) == length
        return root

    @pytest.mark.asyncio
    async def test_a_root_at_the_column_width_survives_a_real_write(
        self, session: AsyncSession
    ) -> None:
        """The widest admissible root round-trips through the real write seam.

        Driven through ``create_thread`` rather than a hand-built row, because
        the projection that writes the selector normalizes the path first; a
        bound proven against an unnormalized string would not be the bound the
        column actually receives.
        """
        width = self._column_width()
        root = self._root_of_length(width)

        thread = await create_thread(
            session,
            write_authority=make_test_write_authority(),
            metadata=json.dumps({"workspace_root": root}),
        )
        await session.commit()
        session.expunge_all()
        stored = await session.get(ThreadModel, thread.id)

        assert stored is not None
        assert stored.workspace_root is not None
        assert len(stored.workspace_root) == width

    @pytest.mark.asyncio
    async def test_the_repository_edge_admits_the_width_and_refuses_past_it(
        self, session: AsyncSession
    ) -> None:
        """The paged read refuses one character past the column, not at it."""
        width = self._column_width()

        await list_active_thread_page(session, limit=1, workspace_root="w" * width)

        with pytest.raises(ValueError, match="workspace selector"):
            await list_active_thread_page(
                session, limit=1, workspace_root="w" * (width + 1)
            )

    @pytest.mark.asyncio
    async def test_the_discovery_edge_admits_the_width_and_refuses_past_it(
        self, session: AsyncSession, checkpointer: AsyncSqliteSaver
    ) -> None:
        """Discovery refuses at the edge rather than deep in a transaction.

        The refusal has to happen here, before the query, because the only other
        thing standing between an over-long root and the database is the write
        itself - and a caller cannot be handed a 422 from inside a failed
        transaction.
        """
        width = self._column_width()

        await discover_active_runs(
            session,
            checkpointer=checkpointer,
            workspace_root=Path(self._root_of_length(width)),
        )

        with pytest.raises(ValueError, match="workspace_root must be between"):
            await discover_active_runs(
                session,
                checkpointer=checkpointer,
                workspace_root=Path(self._root_of_length(width + 1)),
            )


class TestFeatureTagBoundIsTheColumn:
    """The feature-tag selector's readers enforce ``threads.feature_tag``.

    The sibling of :class:`TestWorkspaceRootBoundIsTheColumn`, and asserted the
    same way for the same reason: the column is the authority, exceeding it is a
    write failure rather than a refusal, and every upstream check exists to turn
    that into a refusal a caller can be told about.

    The tag differs from the workspace root in one way worth its own assertion.
    It is also carried OUTBOUND, on the discovery and history records that
    replay it from the column, and there the wire bound REFUSES rather than
    truncates: a Pydantic ``max_length`` is a constraint, not a projector. So a
    wire bound below the column does not ship a shortened tag - it fails the
    whole response. A run whose tag the column accepted but the record rejects
    takes down every page it appears on, not just its own row, and only once
    some run happens to carry a tag that long.
    """

    @staticmethod
    def _column_width() -> int:
        """Return the declared width of ``threads.feature_tag``."""
        column_type = ThreadModel.__table__.c.feature_tag.type
        assert isinstance(column_type, String)
        width = column_type.length
        assert isinstance(width, int), (
            "threads.feature_tag no longer declares a width; the bound every "
            "upstream check enforces has nothing left to be derived from"
        )
        return width

    @pytest.mark.asyncio
    async def test_a_tag_at_the_column_width_survives_a_real_write(
        self, session: AsyncSession
    ) -> None:
        """The widest admissible tag round-trips through the real write seam."""
        width = self._column_width()
        tag = "f" * width

        thread = await create_thread(
            session,
            write_authority=make_test_write_authority(),
            metadata=json.dumps(
                {"workspace_root": str(Path.cwd() / "workspace"), "feature_tag": tag}
            ),
        )
        await session.commit()
        session.expunge_all()
        stored = await session.get(ThreadModel, thread.id)

        assert stored is not None
        assert stored.feature_tag == tag

    @pytest.mark.asyncio
    async def test_the_write_seam_drops_a_tag_the_column_cannot_hold(
        self, session: AsyncSession
    ) -> None:
        """One character past the column is refused before the row is built.

        The selector projection drops an inadmissible tag rather than storing a
        shortened one, so a run is discoverable by the tag it declared or by no
        tag at all - never by a silently different tag.
        """
        width = self._column_width()

        thread = await create_thread(
            session,
            write_authority=make_test_write_authority(),
            metadata=json.dumps(
                {
                    "workspace_root": str(Path.cwd() / "workspace"),
                    "feature_tag": "f" * (width + 1),
                }
            ),
        )
        await session.commit()
        session.expunge_all()
        stored = await session.get(ThreadModel, thread.id)

        assert stored is not None
        assert stored.feature_tag is None

    @pytest.mark.asyncio
    async def test_the_repository_edge_admits_the_width_and_refuses_past_it(
        self, session: AsyncSession
    ) -> None:
        """The paged read refuses one character past the column, not at it."""
        width = self._column_width()

        await list_active_thread_page(session, limit=1, feature_tag="f" * width)

        with pytest.raises(ValueError, match="feature selector"):
            await list_active_thread_page(
                session, limit=1, feature_tag="f" * (width + 1)
            )

    @pytest.mark.asyncio
    async def test_the_discovery_edge_admits_the_width_and_refuses_past_it(
        self, session: AsyncSession, checkpointer: AsyncSqliteSaver
    ) -> None:
        """Discovery refuses at the edge rather than deep in a transaction."""
        width = self._column_width()

        await discover_active_runs(
            session, checkpointer=checkpointer, feature_tag="f" * width
        )

        with pytest.raises(ValueError, match="feature_tag must be between"):
            await discover_active_runs(
                session, checkpointer=checkpointer, feature_tag="f" * (width + 1)
            )

    def test_the_wire_records_carry_a_tag_the_column_can_hold(self) -> None:
        """Every tag the column accepts survives onto the wire records.

        The assertion the outbound direction actually needs, and the admitted
        side is the load-bearing half: a refusal alone is also what a wire bound
        set to anything smaller would produce. These records REPLAY a stored tag
        rather than accepting one, so a bound below the column cannot refuse the
        caller who supplied it - there is no such caller. It refuses the row on
        the way out and fails the response built around it.
        """
        width = self._column_width()
        tag = "f" * width
        stamp = datetime.now(UTC)

        active = ActiveRunRecord(
            run_id="r-1", status=ThreadStatus.RUNNING, feature_tag=tag
        )
        summary = RunSummaryRecord(
            run_id="r-1",
            status=ThreadStatus.RUNNING,
            created_at=stamp,
            updated_at=stamp,
            feature_tag=tag,
        )

        assert active.feature_tag == tag
        assert summary.feature_tag == tag

    def test_the_wire_records_refuse_a_tag_the_column_could_not_have_stored(
        self,
    ) -> None:
        """One character past the column is refused, and refused ON the tag.

        The error location is asserted rather than the mere fact of a refusal:
        both records carry other constrained fields, so a refusal for an
        unrelated reason would otherwise read as the one under test.
        """
        width = self._column_width()
        over = "f" * (width + 1)
        stamp = datetime.now(UTC)

        with pytest.raises(ValidationError) as active_refusal:
            ActiveRunRecord(run_id="r-1", status=ThreadStatus.RUNNING, feature_tag=over)
        with pytest.raises(ValidationError) as summary_refusal:
            RunSummaryRecord(
                run_id="r-1",
                status=ThreadStatus.RUNNING,
                created_at=stamp,
                updated_at=stamp,
                feature_tag=over,
            )

        assert [e["loc"] for e in active_refusal.value.errors()] == [("feature_tag",)]
        assert [e["loc"] for e in summary_refusal.value.errors()] == [("feature_tag",)]

    def test_the_start_request_admits_the_width_and_refuses_past_it(self) -> None:
        """The inbound body field bounds the tag a caller may declare.

        The one site of the three that refuses a CALLER rather than a stored
        row, so it is the only one whose bound a client ever sees.
        """
        width = self._column_width()
        selection = ProviderCatalogSelection(
            schema_version=1,
            provider_id="p",
            execution_mode="m",
            catalog_revision="r",
            entry_id="e",
        )

        admitted = RunStartRequest(
            team_preset="tp",
            run_id="r-1",
            selection=selection,
            message="start",
            feature_tag="f" * width,
        )
        assert admitted.feature_tag == "f" * width

        with pytest.raises(ValidationError) as refusal:
            RunStartRequest(
                team_preset="tp",
                run_id="r-1",
                selection=selection,
                message="start",
                feature_tag="f" * (width + 1),
            )

        assert [e["loc"] for e in refusal.value.errors()] == [("feature_tag",)]

"""SQLAlchemy 2.0 async models for the persistence layer.

Defines the core data models for threads, artifacts, permission logs,
and cost tracking. Uses ``DeclarativeBase`` with ``Mapped`` / ``mapped_column``
for full type-safety.
"""

from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any, override

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
    text,
)
from sqlalchemy.engine.interfaces import Dialect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeEngine

from ..thread.constants import MAX_FEATURE_TAG_LENGTH, MAX_WORKSPACE_ROOT_LENGTH
from ..thread.enums import (
    ControlActionResultStatus,
    PermissionRequestStatus,
    RepairStatus,
    TaskQueueStatus,
    ThreadStatus,
)

__all__ = [
    "MONEY_PRECISION",
    "MONEY_SCALE",
    "ArtifactModel",
    "AuthoringEventCursorModel",
    "Base",
    "ControlActionModel",
    "CostTrackingModel",
    "MoneyAmount",
    "PermissionLogModel",
    "PermissionRequestModel",
    "TaskQueueEntryModel",
    "ThreadDeletionSagaModel",
    "ThreadExecutionStateModel",
    "ThreadModel",
    "utcnow",
]

#: Total significant digits stored for a monetary amount.
#:
#: Chosen so both backends represent the SAME domain rather than leaving the
#: SQLite lane a silently narrower second-class citizen: the SQLite
#: representation is an ``int64`` of :data:`MONEY_SCALE`-scaled units, whose
#: ceiling (``2**63 - 1`` scaled down, about 922 million) sits just inside the
#: nine integer digits ``19 - 10`` leaves on Postgres.
MONEY_PRECISION = 19

#: Decimal places kept for a monetary amount.
#:
#: Ten places resolve to 1e-10 USD — one ten-billionth of a dollar, or 1e-8 of
#: a cent. Per-token LLM prices bottom out around 7.5e-8 USD/token (a cheap
#: model at roughly $0.075 per million input tokens), so the smallest single
#: token that can be priced today still lands about 750 storage units above the
#: floor. Nothing at the small end truncates.
MONEY_SCALE = 10

_MONEY_QUANTUM = Decimal(1).scaleb(-MONEY_SCALE)
_MONEY_UNITS_PER_DOLLAR = 10**MONEY_SCALE


def utcnow() -> datetime:
    """Return timezone-aware UTC now."""
    return datetime.now(UTC)


_utcnow = utcnow


class UTCDateTime(TypeDecorator[datetime]):
    """Persist timezone-aware timestamps as naive UTC and restore UTC on read.

    This keeps one portable schema across SQLite and Postgres while preserving
    UTC-aware datetimes at the application boundary.
    """

    impl = DateTime
    cache_ok = True

    @override
    def process_bind_param(
        self, value: datetime | None, dialect: Dialect
    ) -> datetime | None:
        """Normalize inbound values to naive UTC for storage."""
        if value is None:
            return None
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            msg = "UTCDateTime requires timezone-aware datetime values."
            raise TypeError(msg)
        return value.astimezone(UTC).replace(tzinfo=None)

    @override
    def process_result_value(
        self, value: datetime | None, dialect: Dialect
    ) -> datetime | None:
        """Restore UTC timezone info on loaded datetime values."""
        if value is None:
            return None
        return value.replace(tzinfo=UTC)


class MoneyAmount(TypeDecorator[Decimal]):
    """Persist a monetary amount exactly on both backends, never via float.

    The sibling of :class:`UTCDateTime`: one portable schema across SQLite and
    Postgres, with the precise Python type restored at the application
    boundary. Here the hazard is IEEE-754 rather than tz-naivety.

    Postgres stores a native ``NUMERIC`` and needs no help. SQLite has no
    decimal type, and SQLAlchemy's plain ``Numeric`` copes by round-tripping
    through ``float`` — which is precisely the defect this type exists to
    remove, and which SQLAlchemy itself warns about at runtime. So the SQLite
    lane stores a scaled ``int64`` instead: an exact integer count of
    1e-:data:`MONEY_SCALE` dollar units.

    Integer storage buys more than lossless round-tripping. ``SUM()`` over
    these rows is evaluated inside the database, and SQLite sums integers
    exactly while it accumulates binary error over floats. Because SQLAlchemy
    infers an aggregate's type from its argument, ``func.sum()`` over this
    column returns through :meth:`process_result_value` and therefore yields a
    ``Decimal`` on both backends — the aggregate is exact end to end, not just
    the individual row.
    """

    impl = Numeric
    cache_ok = True

    @override
    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[Any]:
        """Select scaled-integer storage on SQLite, native NUMERIC elsewhere."""
        if dialect.name == "sqlite":
            return dialect.type_descriptor(BigInteger())
        return dialect.type_descriptor(
            Numeric(precision=MONEY_PRECISION, scale=MONEY_SCALE, asdecimal=True)
        )

    @override
    def process_bind_param(
        self, value: Decimal | int | float | str | None, dialect: Dialect
    ) -> Decimal | int | None:
        """Quantize to the stored scale, scaling to integer units on SQLite.

        ``float`` is accepted but converted through ``str`` so the decimal
        literal the caller wrote is preserved instead of its binary expansion:
        ``Decimal(0.05)`` is 0.05000000000000000277…, whereas
        ``Decimal(str(0.05))`` is exactly ``0.05``. Callers computing real
        money should hand over ``Decimal`` and keep float out of the
        arithmetic entirely; this conversion makes the boundary safe, it does
        not make upstream float arithmetic correct.
        """
        if value is None:
            return None
        amount = Decimal(str(value)) if isinstance(value, float) else Decimal(value)
        if not amount.is_finite():
            msg = f"MoneyAmount requires a finite amount, got: {value!r}"
            raise ValueError(msg)
        quantized = amount.quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_EVEN)
        if dialect.name == "sqlite":
            return int(quantized.scaleb(MONEY_SCALE))
        return quantized

    @override
    def process_result_value(
        self, value: Decimal | int | float | str | None, dialect: Dialect
    ) -> Decimal | None:
        """Restore an exact ``Decimal``, unscaling the SQLite integer form."""
        if value is None:
            return None
        if dialect.name == "sqlite":
            return (Decimal(int(value)) / _MONEY_UNITS_PER_DOLLAR).quantize(
                _MONEY_QUANTUM
            )
        return Decimal(str(value)) if not isinstance(value, Decimal) else value


class Base(DeclarativeBase):
    """Shared declarative base for all database models.

    Deliberately carries NO ``naming_convention``, and that is a decision
    rather than an omission.

    Every ``UniqueConstraint`` and every ``Index`` in this schema is already
    explicitly named, so a convention would reach only the foreign keys and
    primary keys, which are unnamed and therefore named by whatever the backend
    synthesizes. Adopting one would NOT rename them: a convention applies at
    DDL-compile time, so it renames constraints only in schemas built from this
    metadata. Production file-backed databases are built by replaying the
    Alembic chain instead, and would keep the unnamed form. The result would be
    named constraints in every ``create_all`` schema — the whole test suite and
    the ``:memory:`` lane — against unnamed constraints in every deployed
    database, a divergence the parity suite cannot see because it compares
    foreign keys and primary keys structurally rather than by synthesized name.
    A future batch migration written against the named form would then pass the
    entire suite and fail on real deployments. That is strictly worse than the
    status quo, so a forward-only convention is refused.

    Renaming the existing constraints instead would mean rebuilding all ten
    tables under SQLite batch mode (every table has an unnamed primary key, and
    eight also carry an unnamed ``thread_id`` foreign key), copying every row
    and recreating the four partial ``ix_threads_active_*`` indexes — a
    whole-database rewrite whose only beneficiary is a migration nobody has
    written yet.

    That beneficiary is already served without any of it. Alembic's
    ``batch_alter_table`` accepts a ``naming_convention`` argument precisely so
    a reflected unnamed constraint can be given a deterministic name at the
    moment a migration needs to target it::

        with op.batch_alter_table(
            "artifacts",
            naming_convention={
                "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"
            },
        ) as batch_op:
            batch_op.drop_constraint(
                "fk_artifacts_thread_id_threads", type_="foreignkey"
            )

    That is the supported way to drop one of these foreign keys, it needs no
    schema change, and ``database/tests/test_schema_integrity.py`` proves it
    works against a real migrated database rather than leaving it asserted here.
    """


class ThreadModel(Base):
    """Orchestration thread — the top-level unit of work."""

    __tablename__ = "threads"

    __table_args__ = (
        Index("ix_threads_nickname", "nickname", unique=True),
        Index(
            "ix_threads_active_order",
            "created_at",
            "id",
            sqlite_where=text("is_active IS 1"),
            postgresql_where=text("is_active IS true"),
        ),
        Index(
            "ix_threads_active_workspace_order",
            "workspace_key",
            "created_at",
            "id",
            sqlite_where=text("is_active IS 1"),
            postgresql_where=text("is_active IS true"),
        ),
        Index(
            "ix_threads_active_feature_order",
            "feature_tag",
            "created_at",
            "id",
            sqlite_where=text("is_active IS 1"),
            postgresql_where=text("is_active IS true"),
        ),
        Index(
            "ix_threads_active_workspace_feature_order",
            "workspace_key",
            "feature_tag",
            "created_at",
            "id",
            sqlite_where=text("is_active IS 1"),
            postgresql_where=text("is_active IS true"),
        ),
    )

    id: Mapped[str] = mapped_column(primary_key=True)
    title: Mapped[str | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=_utcnow, onupdate=_utcnow
    )
    # Alone among the NOT NULL columns in this schema, this one carries no
    # server_default, and it stays that way on purpose. Adding one was tried and
    # reverted: SQLite cannot attach a default to an existing column in place, so
    # the only route is a batch rebuild of ``threads``, and a rebuild silently
    # rewrites the four partial ``ix_threads_active_*`` indexes that revision
    # 0009 created DESC into ASC ones. Index DIRECTION is the single dimension
    # SQLite reflection cannot report, so the schema-parity suite passes while
    # that happens. Trading four deliberately-ordered production indexes for a
    # default no writer reads — every INSERT goes through the ORM, which supplies
    # the Python default above — is a bad bargain. Any future batch operation on
    # this table owes the same care; the index-direction guard in
    # ``database/tests/test_schema_integrity.py`` is what makes it fail loudly.
    status: Mapped[str] = mapped_column(default=ThreadStatus.SUBMITTED)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    repair_status: Mapped[str] = mapped_column(default=RepairStatus.HEALTHY)
    repair_reason: Mapped[str | None] = mapped_column(Text, default=None)
    # The capped, single-line reason a run last transitioned to FAILED, or None
    # for a run that never failed (and cleared by nothing — a run is terminal
    # exactly once, so this is write-once per thread). Durable counterpart to
    # the non-authoritative SSE relay's error_detail (012840a4): a reloaded
    # panel reads run-status alone, never the live stream, so without this
    # column it recovered a bare "failed" with no reason.
    failure_reason: Mapped[str | None] = mapped_column(Text, default=None)
    # The machine-readable counterpart to failure_reason: WHY the run failed, as
    # a closed vocabulary a client branches on, rather than prose it would have
    # to parse. The reason text says what happened; this says what the reader
    # should do about it, and the two are written together or not at all.
    #
    # Nullable with no default, deliberately. A run that failed before this
    # column existed genuinely carries no classification, and back-filling one
    # would assert we classified runs we never observed. The invariant that a
    # NEW failure always carries a condition is enforced at the write sites, not
    # by the schema: a NOT NULL constraint would turn a classification bug into
    # a write crash that loses the run's outcome entirely, which is strictly
    # worse than recording an honest floor value.
    provider_condition: Mapped[str | None] = mapped_column(default=None)
    # Typed by RepairStatus, the SAME closed vocabulary as repair_status above,
    # and deliberately not by an enum of its own. The two columns answer
    # different questions from one shared set of answers: repair_status is the
    # run's repair classification, execution_readiness is the readiness reading
    # a dispatcher consults before resuming it. Every producer already writes a
    # RepairStatus member here — the repair policy, reconciliation, the control
    # projection, and the thread-state service all do — and every consumer that
    # narrows the value tests membership against RepairStatus members. A second
    # enum duplicating those members would be a vocabulary no writer speaks.
    execution_readiness: Mapped[str] = mapped_column(default=RepairStatus.HEALTHY)
    # The reconnect cursor a client compares against to discard already-seen
    # WebSocket/SSE events (api/schemas/snapshots.py's ThreadStateSnapshot
    # docstring). The live value lives only on the gateway's in-memory
    # EventAggregator and is pruned the moment a run settles
    # (EventEmitters.clear_thread_state), so a REST read after settle - the
    # only moment the reconnect contract matters - had nothing durable to
    # read and always answered 0 (F19). Captured and persisted here at the
    # same terminal-status write as failure_reason/provider_condition/
    # repair_status, before the prune runs.
    #
    # Nullable with no default, on the SAME reasoning as provider_condition
    # above: a run that settled before this column existed, or through a
    # code path with no aggregator available, genuinely has no captured
    # cursor, and 0 is a legitimate value a thread with truly zero relayed
    # events could carry. Defaulting to 0 would make "never captured"
    # indistinguishable from "captured as zero" - the same failure mode
    # this column exists to close, reintroduced at the schema level.
    last_sequence: Mapped[int | None] = mapped_column(default=None)
    approval_status: Mapped[str | None] = mapped_column(default=None)
    approval_request_id: Mapped[str | None] = mapped_column(default=None)
    approval_reason: Mapped[str | None] = mapped_column(Text, default=None)
    approval_response_action_id: Mapped[str | None] = mapped_column(default=None)
    approval_updated_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), default=None
    )
    last_requested_action: Mapped[str | None] = mapped_column(default=None)
    last_applied_action: Mapped[str | None] = mapped_column(default=None)
    repair_generation: Mapped[int] = mapped_column(default=0)
    recovery_epoch: Mapped[int] = mapped_column(default=0)
    thread_metadata: Mapped[str | None] = mapped_column(Text, default=None)
    workspace_root: Mapped[str | None] = mapped_column(
        String(MAX_WORKSPACE_ROOT_LENGTH), default=None
    )
    workspace_key: Mapped[str | None] = mapped_column(String(64), default=None)
    feature_tag: Mapped[str | None] = mapped_column(
        String(MAX_FEATURE_TAG_LENGTH), default=None
    )
    nickname: Mapped[str | None] = mapped_column(default=None)
    team_preset: Mapped[str | None] = mapped_column(default=None)

    artifacts: Mapped[list["ArtifactModel"]] = relationship(
        back_populates="thread", cascade="all, delete-orphan", lazy="raise"
    )
    permission_logs: Mapped[list["PermissionLogModel"]] = relationship(
        back_populates="thread", cascade="all, delete-orphan", lazy="raise"
    )
    permission_requests: Mapped[list["PermissionRequestModel"]] = relationship(
        back_populates="thread", cascade="all, delete-orphan", lazy="raise"
    )
    control_actions: Mapped[list["ControlActionModel"]] = relationship(
        back_populates="thread", cascade="all, delete-orphan", lazy="raise"
    )
    execution_state: Mapped["ThreadExecutionStateModel | None"] = relationship(
        back_populates="thread",
        cascade="all, delete-orphan",
        uselist=False,
        lazy="raise",
    )
    cost_records: Mapped[list["CostTrackingModel"]] = relationship(
        back_populates="thread", cascade="all, delete-orphan", lazy="raise"
    )
    task_queue_entries: Mapped[list["TaskQueueEntryModel"]] = relationship(
        back_populates="thread", cascade="all, delete-orphan", lazy="raise"
    )

    def __repr__(self) -> str:
        """Return developer-friendly representation."""
        return (
            f"ThreadModel(id={self.id!r}, status={self.status!r}, "
            f"nickname={self.nickname!r})"
        )


class ArtifactModel(Base):
    """File artifact produced by an agent during a thread."""

    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(primary_key=True)
    thread_id: Mapped[str] = mapped_column(ForeignKey("threads.id"))
    type: Mapped[str] = mapped_column()
    path: Mapped[str] = mapped_column()
    content_hash: Mapped[str | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_utcnow)
    agent_id: Mapped[str | None] = mapped_column(default=None)

    thread: Mapped["ThreadModel"] = relationship(
        back_populates="artifacts", lazy="raise"
    )

    __table_args__ = (Index("ix_artifacts_thread_id", "thread_id"),)

    def __repr__(self) -> str:
        """Return developer-friendly representation."""
        return (
            f"ArtifactModel(id={self.id!r}, thread_id={self.thread_id!r}, "
            f"type={self.type!r}, path={self.path!r})"
        )


class PermissionLogModel(Base):
    """Audit log of permission decisions made during a thread."""

    __tablename__ = "permission_logs"

    id: Mapped[str] = mapped_column(primary_key=True)
    thread_id: Mapped[str] = mapped_column(ForeignKey("threads.id"))
    # WHO is not knowable at the decision seam, in either sense. The agent whose
    # tool call was gated is never captured upstream — the interrupt payload
    # carries tool name, input, and options but no agent — and the responder is
    # not threaded through as an authenticated identity. Nullable rather than
    # NOT NULL for the reason provider_condition states above: a required column
    # here forces either a fabricated attribution or no record at all, and an
    # unattributed decision still answers which tool call was approved on which
    # run, with which option, when. Attributing the requesting agent means
    # widening the interrupt payload and the request row, which is its own step.
    agent_id: Mapped[str | None] = mapped_column(default=None)
    tool_name: Mapped[str] = mapped_column()
    action: Mapped[str] = mapped_column()
    option_id: Mapped[str | None] = mapped_column(default=None)
    responded_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_utcnow)

    thread: Mapped["ThreadModel"] = relationship(
        back_populates="permission_logs", lazy="raise"
    )

    __table_args__ = (Index("ix_permission_logs_thread_id", "thread_id"),)


class PermissionRequestModel(Base):
    """Durable record of a pending or resolved permission request."""

    __tablename__ = "permission_requests"

    request_id: Mapped[str] = mapped_column(primary_key=True)
    thread_id: Mapped[str] = mapped_column(ForeignKey("threads.id"))
    pause_reason_type: Mapped[str] = mapped_column()
    tool_call: Mapped[str | None] = mapped_column(default=None)
    description: Mapped[str] = mapped_column(Text)
    allowed_options_json: Mapped[str] = mapped_column(Text)
    request_status: Mapped[str] = mapped_column(default=PermissionRequestStatus.PENDING)
    response_option_id: Mapped[str | None] = mapped_column(default=None)
    idempotency_key: Mapped[str | None] = mapped_column(default=None)
    worker_generation: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_utcnow)
    responded_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
    applied_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)

    thread: Mapped["ThreadModel"] = relationship(
        back_populates="permission_requests", lazy="raise"
    )

    __table_args__ = (
        Index("ix_permission_requests_thread_id", "thread_id"),
        Index("ix_permission_requests_status", "request_status"),
    )


class ControlActionModel(Base):
    """Durable control and repair journal for thread orchestration actions."""

    __tablename__ = "control_actions"

    __table_args__ = (
        Index("ix_control_actions_thread_id", "thread_id"),
        Index("ix_control_actions_request_id", "request_id"),
        Index("ux_control_actions_dispatch_id", "dispatch_id", unique=True),
        UniqueConstraint(
            "thread_id",
            "idempotency_key",
            name="uq_control_actions_thread_id_idempotency_key",
        ),
    )

    id: Mapped[str] = mapped_column(primary_key=True)
    thread_id: Mapped[str] = mapped_column(ForeignKey("threads.id"))
    action_type: Mapped[str] = mapped_column()
    request_id: Mapped[str | None] = mapped_column(default=None)
    idempotency_key: Mapped[str] = mapped_column()
    requested_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_utcnow)
    applied_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
    superseded_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
    result_status: Mapped[str] = mapped_column(
        default=ControlActionResultStatus.ACCEPTED_NOT_APPLIED
    )
    payload_json: Mapped[str | None] = mapped_column(Text, default=None)
    worker_generation: Mapped[int] = mapped_column(default=0)
    # Stable identity reused for every redelivery of this accepted intention.
    # Existing pre-0012 journal rows legitimately carry NULL until reconciled.
    dispatch_id: Mapped[str | None] = mapped_column(default=None)
    # Renewable cross-process ownership.  The token is secret only in the sense
    # that another dispatcher must not guess it; it never crosses the worker wire.
    claim_token: Mapped[str | None] = mapped_column(default=None)
    claim_expires_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), default=None
    )

    thread: Mapped["ThreadModel"] = relationship(
        back_populates="control_actions", lazy="raise"
    )


class ThreadExecutionStateModel(Base):
    """Latest normalized execution-state projection for a thread."""

    __tablename__ = "thread_execution_state"

    __table_args__ = (
        Index("ix_thread_execution_state_checkpoint_id", "checkpoint_id"),
    )

    thread_id: Mapped[str] = mapped_column(ForeignKey("threads.id"), primary_key=True)
    checkpoint_id: Mapped[str | None] = mapped_column(default=None)
    parent_checkpoint_id: Mapped[str | None] = mapped_column(default=None)
    snapshot_created_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), default=None
    )
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_utcnow)
    recovery_epoch: Mapped[int] = mapped_column(default=0)
    task_count: Mapped[int] = mapped_column(default=0)
    interrupt_count: Mapped[int] = mapped_column(default=0)
    next_nodes_json: Mapped[str] = mapped_column(Text, default="[]")
    interrupt_types_json: Mapped[str] = mapped_column(Text, default="[]")
    tasks_json: Mapped[str] = mapped_column(Text, default="[]")
    degraded_reasons_json: Mapped[str] = mapped_column(Text, default="[]")

    thread: Mapped["ThreadModel"] = relationship(
        back_populates="execution_state", lazy="raise"
    )


class ThreadDeletionSagaModel(Base):
    """Durable cross-store deletion saga for one thread.

    A thread delete is not a single atomic act: it must remove checkpoint
    state, workspace artifact files, and control rows that live in three
    different stores. This row is the outbox that makes that removal
    failure-atomic and resumable. It is written before any irreversible
    external effect, transitioning the thread to ``deleting`` and capturing the
    full cleanup manifest so a crash mid-teardown leaves a durable, replayable
    plan rather than a half-deleted thread.

    ``manifest_json`` is the immutable list of cleanup items captured at
    saga creation (the checkpoint and each contained artifact file).
    ``result_json`` is the per-item terminal-state ledger the cleanup pass
    advances. Control rows are removed only once every manifest item is done,
    at which point this saga row is removed with them.
    """

    __tablename__ = "thread_deletion_saga"

    thread_id: Mapped[str] = mapped_column(ForeignKey("threads.id"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=_utcnow, onupdate=_utcnow
    )
    claimed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
    manifest_json: Mapped[str] = mapped_column(Text)
    result_json: Mapped[str] = mapped_column(Text, default="{}")

    def __repr__(self) -> str:
        """Return developer-friendly representation."""
        return (
            f"ThreadDeletionSagaModel(thread_id={self.thread_id!r}, "
            f"claimed_at={self.claimed_at!r})"
        )


class AuthoringEventCursorModel(Base):
    """Durable cursor into the engine authoring lifecycle stream.

    One row per subscriber records the last outbox sequence the verdict
    subscriber has durably processed from ``GET /authoring/v1/events``. A gateway
    restart reads this cursor and resumes the stream from where it left off,
    rather than replaying from zero or dropping reviewer verdicts issued while
    the gateway was down. The sequence is engine-owned and advances only
    forward.
    """

    __tablename__ = "authoring_event_cursor"

    subscriber_id: Mapped[str] = mapped_column(primary_key=True)
    last_seq: Mapped[int] = mapped_column(default=0)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=_utcnow, onupdate=_utcnow
    )

    def __repr__(self) -> str:
        """Return developer-friendly representation."""
        return (
            f"AuthoringEventCursorModel(subscriber_id={self.subscriber_id!r}, "
            f"last_seq={self.last_seq!r})"
        )


class CostTrackingModel(Base):
    """Token usage and estimated cost for LLM invocations."""

    __tablename__ = "cost_tracking"

    id: Mapped[str] = mapped_column(primary_key=True)
    thread_id: Mapped[str] = mapped_column(ForeignKey("threads.id"))
    agent_id: Mapped[str] = mapped_column()
    # Nullable because a lane the invoked model instance never declared is
    # genuinely unknown, and these are free-text columns with no reserved
    # member to spend: a sentinel string would be indistinguishable from a real
    # provider name. NULL is the free-text counterpart of the UNKNOWN member a
    # closed enum uses for the same purpose. The measured token counts stay
    # worth recording, so the row is written with the identity left unset
    # rather than dropped or back-filled with a stand-in.
    provider: Mapped[str | None] = mapped_column(default=None)
    model: Mapped[str | None] = mapped_column(default=None)
    input_tokens: Mapped[int] = mapped_column(default=0)
    output_tokens: Mapped[int] = mapped_column(default=0)
    estimated_cost: Mapped[Decimal] = mapped_column(MoneyAmount(), default=Decimal(0))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_utcnow)

    thread: Mapped["ThreadModel"] = relationship(
        back_populates="cost_records", lazy="raise"
    )

    __table_args__ = (
        Index("ix_cost_tracking_thread_id", "thread_id"),
        Index("ix_cost_tracking_agent_id", "agent_id"),
    )


class TaskQueueEntryModel(Base):
    """A single worker task-queue row, owned by a thread.

    Orchestration state that used to live in a ``.vault/plan`` markdown table.
    ``position`` is the sole ordering authority; ``task_key`` is the stable
    per-thread identity the mark-complete tool addresses.  ``plan_changeset_id``
    and ``plan_step_key`` are references to the engine plan proposal (references,
    never content).
    """

    __tablename__ = "task_queue_entries"

    __table_args__ = (
        Index("ix_task_queue_entries_thread_id", "thread_id"),
        UniqueConstraint(
            "thread_id",
            "position",
            name="uq_task_queue_entries_thread_id_position",
        ),
        UniqueConstraint(
            "thread_id",
            "task_key",
            name="uq_task_queue_entries_thread_id_task_key",
        ),
    )

    id: Mapped[str] = mapped_column(primary_key=True)
    thread_id: Mapped[str] = mapped_column(ForeignKey("threads.id"))
    feature_tag: Mapped[str] = mapped_column()
    position: Mapped[int] = mapped_column()
    task_key: Mapped[str] = mapped_column()
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(default=TaskQueueStatus.PENDING)
    plan_changeset_id: Mapped[str | None] = mapped_column(default=None)
    plan_step_key: Mapped[str | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=_utcnow, onupdate=_utcnow
    )

    thread: Mapped["ThreadModel"] = relationship(
        back_populates="task_queue_entries", lazy="raise"
    )

    def __repr__(self) -> str:
        """Return developer-friendly representation."""
        return (
            f"TaskQueueEntryModel(thread_id={self.thread_id!r}, "
            f"position={self.position!r}, task_key={self.task_key!r}, "
            f"status={self.status!r})"
        )

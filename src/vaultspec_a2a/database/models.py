"""SQLAlchemy 2.0 async models for the persistence layer.

Defines the core data models for threads, artifacts, permission logs,
and cost tracking. Uses ``DeclarativeBase`` with ``Mapped`` / ``mapped_column``
for full type-safety.

References:
    - ADR-007: SQLite WAL mode, aiosqlite
    - ADR-009: Module hierarchy (``src/vaultspec_a2a/database/``)
    - ADR-011: Wire contract (data model context)
"""

from datetime import UTC, datetime
from typing import override

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Text,
    TypeDecorator,
    UniqueConstraint,
)
from sqlalchemy.engine.interfaces import Dialect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

__all__ = [
    "ArtifactModel",
    "Base",
    "ControlActionModel",
    "CostTrackingModel",
    "PermissionLogModel",
    "PermissionRequestModel",
    "ThreadExecutionStateModel",
    "ThreadModel",
]


def _utcnow() -> datetime:
    """Return timezone-aware UTC now."""
    return datetime.now(UTC)


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


class Base(DeclarativeBase):
    """Shared declarative base for all database models."""


class ThreadModel(Base):
    """Orchestration thread — the top-level unit of work."""

    __tablename__ = "threads"

    __table_args__ = (Index("ix_threads_nickname", "nickname", unique=True),)

    id: Mapped[str] = mapped_column(primary_key=True)
    title: Mapped[str | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=_utcnow, onupdate=_utcnow
    )
    status: Mapped[str] = mapped_column(default="submitted")
    repair_status: Mapped[str] = mapped_column(default="healthy")
    repair_reason: Mapped[str | None] = mapped_column(Text, default=None)
    execution_readiness: Mapped[str] = mapped_column(default="healthy")
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
    nickname: Mapped[str | None] = mapped_column(default=None)
    team_preset: Mapped[str | None] = mapped_column(default=None)

    artifacts: Mapped[list["ArtifactModel"]] = relationship(
        back_populates="thread", cascade="all, delete-orphan"
    )
    permission_logs: Mapped[list["PermissionLogModel"]] = relationship(
        back_populates="thread", cascade="all, delete-orphan"
    )
    permission_requests: Mapped[list["PermissionRequestModel"]] = relationship(
        back_populates="thread", cascade="all, delete-orphan"
    )
    control_actions: Mapped[list["ControlActionModel"]] = relationship(
        back_populates="thread", cascade="all, delete-orphan"
    )
    execution_state: Mapped["ThreadExecutionStateModel | None"] = relationship(
        back_populates="thread",
        cascade="all, delete-orphan",
        uselist=False,
    )
    cost_records: Mapped[list["CostTrackingModel"]] = relationship(
        back_populates="thread", cascade="all, delete-orphan"
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

    thread: Mapped["ThreadModel"] = relationship(back_populates="artifacts")

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
    agent_id: Mapped[str] = mapped_column()
    tool_name: Mapped[str] = mapped_column()
    action: Mapped[str] = mapped_column()
    option_id: Mapped[str | None] = mapped_column(default=None)
    responded_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_utcnow)

    thread: Mapped["ThreadModel"] = relationship(back_populates="permission_logs")

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
    request_status: Mapped[str] = mapped_column(default="pending")
    response_option_id: Mapped[str | None] = mapped_column(default=None)
    idempotency_key: Mapped[str | None] = mapped_column(default=None)
    worker_generation: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_utcnow)
    responded_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
    applied_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)

    thread: Mapped["ThreadModel"] = relationship(back_populates="permission_requests")

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
    result_status: Mapped[str] = mapped_column(default="accepted_not_applied")
    payload_json: Mapped[str | None] = mapped_column(Text, default=None)
    worker_generation: Mapped[int] = mapped_column(default=0)

    thread: Mapped["ThreadModel"] = relationship(back_populates="control_actions")


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

    thread: Mapped["ThreadModel"] = relationship(back_populates="execution_state")


class CostTrackingModel(Base):
    """Token usage and estimated cost for LLM invocations."""

    __tablename__ = "cost_tracking"

    id: Mapped[str] = mapped_column(primary_key=True)
    thread_id: Mapped[str] = mapped_column(ForeignKey("threads.id"))
    agent_id: Mapped[str] = mapped_column()
    provider: Mapped[str] = mapped_column()
    model: Mapped[str] = mapped_column()
    input_tokens: Mapped[int] = mapped_column(default=0)
    output_tokens: Mapped[int] = mapped_column(default=0)
    estimated_cost: Mapped[float] = mapped_column(default=0.0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_utcnow)

    thread: Mapped["ThreadModel"] = relationship(back_populates="cost_records")

    __table_args__ = (
        Index("ix_cost_tracking_thread_id", "thread_id"),
        Index("ix_cost_tracking_agent_id", "agent_id"),
    )

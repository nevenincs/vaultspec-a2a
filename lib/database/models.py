"""SQLAlchemy 2.0 async models for the persistence layer.

Defines the core data models for threads, artifacts, permission logs,
and cost tracking. Uses ``DeclarativeBase`` with ``Mapped`` / ``mapped_column``
for full type-safety.

References:
    - ADR-007: SQLite WAL mode, aiosqlite
    - ADR-009: Module hierarchy (``lib/database/``)
    - ADR-011: Wire contract (data model context)
"""

from datetime import UTC, datetime

from sqlalchemy import ForeignKey, Index, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


__all__ = [
    "ArtifactModel",
    "Base",
    "CostTrackingModel",
    "PermissionLogModel",
    "ThreadModel",
]


def _utcnow() -> datetime:
    """Return timezone-aware UTC now."""
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Shared declarative base for all database models."""


class ThreadModel(Base):
    """Orchestration thread — the top-level unit of work."""

    __tablename__ = "threads"

    __table_args__ = (Index("ix_threads_nickname", "nickname", unique=True),)

    id: Mapped[str] = mapped_column(primary_key=True)
    title: Mapped[str | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=_utcnow, onupdate=_utcnow)
    status: Mapped[str] = mapped_column(default="submitted")
    thread_metadata: Mapped[str | None] = mapped_column(Text, default=None)
    nickname: Mapped[str | None] = mapped_column(default=None)

    artifacts: Mapped[list["ArtifactModel"]] = relationship(
        back_populates="thread", cascade="all, delete-orphan"
    )
    permission_logs: Mapped[list["PermissionLogModel"]] = relationship(
        back_populates="thread", cascade="all, delete-orphan"
    )
    cost_records: Mapped[list["CostTrackingModel"]] = relationship(
        back_populates="thread", cascade="all, delete-orphan"
    )


class ArtifactModel(Base):
    """File artifact produced by an agent during a thread."""

    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(primary_key=True)
    thread_id: Mapped[str] = mapped_column(ForeignKey("threads.id"))
    type: Mapped[str] = mapped_column()
    path: Mapped[str] = mapped_column()
    content_hash: Mapped[str | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)
    agent_id: Mapped[str | None] = mapped_column(default=None)

    thread: Mapped["ThreadModel"] = relationship(back_populates="artifacts")

    __table_args__ = (Index("ix_artifacts_thread_id", "thread_id"),)


class PermissionLogModel(Base):
    """Audit log of permission decisions made during a thread."""

    __tablename__ = "permission_logs"

    id: Mapped[str] = mapped_column(primary_key=True)
    thread_id: Mapped[str] = mapped_column(ForeignKey("threads.id"))
    agent_id: Mapped[str] = mapped_column()
    tool_name: Mapped[str] = mapped_column()
    action: Mapped[str] = mapped_column()
    option_id: Mapped[str | None] = mapped_column(default=None)
    responded_at: Mapped[datetime] = mapped_column(default=_utcnow)

    thread: Mapped["ThreadModel"] = relationship(back_populates="permission_logs")

    __table_args__ = (Index("ix_permission_logs_thread_id", "thread_id"),)


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
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)

    thread: Mapped["ThreadModel"] = relationship(back_populates="cost_records")

    __table_args__ = (
        Index("ix_cost_tracking_thread_id", "thread_id"),
        Index("ix_cost_tracking_agent_id", "agent_id"),
    )

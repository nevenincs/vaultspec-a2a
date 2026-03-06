"""initial_schema

Baseline migration capturing the 4 app-owned tables as declared in
``lib/database/models.py``.  LangGraph checkpoint tables (``checkpoints``,
``writes``) are excluded — they are managed by ``AsyncSqliteSaver.setup()``.

Revision ID: 0001
Revises: (none)
Create Date: 2026-03-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create all app-owned tables."""
    # -- threads --
    op.create_table(
        "threads",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("thread_metadata", sa.Text(), nullable=True),
        sa.Column("nickname", sa.String(), nullable=True),
        sa.Column("team_preset", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_threads_nickname", "threads", ["nickname"], unique=True)

    # -- artifacts --
    op.create_table(
        "artifacts",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("thread_id", sa.String(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("path", sa.String(), nullable=False),
        sa.Column("content_hash", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("agent_id", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["thread_id"], ["threads.id"]),
    )
    op.create_index("ix_artifacts_thread_id", "artifacts", ["thread_id"])

    # -- permission_logs --
    op.create_table(
        "permission_logs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("thread_id", sa.String(), nullable=False),
        sa.Column("agent_id", sa.String(), nullable=False),
        sa.Column("tool_name", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("option_id", sa.String(), nullable=True),
        sa.Column("responded_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["thread_id"], ["threads.id"]),
    )
    op.create_index(
        "ix_permission_logs_thread_id", "permission_logs", ["thread_id"]
    )

    # -- cost_tracking --
    op.create_table(
        "cost_tracking",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("thread_id", sa.String(), nullable=False),
        sa.Column("agent_id", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("estimated_cost", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["thread_id"], ["threads.id"]),
    )
    op.create_index("ix_cost_tracking_thread_id", "cost_tracking", ["thread_id"])
    op.create_index("ix_cost_tracking_agent_id", "cost_tracking", ["agent_id"])


def downgrade() -> None:
    """Drop all app-owned tables."""
    op.drop_table("cost_tracking")
    op.drop_table("permission_logs")
    op.drop_table("artifacts")
    op.drop_table("threads")
